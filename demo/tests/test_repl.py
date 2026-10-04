"""The demo shell (DEMO_PLAN §5.9) on synthetic data. Expected states come from the spec oracle."""

import json
import re
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from rich.console import Console

from sever_demo import group as group_module
from sever_demo import guide
from sever_demo.crypto import scalar_bytes
from sever_demo.errors import Outcome
from sever_demo.index import Index
from sever_demo.ledger import describe, open_ledger
from sever_demo.partition import route
from sever_demo.repl import Session, SeverShell
from spec_oracle import field_diffs, nearest
from synthetic import SEED, D, K, quantised_rows, record_ids, unit_rows

N_ROWS = 120
COHORTS = [f"title-{r % 15}" for r in range(N_ROWS)]  # 15 cohorts of 8 records


def new_session() -> Session:
    """120 synthetic records in K groups, inserted in a seeded order (the same every call)."""
    vectors = quantised_rows(N_ROWS)
    centroids = unit_rows(K, seed=7).astype(np.float64)
    ids = record_ids(N_ROWS)
    index = Index(vectors, ids, route(vectors, centroids), K)
    order = np.random.default_rng(SEED).permutation(N_ROWS)
    for row in order:
        index.insert(ids[row])
    return Session(index, ids, COHORTS, unit_rows(N_ROWS), order, SEED)


@pytest.fixture
def shell(tmp_path: Path) -> Iterator[tuple[SeverShell, Path, list[list[int]], list[int]]]:
    vectors = quantised_rows(N_ROWS)
    centroids = unit_rows(K, seed=7).astype(np.float64)
    want_group = [nearest(v, centroids.tolist()) for v in vectors.tolist()]
    path = tmp_path / "RUN_LEDGER.jsonl"
    with open_ledger(path) as ledger:
        sh = SeverShell(
            ledger, seed=SEED, session=new_session(), console=Console(record=True, width=120)
        )
        yield sh, path, vectors.tolist(), want_group
    group_module.SABOTAGE = None


def live_members(sh: SeverShell, g: int, vecs: list[list[int]], want: list[int]) -> dict:
    """What group g must hold: every live record whose §7.1 group is g (tracked from outside)."""
    deleted = sh.session.deleted if sh.session else set()
    return {f"doc{r}": vecs[r] for r in range(N_ROWS) if want[r] == g and f"doc{r}" not in deleted}


def ledger_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_delete_then_verify_is_exact(shell) -> None:
    sh, path, vecs, want = shell
    sh.onecmd("delete doc3")
    assert sh.last["outcome"] is Outcome.DELETED
    g = want[3]
    assert sh.last["group"] == g
    sh.onecmd(f"verify {g}")
    assert all(sh.last["result"].values())
    assert field_diffs(sh.session.index.groups[g], live_members(sh, g, vecs, want), D) == []

    # §5.4: the retry changes nothing and says AlreadyAbsent.
    blob = sh.session.index.groups[g].blob()
    sh.onecmd("delete doc3")
    assert sh.last["outcome"] is Outcome.ALREADY_ABSENT
    assert sh.session.index.groups[g].blob() == blob

    lines = ledger_lines(path)
    assert [e["outcome"] for e in lines] == ["Deleted", "PASS", "AlreadyAbsent"]
    assert all("doc3" not in json.dumps(e) for e in lines)  # §17: no record ID in the ledger


def test_delete_user_by_title(shell) -> None:
    sh, path, vecs, want = shell
    sh.onecmd("delete_user title-4")
    rows = [r for r in range(N_ROWS) if COHORTS[r] == "title-4"]
    assert sh.last["touched"] == {want[r] for r in rows}
    assert sh.last["mismatches"] == 0
    assert sh.last["untouched"] == 0
    for g in range(K):
        assert field_diffs(sh.session.index.groups[g], live_members(sh, g, vecs, want), D) == []
    assert ledger_lines(path)[-1]["outcome"] == "PASS"


