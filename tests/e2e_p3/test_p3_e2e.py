"""L9 end-to-end tests of Part 3 (Build 3-4 §1.8: E2E-3.1 … E2E-3.3), through the ``sever_db_p3``
SDK and the ``sever-verify`` process (``verifier/``, its own workspace), on real files under
``target/``. E2E-3.4 and 3.6 need the auditor (module 9); E2E-3.5 a ``test-hooks`` build (module
11); E2E-3.7 is ``verifier/src/tests.rs::p3_verify_an_older_verifier_rejects_a_later_epoch``;
E2E-3.8 is ``python/sever_db_p3/tests``.

The SDK's native module must be installed first:
``uv run --no-sync maturin develop --release --uv -m crates/sever-py-p3/Cargo.toml``.
"""

import json
import os
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from sever_db_p3 import Database, UserKey, prepare_insert
from sever_refmodel_durable.oracle import fixture_rows

ROOT = Path(__file__).resolve().parents[2]
VERIFY = ROOT / "verifier/target/release/sever-verify"
SMALL = ROOT / "golden/p1_partition_small.svp"
D = 16


@pytest.fixture(scope="session")
def verifier() -> Path:
    # Its own target directory, whatever CARGO_TARGET_DIR says (the proof runner sets one).
    env = dict(os.environ, CARGO_TARGET_DIR=str(ROOT / "verifier/target"))
    subprocess.run(
        ["cargo", "build", "-q", "--release", "--offline"],
        cwd=ROOT / "verifier",
        env=env,
        check=True,
    )
    return VERIFY


@pytest.fixture
def where() -> Iterator[Path]:
    base = ROOT / "target/e2e-p3" / uuid.uuid4().hex
    base.mkdir(parents=True)
    yield base
    shutil.rmtree(base, ignore_errors=True)


def verify(cert: Path, anchors: Path) -> tuple[int, Any]:
    p = subprocess.run(
        [str(VERIFY), str(cert), "--anchors", str(anchors)],
        capture_output=True,
        text=True,
        check=False,
    )
    out = p.stdout.strip().splitlines()
    return p.returncode, (json.loads(out[-1]) if out else None)


def deletions(base: Path) -> tuple[Path, dict[str, Path]]:
    """Through the SDK: an account inserts 6 records into frozen groups and 3 into the holding area
    (spawn target 8), then one of each is deleted. Writes the anchors and both certificates, closes
    the database and moves its directories away: the verifier gets nothing else."""
    rows = fixture_rows()
    user = UserKey.generate()
    out: dict[str, Path] = {}
    with Database.open(base / "data", base / "keys", d=D) as db:
        cid = db.create_collection(SMALL, spawn_target=8)
        for i in range(6):
            db.insert(cid, prepare_insert(cid, f"g{i}", [float(x) for x in rows[i]], user))
        for i in range(3):
            v = [float(x) for x in rows[120 + i]]  # out of distribution: the holding area
            db.insert(cid, prepare_insert(cid, f"h{i}", v, user))
        assert db.stats(cid)["holding"] == 3
        for name, rid in [("group", "g3"), ("holding", "h1")]:
            c = db.delete(cid, rid).certificate
            assert c is not None
            out[name] = base / f"{name}.cert"
            out[name].write_bytes(c)
        anchors = base / "anchors.json"
        anchors.write_text(db.anchors(), encoding="utf-8")
    gone = base / "moved-away"
    gone.mkdir()
    for d in ("data", "keys"):
        (base / d).rename(gone / d)
    return anchors, out


@pytest.mark.spec("SR-16.3-1", "SR-11.3-9")
@pytest.mark.oracle(
    "A",
    "§11.3 inputs: the certificate and the trust anchors, no database access; an honest "
    "certificate passes every step; §16.3 sever-verify <certificate> (E2E-3.1)",
)
def test_p3_e2e_3_1_the_verifier_accepts_a_deletion_in_another_process(
    verifier: Path, where: Path
) -> None:
    anchors, certs = deletions(where)
    code, out = verify(certs["group"], anchors)
    assert (code, out["accepted"]) == (0, True), out
    assert out["deletion_kind"] == 0
    assert out["database_lsn"] > out["leaf_index"]


@pytest.mark.spec("SR-11.3-7")
@pytest.mark.oracle(
    "A", "§11.1 tag 12 deletion_kind = 1 from the holding area; §11.3 step 7 (E2E-3.3)"
)
def test_p3_e2e_3_3_a_holding_area_deletion_verifies(verifier: Path, where: Path) -> None:
    anchors, certs = deletions(where)
    code, out = verify(certs["holding"], anchors)
    assert (code, out["accepted"], out["deletion_kind"]) == (0, True, 1), out
    assert out["group_emptied"] is False


def tlv_spans(c: bytes) -> list[tuple[int, int]]:
    """``(start, end)`` of each TLV entry of a certificate, walked by hand from §11.1."""
    spans, at = [], 0
    while at < len(c):
        n = int.from_bytes(c[at + 1 : at + 5], "big")
        spans.append((at, at + 5 + n))
        at += 5 + n
    return spans


@pytest.mark.spec("SR-11.3-8")
@pytest.mark.oracle(
    "A", "§11.3 step 8 'Accept only if every step passes'; the rejection names the step (E2E-3.2)"
)
def test_p3_e2e_3_2_a_changed_byte_is_rejected_naming_the_check(
    verifier: Path, where: Path
) -> None:
    anchors, certs = deletions(where)
    tried = 0
    for path in certs.values():
        good = path.read_bytes()
        spans = tlv_spans(good)
        assert len(spans) == 14  # tags 1–13 and the trailer
        # Every tag byte, the last length byte, and the first and last value byte of every entry.
        where_ = sorted({i for s, e in spans for i in (s, s + 4, s + 5, e - 1) if s + 5 < e})
        for i in where_:
            bad = bytearray(good)
            bad[i] ^= 0x01
            path.with_suffix(".bad").write_bytes(bytes(bad))
            code, out = verify(path.with_suffix(".bad"), anchors)
            assert (code, out["accepted"]) == (1, False), (path.name, i, out)
            assert out["step"] in range(1, 8), out
            assert out["reason"], out
            tried += 1
    assert tried > 50
