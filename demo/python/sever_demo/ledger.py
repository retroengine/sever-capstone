"""Append-only run ledger (DEMO_PLAN §5.8, Overview §13.3).

One JSON line per run, written by code, never by hand. The file is only ever opened in append mode,
so earlier lines cannot be rewritten by this module.

Lines written from 3 Oct 2026 also carry `kind` (check, action, setting or run), `summary` (one
plain sentence, from `describe`) and, from the shell, `session` (the shell's start time). Shell
deletes add `group`, `n_after` and `cert`; shell verifies add `failed`. Older lines lack these
fields; `describe` writes their sentence from the fields they do have. No line ever holds a
record ID (§17) or a secret.
"""

import hashlib
import json
import os
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO
from zoneinfo import ZoneInfo

import numpy as np

from sever_demo.data import DATASETS, REPO

LEDGER_PATH = REPO / "docs" / "RUN_LEDGER.jsonl"
MANIFEST_PATH = DATASETS / "MANIFEST.sha256"
IST = ZoneInfo("Asia/Kolkata")


def open_ledger(path: Path = LEDGER_PATH) -> TextIO:
    """Open the ledger for appending *before* the run starts.

    Overview §13.3: if the ledger cannot be written, the run does not start. Any OSError propagates.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    return open(path, "a", encoding="utf-8", newline="\n")  # the caller closes it


def append(handle: TextIO, entry: dict[str, Any]) -> None:
    """Write one entry as one line. sort_keys makes the line's bytes independent of dict order."""
    handle.write(json.dumps(entry, sort_keys=True, ensure_ascii=True) + "\n")
    handle.flush()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 22):
            h.update(chunk)
    return h.hexdigest()


def _git(*args: str) -> str:
    done = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True)
    return done.stdout.strip()


def git_state() -> tuple[str, bool | None]:
    """(commit, dirty) of the code being run. Dirty means the code is not the commit above.

    Inside the Docker image there is no git: the image was stamped at build time through
    SEVER_GIT_COMMIT and SEVER_GIT_DIRTY (scripts/demo.sh docker-build). Without a stamp the commit
    is "unknown" and dirty is None: never guessed.
    """
    try:
        return _git("rev-parse", "HEAD"), _git("status", "--porcelain") != ""
    except (OSError, subprocess.CalledProcessError):
        dirty = os.environ.get("SEVER_GIT_DIRTY", "")
        return (
            os.environ.get("SEVER_GIT_COMMIT") or "unknown",
            {"true": True, "false": False}.get(dirty),
        )


def run_context(command: str, seed: int, sabotage: str) -> dict[str, Any]:
    """Fields known at the start of a run. The caller adds outcome, counts and the result file."""
    now = datetime.now(UTC)
    commit, dirty = git_state()
    return {
        "ts_utc": now.isoformat(timespec="seconds"),
        "ts_ist": now.astimezone(IST).isoformat(timespec="seconds"),
        "command": command,
        "git_commit": commit,
        # Dirty means the run used code that is not in the commit above.
        "git_dirty": dirty,
        "seed": seed,
        "dataset_manifest_sha256": sha256_file(MANIFEST_PATH),
        "platform": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "os": platform.platform(),
        },
        "sabotage": sabotage,
    }


def read_entries(path: Path = LEDGER_PATH, last: int | None = None) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    if last is not None:
        lines = lines[-last:] if last > 0 else []
    return [json.loads(line) for line in lines]