def test_sabotage_shows_red_then_off_rolls_back(shell) -> None:
    sh, path, vecs, want = shell
    g = want[10]
    before = sh.session.index.groups[g].blob()

    sh.onecmd("sabotage SB-2")  # skip n -= 1
    sh.onecmd("delete doc10")
    sh.onecmd(f"verify {g}")
    assert sh.last["result"]["n"] is False  # the bug is visible

    sh.onecmd("sabotage off")
    assert group_module.SABOTAGE is None
    assert sh.session.index.groups[g].blob() == before  # rolled back to before the bug ran
    assert "doc10" in sh.session.index.locator
    sh.onecmd(f"verify {g}")
    assert all(sh.last["result"].values())
    assert field_diffs(sh.session.index.groups[g], live_members(sh, g, vecs, want), D) == []

    outcomes = [(e["command"], e["sabotage"], e["outcome"]) for e in ledger_lines(path)]
    assert outcomes[2] == (f"repl verify {g}", "SB-2", "FAIL")
    assert outcomes[-1] == (f"repl verify {g}", "none", "PASS")


def test_ghost_after_deletes(shell) -> None:
    sh, _, _, _ = shell
    sh.onecmd("delete_user title-1")
    sh.onecmd("ghost")
    assert sh.last["sever_max_abs_diff"] == 0
    assert sh.last["sever_bit_identical"]
    assert sh.last["soft_still_stored"] >= 1


def test_stress_has_no_mismatches(shell) -> None:
    sh, path, vecs, want = shell
    sh.onecmd("delete_user 3")
    sh.onecmd("stress 300")
    assert sh.last["mismatches"] == 0
    for g in range(K):
        assert field_diffs(sh.session.index.groups[g], live_members(sh, g, vecs, want), D) == []
    assert ledger_lines(path)[-1]["outcome"] == "PASS"


def test_group_and_ledger_and_save(shell, tmp_path: Path, monkeypatch) -> None:
    sh, _, _, want = shell
    sh.onecmd(f"group {want[0]}")
    assert sh.last["n"] == sum(1 for w in want if w == want[0])
    sh.onecmd("ledger 3")
    monkeypatch.setattr("sever_demo.repl.RESULTS", tmp_path)
    sh.onecmd("save step1")
    assert (tmp_path / "screens" / "step1.svg").read_text(encoding="utf-8").startswith("<svg")


def test_bad_input_is_reported_not_raised(shell) -> None:
    # A typo during the live demo must print an error, not crash the shell.
    sh, _, _, _ = shell
    sh.onecmd("group abc")
    sh.onecmd("group 999")
    text = sh.console.export_text()
    assert "ValueError" in text
    assert "IndexError" in text


# --- Part 3 preview in the shell --------------------------------------------------------------


@pytest.fixture
def committed_shell(shell, tmp_path: Path):
    sh, path, vecs, want = shell
    sh.session.index.enable_commitments()
    sh.cert_dir = tmp_path / "certs"
    return sh, path, vecs, want


def test_delete_writes_a_certificate_the_verifier_accepts(committed_shell) -> None:
    sh, _, _, want = committed_shell
    sh.onecmd("delete doc3")
    files = sorted((sh.cert_dir).glob("*.cert"))
    assert [f.name for f in files] == ["000000.cert"]
    sh.onecmd("cert last")
    assert sh.last["accepted"] == {"000000.cert": True}
    sh.onecmd(f"verify {want[3]}")
    assert sh.last["result"] == {"S": True, "n": True, "members": True, "C_S": True, "blob": True}


@pytest.mark.mustfail
def test_tampered_certificate_is_rejected(committed_shell) -> None:
    sh, _, _, _ = committed_shell
    sh.onecmd("delete doc3")
    sh.onecmd("tamper last")
    assert sh.last["accepted"] is False
    text = sh.console.export_text()
    assert "REJECTED" in text
    assert "FAIL        2 operator signature" in text  # the receipt was altered after signing
    assert "FAIL        6b proof of knowledge" in text  # and the proof is bound to its lsn


