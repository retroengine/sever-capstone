"""Part 3's SDK tests on the final build (spec §16.2; F-5 regression by reuse; their labels and
proofs stay with Part 3). Signatures and certificates are checked
with the certificate reference model (``sever_refmodel_certs``), which shares no code with the
engine."""

import json
import pickle
import random
import re
import shutil
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
import pytest

from sever_db import (
    BadUserSignature,
    Database,
    DuplicateRecord,
    NotNormalised,
    SeededNonceForbidden,
    UserKey,
    WrongDimension,
    prepare_insert,
)
from sever_refmodel_certs import cert, ed25519
from sever_refmodel_certs.ristretto import IDENTITY, decode
from sever_refmodel_durable.oracle import fixture_rows

ROOT = Path(__file__).resolve().parents[3]
ARTEFACT = ROOT / "golden/p1_partition_small.svp"
D = 16


@pytest.fixture
def db() -> Iterator[tuple[Database, str]]:
    base = ROOT / "target/sdk-tests-p4" / uuid.uuid4().hex
    d = Database.open(base / "data", base / "keys", d=D, allow_unsafe_memory=True)
    cid = d.create_collection(ARTEFACT, spawn_target=8)
    yield d, cid
    d.close()
    shutil.rmtree(base, ignore_errors=True)


def rows(n: int) -> list[list[float]]:
    return [[float(x) for x in r] for r in fixture_rows()[:n]]


def anchors(db: Database) -> cert.Anchors:
    a = json.loads(db.anchors())
    return cert.Anchors(
        operators={int(e): bytes.fromhex(k) for e, k in a["operator"].items()},
        witnesses={
            (i, int(e)): bytes.fromhex(k)
            for i, ring in enumerate(a["witnesses"])
            for e, k in ring.items()
        },
        d=a["d"],
    )


def test_p4_sdk_refuses_every_attempt_to_pass_randomness(db: tuple[Database, str]) -> None:
    d, cid = db
    user = UserKey.generate()
    v = rows(1)[0]
    attempts: list[Callable[[], object]] = [
        lambda: UserKey.generate(seed=42),
        lambda: UserKey.generate(random.Random(42)),
        lambda: prepare_insert(cid, "a", v, user, rng=random.Random(42)),
        lambda: prepare_insert(cid, "a", v, user, b"\x00" * 32),
        lambda: d.insert(cid, prepare_insert(cid, "a", v, user), None, seed=7),
        lambda: Database.open(ROOT / "target", ROOT / "target", D, False, nonce=b"\x01" * 64),
    ]
    for attempt in attempts:
        with pytest.raises(SeededNonceForbidden):
            attempt()
    assert d.stats(cid)["N"] == 0, "a refused insert inserted nothing"
    # Deletion is where the engine makes a proof (§9.6): no RNG, seed or nonce can reach it.
    d.insert(cid, prepare_insert(cid, "a", v, user))
    deletions: list[Callable[[], object]] = [
        lambda: d.delete(cid, "a", nonce=b"\x00" * 32),
        lambda: d.delete(cid, "a", np.random.default_rng(1)),
        lambda: d.delete_user(cid, ["a"], rng=random.Random(1)),
        lambda: d.delete_user(cid, ["a"], 1234),
    ]
    for attempt in deletions:
        with pytest.raises(SeededNonceForbidden):
            attempt()
    assert d.stats(cid)["N"] == 1, "a refused deletion deleted nothing"
    assert d.delete(cid, "a").outcome == "deleted"


