"""L9 end-to-end tests of Part 2 (Build §5.7: E2E-2.1 … E2E-2.8), through the ``sever-db-p2``
process and the ``sever_db_p2`` SDK, on real files under ``target/`` (the repository's ext4 disk).

The binaries are built once per session (``--features demo`` adds the fsync fault injection of
E2E-2.5); the SDK's native module must be installed first:
``uv run --no-sync maturin develop --release --uv -m crates/sever-py-p2/Cargo.toml``.
"""

import json
import math
import random
import shutil
import signal
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from sever_db_p2 import (
    Database,
    DuplicateRecord,
    InvalidRecordId,
    NonFinite,
    NotNormalised,
    SeverError,
    UnknownCollection,
    WrongDimension,
)
from sever_refmodel_durable.oracle import fixture_rows

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "target/release/sever-db-p2"
SMALL = ROOT / "golden/p1_partition_small.svp"


@pytest.fixture(scope="session")
def built() -> Path:
    subprocess.run(
        ["cargo", "build", "-q", "--release", "-p", "sever-p2", "--features", "demo"],
        cwd=ROOT,
        check=True,
    )
    return CLI


@pytest.fixture
def where() -> Iterator[tuple[Path, Path]]:
    base = ROOT / "target/e2e" / uuid.uuid4().hex
    base.mkdir(parents=True)
    yield base / "data", base / "keys"
    shutil.rmtree(base, ignore_errors=True)


