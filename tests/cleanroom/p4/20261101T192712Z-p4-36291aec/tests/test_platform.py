"""§12.8 memory hygiene and §12.9 platform checks at startup."""

import os
import subprocess
import sys
import tempfile
import textwrap

import pytest

import helpers as h
from sever_db import Database, IntegrityViolation, PlatformUnsafe


def _tmpfs_dir():
    for base in ("/tmp", "/dev/shm"):
        if os.path.isdir(base) and h.fs_type(base) == "tmpfs":
            return tempfile.mkdtemp(dir=base)
    pytest.skip("no tmpfs mount on this machine")


@pytest.mark.req("SR-12.8-4", "SR-12.8-6", "SR-17-6")
def test_unsafe_memory_refused_without_override(dirs):
    """§12.8: "The engine refuses to start if swap is enabled and not encrypted, or if hibernation is
    enabled, unless memory.allow_unsafe_memory = true" and "If locking memory fails ..., the engine
    refuses to start (PlatformUnsafe ...)"."""
    data, keys = dirs
    # The test machine has unencrypted swap and cannot lock memory (PROMPT), so both §12.8 checks
    # fail; without the override the only allowed outcome is PlatformUnsafe (§17 row).
    with pytest.raises(PlatformUnsafe):
        Database.open(data, keys, d=16)


@pytest.mark.req("SR-12.8-6", "SR-12.9-4")
def test_fs_override_does_not_cover_memory_checks(dirs):
    """§12.8: "allow_unsafe_memory covers this section's checks only; the filesystem checks of §12.9
    have their own flag" — so the §12.9 flag cannot stand in for the §12.8 one."""
    data, keys = dirs
    # allow_unsafe_fs overrides the filesystem checks only; the §12.8 failures remain → PlatformUnsafe.
    with pytest.raises(PlatformUnsafe):
        Database.open(data, keys, d=16, allow_unsafe_fs=True, allow_unsafe_memory=False)


@pytest.mark.req("SR-12.8-4", "SR-12.8-6")
def test_memory_override_opens_and_is_reported(dirs):
    """§12.8: the override "is for development only and is recorded"; API: "every override used is
    reported in db.startup"."""
    data, keys = dirs
    db = h.open_db(data, keys)
    try:
        overridden, locked = db.startup
        # §12.8 checks fail on this machine and were overridden → at least one entry is listed.
        assert len(overridden) >= 1
        # Memory cannot be locked here (PROMPT) → the report must not claim it is locked.
        assert locked is False
    finally:
        db.close()


@pytest.mark.req("SR-12.9-3", "SR-17-6")
def test_key_dir_on_tmpfs_refused(root):
    """§12.9: "The key file's filesystem overwrites in place. It is an allow-list: ext4, XFS, and btrfs
    ... Anything else (... tmpfs ...) is refused." Before KEYS exists the key directory decides."""
    data = os.path.join(root, "data")
    os.mkdir(data)
    keys = _tmpfs_dir()
    try:
        # Memory override given (it covers §12.8 only) but no fs override → the key-dir check of
        # §12.9 still fails → PlatformUnsafe (§17).
        with pytest.raises(PlatformUnsafe):
            h.open_db(data, keys)
    finally:
        h.rmtree(keys)


@pytest.mark.req("SR-12.9-1", "SR-17-6")
def test_data_dir_on_tmpfs_refused(root):
    """§12.9: "The data directory is on ext4 or XFS." tmpfs is neither."""
    keys = os.path.join(root, "keys")
    os.mkdir(keys)
    data = _tmpfs_dir()
    try:
        # §12.9 data-directory check fails; allow_unsafe_memory does not cover it (§12.8 last bullet).
        with pytest.raises(PlatformUnsafe):
            h.open_db(data, keys)
    finally:
        h.rmtree(data)


