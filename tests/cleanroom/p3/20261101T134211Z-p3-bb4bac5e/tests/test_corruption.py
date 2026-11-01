"""Damaged files on disk (§12.3, §12.7, §14.8, §14.9, §15.7, §17): the engine refuses with
IntegrityViolation or serves exactly what was committed — never altered data."""

import glob
import os
import shutil
import struct

import pytest
import sever_db_p3 as sdk

import helpers as h
import sevlib


class Built:
    """A closed database: 3 records in frozen-0000, then two deletions (leaves 3 and 4)."""

    def __init__(self, user, art, rng):
        self.env = h.Env()
        db = h.open_db(self.env)
        self.cid = db.create_collection(h.SMALL)
        self.reqs = [h.insert(db, self.cid, f"c-{i}", sevlib.in_dist_vector(art, rng, 0), user)[0]
                     for i in range(3)]  # leaves 0, 1, 2
        self.cert3 = db.delete(self.cid, "c-0").certificate  # leaf 3
        self.cert4 = db.delete(self.cid, "c-1").certificate  # leaf 4
        self.cp = db.latest_log_checkpoint()
        db.close()  # clean shutdown: a storage checkpoint (§12.4)

    def clone(self) -> h.Env:
        e = h.Env()
        shutil.rmtree(e.data)
        shutil.rmtree(e.keys)
        shutil.copytree(self.env.data, e.data)
        shutil.copytree(self.env.keys, e.keys)
        return e


@pytest.fixture
def built(user, art16, rng):
    return Built(user, art16, rng)


def store_records(path):
    """§14.8 after the 16-byte §14.9 header: u64be key ‖ u32be len ‖ bytes ‖ u32be crc32c."""
    raw = open(path, "rb").read()
    off, recs = 16, []
    while off + 12 <= len(raw):
        key, ln = struct.unpack(">QI", raw[off:off + 12])
        if off + 12 + ln + 4 > len(raw):
            break
        recs.append((key, off + 12, ln))  # (key, value offset, value length)
        off += 12 + ln + 4
    return recs


def flip(path, pos):
    with open(path, "r+b") as f:
        f.seek(pos)
        b = f.read(1)
        f.seek(pos)
        f.write(bytes([b[0] ^ 0x5A]))


def observe(e: h.Env, b: Built):
    """Opens and reads back; returns 'refused' on IntegrityViolation at open or on a read
    (§17: after one, the engine stops serving), else 'served'. Any read that succeeds must equal
    what was committed."""
    try:
        db = h.open_db(e)
    except sdk.IntegrityViolation:
        return "refused"
    try:
        try:
            c3 = db.certificate(3)
            # Leaf 3's certificate is not the certificate store's last record, so §12.3 allows
            # no silent drop: exactly the committed bytes.
            assert c3 == b.cert3
            c4 = db.certificate(4)
            # The last record may be dropped as a torn append (§12.3, §14.8), never altered.
            assert c4 in (b.cert4, None)
            assert db.insert(b.cid, b.reqs[2]).retried  # c-2 is still live, same C_t
            assert db.delete(b.cid, "c-0").outcome == "absent"
            # Deleting the live c-2 reads its insert leaf (§15.3 step 2) and the log.
            out = db.delete(b.cid, "c-2")
            assert out.outcome == "deleted"
            c = h.cert(out.certificate)
            assert c.c_t == b.reqs[2].c_t and c.leaf_index == 2
            assert c.cs_pre == b.reqs[2].c_t and c.emptied == 1  # c-2 was the last member
            return "served"
        except sdk.IntegrityViolation:
            return "refused"
    finally:
        h.quiet_close(db)


