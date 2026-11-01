"""Errors of §17 reachable through the interface, the artefact check (§6.3), the platform checks
(§12.9) and stopping after an IntegrityViolation (§17)."""

import hashlib
import os
import shutil
import struct
import tempfile

import pytest
import sever_db_p3 as sdk

import helpers as h
import sevlib

NO_SUCH = "00112233445566778899aabbccddeeff"  # a well-formed collection ID nobody created


def copy_artefact(mutate) -> str:
    raw = bytearray(open(h.SMALL, "rb").read())
    raw = mutate(raw)
    path = os.path.join(h.scratch(), "bad.svp")
    with open(path, "wb") as f:
        f.write(bytes(raw))
    return path


@pytest.mark.req("SR-17-1")
@pytest.mark.parametrize("op", ["insert", "delete", "delete_user", "search", "group_sizes"])
def test_unknown_collection(db16, user, art16, rng, op):
    """§17: `UnknownCollection` — "No such collection"; §15.1 step 1: "Validate: collection
    exists"."""
    db = db16.db
    x = sevlib.in_dist_vector(art16, rng)
    with pytest.raises(sdk.UnknownCollection):
        if op == "insert":
            db.insert(NO_SUCH, sdk.prepare_insert(NO_SUCH, "doc-u", x, user))
        elif op == "delete":
            db.delete(NO_SUCH, "doc-u")
        elif op == "delete_user":
            db.delete_user(NO_SUCH, ["doc-u"])
        elif op == "search":
            db.search(NO_SUCH, x, k=1)
        else:
            db.group_sizes(NO_SUCH)


@pytest.mark.req("SR-17-1")
def test_dropped_collection_is_unknown(db16, user, art16, rng):
    """§15.9 removes the collection; afterwards it is "No such collection" (§17)."""
    db, cid = db16.db, db16.cid
    h.insert(db, cid, "doc-d", sevlib.in_dist_vector(art16, rng), user)
    db.drop_collection(cid)
    assert cid not in db.collections()
    with pytest.raises(sdk.UnknownCollection):
        db.delete(cid, "doc-d")


@pytest.mark.req("SR-17-7", "SR-17-1")
@pytest.mark.parametrize("damage", ["flip_centroid", "flip_hash", "truncate", "append"])
def test_damaged_artefact_is_an_integrity_violation(env, damage):
    """§6.3: "`create_collection` MUST verify `sha256_artefact`, `d`, and that `P` has finite
    entries; a failed check is rejected with `IntegrityViolation` naming the check"."""
    def mutate(raw):
        if damage == "flip_centroid":
            raw[200] ^= 0x01  # inside the centroids: the stored SHA-256 no longer matches
        elif damage == "flip_hash":
            raw[-1] ^= 0x80  # the stored SHA-256 itself
        elif damage == "truncate":
            raw = raw[:-40]
        else:
            raw = raw + b"\x00"
        return raw

    db = h.open_db(env)
    try:
        with pytest.raises(sdk.IntegrityViolation):
            db.create_collection(copy_artefact(mutate))
    finally:
        h.quiet_close(db)


@pytest.mark.req("SR-17-7")
def test_artefact_with_non_finite_precision_is_an_integrity_violation(env):
    """§6.3: create_collection MUST verify "that `P` has finite entries"."""
    art = sevlib.parse_artefact(h.SMALL)

    def mutate(raw):
        # P starts after the centroids; it is followed only by the 32-byte hash.
        p_off = len(raw) - 32 - 8 * art.d * art.d
        raw[p_off:p_off + 8] = struct.pack(">d", float("nan"))
        body = bytes(raw[:-32])
        return bytearray(body + hashlib.sha256(body).digest())  # a valid hash over a NaN

    db = h.open_db(env)
    try:
        with pytest.raises(sdk.IntegrityViolation):
            db.create_collection(copy_artefact(mutate))
    finally:
        h.quiet_close(db)


@pytest.mark.req("SR-17-7")
def test_artefact_of_another_dimension_is_an_integrity_violation(env):
    """§6.3: create_collection MUST verify `d`; the d = 384 artefact does not fit a d = 16
    database."""
    db = h.open_db(env)
    try:
        with pytest.raises(sdk.IntegrityViolation):
            db.create_collection(h.BIG)
    finally:
        h.quiet_close(db)


@pytest.mark.req("SR-17-8")
def test_engine_stops_serving_after_an_integrity_violation(env):
    """§17: "every `IntegrityViolation` stops the engine serving: each later call, `close()`
    included, fails with `IntegrityViolation` (`§17 the engine stopped serving`)"."""
    db = h.open_db(env)
    cid = db.create_collection(h.SMALL)
    bad = copy_artefact(lambda raw: raw[:-1])
    with pytest.raises(sdk.IntegrityViolation):
        db.create_collection(bad)  # the §6.3 artefact check names it
    with pytest.raises(sdk.IntegrityViolation):
        db.collections()
    with pytest.raises(sdk.IntegrityViolation):
        db.delete(cid, "anything")
    with pytest.raises(sdk.IntegrityViolation):
        db.close()


