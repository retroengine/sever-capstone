"""The Part 3 command-line tool playing the application backend (§3.3, §16.2, §16.3; API doc:
"prints one JSON line per command (§17 errors carry no record ID, vector value, key or r_t)")."""

import base64
import json
import os
import re
import stat

import pytest

import helpers as h
import sevlib


def as_bytes(v):
    """The CLI's JSON carries the certificate as text; hex or base64 are both read."""
    if isinstance(v, list):
        return bytes(v)
    try:
        return bytes.fromhex(v)
    except ValueError:
        return base64.b64decode(v)


@pytest.fixture
def cli_db(art16):
    env = h.Env()
    out = h.cli_json(env, "create", "--artefact", h.SMALL, "--spawn-target", "8")
    return env, out["cid"]


@pytest.mark.req("SR-16.2-1", "SR-3.3-2")
def test_user_key_file_is_private():
    """API doc: `user-key --out /path/user.key  # an account key (0600)`; §3.3: the backend keeps
    the account key in its own key store."""
    path = h.user_key_file()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


@pytest.mark.req("SR-3.1-1")
def test_create_prints_a_collection_id(cli_db):
    """§3.1: "`collection_id`: 16 random bytes"; the SDK's create_collection "returns its ID (32
    hex characters)"."""
    _, cid = cli_db
    assert re.fullmatch(r"[0-9a-f]{32}", cid)


@pytest.mark.req("SR-16.2-2", "SR-15.1-5", "SR-15.3-6", "SR-5.4-2")
def test_insert_delete_and_certificate_through_the_cli(cli_db, art16, rng):
    """§16.2: "The SDK and the command-line tool report the placement as the §5.1 text form";
    §15.3 step 9: "Acknowledge with the certificate"; a retry returns AlreadyAbsent (§15.4)."""
    env, cid = cli_db
    key = h.user_key_file()
    x = sevlib.in_dist_vector(art16, rng, 3)
    ins = h.cli_json(env, "insert", "--cid", cid, "--id", "doc-1", "--vector", h.vec_arg(x),
                     "--user-key", key)
    assert ins["database_lsn"] == 0  # the first leaf of the log (§10.2)
    assert ins["placement"] == "frozen-0003"  # in-distribution for label 3 (§7.3)
    dele = h.cli_json(env, "delete", "--cid", cid, "--id", "doc-1")
    assert dele["outcome"] == "deleted" and dele["database_lsn"] == 1
    raw = as_bytes(dele["certificate"])
    later = h.cli_json(env, "certificate", "--lsn", "1")
    assert as_bytes(later["certificate"] if isinstance(later, dict) else later) == raw
    again = h.cli_json(env, "delete", "--cid", cid, "--id", "doc-1")
    assert again["outcome"] == "absent"
    anchors_path = os.path.join(h.scratch(), "anchors.json")
    assert h.cli(env, "anchors", "--out", anchors_path).returncode == 0
    anchors = json.load(open(anchors_path))
    assert anchors["d"] == 16 and bytes.fromhex(anchors["gdigest"]) == sevlib.gdigest(16)
    c = h.cert(raw)
    assert c.leaf_index == 0 and c.database_lsn == 1 and c.collection_id == bytes.fromhex(cid)
    ok, step = sevlib.verify_certificate(raw, anchors)
    assert ok, step


@pytest.mark.req("SR-16.2-2")
def test_cli_holding_then_spawned_placement(cli_db, art16, rng):
    """§7.4 / §7.5 with the collection's spawn target 8: seven OOD inserts wait in `holding`; the
    eighth flushes them into `spawn-` + 16 hex characters of SHA-256 over the sorted IDs."""
    env, cid = cli_db
    key = h.user_key_file()
    ids = [f"far-{i}" for i in range(8)]
    for i, rid in enumerate(ids):
        out = h.cli_json(env, "insert", "--cid", cid, "--id", rid, "--vector",
                         h.vec_arg(sevlib.ood_vector(art16, rng)), "--user-key", key)
        assert out["database_lsn"] == i
        assert out["placement"] == ("holding" if i < 7 else sevlib.spawn_id(ids))


@pytest.mark.req("SR-17-2", "SR-3.2-3")
def test_cli_error_output_carries_no_record_id(cli_db, art16, rng):
    """API doc: "§17 errors carry no record ID, vector value, key or `r_t`"."""
    env, cid = cli_db
    key = h.user_key_file()
    rid = "very-private-record-QQ7"
    x = h.vec_arg(sevlib.ood_vector(art16, rng))
    assert h.cli(env, "insert", "--cid", cid, "--id", rid, "--vector", x,
                 "--user-key", key).returncode == 0
    p = h.cli(env, "insert", "--cid", cid, "--id", rid, "--vector", x, "--user-key", key)
    # A second CLI insert prepares a new request (new r_t), so DuplicateRecord (§3.2 rule 3).
    assert "private-record-QQ7" not in p.stdout + p.stderr
    bad = h.cli(env, "insert", "--cid", cid, "--id", "918273645", "--vector", x, "--user-key", key)
    assert "918273645" not in bad.stdout + bad.stderr  # InvalidRecordId, §3.2 rule 2
