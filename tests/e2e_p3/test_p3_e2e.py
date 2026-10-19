"""L9 end-to-end tests of Part 3 (Build 3-4 §1.8: E2E-3.1 … E2E-3.4, E2E-3.6), through the
``sever_db_p3`` SDK and the ``sever-verify`` and ``sever-audit`` processes (``verifier/``,
``audit/``, each its own workspace), on real files under ``target/``. E2E-3.5 needs a
``test-hooks`` build (module 11); E2E-3.7 is a verifier test
(``p3_verify_an_older_verifier_rejects_a_later_epoch``); E2E-3.8 is ``python/sever_db_p3/tests``.

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
AUDIT = ROOT / "audit/target/release/sever-audit"
SMALL = ROOT / "golden/p1_partition_small.svp"
D = 16


@pytest.fixture(scope="session")
def verifier() -> Path:
    # Its own target directory, whatever CARGO_TARGET_DIR says (the proof runner sets one).
    env = dict(os.environ, CARGO_TARGET_DIR=str(ROOT / "verifier/target"))
    subprocess.run(
        ["cargo", "build", "-q", "--release", "--locked"],
        cwd=ROOT / "verifier",
        env=env,
        check=True,
    )
    return VERIFY


@pytest.fixture(scope="session")
def auditor() -> Path:
    env = dict(os.environ, CARGO_TARGET_DIR=str(ROOT / "audit/target"))
    subprocess.run(
        ["cargo", "build", "-q", "--release", "--locked"],
        cwd=ROOT / "audit",
        env=env,
        check=True,
    )
    return AUDIT


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


def run_audit(export: Path, anchors: Path, *held: Path) -> tuple[int, Any]:
    args = [str(AUDIT), str(export), "--anchors", str(anchors)]
    for h in held:
        args += ["--certificate", str(h)]
    p = subprocess.run(args, capture_output=True, text=True, check=False)
    out = p.stdout.strip().splitlines()
    return p.returncode, (json.loads(out[-1]) if out else None)


def cohort(base: Path) -> tuple[Path, Path, list[Path]]:
    """Through the SDK: records in several groups and the holding area; one account's cohort
    (two records of one group, one of another, one held) deleted by one delete_user (§15.3); then
    the export, the anchors and the cohort's certificates, with the database closed."""
    rows = fixture_rows()
    user = UserKey.generate()
    certs: list[Path] = []
    with Database.open(base / "data", base / "keys", d=D) as db:
        cid = db.create_collection(SMALL, spawn_target=8)
        for i in range(12):
            db.insert(cid, prepare_insert(cid, f"g{i}", [float(x) for x in rows[i]], user))
        db.insert(cid, prepare_insert(cid, "h0", [float(x) for x in rows[120]], user))
        sizes = dict(db.group_sizes(cid))
        assert sum(1 for n in sizes.values() if n) >= 2, "records in several groups"
        outs = db.delete_user(cid, ["g0", "g1", "g2", "g3", "h0"])
        assert [o.outcome for o in outs] == ["deleted"] * 5
        for k, o in enumerate(outs):
            assert o.certificate is not None
            certs.append(base / f"c{k}.cert")
            certs[-1].write_bytes(o.certificate)
        db.insert(cid, prepare_insert(cid, "g12", [float(x) for x in rows[12]], user))
        db.delete(cid, "g4")
        export = base / "export.json"
        export.write_text(db.export_log(), encoding="utf-8")
        anchors = base / "anchors.json"
        anchors.write_text(db.anchors(), encoding="utf-8")
    return export, anchors, certs


@pytest.mark.spec("SR-16.3-2", "SR-11.3-10")
@pytest.mark.oracle(
    "A",
    "§15.3 'consecutive certificates chain'; §11.3 the auditor checks deletion leaves, chains and "
    "log consistency; §16.3 sever-audit <log export> (E2E-3.4)",
)
def test_p3_e2e_3_4_a_cohort_deletion_chains_and_the_auditor_confirms(
    verifier: Path, auditor: Path, where: Path
) -> None:
    export, anchors, certs = cohort(where)
    for c in certs:
        code, out = verify(c, anchors)
        assert (code, out["accepted"]) == (0, True), out
    code, out = run_audit(export, anchors, *certs)
    assert (code, out["findings"]) == (0, []), out
    assert out["leaves"] == 13 + 5 + 1 + 1


@pytest.mark.spec("SR-16.3-2", "SR-11.3-10")
@pytest.mark.oracle(
    "A",
    "§11.3 'that the deletion leaf itself was appended at database_lsn' is the auditor's check; "
    "a missing deletion leaf is reported (E2E-3.6, AF-1)",
)
def test_p3_e2e_3_6_a_missing_deletion_leaf_is_reported(
    verifier: Path, auditor: Path, where: Path
) -> None:
    export, anchors, certs = cohort(where)
    e = json.loads(export.read_text(encoding="utf-8"))
    gone = next(i for i, leaf in enumerate(e["leaves"]) if leaf.startswith("02"))
    del e["leaves"][gone]
    del e["placements"][gone]
    export.write_text(json.dumps(e), encoding="utf-8")
    code, out = run_audit(export, anchors, *certs)
    assert code == 1, out
    kinds = {f["kind"] for f in out["findings"]}
    assert "AF-1" in kinds, out
    assert any(f["kind"] == "AF-1" and f["at"] == gone for f in out["findings"]), out