@pytest.mark.req("SR-12.9-5", "SR-17-8")
def test_replaced_data_directory_is_detected_and_left_untouched(env, user, art16, rng):
    """§12.9: before each call the engine checks "that `data/ENGINE.lock` is still the file it
    locked ... If it is not, the call fails with `IntegrityViolation` (`§12.9 data directory
    replaced`), the engine stops serving (§17), and nothing more is written to the data
    directory." """
    db = h.open_db(env)
    cid = db.create_collection(h.SMALL)
    h.insert(db, cid, "doc-rep", sevlib.in_dist_vector(art16, rng), user)
    moved = env.data + ".moved"
    os.rename(env.data, moved)
    os.mkdir(env.data)  # a different directory now sits at the path
    with pytest.raises(sdk.IntegrityViolation):
        db.collections()
    with pytest.raises(sdk.IntegrityViolation):
        db.delete(cid, "doc-rep")
    with pytest.raises(sdk.IntegrityViolation):
        db.close()
    assert os.listdir(env.data) == []  # nothing written into the replacement


@pytest.mark.req("SR-12.9-1", "SR-17-6")
def test_data_directory_on_tmpfs_is_refused(user):
    """§12.9: "The data directory is on ext4 or XFS." §17: `PlatformUnsafe` when a §12.9 check
    fails. /tmp in this sandbox is tmpfs."""
    data = tempfile.mkdtemp(dir="/tmp")
    keys = h.scratch()
    try:
        with pytest.raises(sdk.PlatformUnsafe):
            sdk.Database.open(data, keys, d=16)
    finally:
        shutil.rmtree(data, ignore_errors=True)


@pytest.mark.req("SR-12.9-1", "SR-12.9-4")
def test_allow_unsafe_fs_overrides_the_data_directory_check(user, art16, rng):
    """§12.9: "Both filesystem checks are overridden only by `platform.allow_unsafe_fs = true`";
    the SDK's `allow_unsafe_fs` "is for development on tmpfs only"."""
    data = tempfile.mkdtemp(dir="/tmp")
    keys = h.scratch()
    try:
        db = sdk.Database.open(data, keys, d=16, allow_unsafe_fs=True)
        try:
            cid = db.create_collection(h.SMALL)
            assert h.insert(db, cid, "doc-t", sevlib.ood_vector(art16, rng), user)[1].database_lsn == 0
        finally:
            h.quiet_close(db)
    finally:
        shutil.rmtree(data, ignore_errors=True)


@pytest.mark.req("SR-12.9-1")
def test_key_directory_on_tmpfs_is_accepted_in_part_3(user, art16, rng):
    """§12.9: "the builds of Parts 2 and 3 keep their secrets in plaintext ... so they check the
    data directory only (G-40)." A key directory on tmpfs is not refused."""
    env = h.Env()
    keys = tempfile.mkdtemp(dir="/tmp")
    try:
        db = sdk.Database.open(env.data, keys, d=16)
        try:
            cid = db.create_collection(h.SMALL)
            assert h.insert(db, cid, "doc-k", sevlib.ood_vector(art16, rng), user)[1].database_lsn == 0
        finally:
            h.quiet_close(db)
    finally:
        shutil.rmtree(keys, ignore_errors=True)


@pytest.mark.req("SR-12.9-2")
def test_engine_lock_excludes_a_second_process(env, user, art16, rng):
    """§12.9: "`ENGINE.lock` is taken exclusively (one process per data directory)." While this
    process holds the database, the CLI cannot use it, and the holder is unaffected."""
    db = h.open_db(env)
    try:
        cid = db.create_collection(h.SMALL)
        h.insert(db, cid, "doc-l0", sevlib.ood_vector(art16, rng), user)  # leaf 0
        key = h.user_key_file()
        vec = h.vec_arg(sevlib.ood_vector(art16, rng))
        p = h.cli(env, "insert", "--cid", cid, "--id", "doc-cli", "--vector", vec,
                  "--user-key", key)
        assert p.returncode != 0
        # The holder still serves, and the CLI added no leaf: the next insert is leaf 1.
        assert h.insert(db, cid, "doc-l1", sevlib.ood_vector(art16, rng), user)[1].database_lsn == 1
    finally:
        h.quiet_close(db)


@pytest.mark.req("SR-10.2-3", "SR-10.5-1")
def test_dropping_a_collection_does_not_shorten_the_log(db16, user, art16, rng):
    """§3.1: "The transparency log is shared by the whole database"; §10.1: "One append-only
    Merkle log per database". Dropping a collection removes no leaf."""
    db = db16.db
    for i in range(3):
        h.insert(db, db16.cid, f"dr-{i}", sevlib.ood_vector(art16, rng), user)  # leaves 0–2
    db.drop_collection(db16.cid)
    cid2 = db.create_collection(h.SMALL)
    assert h.insert(db, cid2, "after-drop", sevlib.ood_vector(art16, rng), user)[1].database_lsn == 3