def test_delete_user_certificates_all_verify(committed_shell) -> None:
    sh, _, _, _ = committed_shell
    sh.onecmd("delete_user title-4")
    assert sh.last["mismatches"] == 0
    sh.onecmd("cert all")
    assert len(sh.last["accepted"]) == 8
    assert all(sh.last["accepted"].values())


@pytest.mark.mustfail
def test_sb4_is_seen_by_blob_and_proof_then_rolled_back(committed_shell) -> None:
    sh, _, _, want = committed_shell
    g = want[10]
    before = sh.session.index.groups[g].blob()
    sh.onecmd("sabotage SB-4")
    sh.onecmd("delete doc10")
    sh.onecmd(f"verify {g}")
    assert sh.last["result"]["C_S"] is True  # the point moved by exactly C_t ...
    assert sh.last["result"]["blob"] is False  # ... but r_agg (inside the blob) is wrong
    sh.onecmd("cert last")
    assert sh.last["accepted"] == {"000000.cert": False}  # the proof cannot be made
    sh.onecmd("sabotage off")
    assert sh.session.index.groups[g].blob() == before
    sh.onecmd(f"verify {g}")
    assert all(sh.last["result"].values())


def test_ledger_never_holds_a_blinding_value(committed_shell) -> None:
    # CLAUDE.md §8: never print, log or commit r_t.
    sh, path, _, _ = committed_shell
    sh.onecmd("delete doc3")
    sh.onecmd("cert last")
    blinding = sh.session.index.groups[0].blinding
    text = path.read_text(encoding="utf-8") + sh.console.export_text()
    for r in blinding[:20]:
        assert str(r) not in text
        assert r.to_bytes(32, "little").hex() not in text


# --- guidance: help, explain, notes, tour (DEMO_PLAN §5.9) -----------------------------------


def test_help_lists_every_command(shell) -> None:
    # A new command cannot be left out of `help`: every do_* command is in guide.HELP_GROUPS.
    sh, _, _, _ = shell
    names = {n[3:] for n in sh.get_names() if n.startswith("do_") and n != "do_EOF"}
    listed = {usage.split()[0] for _, cmds in guide.HELP_GROUPS for usage, _ in cmds}
    assert names == listed
    sh.onecmd("help")
    text = sh.console.export_text()
    assert all(name in text for name in names)
    sh.onecmd("help delete")
    assert "AlreadyAbsent" in sh.console.export_text()  # the command's own docstring


def test_explain_finds_terms_and_suggests_close_ones(shell) -> None:
    sh, _, _, _ = shell
    assert set(guide.ALIASES.values()) <= set(guide.GLOSSARY)
    assert all(section for _, section in guide.GLOSSARY.values())  # every term cites its source
    sh.onecmd("explain c_s")
    sh.onecmd("explain receipt")
    sh.onecmd("explain blobb")
    text = sh.console.export_text()
    assert "§9.3" in text  # C_S, found without regard to case
    assert "deletion receipt" in text  # an alias of "certificate"
    assert "Did you mean: blob" in text


def test_notes_off_hides_notes_and_hints(shell) -> None:
    sh, _, _, want = shell
    sh.onecmd("delete doc3")
    assert "┊" in sh.console.export_text(clear=True)
    sh.onecmd("notes off")
    sh.onecmd("delete doc5")
    sh.onecmd(f"verify {want[5]}")
    text = sh.console.export_text()
    assert "┊" not in text
    assert "→ next" not in text