def cli(*args: str, data: Path, keys: Path, env: dict[str, str] | None = None) -> tuple[int, Any]:
    p = subprocess.run(
        [str(CLI), args[0], "--data", str(data), "--keys", str(keys), *args[1:]],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    out = p.stdout.strip().splitlines()
    return p.returncode, (json.loads(out[-1]) if out else None)


def small_db(data: Path, keys: Path) -> tuple[Database, str, np.ndarray]:
    db = Database.open(data, keys)
    cid = db.create_collection(SMALL, spawn_target=8)
    rows = fixture_rows()
    for i, v in enumerate(rows):
        db.insert(cid, f"r{i:03d}", v, passage=f"text {i}".encode())
    return db, cid, rows


def observe(db: Database, cid: str, queries: np.ndarray) -> tuple[Any, ...]:
    stats = {k: v for k, v in db.stats(cid).items() if k != "checkpoint_id"}  # a close checkpoints
    return (
        stats,
        db.group_sizes(cid),
        [db.search(cid, q, k=20) for q in queries],
    )


@pytest.mark.spec("SR-15.7-1", "SR-12.4-1")
def test_p2_e2e_2_1_close_and_reopen_changes_nothing(where: tuple[Path, Path]) -> None:
    data, keys = where
    db, cid, rows = small_db(data, keys)
    before = observe(db, cid, rows[::7])
    db.close()
    with Database.open(data, keys) as again:
        assert observe(again, cid, rows[::7]) == before


@pytest.mark.slow
@pytest.mark.spec("SR-15.7-1")
def test_p2_e2e_2_1_nq10k_close_and_reopen_changes_nothing(where: tuple[Path, Path]) -> None:
    data, keys = where
    vectors = np.load(ROOT / "datasets/processed/nq_1m/embeddings.npy", mmap_mode="r")[:10_000]
    queries = np.load(ROOT / "datasets/processed/nq_queries/embeddings.npy")[:200]
    db = Database.open(data, keys)
    cid = db.create_collection(ROOT / "artefacts/partition-seed42.svp")
    for i, v in enumerate(vectors):
        db.insert(cid, f"doc{i}", v)
    before = observe(db, cid, queries)
    assert before[0]["N"] + before[0]["holding"] == 10_000
    db.close()
    with Database.open(data, keys) as again:
        assert observe(again, cid, queries) == before


@pytest.mark.spec("SR-12.5-1", "SR-15.3-1")
def test_p2_e2e_2_2_sigkill_during_delete_user_is_all_or_nothing(
    built: Path, where: tuple[Path, Path]
) -> None:
    data, keys = where
    rc, out = cli("create", "--artefact", str(SMALL), "--spawn-target", "8", data=data, keys=keys)
    assert rc == 0, out
    cid = out["cid"]
    rc, _ = cli(
        "load", "--cid", cid, "--slice", "synthetic", "--root", str(ROOT), data=data, keys=keys
    )
    assert rc == 0
    # The fixture's cohorts (sever_p1::data::load_synthetic): rows whose number is c mod 40.
    cohorts = [
        [f"syn-{kind}-{n:03d}" for kind in ("ref", "live") for n in range(120) if n % 40 == c]
        for c in range(40)
    ]
    rnd = random.Random(42)
    killed = 0
    for cohort in cohorts[:16]:
        p = subprocess.Popen(
            [str(CLI), "delete-user", "--data", str(data), "--keys", str(keys), "--cid", cid,
             "--ids", json.dumps(cohort)],
            stdout=subprocess.DEVNULL,
        )  # fmt: skip
        time.sleep(rnd.uniform(0.0, 0.03))
        p.send_signal(signal.SIGKILL)
        killed += p.wait() == -signal.SIGKILL
        # Recovery and the full invariant check run at open; then the retry tells what survived.
        rc, out = cli(
            "delete-user", "--cid", cid, "--ids", json.dumps(cohort), data=data, keys=keys
        )
        assert rc == 0, out
        assert len(set(out["outcomes"])) == 1, f"a partial delete_user: {out['outcomes']}"
    assert killed > 0, "no process was killed mid-run"
    rc, out = cli("verify", data=data, keys=keys)
    assert (rc, out["ok"]) == (0, True)


@pytest.mark.spec("SR-15.1-2")
def test_p2_e2e_2_3_insert_retry_is_success(where: tuple[Path, Path]) -> None:
    data, keys = where
    db, cid, rows = small_db(data, keys)
    receipt = db.insert(cid, "r005", rows[5])
    assert receipt.retried, "same commitment: the SDK's success"
    assert receipt.placement is None
    with pytest.raises(DuplicateRecord) as e:
        db.insert(cid, "r005", rows[6])
    assert e.value.args == (False,)
    db.close()


@pytest.mark.spec("SR-15.4-1")
def test_p2_e2e_2_4_delete_retry_is_absent(where: tuple[Path, Path]) -> None:
    data, keys = where
    db, cid, _ = small_db(data, keys)
    assert db.delete(cid, "r010") == "deleted"
    assert db.delete(cid, "r010") == "absent"
    assert db.delete_user(cid, ["r010", "r011"]) == ["absent", "deleted"]
    db.close()


@pytest.mark.spec("SR-12.7-2")
def test_p2_e2e_2_5_failed_fsync_aborts_and_restart_recovers(
    built: Path, where: tuple[Path, Path]
) -> None:
    data, keys = where
    rc, out = cli("create", "--artefact", str(SMALL), "--spawn-target", "8", data=data, keys=keys)
    cid = out["cid"]
    vector = json.dumps([float(x) for x in fixture_rows()[0]])
    # An insert with passage text syncs the payload store (fsync 1), then the WAL (fsync 2).
    for n in (1, 2):
        fail = {"SEVER_TEST_FAIL_FSYNC_AT": str(n)}
        rc, out = cli("insert", "--cid", cid, "--id", f"x{n}", "--vector", vector, "--passage",
                      "text", data=data, keys=keys, env=fail)  # fmt: skip
        assert rc == -signal.SIGABRT, f"fsync {n}: the process must abort, got {rc} {out}"
        rc, out = cli("verify", data=data, keys=keys)
        assert (rc, out["ok"]) == (0, True), "the restart recovers a valid state"
        rc, out = cli("insert", "--cid", cid, "--id", f"x{n}", "--vector", vector,
                      data=data, keys=keys)  # fmt: skip
        retried = {"error": "DuplicateRecord(same_commitment=true)"}
        assert rc == 0 or out == retried, out


@pytest.mark.spec("SR-15.7-1")
def test_p2_e2e_2_6_disk_image_round_trip(where: tuple[Path, Path]) -> None:
    # DB-70: no root, so the image is built with mkfs.ext4 -d and read back with debugfs.
    data, keys = where
    db, cid, rows = small_db(data, keys)
    before = observe(db, cid, rows[::5])
    db.close()
    image = data.parent / "disk.img"
    subprocess.run(["mkfs.ext4", "-q", "-F", "-d", str(data), str(image), "64M"], check=True)
    out_dir = data.parent / "restored"
    out_dir.mkdir()
    subprocess.run(
        ["debugfs", "-R", f"rdump / {out_dir}", str(image)], check=True, capture_output=True
    )
    restored = out_dir if (out_dir / "MANIFEST").exists() else next(out_dir.iterdir())
    shutil.rmtree(restored / "lost+found", ignore_errors=True)
    (restored / "ENGINE.lock").unlink(missing_ok=True)
    with Database.open(restored, keys) as again:
        assert observe(again, cid, rows[::5]) == before


@pytest.mark.spec("SR-15.9-1", "SR-16.1-1")
def test_p2_e2e_2_7_dropping_one_collection_leaves_the_other(where: tuple[Path, Path]) -> None:
    data, keys = where
    db, a, rows = small_db(data, keys)
    b = db.create_collection(SMALL, spawn_target=8)
    for i, v in enumerate(rows[:100]):
        db.insert(b, f"b{i}", v)
    before = observe(db, a, rows[::9])
    db.drop_collection(b)
    assert observe(db, a, rows[::9]) == before
    assert db.collections() == [a]
    db.close()
    with Database.open(data, keys) as again:
        assert observe(again, a, rows[::9]) == before
        with pytest.raises(UnknownCollection):
            again.stats(b)


@pytest.mark.spec("SR-17-1", "SR-17-2")
def test_p2_e2e_2_8_malformed_requests_get_typed_errors_without_content(
    where: tuple[Path, Path],
) -> None:
    data, keys = where
    db, cid, rows = small_db(data, keys)
    good = rows[0]
    unit = good / np.linalg.norm(good.astype(np.float64))
    nan = good.copy()
    nan[3] = math.nan
    cases: list[tuple[type[SeverError], str, Any]] = [
        (WrongDimension, "ok-id", good[:8]),
        (NonFinite, "ok-id", nan),
        (NotNormalised, "ok-id", unit * 1.5),
        (InvalidRecordId, "", good),
        (InvalidRecordId, "z" * 257, good),
        (InvalidRecordId, "-0042", good),
    ]
    for exc, rid, vec in cases:
        with pytest.raises(exc) as e:
            db.insert(cid, rid, vec)
        text = str(e.value)
        assert not rid or rid not in text
        assert "0.0" not in text
        assert "nan" not in text.lower()
    for bad_cid in ("00" * 16, "not-hex"):
        with pytest.raises(UnknownCollection):
            db.search(bad_cid, good)
    with pytest.raises(WrongDimension):
        db.search(cid, good[:3])
    db.close()
