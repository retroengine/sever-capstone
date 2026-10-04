import json
from datetime import datetime
from pathlib import Path

import pytest

from sever_demo.ledger import append, describe, open_ledger, read_entries, run_context


def test_ledger_appends_and_never_rewrites(tmp_path: Path) -> None:
    # T13 (Overview §13.3): two runs give two lines, and the first line's bytes never change.
    path = tmp_path / "RUN_LEDGER.jsonl"
    with open_ledger(path) as handle:
        append(handle, {"run": 1, "outcome": "PASS"})
    first = path.read_bytes()

    with open_ledger(path) as handle:
        append(handle, {"run": 2, "outcome": "FAIL"})
    both = path.read_bytes()

    assert both.startswith(first)
    lines = both.decode("utf-8").splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["run"] for line in lines] == [1, 2]
    assert [e["outcome"] for e in read_entries(path, last=1)] == ["FAIL"]


def test_ledger_line_bytes_do_not_depend_on_key_order(tmp_path: Path) -> None:
    path = tmp_path / "RUN_LEDGER.jsonl"
    with open_ledger(path) as handle:
        append(handle, {"b": 1, "a": 2})
        append(handle, {"a": 2, "b": 1})
    one, two = path.read_text(encoding="utf-8").splitlines()
    assert one == two


def test_ledger_context_has_the_planned_fields() -> None:
    # DEMO_PLAN §5.8: the fields known when a run starts (outcome, counts and the result file are
    # added at the end). Times: UTC and IST (+05:30) for the same instant.
    entry = run_context("test", seed=42, sabotage="none")
    for key in [
        "ts_utc",
        "ts_ist",
        "command",
        "git_commit",
        "git_dirty",
        "seed",
        "dataset_manifest_sha256",
        "platform",
        "sabotage",
    ]:
        assert key in entry, key
    assert set(entry["platform"]) == {"python", "numpy", "os"}
    assert entry["ts_utc"].endswith("+00:00")
    assert entry["ts_ist"].endswith("+05:30")
    utc = datetime.fromisoformat(entry["ts_utc"])
    assert utc == datetime.fromisoformat(entry["ts_ist"])
    assert len(entry["git_commit"]) == 40
    assert len(entry["dataset_manifest_sha256"]) == 64
    assert isinstance(entry["git_dirty"], bool)


def test_ledger_unwritable_stops_the_run(tmp_path: Path) -> None:
    # The run must not start if the ledger cannot be opened: a directory is not a writable file.
    blocked = tmp_path / "RUN_LEDGER.jsonl"
    blocked.mkdir()
    with pytest.raises(IsADirectoryError):
        open_ledger(blocked)


def test_describe_old_and_new_lines() -> None:
    # Lines written before 3 Oct have no summary: describe builds one from what they do have.
    assert describe({"command": "repl delete <id>", "outcome": "Deleted"}) == (
        "Deleted 1 record from its group."
    )
    old_user = {
        "command": "repl delete_user 5",
        "outcome": "PASS",
        "counts": {"ops": 57, "checks": 15, "mismatches": 0, "untouched_changed": 0},
    }
    assert describe(old_user) == (
        "Deleted 57 records (5 cohorts) across 15 groups; 15 of 15 groups exact; "
        "0 other groups changed."
    )
    new_verify = {"command": "repl verify 3", "outcome": "FAIL", "failed": ["n", "blob"]}
    assert describe(new_verify) == "Group 3 differs from its survivors-only rebuild in: n, blob."
    new_delete = {
        "command": "repl delete <id>",
        "outcome": "Deleted",
        "group": 3,
        "n_after": 4605,
        "cert": "000000.cert",
    }
    assert describe(new_delete) == (
        "Deleted 1 record from group 3 (n now 4,605); certificate 000000.cert written."
    )
    assert describe(dict(new_delete, summary="as written")) == "as written"  # stored wins


def test_describe_full_runs() -> None:
    counts = {
        "manifest_mismatches": 0,
        "norm_failures": 0,
        "id_rejections": 0,
        "ops": 2085,
        "checks": 2155,
        "mismatches": 0,
        "untouched_changed": 0,
        "certs_issued": 912,
        "certs_verified": 912,
        "certs_rejected": 0,
        "tamper_caught": 10,
    }
    run = {
        "command": "sever_demo.demo --seed 42",
        "outcome": "PASS",
        "seed": 42,
        "rows_loaded": 1_000_000,
        "sabotage": "none",
        "counts": counts,
    }
    assert describe(run) == (
        "Full run, seed 42, 1,000,000 records: 2,085 operations and 2,155 checks, 0 mismatches; "
        "0 untouched groups changed; 912/912 certificates accepted; 10 forged copies rejected."
    )
    sabotaged = dict(run, sabotage="SB-2", outcome="FAIL")
    assert describe(sabotaged).startswith("Sabotage SB-2 run (must fail), seed 42")
    stopped = dict(run, outcome="FAIL", counts=dict(counts, manifest_mismatches=1))
    assert describe(stopped).endswith("stopped early, 1 dataset file(s) differ from the manifest.")