def test_tour_gives_the_same_result_as_typing(tmp_path: Path) -> None:
    # The tour runs the runbook's commands through the same code in the same order, so it draws
    # from the seeded generator exactly as typing them does: same outcomes, same final groups.
    a, b = list(new_session().index.groups[3].members)[:2]  # what `ids 3` shows first
    typed = [
        *("group 3", "ids 3", f"delete {a}", "verify 3", "cert last", "tamper last"),
        *("delete_user 5", "cert all", f"delete {a}", "ghost"),
        *("sabotage SB-4", f"delete {b}", "verify 3", "cert last", "sabotage off", "verify 3"),
        "ledger session",
    ]
    seen = []
    for way in ["tour", "typed"]:
        session = new_session()
        session.index.enable_commitments()
        with open_ledger(tmp_path / f"{way}.jsonl") as ledger:
            sh = SeverShell(ledger, seed=SEED, session=session, console=Console(record=True))
            sh.cert_dir = tmp_path / way
            if way == "tour":
                sh.onecmd("tour 3")  # steps 1-2 (verify_data, load) need the real data
                for _ in range(11):
                    sh.onecmd("next")
                assert sh.tour_pos == len(guide.TOUR) + 1
            else:
                for line in typed:
                    sh.onecmd(line)
        lines = ledger_lines(tmp_path / f"{way}.jsonl")
        groups = [(g.S.tobytes(), g.n, sorted(g.members)) for g in session.index.groups]
        seen.append(
            (
                [(e["command"], e["outcome"], e.get("counts"), e["summary"]) for e in lines],
                groups,
                len(session.index.issued),
            )
        )
        assert group_module.SABOTAGE is None
    assert seen[0] == seen[1]
    outcomes = [(c, o) for c, o, _, _ in seen[0][0]]
    assert ("repl tamper", "PASS") in outcomes  # the forged receipt was rejected
    assert outcomes[-4:] == [  # SB-4: blob and proof catch it; off: exact again
        ("repl verify 3", "FAIL"),
        ("repl cert last", "FAIL"),
        ("repl sabotage off", "INFO"),
        ("repl verify 3", "PASS"),
    ]


def test_next_needs_a_loaded_index(tmp_path: Path) -> None:
    with open_ledger(tmp_path / "RUN_LEDGER.jsonl") as ledger:
        sh = SeverShell(ledger, seed=SEED, console=Console(record=True, width=120))
        sh.onecmd("tour 3")
        sh.onecmd("next")
        assert sh.tour_pos == 3  # did not advance
        assert "needs a loaded index" in sh.console.export_text()


# --- clearer results ---------------------------------------------------------------------------


def test_insert_round_trip_returns_the_same_hash(shell) -> None:
    # Delete, then re-insert: the blob hash is back, bit for bit (§5.3), and the shell says so.
    sh, path, vecs, want = shell
    g = want[3]
    group = sh.session.index.groups[g]
    h0 = group.blob_hash()
    sh.onecmd("delete doc3")
    h1 = group.blob_hash()
    sh.onecmd("insert doc3")
    assert group.blob_hash() == h0
    assert "the same blob hash as before `delete doc3`" in sh.console.export_text(clear=True)
    sh.onecmd("delete doc3")
    assert group.blob_hash() == h1
    sh.onecmd("insert doc3")
    sh.onecmd("insert doc3")  # already live: refused, nothing changes (§3.2 rule 3)
    assert "already live" in sh.console.export_text()
    assert group.blob_hash() == h0
    assert field_diffs(group, live_members(sh, g, vecs, want), D) == []
    assert [e["outcome"] for e in ledger_lines(path)] == ["Deleted", "Inserted"] * 2


@pytest.mark.mustfail
def test_sb2_verify_names_the_count(shell) -> None:
    # SB-2 (skip n -= 1): the screen shows n not moving, and verify says which field is wrong.
    sh, _, _, want = shell
    g = want[10]
    n = sh.session.index.groups[g].n
    sh.onecmd("sabotage SB-2")
    assert sh.prompt == "sever [SB-2 ON]> "
    sh.onecmd("delete doc10")
    sh.onecmd(f"verify {g}")
    assert sh.last["failed"] == ["n", "blob"]
    text = sh.console.export_text()
    assert f"n {n:,} → {n:,}" in text
    assert f"n: the count says {n:,}, but {n - 1:,} records are members" in text
    sh.onecmd("sabotage off")
    assert sh.prompt == "sever> "


