"""SDK tests (spec §16.2, Part 2 form)."""

import inspect
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

import sever_db_p2
from sever_db_p2 import Database
from sever_refmodel_durable.oracle import fixture_rows

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def db() -> Iterator[tuple[Database, str]]:
    base = ROOT / "target/sdk-tests" / uuid.uuid4().hex
    d = Database.open(base / "data", base / "keys")
    cid = d.create_collection(ROOT / "golden/p1_partition_small.svp", spawn_target=8)
    yield d, cid
    d.close()
    shutil.rmtree(base, ignore_errors=True)


@pytest.mark.spec("SR-4.2-4")
@pytest.mark.oracle(
    "A",
    "§4.2 one quantiser, the engine's: no SDK quantiser by name; a 1-ULP change is a retry",
)
def test_p2_sdk_has_no_quantiser_of_its_own_and_forwards_vectors_exactly(
    db: tuple[Database, str],
) -> None:
    # One quantiser (§4.2): the engine's. The SDK must not round, scale or renormalise.
    assert "quantis" not in inspect.getsource(sever_db_p2).lower()
    d, cid = db
    v = fixture_rows()[0].astype(np.float32)
    d.insert(cid, "a", v)
    # One float32 ULP on the smallest component is far below the Q24 step (2^-24), so the engine
    # quantises both vectors to the same x̃: the second insert is a retry of the first.
    i = int(np.argmin(np.abs(v)))
    w = v.copy()
    w[i] = np.nextafter(v[i], np.float32(1.0))
    assert w[i] != v[i]
    assert d.insert(cid, "a", w).retried


def test_p2_sdk_context_manager_closes(tmp_path_factory: pytest.TempPathFactory) -> None:
    base = ROOT / "target/sdk-tests" / uuid.uuid4().hex
    with Database.open(base / "data", base / "keys") as d:
        assert d.collections() == []
    with Database.open(base / "data", base / "keys") as d:  # the lock was released
        assert d.collections() == []
    shutil.rmtree(base, ignore_errors=True)