def describe(entry: dict[str, Any]) -> str:
    """One plain sentence saying what a ledger line records. Works for old and new lines.

    Built only from the command's name and number arguments, the outcome, the counts and group
    numbers, so it can never contain a record ID (§17) or a secret.
    """
    if entry.get("summary"):
        return str(entry["summary"])
    words = str(entry.get("command", "")).split()
    outcome = str(entry.get("outcome", ""))
    c: dict[str, int] = entry.get("counts", {})
    if words and words[0] == "sever_demo.demo":
        return _describe_run(entry, c)
    if len(words) < 2 or words[0] != "repl":
        return f"{' '.join(words)}: {outcome}"
    name, arg = words[1], (words[2] if len(words) > 2 else "")
    passed = outcome == "PASS"

    if name == "verify_data":
        if passed:
            return "Every dataset file matches the committed manifest (0 mismatches)."
        return f"{c.get('manifest_mismatches', '?')} dataset file(s) differ from the manifest."
    if name == "load":
        rows = f"{int(arg):,}" if arg.isdigit() else "the"
        if passed:
            return (
                f"Loaded {rows} records into {entry.get('k_groups', '?')} groups; "
                "0 bad vectors, 0 bad record IDs."
            )
        return (
            f"Load refused: {c.get('norm_failures', 0)} bad vectors, "
            f"{c.get('id_rejections', 0)} bad record IDs (checked, never fixed)."
        )
    if name in ("delete", "insert"):
        if outcome == "AlreadyAbsent":
            return "Record was not live: nothing subtracted, nothing changed (§5.4)."
        verb = "Deleted 1 record from" if name == "delete" else "Re-inserted 1 record into"
        where = f" group {entry['group']}" if "group" in entry else " its group"
        n_after = f" (n now {entry['n_after']:,})" if "n_after" in entry else ""
        cert = f"; certificate {entry['cert']} written" if entry.get("cert") else ""
        return f"{verb}{where}{n_after}{cert}."
    if name == "delete_user":
        groups, bad = c.get("checks", 0), c.get("mismatches", 0)
        deleted = c.get("deleted", c.get("ops", 0))
        cohorts = f"{arg} cohorts" if arg.isdigit() else "one cohort"
        return (
            f"Deleted {deleted:,} records ({cohorts}) across {groups} groups; "
            f"{groups - bad} of {groups} groups exact; "
            f"{c.get('untouched_changed', 0)} other groups changed."
        )
    if name == "verify":
        if passed:
            return f"Group {arg} equals a group rebuilt from its survivors only, on every field."
        failed = entry.get("failed")
        return f"Group {arg} differs from its survivors-only rebuild" + (
            f" in: {', '.join(failed)}." if failed else "."
        )
    if name == "ghost":
        g = entry.get("ghost", {})
        if not g:
            return f"Ghost comparison on group {arg}: {outcome}."
        return (
            f"Ghost table, group {arg} ({g['deleted']} deleted of {g['members']:,}): "
            f"SEVER {'exact' if g['sever_bit_identical'] else 'NOT exact'}; "
            f"float32 off by {g['float_max_abs_diff']:.1e}; "
            f"soft delete still stores {g['soft_still_stored']}."
        )
    if name == "stress":
        return (
            f"{c.get('ops', arg)} random operations, each followed by a check: "
            f"{c.get('mismatches', '?')} mismatches."
        )
    if name == "sabotage":
        if arg == "off":
            rolled = entry.get("rolled_back")
            return "Planted bug switched off" + (
                f"; {rolled} group(s) rolled back." if rolled is not None else "."
            )
        return f"Planted bug {arg} switched on: the checks that follow should catch it."
    if name == "cert":
        return (
            f"Independent verifier (own process): {c.get('certs_verified', 0)} of "
            f"{c.get('certs_checked', 0)} certificate(s) accepted."
        )
    if name == "tamper":
        if passed:
            return "Forged certificate (one bit of its deletion number changed) was rejected."
        return "Forged certificate was ACCEPTED: a check is missing."
    return f"{name} {arg}: {outcome}".replace("  ", " ")


def _describe_run(entry: dict[str, Any], c: dict[str, int]) -> str:
    """The full acceptance run (demo.py): the claims its counts support, in one sentence."""
    seed, rows = entry.get("seed", "?"), entry.get("rows_loaded", 0)
    head = f"Full run, seed {seed}, {rows:,} records"
    if entry.get("sabotage", "none") != "none":
        head = f"Sabotage {entry['sabotage']} run (must fail), seed {seed}, {rows:,} records"
    if entry.get("outcome") == "ERROR":
        return f"{head}: stopped by an error ({entry.get('error', '?')})."
    stops = [
        (c.get("manifest_mismatches", 0), "dataset file(s) differ from the manifest"),
        (c.get("norm_failures", 0), "bad vector(s)"),
        (c.get("id_rejections", 0), "bad record ID(s)"),
    ]
    for count, what in stops:
        if count:
            return f"{head}: stopped early, {count} {what}."
    parts = [
        f"{c.get('ops', 0):,} operations and {c.get('checks', 0):,} checks, "
        f"{c.get('mismatches', 0)} mismatches",
        f"{c.get('untouched_changed', 0)} untouched groups changed",
    ]
    if "certs_issued" in c:
        parts.append(f"{c.get('certs_verified', 0)}/{c['certs_issued']} certificates accepted")
        parts.append(f"{c.get('tamper_caught', 0)} forged copies rejected")
    return f"{head}: " + "; ".join(parts) + "."