@pytest.mark.req("SR-12.9-4", "SR-12.9-3")
def test_fs_override_opens_tmpfs_key_dir_and_is_reported(root):
    """§12.9: "Both filesystem checks are overridden only by platform.allow_unsafe_fs = true, which is
    for development only and is recorded"."""
    d1, k1 = h.new_dirs(os.path.join(root))
    db = h.open_db(d1, k1)
    base_overrides = len(db.startup[0])  # memory overrides only (ext4 key dir passes §12.9)
    db.close()

    data = os.path.join(root, "data2")
    os.mkdir(data)
    keys = _tmpfs_dir()
    try:
        db = h.open_db(data, keys, allow_unsafe_fs=True)
        try:
            # The tmpfs key-dir check failed and was overridden, so one more override is reported
            # than on the all-ext4 open with the same memory override.
            assert len(db.startup[0]) > base_overrides
            cid = db.create_collection(h.SMALL_SVP)
            assert cid in db.collections()
        finally:
            db.close()
    finally:
        h.rmtree(keys)


@pytest.mark.req("SR-12.9-2")
def test_engine_lock_is_exclusive_across_processes(dirs):
    """§12.9: "ENGINE.lock is taken exclusively (one process per data directory)."""
    data, keys = dirs
    script = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {os.path.dirname(h.__file__)!r})
        import helpers as h
        db = h.open_db({data!r}, {keys!r})
        print("ready", flush=True)
        sys.stdin.readline()
        db.close()
        """
    )
    child = subprocess.Popen(
        [sys.executable, "-c", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    )
    try:
        assert child.stdout.readline().strip() == "ready"
        # A second process (this one) must not open the same data directory while the child holds
        # the lock. The spec does not name the error (NOTES.md), only that it cannot open.
        with pytest.raises(Exception):
            h.open_db(data, keys)
    finally:
        try:
            child.stdin.write("\n")
            child.stdin.flush()
        except BrokenPipeError:
            pass
        child.wait(timeout=120)
    assert child.returncode == 0
    # Once the child closed (lock released), this process can open it.
    h.open_db(data, keys).close()


@pytest.mark.req("SR-12.9-5", "SR-17-8")
def test_replaced_data_directory_stops_serving(dirs):
    """§12.9: "before each call ... check that data/ENGINE.lock is still the file it locked ... If it
    is not, the call fails with IntegrityViolation (§12.9 data directory replaced), the engine stops
    serving (§17), and nothing more is written to the data directory."""
    data, keys = dirs
    db = h.open_db(data, keys)
    db.create_collection(h.SMALL_SVP)
    os.rename(data, data + ".moved")
    os.mkdir(data)  # a different directory now sits at the path
    with pytest.raises(IntegrityViolation) as e:
        db.collections()
    # §12.9 names the check: "§12.9 data directory replaced".
    assert "data directory replaced" in str(e.value)
    # §17: "each later call, close() included, fails with IntegrityViolation ... and writes nothing".
    with pytest.raises(IntegrityViolation):
        db.collections()
    with pytest.raises(IntegrityViolation):
        db.close()
    # Nothing was written into the replacement directory.
    assert os.listdir(data) == []


@pytest.mark.req("SR-12.9-4", "SR-12.9-3")
def test_unused_fs_override_not_reported(root):
    """§12.9: the filesystem override is "recorded" when used; API: startup lists "the startup checks
    that failed and were overridden". On ext4 both §12.9 filesystem checks pass, so giving
    allow_unsafe_fs adds nothing to the report."""
    os.mkdir(os.path.join(root, "a"))
    d1, k1 = h.new_dirs(os.path.join(root, "a"))
    db = h.open_db(d1, k1)
    mem_only = db.startup[0]
    db.close()
    os.mkdir(os.path.join(root, "b"))
    d2, k2 = h.new_dirs(os.path.join(root, "b"))
    db = h.open_db(d2, k2, allow_unsafe_fs=True)
    try:
        # Same failed checks (the §12.8 ones only) → the same number of overrides reported.
        assert len(db.startup[0]) == len(mem_only)
    finally:
        db.close()