def test_p4_sdk_prepare_insert_signs_the_collection_and_commitment(
    db: tuple[Database, str],
) -> None:
    d, cid = db
    user = UserKey.generate()
    assert user.public_key == ed25519.public_key(user.secret_bytes())
    req = prepare_insert(cid, "doc-1", rows(1)[0], user)
    assert (req.collection_id, req.record_id) == (cid, "doc-1")
    assert req.user_public_key == user.public_key
    msg = cert.insert_message(bytes.fromhex(cid), req.c_t)
    assert len(msg) == 65
    assert ed25519.verify(user.public_key, msg, req.signature)
    # The engine accepts it: the first leaf of the log (§10.2) is this insert's.
    receipt = d.insert(cid, req)
    assert (receipt.database_lsn, receipt.retried) == (0, False)
    # A stored key signs the same way (Ed25519 is deterministic, RFC 8032).
    again = UserKey.from_secret_bytes(user.secret_bytes())
    assert again.public_key == user.public_key


def test_p4_sdk_draws_a_fresh_r_t_for_every_request(db: tuple[Database, str]) -> None:
    _, cid = db
    user = UserKey.generate()
    v = rows(1)[0]
    cts = {prepare_insert(cid, "a", v, user).c_t for _ in range(8)}
    assert len(cts) == 8, "same vector, same record: a fresh r_t gives a fresh C_t every time"
    for c_t in cts:
        assert not decode(c_t).equals(IDENTITY)


def test_p4_sdk_and_engine_quantise_alike(db: tuple[Database, str]) -> None:
    d, cid = db
    user = UserKey.generate()
    for i, v in enumerate(rows(24)):
        assert d.insert(cid, prepare_insert(cid, f"r{i}", v, user)).database_lsn == i


def test_p4_sdk_retry_with_the_same_request_is_success(db: tuple[Database, str]) -> None:
    d, cid = db
    user = UserKey.generate()
    v = rows(1)[0]
    req = prepare_insert(cid, "a", v, user)
    assert d.insert(cid, req).database_lsn == 0
    assert d.insert(cid, req).retried
    with pytest.raises(DuplicateRecord) as other:
        d.insert(cid, prepare_insert(cid, "a", v, user))  # a fresh r_t: another C_t
    assert other.value.args == (False,)
    assert d.stats(cid)["N"] == 1


# E2E-4.6 (insert, search, delete, verify; the scan step of E2E-4.6 and E2E-4.1/4.2 run in EX-2,
# `gates p4-forensics`, on a raw ext4 image).
def test_p4_sdk_delete_returns_a_certificate_that_verifies(db: tuple[Database, str]) -> None:
    d, cid = db
    user = UserKey.generate()
    for i, v in enumerate(rows(4)):
        d.insert(cid, prepare_insert(cid, f"r{i}", v, user))
    out = d.delete(cid, "r2")  # no r_t argument (§16.2)
    assert out.outcome == "deleted"
    assert out.certificate is not None
    cert.verify(out.certificate, anchors(d))
    assert out.database_lsn == 4, "leaves 0–3 are the inserts; the delete leaf is 4 (§11.1 tag 10)"
    assert d.certificate(out.database_lsn) == out.certificate
    assert d.delete(cid, "r2").outcome == "absent"
    both = d.delete_user(cid, ["r0", "r1", "missing"])
    assert [o.outcome for o in both] == ["deleted", "deleted", "absent"]
    for o in both[:2]:
        assert o.certificate is not None
        cert.verify(o.certificate, anchors(d))


def test_p4_sdk_a_request_is_bound_to_its_collection(db: tuple[Database, str]) -> None:
    d, a = db
    b = d.create_collection(ARTEFACT, spawn_target=8)
    user = UserKey.generate()
    req = prepare_insert(a, "x", rows(1)[0], user)
    with pytest.raises(BadUserSignature):
        d.insert(b, req)
    assert d.stats(b)["N"] == 0
    assert d.insert(a, req).database_lsn == 0, "the engine still serves"


def test_p4_sdk_r_t_and_keys_never_reach_python_text(db: tuple[Database, str]) -> None:
    _, cid = db
    user = UserKey.generate()
    req = prepare_insert(cid, "secret-id", rows(1)[0], user)
    assert not any("r_t" in n or n == "vector" for n in dir(req))
    assert "secret-id" not in repr(req)
    assert user.secret_bytes().hex() not in repr(user)
    with pytest.raises(TypeError):
        pickle.dumps(req)