@pytest.mark.mustfail
def test_sb4_verify_points_at_the_hidden_total(committed_shell) -> None:
    # SB-4 (skip r_agg -= r_t): every field on screen matches; only the blob differs, and the
    # shell says why without ever showing r_agg (CLAUDE.md §8).
    sh, path, _, want = committed_shell
    g = want[10]
    sh.onecmd("sabotage SB-4")
    sh.onecmd("delete doc10")
    sh.onecmd(f"verify {g}")
    assert sh.last["failed"] == ["blob"]
    text = sh.console.export_text() + path.read_text(encoding="utf-8")
    assert "the secret blinding total r_agg" in " ".join(text.split())
    r_agg = sh.session.index.groups[g].r_agg
    assert str(r_agg) not in text
    assert scalar_bytes(r_agg).hex() not in text


def test_errors_say_what_to_type(shell) -> None:
    sh, _, _, _ = shell
    sh.onecmd("verify abc")
    sh.onecmd("verify 99")
    sh.onecmd("verfy 3")
    text = sh.console.export_text()
    assert "ValueError: verify needs a group number, e.g. verify 3" in text
    assert f"IndexError: no group 99: groups are numbered 0 to {K - 1}" in text
    assert "did you mean verify?" in text


def test_an_unexpected_error_stops_tests_but_not_the_live_shell(shell, monkeypatch) -> None:
    sh, _, _, _ = shell
    monkeypatch.setattr(sh, "do_stats", lambda arg: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        sh.onecmd("stats")
    sh.keep_going = True  # what main() sets for the live demo
    assert sh.onecmd("stats") is False
    assert "unexpected ZeroDivisionError" in sh.console.export_text()


def test_save_does_not_leak_into_the_next_screen(shell, tmp_path: Path, monkeypatch) -> None:
    sh, _, _, _ = shell
    monkeypatch.setattr("sever_demo.repl.RESULTS", tmp_path)
    sh.onecmd("stats")
    sh.onecmd("save one")
    assert sh.console.export_text() == ""  # the "saved ..." line is not kept for the next screen
    sh.onecmd("stats")
    sh.onecmd("save two")
    assert "saved" not in (tmp_path / "screens" / "two.svg").read_text(encoding="utf-8")


def test_ledger_lines_say_what_happened_without_record_ids(committed_shell) -> None:
    # Every new line says how to read it (kind), which shell wrote it (session) and what it did
    # (summary), and still never holds a record ID (§17).
    sh, path, _, want = committed_shell
    n_before = sh.session.index.groups[want[3]].n
    commands = [
        *("delete doc3", "delete doc3", f"verify {want[3]}", "insert doc3"),
        *("delete_user title-4", "cert all", "tamper last", "sabotage SB-2", "sabotage off"),
        *("ghost", "stress 30"),
    ]
    for line in commands:
        sh.onecmd(line)
    lines = ledger_lines(path)
    assert len(lines) == len(commands)
    for e in lines:
        assert e["kind"] in {"check", "action", "setting"}
        assert e["session"] == sh.session_id
        assert e["summary"] == describe({k: v for k, v in e.items() if k != "summary"})
        assert not re.search(r"doc[0-9]+", json.dumps(e))
    assert lines[0]["summary"] == (
        f"Deleted 1 record from group {want[3]} (n now {n_before - 1:,}); "
        "certificate 000000.cert written."
    )
    assert lines[1]["summary"].startswith("Record was not live")
    sh.onecmd("ledger session")
    assert lines[0]["summary"][:30] in sh.console.export_text()


@pytest.mark.parametrize("script", ["repl.py", "demo.py"])
def test_entry_points_run_as_plain_files(script: str) -> None:
    # `uv run python repl.py` from inside python/sever_demo must work (no PYTHONPATH needed).
    import os
    import subprocess
    import sys

    folder = Path(__file__).resolve().parents[1] / "python" / "sever_demo"
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    args = [sys.executable, script] + (["--help"] if script == "demo.py" else [])
    done = subprocess.run(
        args, cwd=folder, env=env, input="quit\n", capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr[-500:]