@pytest.mark.req("SR-17-7", "SR-10.5-1")
def test_damage_before_the_last_certificate_record_is_refused(built):
    """§12.3: "Damage anywhere before it [a store's last record], a lost or emptied store file ...
    are `IntegrityViolation` (G-51)." Here a byte inside the first certificate record flips."""
    e = built.clone()
    stores = sorted(glob.glob(os.path.join(e.data, "certs", "*.store")))
    assert stores, "§14.1 names certs/<seq>.store"
    target = None
    for s in stores:
        recs = store_records(s)
        for i, (key, voff, ln) in enumerate(recs):
            if key == 3 and (i < len(recs) - 1 or s != stores[-1]):
                target = (s, voff + ln // 2)
    assert target, "the certificate at database_lsn 3 is a store record before the last"
    flip(*target)
    assert observe(e, built) == "refused"


@pytest.mark.req("SR-17-7", "SR-10.5-1")
@pytest.mark.parametrize("area", ["certs", "log/hashes", "log/leaves"])
def test_emptied_store_file_is_refused(built, area):
    """§12.3: "a lost or emptied store file ... [is] `IntegrityViolation` (G-51)." """
    e = built.clone()
    stores = sorted(glob.glob(os.path.join(e.data, area, "*.store")))
    assert stores, f"§14.1 names {area}/<seq>.store"
    for s in stores:
        open(s, "wb").close()  # emptied
    assert observe(e, built) == "refused"


@pytest.mark.req("SR-17-7", "SR-21-15")
def test_damaged_leaf_hash_record_is_refused(built):
    """§15.7 step 6: "the log root equals the latest log checkpoint's root at that size. Refuse to
    serve on any violation." §12.3: damage before a store's last record is IntegrityViolation."""
    e = built.clone()
    stores = sorted(glob.glob(os.path.join(e.data, "log", "hashes", "*.store")))
    recs = [(s, r) for s in stores for r in store_records(s)]
    assert len(recs) >= 2  # five leaves were committed
    s, (_, voff, ln) = recs[0]  # leaf 0's record: not the last
    flip(s, voff + ln // 2)
    assert observe(e, built) == "refused"


@pytest.mark.req("SR-17-7")
@pytest.mark.parametrize("how", ["flip", "truncate"])
def test_damaged_manifest_is_refused(built, how):
    """§14.9: `MANIFEST` carries a CRC-32C; "Every parser rejects a wrong magic, version,
    `sealer_id`, CRC ..." — an IntegrityViolation (§17)."""
    e = built.clone()
    path = os.path.join(e.data, "MANIFEST")
    if how == "flip":
        flip(path, 20)  # inside checkpoint_id / first_wal_seq: the CRC no longer matches
    else:
        with open(path, "r+b") as f:
            f.truncate(10)
    assert observe(e, built) == "refused"


@pytest.mark.req("SR-17-7")
def test_damaged_storage_checkpoint_file_is_refused(built):
    """§14.9: storage checkpoint files are paged and checked; "Every parser rejects a wrong magic,
    version, `sealer_id`, CRC, count, order, padding or any trailing byte." """
    e = built.clone()
    files = glob.glob(os.path.join(e.data, "checkpoint", "*", "groups.bin"))
    assert files, "§14.1 names checkpoint/<id>/groups.bin"
    path = files[0]
    flip(path, os.path.getsize(path) // 2)
    assert observe(e, built) == "refused"


@pytest.mark.req("SR-17-7")
def test_damaged_secrets_file_is_refused(built):
    """§14.9: `SECRETS` ends with a CRC-32C covering every preceding byte; a damaged file must not
    be used to sign (§12.7: "Every record on disk has a CRC-32C")."""
    e = built.clone()
    path = os.path.join(e.keys, "SECRETS")
    assert os.path.exists(path)
    flip(path, 30)
    assert observe(e, built) == "refused"


@pytest.mark.req("SR-17-7", "SR-15.3-5")
def test_no_single_byte_flip_anywhere_yields_altered_data(built):
    """§12.7: "Every record on disk has a CRC-32C; every file has a magic number and a format
    version." Whatever byte of whatever data file is damaged, the engine either refuses with
    IntegrityViolation or serves the committed state (§12.3 allows only a torn last record or a
    discarded WAL tail transaction to vanish)."""
    files = []
    for root, _, names in os.walk(built.env.data):
        for n in names:
            if n != "ENGINE.lock":
                files.append(os.path.relpath(os.path.join(root, n), built.env.data))
    assert files
    for rel in sorted(files):
        size = os.path.getsize(os.path.join(built.env.data, rel))
        for pos in sorted({0, size // 3, size // 2, size - 1} - {-1}):
            if size == 0:
                continue
            e = built.clone()
            flip(os.path.join(e.data, rel), pos)
            try:
                outcome = observe(e, built)
            except AssertionError as err:
                raise AssertionError(f"{rel} byte {pos}: altered data served: {err}") from None
            assert outcome in ("refused", "served"), rel