def test_p4_sdk_errors_are_typed(db: tuple[Database, str]) -> None:
    d, cid = db
    user = UserKey.generate()
    with pytest.raises(NotNormalised):
        prepare_insert(cid, "a", [0.5] * D, user)
    # The request's dimension is its vector's (DB-84); the engine refuses another (§4.1 step 0).
    v = np.zeros(384, dtype=np.float32)
    v[0] = 1.0
    with pytest.raises(WrongDimension):
        d.insert(cid, prepare_insert(cid, "a", v.tolist(), user))
    with pytest.raises(TypeError):
        prepare_insert(cid, "a", rows(1)[0], user._k)  # type: ignore[arg-type]


def test_p4_sdk_the_user_key_is_published_with_every_insert(db: tuple[Database, str]) -> None:
    d, cid = db
    alice, bob = UserKey.generate(), UserKey.generate()
    vs = rows(3)
    d.insert(cid, prepare_insert(cid, "a0", vs[0], alice))
    d.insert(cid, prepare_insert(cid, "b0", vs[1], bob))
    stored = UserKey.from_secret_bytes(alice.secret_bytes())  # the backend's key store
    d.insert(cid, prepare_insert(cid, "a1", vs[2], stored))
    for rid, key in [("a0", alice), ("b0", bob), ("a1", alice)]:
        c = d.delete(cid, rid).certificate
        assert c is not None
        leaf = cert.parse(c, D).inclusion.leaf
        assert leaf[113:145] == key.public_key, rid


def test_p4_sdk_delete_takes_no_key_signature_or_r_t(db: tuple[Database, str]) -> None:
    d, cid = db
    owner = UserKey.generate()
    d.insert(cid, prepare_insert(cid, "a", rows(1)[0], owner))
    del owner  # the backend authorised the deletion; nothing of the account is passed in
    assert d.delete(cid, "a").outcome == "deleted"
    assert d.delete_user(cid, ["a"])[0].outcome == "absent"


def test_p4_sdk_reports_its_overrides_and_keeps_passage_text_off_disk() -> None:
    base = ROOT / "target/sdk-tests-p4" / uuid.uuid4().hex
    text = b"a passage that must never reach the disk in the clear, scanned for below"
    with Database.open(base / "data", base / "keys", d=D, allow_unsafe_memory=True) as d:
        overridden, locked = d.startup
        assert all(c.startswith("§12.8") for c in overridden)
        assert locked == ("§12.8 mlock" not in overridden)
        cid = d.create_collection(ARTEFACT, spawn_target=8)
        user = UserKey.generate()
        d.insert(cid, prepare_insert(cid, "doc-1", rows(1)[0], user), passage=text)
        d.delete(cid, "doc-1")
    on_disk = b"".join(p.read_bytes() for p in base.rglob("*") if p.is_file())
    assert text[:32] not in on_disk
    shutil.rmtree(base, ignore_errors=True)


@pytest.mark.spec("SR-16.2-2")
@pytest.mark.oracle(
    "A",
    "§16.2 (G-38) 'the placement is the §5.1 text form of the group'; §5.1 table: frozen-NNNN, "
    "spawn- + 16 lowercase hex characters, holding",
)
def test_p4_sdk_reports_the_placement_as_the_groups_text_form(db: tuple[Database, str]) -> None:
    d, cid = db
    user = UserKey.generate()
    placed = [d.insert(cid, prepare_insert(cid, f"r{i}", v, user)).placement for i, v in
              enumerate(rows(40))]  # fmt: skip
    groups = {g for g, _ in d.group_sizes(cid)}
    grammar = re.compile(r"frozen-[0-9]{4}|spawn-[0-9a-f]{16}|holding")
    assert all(p is not None and grammar.fullmatch(p) for p in placed), placed
    assert all(p in groups or p == "holding" for p in placed)
    assert any(p.startswith("frozen-") for p in placed if p)
    assert "holding" in placed
