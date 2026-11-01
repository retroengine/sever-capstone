"""Engine-facing helpers for the tests (public SDK and CLI only)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass

import sever_db_p3 as sdk

import sevlib

INPUTS = os.environ["SEVER_INPUTS"]
SMALL = os.path.join(INPUTS, "p1_partition_small.svp")  # d = 16, 4 groups
BIG = os.path.join(INPUTS, "partition-seed42.svp")  # d = 384, 128 groups
CLI = os.environ["SEVER_CLI"]


def scratch() -> str:
    return tempfile.mkdtemp(dir=os.environ["SEVER_SCRATCH"])


class Env:
    """A data folder and a key folder, both new and on ext4."""

    def __init__(self) -> None:
        root = scratch()
        self.root = root
        self.data = os.path.join(root, "data")
        self.keys = os.path.join(root, "keys")
        os.mkdir(self.data)
        os.mkdir(self.keys)


def open_db(env: Env, d: int = 16, **kw) -> sdk.Database:
    return sdk.Database.open(env.data, env.keys, d=d, **kw)


def quiet_close(db) -> None:
    try:
        db.close()
    except Exception:
        pass


@dataclass
class Ctx:
    env: Env
    db: sdk.Database
    cid: str


def insert(db, cid, rid, vec, user, passage=None):
    """prepare_insert then insert; returns (request, receipt)."""
    req = sdk.prepare_insert(cid, rid, vec, user)
    return req, db.insert(cid, req, passage)


def prepare_and_insert(db, cid, rid, vec, user):
    """For error tests: §16.2 lets the SDK or the engine raise a validation error, so both calls
    sit inside the caller's pytest.raises block."""
    req = sdk.prepare_insert(cid, rid, vec, user)
    return db.insert(cid, req)


def next_lsn(db, cid, user, art, rng) -> int:
    """The database_lsn the next insert receives = the current number of log leaves (§10.2).
    It inserts a fresh holding-area probe record, so call it only at the end of a test."""
    rid = "probe-" + os.urandom(6).hex()
    _, rec = insert(db, cid, rid, sevlib.ood_vector(art, rng), user)
    return rec.database_lsn


def total_group_n(db, cid) -> int:
    """Σ n over frozen and spawned groups (holding area excluded, §2.1 N)."""
    return sum(n for _, n in db.group_sizes(cid))


def cert(raw: bytes, d: int = 16) -> sevlib.Certificate:
    return sevlib.parse_certificate(raw, d)


def anchors(db) -> dict:
    return json.loads(db.anchors())


def cli(env: Env, *args, d: int = 16, timeout: float = 120):
    """Runs the CLI with --data/--keys/--d after the subcommand (API doc); returns the process."""
    sub, rest = args[0], list(args[1:])
    cmd = [CLI, sub, "--data", env.data, "--keys", env.keys, "--d", str(d)] + rest
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def cli_bare(*args, timeout: float = 120):
    """Runs a CLI subcommand that takes no database options (`user-key`)."""
    return subprocess.run([CLI, *args], capture_output=True, text=True, timeout=timeout)


def user_key_file() -> str:
    """`sever-db-p3 user-key --out FILE`: an account key file (API doc)."""
    path = os.path.join(scratch(), "user.key")
    p = cli_bare("user-key", "--out", path)
    assert p.returncode == 0, p.stderr[-2000:]
    return path


def vec_arg(v) -> str:
    return "[" + ",".join(repr(float(x)) for x in v) + "]"


def cli_json(env: Env, *args, d: int = 16) -> dict:
    p = cli(env, *args, d=d)
    assert p.returncode == 0, (p.returncode, p.stderr[-2000:])
    lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
    return json.loads(lines[-1])


def py_subprocess(code: str, cwd: str) -> subprocess.Popen:
    """Runs SDK code in a child Python (inherits PYTHONPATH), stdout line-buffered."""
    return subprocess.Popen([sys.executable, "-u", "-c", code], cwd=cwd,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
