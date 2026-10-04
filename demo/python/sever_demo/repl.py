"""Interactive demo shell (DEMO_PLAN §5.9): a thin wrapper around the same code demo.py runs.

    scripts/demo.sh repl                                   # recommended (fast environment)
    PYTHONHASHSEED=0 PYTHONPATH=python uv run python -m sever_demo.repl
    uv run python repl.py                                  # also works, from python/sever_demo

New here: `tour` shows the demo story in 13 steps and `next` runs each one; `help` lists every
command and `explain <word>` explains any term. Each result ends with a short note in plain words
and a hint for what to type next (`notes off` hides them; `--no-notes` starts with them off). The
words themselves live in guide.py.

Every state-changing or checking command appends a line to docs/RUN_LEDGER.jsonl, with a plain
sentence saying what it did. `save <name>` writes everything shown so far as an SVG screenshot in
results/screens/ (backup for the live demo).

Part 3 preview (on by default; `--no-commitments` for the Day 2 shell): `load` adds commitments,
each deletion writes a signed certificate to results/certs/repl-<time>/, `cert` checks certificates
with the independent verifier run as its own process, and `tamper` shows a forged certificate being
rejected.

Only `verify`, `delete_user N` and `stress` draw from the shell's seeded random generator, in that
order of commands; nothing else does, so the same commands typed in the same order (or run by the
tour) give the same numbers as the runbook.
"""

import sys
from pathlib import Path

if not __package__:
    # Run as a plain file (`python repl.py` inside python/sever_demo): put python/ on the import
    # path instead of this folder, so `import sever_demo` works from anywhere.
    sys.path[0] = str(Path(__file__).resolve().parents[1])

import argparse
import cmd
import difflib
import hashlib
import inspect
import json
import textwrap
import time
from dataclasses import dataclass, field
from typing import Any, TextIO

import numpy as np
import numpy.typing as npt
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from sever_demo import group as group_module
from sever_demo import guide
from sever_demo.baselines import ghost_report
from sever_demo.crypto import IDENTITY, point_add
from sever_demo.data import REPO, check_manifest, check_norms, load_ids_and_cohorts
from sever_demo.demo import (
    CACHE,
    CERTS,
    NQ,
    NQ_PASSAGES,
    NQ_REL,
    RESULTS,
    SCIQ,
    SCIQ_REL,
    cached_centroids,
    cached_quantised,
    ghost_table,
    manifest_hash,
    size_table,
)
from sever_demo.errors import InvalidRecordId, Outcome
from sever_demo.group import Group, Snapshot, fresh_sum
from sever_demo.ids import validate_record_id
from sever_demo.index import Index
from sever_demo.ledger import (
    LEDGER_PATH,
    MANIFEST_PATH,
    append,
    describe,
    open_ledger,
    read_entries,
    run_context,
)
from sever_demo.partition import K_FROZEN, route, sub_seed
from sever_demo.receipts import run_verifier, tampered_copy, write_receipts

TICK, CROSS = "[green]✓[/green]", "[red]✗[/red]"
SABOTAGES = list(guide.SABOTAGE_BUGS)
# A ledger line's `kind` says how to read its outcome: a check's verdict (PASS/FAIL), what an
# action did (Deleted, Inserted, AlreadyAbsent), or a setting (INFO).
KIND = {
    "verify_data": "check",
    "load": "action",
    "delete": "action",
    "insert": "action",
    "delete_user": "check",
    "verify": "check",
    "ghost": "check",
    "stress": "check",
    "cert": "check",
    "tamper": "check",
    "sabotage": "setting",
}
OUTCOME_STYLE = {
    "PASS": "green",
    "FAIL": "red",
    "ERROR": "red",
    "Deleted": "cyan",
    "Inserted": "cyan",
    "AlreadyAbsent": "yellow",
    "INFO": "dim",
}


def short(value: bytes | str, k: int = 16) -> str:
    """The first k hex characters of a hash or a point, for the screen."""
    text = value.hex() if isinstance(value, bytes) else value
    return text[:k] + "…"


def lsn_byte(cert: bytes) -> int:
    """Position of the last byte of tag 10 (database_lsn) in a certificate: walk the TLV fields."""
    pos = 0
    for _ in range(9):  # tags 1..9: u8 tag ‖ u32be length ‖ value
        pos += 5 + int.from_bytes(cert[pos + 1 : pos + 5], "big")
    return pos + 5 + 7


def cached_norm_report(path: Path, rel: str) -> tuple[dict[str, Any], bool]:
    """§4.1 on the whole file, remembered per file hash. Returns (report, came_from_cache).

    The report is stored under the file's manifest SHA-256, so it only applies to those exact bytes
    (which `verify_data` re-checks). demo.py always recomputes; the shell reuses it to stay fast.
    """
    cache = CACHE / f"norms_{path.parent.name}_{manifest_hash(rel)[:16]}.json"
    if cache.exists():
        report: dict[str, Any] = json.loads(cache.read_text(encoding="utf-8"))
        return report, True
    report = check_norms(np.load(path, mmap_mode="r"))
    report["checked_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(report), encoding="utf-8")
    return report, False


def field_values(name: str, live: Snapshot, rebuilt: Snapshot) -> tuple[str, str]:
    """One §5.5 field of both snapshots, as short text for the verify table."""

    def one(s: Snapshot) -> str:
        if name == "S":
            return short(hashlib.sha256(s.S).hexdigest(), 12)
        if name == "n":
            return f"{s.n:,}"
        if name == "members":
            ids = b"".join(len(i).to_bytes(2, "big") + i for i in s.member_ids)
            return f"{len(s.member_ids):,} IDs · {short(hashlib.sha256(ids).hexdigest(), 8)}"
        if name == "C_S":
            return short(s.C_S, 12)
        return short(s.blob_sha256, 12)

    return one(live), one(rebuilt)


def diagnose(live: Snapshot, result: dict[str, bool], committed: bool) -> list[str]:
    """Plain words for a failed survivors check: which field disagrees, and what that means."""
    lines = []
    if not result["n"]:
        lines.append(
            f"n: the count says {live.n:,}, but {len(live.member_ids):,} records are members"
        )
    if not result["S"]:
        lines.append("S: the sum is not the sum of the members' vectors")
    if not result["members"]:
        lines.append("members: the list of record IDs differs from the rebuild's")
    if not result.get("C_S", True):
        lines.append("C_S: the fingerprint differs from one computed from the survivors")
    if not result["blob"]:
        if all(ok for name, ok in result.items() if name != "blob"):
            lines.append(
                "blob only: every field on screen matches, so the difference is in the part no "
                "screen shows, the secret blinding total r_agg (it is inside the blob)"
                if committed
                else "blob only: the members' stored vectors differ"
            )
        else:
            lines.append("blob: differs because the fields above differ (it contains them all)")
    return lines


@dataclass
class Session:
    """Everything a loaded index needs. Built from the real data by `load`, or directly in tests."""

    index: Index
    ids: list[str]
    cohorts: list[str]
    x: npt.NDArray[np.float32]  # float32 rows (for the ghost baselines)
    order: npt.NDArray[np.int64]  # insertion order (rows)
    seed: int
    deleted: set[str] = field(default_factory=set)  # deleted in this session
    _cohort_index: dict[str, list[str]] | None = None

    def cohort_members(self, title: str) -> list[str]:
        if self._cohort_index is None:
            idx: dict[str, list[str]] = {}
            for rid, c in zip(self.ids, self.cohorts, strict=True):
                idx.setdefault(c, []).append(rid)
            self._cohort_index = idx
        return self._cohort_index.get(title, [])

    def cohort_titles(self) -> list[str]:
        self.cohort_members("")  # build the index
        assert self._cohort_index is not None
        return sorted(self._cohort_index, key=lambda c: c.encode("utf-8"))


class SeverShell(cmd.Cmd):
    intro = ""  # the banner is printed by preloop, through the console, so `save` records it

    def __init__(
        self,
        ledger: TextIO,
        seed: int = 42,
        session: Session | None = None,
        console: Console | None = None,
        commitments: bool = True,
        notes: bool = True,
    ) -> None:
        super().__init__()
        self.commitments = commitments
        self.cert_dir: Path | None = None
        self.ledger = ledger
        self.seed = seed
        self.session = session
        self.console = console or Console(record=True)
        self.rng = np.random.default_rng(sub_seed(seed, b"repl"))
        self.last: dict[str, Any] = {}  # result of the last command (used by tests)
        self.notes = notes
        self.session_id = time.strftime("%Y-%m-%dT%H%M%SZ", time.gmtime())
        self.focus: int | None = None  # the group the last command looked at or changed (hints)
        # Blob hashes shown in this session, per group: hash -> when it was seen (so a later
        # command can say "the same hash as before ...").
        self.seen: dict[int, dict[str, str]] = {}
        # Guided tour: the next step to run (1-based) or None, and its group and record IDs.
        self.tour_pos: int | None = None
        self.tour_vars: dict[str, str] = {}
        self._in_step = False  # while `next` runs a step's commands, their hints wait
        self._interactive = True  # False when commands are piped in (set by preloop)
        self.keep_going = False  # main() sets it: report unexpected errors instead of stopping
        self.label = "sever> "
        self._set_prompt()
        # Sabotage rollback: what the groups and locator looked like before the bug ran.
        self._backup_groups: dict[
            int, tuple[npt.NDArray[np.int64], int, dict[str, int], int, bytes]
        ] = {}
        self._backup_locator: dict[str, int] | None = None
        self._backup_deleted: set[str] | None = None

    # ------------------------------------------------------------------ helpers

    def _set_prompt(self) -> None:
        bug = group_module.SABOTAGE
        self.label = f"sever [{bug} ON]> " if bug else "sever> "
        # Piped input (a rehearsal script): precmd echoes each command through the console instead,
        # so the screenshots show what was typed.
        self.prompt = self.label if self._interactive else ""

    def _ledger_path(self) -> Path:
        path = Path(self.ledger.name).resolve()
        return path.relative_to(REPO) if path.is_relative_to(REPO) else path

    def _session_lines(self) -> int:
        entries = read_entries(Path(self.ledger.name))
        return sum(e.get("session") == self.session_id for e in entries)

    def log(self, command: str, outcome: str, **extra: Any) -> None:
        entry = run_context(f"repl {command}".strip(), self.seed, group_module.SABOTAGE or "none")
        entry["rows_loaded"] = len(self.session.ids) if self.session else 0
        entry["k_groups"] = len(self.session.index.groups) if self.session else K_FROZEN
        entry["outcome"] = outcome
        entry["kind"] = KIND.get(command.split()[0], "check")
        entry["session"] = self.session_id
        entry.update(extra)
        entry["summary"] = describe(entry)  # one plain sentence; never a record ID (§17)
        append(self.ledger, entry)

    def note(self, key: str, **values: Any) -> None:
        """The plain-words note under a result (guide.NOTES), while notes are on."""
        if not self.notes:
            return
        text = guide.NOTES[key].format(**values) if values else guide.NOTES[key]
        for line in textwrap.wrap(text, max(40, min(self.console.width, 110) - 6)):
            self.console.print(f"  [cyan]┊ {escape(line)}[/cyan]", highlight=False)

    def hint(self, key: str) -> None:
        """What to type next: the tour's next step while a tour runs, else guide.NEXT_HINT."""
        if not self.notes or self._in_step:
            return
        if self.tour_pos is not None and self.tour_pos <= len(guide.TOUR):
            step = guide.TOUR[self.tour_pos - 1]
            todo, why = "next", f"step {self.tour_pos} of {len(guide.TOUR)} · {step.title}"
        else:
            todo, why = guide.NEXT_HINT[key]
            todo = todo.format(g=self.focus if self.focus is not None else 3)
        self.console.print(
            f"  [dim]→ next: [bold]{escape(todo)}[/bold]  ({escape(why)})[/dim]", highlight=False
        )

    def need_session(self) -> Session | None:
        if self.session is None:
            self.console.print("[yellow]No index loaded. Run: load[/yellow]")
        return self.session

    def group_arg(self, s: Session, arg: str, command: str) -> int:
        """A group number from the command line, with an error that says what to type."""
        text = arg.strip()
        if not text.lstrip("-").isdigit():
            raise ValueError(f"{command} needs a group number, e.g. {command} 3")
        gid, k = int(text), len(s.index.groups)
        if not 0 <= gid < k:
            raise IndexError(f"no group {gid}: groups are numbered 0 to {k - 1}")
        return gid

    def remember(self, gid: int, blob_hash: str, when: str) -> None:
        self.seen.setdefault(gid, {}).setdefault(blob_hash, when)

    def same_as(self, gid: int, blob_hash: str) -> None:
        """If this blob hash was seen before in this session, say so: the group is back there."""
        when = self.seen.get(gid, {}).get(blob_hash)
        if when is not None:
            self.console.print(
                f"  [bold green]= the same blob hash as {escape(when)}[/bold green]: "
                f"group {gid} is bit for bit what it was then",
                highlight=False,
            )

    def backup(self, gids: set[int]) -> None:
        """While a sabotage is on, remember each group's state before the broken code touches it."""
        if group_module.SABOTAGE is None or self.session is None:
            return
        for gid in gids:
            if gid not in self._backup_groups:
                g = self.session.index.groups[gid]
                self._backup_groups[gid] = (g.S.copy(), g.n, dict(g.members), g.r_agg, g.C_S)

    def fields(self) -> list[str]:
        """§5.5 fields shown: 5 of 5 with commitments, 4 of 5 without (C_S is Part 3)."""
        committed = self.session is not None and self.session.index.committed
        return ["S", "n", "members", "C_S", "blob"] if committed else ["S", "n", "members", "blob"]

    def save_certificates(self) -> list[Path]:
        """Writes any new certificates (public data) and the anchors to this session's folder."""
        if self.session is None or self.cert_dir is None:
            return []
        idx = self.session.index
        return write_receipts(self.cert_dir, idx.anchors(), idx.issued)

    def cert_choice(self, arg: str, paths: list[Path], command: str) -> list[Path]:
        """`last`, `all` or a certificate number, with an error that says what to type."""
        text = arg.strip() or "last"
        if text == "last":
            return [paths[-1]]
        if text == "all" and command == "cert":
            return paths
        if not text.isdigit():
            choices = "last, all" if command == "cert" else "last"
            raise ValueError(f"{command} takes {choices} or a certificate number, e.g. {command} 0")
        if int(text) >= len(paths):
            raise IndexError(f"no certificate {text}: this session has 0 to {len(paths) - 1}")
        return [paths[int(text)]]

    def tour_values(self, keep: bool) -> dict[str, str]:
        """The tour's group {g} and its first two live record IDs {a}, {b}, chosen as the runbook
        chose them (group 3, the first two IDs `ids 3` shows). Kept once chosen (keep=True), so the
        retry at step 9 deletes the record step 4 deleted."""
        values = dict(self.tour_vars)
        s = self.session
        if s is None:
            return {"g": "3", "a": "<1st ID>", "b": "<2nd ID>", **values}
        groups = s.index.groups
        if "g" not in values:
            big = max(range(len(groups)), key=lambda i: groups[i].n)
            values["g"] = str(3 if len(groups) > 3 and groups[3].n >= 2 else big)
        if "a" not in values:
            first = list(groups[int(values["g"])].members)[:2]
            values["a"] = first[0] if first else "<none>"
            values["b"] = first[1] if len(first) > 1 else values["a"]
        if keep:
            self.tour_vars = values
        return values

    # ------------------------------------------------------------------ cmd.Cmd hooks

    def preloop(self) -> None:
        self._interactive = sys.stdin.isatty()
        self._set_prompt()
        mode = "commitments on" if self.commitments else "no commitments (Day 2 mode)"
        notes = (
            "notes on (notes off hides them)" if self.notes else "notes off (notes on shows them)"
        )
        body = (
            f"[bold]Claim:[/bold] {escape(guide.CLAIM)}\n\n"
            "New here?  [bold]tour[/bold] shows the story in 13 steps; [bold]next[/bold] runs "
            "each one.\n"
            "           [bold]help[/bold] lists every command; [bold]explain <word>[/bold] "
            "explains any term (try: explain C_S).\n"
            f"[dim]Ledger {self._ledger_path()} · session {self.session_id} · {mode} · "
            f"{notes}[/dim]"
        )
        self.console.print(Panel(body, title=f"[bold]{guide.TITLE}[/bold]", border_style="blue"))

    def precmd(self, line: str) -> str:
        word = line.split()[0] if line.split() else ""
        if not self._interactive and word not in ("", "EOF", "save"):  # `save` ends a screenshot
            self.console.print(
                f"[dim]{escape(self.label)}[/dim]{escape(line.strip())}", highlight=False
            )
        return line

    def onecmd(self, line: str) -> bool:
        try:
            return super().onecmd(line)
        except (ValueError, IndexError) as exc:  # typed errors (§17) and typos: report, go on
            self.console.print(f"[red]{type(exc).__name__}[/red]: {escape(str(exc))}")
            return False
        except Exception as exc:
            if not self.keep_going:
                raise
            # Live demo (main sets keep_going): an unexpected error must not end the shell.
            self.console.print(
                f"[red]unexpected {type(exc).__name__}[/red]: {escape(str(exc))} "
                "(the shell keeps going)"
            )
            return False

    def emptyline(self) -> bool:
        return False

    def default(self, line: str) -> None:
        word = line.split()[0] if line.split() else line
        names = [n[3:] for n in self.get_names() if n.startswith("do_") and n != "do_EOF"]
        close = difflib.get_close_matches(word, names, n=1)
        maybe = f": did you mean [bold]{close[0]}[/bold]?" if close else "."
        self.console.print(
            f"  [yellow]unknown command {escape(word)}[/yellow]{maybe} Type help for the list."
        )

    # ------------------------------------------------------------------ guide

    def do_help(self, arg: str) -> None:
        """help [command]: every command in the order the demo uses them, or one in detail."""
        name = arg.strip()
        if name:
            method = getattr(self, f"do_{name}", None)
            if method is None or name == "EOF":
                self.console.print(f"  [yellow]no command {escape(name)}[/yellow]: type help")
                return
            usage = next(
                (u for _, cmds in guide.HELP_GROUPS for u, _ in cmds if u.split()[0] == name), name
            )
            doc = inspect.getdoc(method) or ""
            self.console.print(Panel(escape(doc), title=f"[bold]{escape(usage)}[/bold]"))
            return
        t = Table(title="Commands, in the order the demo uses them")
        t.add_column("", style="bold")
        t.add_column("command", style="cyan")
        t.add_column("what it does")
        for section, cmds in guide.HELP_GROUPS:
            for i, (usage, what) in enumerate(cmds):
                t.add_row(section if i == 0 else "", escape(usage), escape(what))
            t.add_section()
        self.console.print(t)
        self.console.print(
            "  New here? [bold]tour[/bold], then [bold]next[/bold] for each step. "
            "[bold]help <command>[/bold] for details; [bold]explain <word>[/bold] for any term."
        )

    def do_explain(self, arg: str) -> None:
        """explain [word]: a term in plain words, with the spec section that defines it.

        With no word, lists the terms. For example: explain blob, explain C_S, explain lsn."""
        word = arg.strip()
        terms = {t.lower(): t for t in guide.GLOSSARY}
        if not word:
            self.console.print("  terms: " + ", ".join(guide.GLOSSARY), highlight=False)
            self.console.print("  type explain <term>, for example: explain blob")
            return
        low = word.lower()
        key = terms.get(low) or terms.get(low.replace("_", " ")) or guide.ALIASES.get(low)
        if key is None:
            close = difflib.get_close_matches(low, [*terms, *guide.ALIASES], n=3, cutoff=0.5)
            names = [terms.get(c) or guide.ALIASES[c] for c in close]
            maybe = f" Did you mean: {', '.join(dict.fromkeys(names))}?" if names else ""
            self.console.print(
                f"  [yellow]no term {escape(word)}[/yellow].{escape(maybe)} explain lists them all."
            )
            return
        text, section = guide.GLOSSARY[key]
        self.console.print(
            Panel(f"{escape(text)}\n[dim]{escape(section)}[/dim]", title=f"[bold]{escape(key)}[/]")
        )

    def do_notes(self, arg: str) -> None:
        """notes [on|off]: show or hide the plain-words note and next-step hint after results."""
        choice = arg.strip().lower()
        if choice in ("on", "off"):
            self.notes = choice == "on"
        elif choice:
            raise ValueError("notes takes on or off")
        self.console.print(f"  notes are {'on' if self.notes else 'off'}")

    def do_tour(self, arg: str) -> None:
        """tour [k | off]: the demo story in 13 steps, in the runbook's order (same numbers).

        `tour` starts it or shows where you are; `tour k` jumps to step k (tour 2 skips the slow
        data check); `tour off` leaves it. Then type `next` for each step: it says what to tell the
        audience, runs the step's commands for you and says what to look for. Any other command can
        be typed between steps."""
        choice = arg.strip().lower()
        n_steps = len(guide.TOUR)
        if choice == "off":
            self.tour_pos = None
            self.console.print("  tour off (tour starts it again)")
            return
        if choice:
            if not choice.isdigit() or not 1 <= int(choice) <= n_steps:
                raise ValueError(f"tour takes a step number from 1 to {n_steps}, or off")
            self.tour_pos = int(choice)
            if self.tour_pos <= 3:
                self.tour_vars = {}  # the group and records are chosen again at step 3
        elif self.tour_pos is None:
            self.tour_pos = 1
        pos = self.tour_pos
        values = self.tour_values(keep=False)
        t = Table(title=f"The demo story in {n_steps} steps")
        t.add_column("", justify="right")
        t.add_column("step")
        t.add_column("commands", style="cyan")
        for i, step in enumerate(guide.TOUR, start=1):
            mark = (
                "[green]✓[/green]"
                if i < pos
                else "[bold yellow]▶[/bold yellow]"
                if i == pos
                else ""
            )
            todo = "; ".join(c.format(**values) for c in step.commands)
            t.add_row(f"{mark} {i}", escape(step.title), escape(todo))
        self.console.print(t)
        if pos <= n_steps:
            self.console.print(
                f"  type [bold]next[/bold] to run step {pos}: {escape(guide.TOUR[pos - 1].title)}"
            )
        else:
            self.console.print("  the tour is finished: tour 1 starts it again")

    def do_next(self, arg: str) -> None:
        """next: run the next step of the tour (and start the tour if needed). See: help tour."""
        n_steps = len(guide.TOUR)
        if self.tour_pos is None:
            self.tour_pos = 1
        if self.tour_pos > n_steps:
            self.console.print("  the tour is finished: tour 1 starts it again")
            return
        k = self.tour_pos
        step = guide.TOUR[k - 1]
        if step.needs_session and self.session is None:
            self.console.print(
                f"  [yellow]step {k} needs a loaded index: run step 2 first (tour 2, then next), "
                "or type load[/yellow]"
            )
            return
        committed = self.session is not None and self.session.index.committed
        self.console.rule(f"[bold]Step {k} of {n_steps} · {escape(step.title)}[/bold]")
        if step.needs_commitments and not committed:
            self.console.print(
                "  [yellow]skipped: this step needs commitments, and this shell runs without "
                "them (--no-commitments)[/yellow]"
            )
            self.tour_pos += 1
            self.hint("tour")
            return
        values = self.tour_values(keep=self.session is not None and k >= 3)
        self.console.print(
            f"[bold]Say:[/bold] {escape(step.say.format(**values))}", highlight=False
        )
        self._in_step = True
        try:
            for template in step.commands:
                line = template.format(**values)
                if not committed and line.startswith(("cert", "tamper")):
                    continue  # no certificates without commitments
                self.console.print(
                    f"[dim]{escape(self.label)}[/dim]{escape(line)}", highlight=False
                )
                self.onecmd(line)
        finally:
            self._in_step = False
        self.console.print(
            f"[bold]Look for:[/bold] {escape(step.look_for.format(**values))}", highlight=False
        )
        self.tour_pos += 1
        if self.tour_pos <= n_steps:
            self.hint("tour")
        elif self.notes:
            self.console.print(
                "  [dim]→ tour complete: that is the whole story. quit to leave, or keep "
                "exploring (help).[/dim]"
            )

    def do_status(self, arg: str) -> None:
        """status: what this session has loaded, deleted and certified, and what is switched on."""
        t = Table(title="This session", show_header=False)
        t.add_column("what", style="bold")
        t.add_column("now")
        s = self.session
        if s is None:
            t.add_row("index", "not loaded (type load)")
        else:
            idx = s.index
            sizes = idx.sizes()
            t.add_row(
                "records",
                f"{len(s.ids):,} loaded, {len(idx.locator):,} live, "
                f"{len(s.deleted):,} deleted in this session",
            )
            t.add_row("groups", f"{len(sizes)}, holding {min(sizes):,} to {max(sizes):,} records")
            if idx.committed and self.cert_dir is not None:
                folder = (
                    self.cert_dir.relative_to(REPO)
                    if self.cert_dir.is_relative_to(REPO)
                    else self.cert_dir
                )
                t.add_row("certificates", f"{len(idx.issued):,} issued, in {folder}/")
            else:
                t.add_row("certificates", "on" if idx.committed else "off (no commitments)")
        t.add_row("planted bug", group_module.SABOTAGE or "none")
        if self.tour_pos is None:
            tour = "not started (type tour)"
        elif self.tour_pos > len(guide.TOUR):
            tour = "finished"
        else:
            tour = f"next: step {self.tour_pos} of {len(guide.TOUR)}, "
            tour += guide.TOUR[self.tour_pos - 1].title
        t.add_row("tour", tour)
        t.add_row("notes", "on" if self.notes else "off")
        t.add_row(
            "ledger", f"{self._ledger_path()}: {self._session_lines()} lines from this session"
        )
        self.console.print(t)
        self.hint("status")

    # ------------------------------------------------------------------ data

    def do_verify_data(self, arg: str) -> None:
        """verify_data: re-hash every dataset file against datasets/MANIFEST.sha256 (Phase 0).

        Reads about 1.5 GB (10-90 s). Loads nothing: it only proves that the data on disk is the
        data that was pinned and committed."""
        t0 = time.perf_counter()
        bad = check_manifest()
        ok = not bad
        files = sum(1 for line in MANIFEST_PATH.read_text(encoding="utf-8").splitlines() if line)
        colour = "green" if ok else "red"
        self.console.print(
            f"[bold {colour}]{'PASS' if ok else 'FAIL'}[/]: {files} files re-hashed, "
            f"{len(bad)} mismatches {escape(str(bad)) if bad else ''}"
            f"({time.perf_counter() - t0:.0f}s)"
        )
        self.last = {"mismatches": bad}
        self.log("verify_data", "PASS" if ok else "FAIL", counts={"manifest_mismatches": len(bad)})
        self.note("verify_data")
        self.hint("verify_data")

    def do_load(self, arg: str) -> None:
        """load [N]: check, quantise, route and insert the first N NQ records (default: all).

        The norm check on every vector (§4.1; results cached per file hash), the record ID check
        (§3.2), quantise (§4.2), route each vector to the nearest of 128 fixed groups (§7.1) and
        insert in a seeded order. With commitments: r_t for every record, C_S for every group."""
        text = arg.strip()
        if text and not text.isdigit():
            raise ValueError("load takes a number of records, e.g. load 50000 (or nothing: all)")
        t0 = time.perf_counter()
        x = np.load(NQ, mmap_mode="r")
        n = min(int(text) if text else x.shape[0], x.shape[0])

        failures = 0
        for name, path, rel in [("SciQ", SCIQ, SCIQ_REL), ("NQ", NQ, NQ_REL)]:
            rep, cached = cached_norm_report(path, rel)
            failures += rep["non_finite"] + rep["bad_length"]
            when = f"cached result of {rep.get('checked_utc', '?')}" if cached else "checked now"
            self.console.print(
                f"  norm check §4.1, {name}: {rep['rows']:,} rows, "
                f"{rep['non_finite'] + rep['bad_length']} failures, "
                f"worst {rep['worst_abs_diff']:.3e} "
                f"({when}, file sha256 {manifest_hash(rel)[:12]}…)"
            )
        if failures:
            self.console.print("[red]Norm check failed: not loading (§4.1, check never fix)[/red]")
            self.log(f"load {n}", "FAIL", counts={"norm_failures": failures})
            return

        ids, cohorts = load_ids_and_cohorts(NQ_PASSAGES, n)
        rejected = 0
        for rid in ids:
            try:
                validate_record_id(rid)
            except InvalidRecordId:
                rejected += 1
        self.console.print(f"  ID check §3.2: {len(ids):,} IDs, {rejected} rejected")
        if rejected:
            self.log(f"load {n}", "FAIL", counts={"id_rejections": rejected})
            return

        q = cached_quantised(NQ, NQ_REL)[:n]
        labels = route(q, cached_centroids(self.seed))
        index = Index(q, ids, labels, K_FROZEN)
        order = np.random.default_rng(sub_seed(self.seed, b"stream")).permutation(n)
        for row in order:
            index.insert(ids[row])
        self.session = Session(index, ids, cohorts, x[:n], order, self.seed)
        self.tour_vars, self.seen, self.focus = {}, {}, None
        self.console.print(size_table(index.sizes()))
        if self.commitments:
            t1 = time.perf_counter()
            index.enable_commitments()  # §9.3-9.4; r_t and keys stay in memory
            self.cert_dir = CERTS / time.strftime("repl-%Y-%m-%dT%H%M%SZ", time.gmtime())
            self.save_certificates()
            self.console.print(
                f"  commitments: r_t for {n:,} records from the OS (never shown or stored), "
                f"C_S for {K_FROZEN} groups ({time.perf_counter() - t1:.0f}s); certificates go to "
                f"{self.cert_dir.relative_to(CERTS.parent.parent)}/"
            )
        self.console.print(f"  loaded in {time.perf_counter() - t0:.0f}s")
        self.log(f"load {n}", "PASS", counts={"norm_failures": 0, "id_rejections": 0})
        self.note("load")
        if self.commitments:
            self.note("load_commitments")
        self.hint("load")

    # ------------------------------------------------------------------ look

    def do_stats(self, arg: str) -> None:
        """stats: how many groups, and how many records the smallest, middle and largest hold."""
        if s := self.need_session():
            groups = s.index.groups
            self.console.print(size_table(s.index.sizes()))
            biggest = sorted(range(len(groups)), key=lambda g: -groups[g].n)[:5]
            self.console.print(
                "  largest groups: " + ", ".join(f"{g} ({groups[g].n:,})" for g in biggest)
            )
            self.note("stats")
            self.hint("stats")

    def do_group(self, arg: str) -> None:
        """group <g>: one group's state: n, the SHA-256 of S, the blob hash, and C_S.

        Use it before a deletion, to have the 'before' values on screen."""
        if not (s := self.need_session()):
            return
        gid = self.group_arg(s, arg, "group")
        g = s.index.groups[gid]
        s_hash = hashlib.sha256(g.S.astype(">i8").tobytes()).hexdigest()
        blob = g.blob_hash()
        t = Table(title=f"group {gid}")
        cols = ["n (records)", "S (SHA-256 of the sum)", "blob (SHA-256 of everything)"]
        for col in cols + (["C_S (sealed fingerprint)"] if g.committed else []):
            t.add_column(col)
        row = [f"{g.n:,}", short(s_hash), short(blob)]
        t.add_row(*row, *([short(g.C_S)] if g.committed else []))
        self.console.print(t)
        self.remember(gid, blob, f"at `group {gid}`")
        self.focus = gid
        self.last = {"n": g.n, "s_hash": s_hash}
        self.note("group", g=gid)
        self.hint("group")

    def do_ids(self, arg: str) -> None:
        """ids <g>: a few live record IDs in group g, in arrival order (to pick one to delete)."""
        if not (s := self.need_session()):
            return
        gid = self.group_arg(s, arg, "ids")
        g = s.index.groups[gid]
        some = list(g.members)[:5]
        self.console.print(f"  some live IDs in group {gid} (of {g.n:,}): {', '.join(some)}")
        self.focus = gid
        self.note("ids")
        self.hint("ids")

    def do_find(self, arg: str) -> None:
        """find <record_id>: is this record live, and in which group? Or deleted, or not loaded."""
        if not (s := self.need_session()):
            return
        rid = arg.strip()
        if not rid:
            raise ValueError("find needs a record ID, e.g. find doc2015226")
        gid = s.index.locator.get(rid)
        if gid is not None:
            self.console.print(
                f"  {escape(rid)} is [green]live[/green] in group {gid} "
                f"(n = {s.index.groups[gid].n:,})"
            )
            self.focus = gid
        elif rid in s.index.row_of:
            home = int(s.index.labels[s.index.row_of[rid]])
            self.console.print(
                f"  {escape(rid)} is [yellow]not live[/yellow]: deleted in this session. Its group "
                f"was {home}; nothing of it is left there, not even a marker (§5.4)"
            )
            self.focus = home
            self.hint("find_gone")
            return
        else:
            self.console.print(
                f"  {escape(rid)} is not in the loaded data ({len(s.ids):,} records loaded)"
            )
        self.hint("find")

    # ------------------------------------------------------------------ change

    def do_delete(self, arg: str) -> None:
        """delete <record_id>: delete one record (§5.3, §5.4) and show exactly what changed.

        Shows the group touched, n before → after, the blob hash before → after and, with
        commitments, C_S before → after, the public check C_S_post + C_t = C_S_pre and the signed
        certificate written. Deleting a record that is not live returns AlreadyAbsent and changes
        nothing."""
        if not (s := self.need_session()):
            return
        rid = arg.strip()
        if not rid:
            raise ValueError("delete needs a record ID, e.g. delete doc2015226 (ids 3 lists some)")
        gid = s.index.locator.get(rid)
        before, n_before, c_pre = "", 0, IDENTITY
        if gid is not None:
            self.backup({gid})
            g = s.index.groups[gid]
            before, n_before, c_pre = g.blob_hash(), g.n, g.C_S
            self.remember(gid, before, f"before `delete {rid}`")
        outcome, gid_out = s.index.delete(rid)
        if outcome is Outcome.DELETED:
            s.deleted.add(rid)
        if gid_out is None or outcome is not Outcome.DELETED:
            self.console.print(
                f"  [yellow]{outcome.value}[/yellow]: {escape(rid)} is not live, so nothing was "
                "subtracted and nothing changed"
            )
            self.last = {"outcome": outcome, "group": gid_out}
            self.log("delete <id>", outcome.value)  # the ledger never holds the record ID (§17)
            self.note("delete_absent")
            self.hint("delete_absent")
            return
        g = s.index.groups[gid_out]
        after = g.blob_hash()
        self.console.print(
            f"  [bold]Deleted[/bold] {escape(rid)} from group {gid_out}      "
            f"n {n_before:,} → {g.n:,}\n"
            f"  blob hash  {short(before)} → {short(after)}"
        )
        self.same_as(gid_out, after)
        self.remember(gid_out, after, f"after `delete {rid}`")
        cert = s.index.last_certificate
        cert_name = None
        if cert is not None:
            path = self.save_certificates()[-1]
            cert_name = path.name
            c_t, c_post = cert[5:37], g.C_S  # tag 1's value is bytes 5..36
            public_ok = point_add(c_post, c_t) == c_pre
            self.console.print(
                f"  C_S        {short(c_pre)} → {short(c_post)}   moved by this record's "
                f"C_t {short(c_t)}\n"
                f"  public check C_S_post + C_t = C_S_pre: "
                f"{'[green]holds[/green]' if public_ok else '[red]FAILS[/red]'}\n"
                f"  certificate {path.name} written ({len(cert):,} bytes: signed, with a proof); "
                f"check it with: cert last"
            )
        self.focus = gid_out
        self.last = {"outcome": outcome, "group": gid_out}
        extra: dict[str, Any] = {"group": gid_out, "n_after": g.n}
        if cert_name:
            extra["cert"] = cert_name
        self.log("delete <id>", outcome.value, **extra)  # never the record ID (§17)
        if group_module.SABOTAGE:
            self.note("delete_sabotaged")
            self.hint("delete_sabotaged")
            return
        self.note("delete")
        if cert is not None:
            self.note("delete_commit")
        self.hint("delete")

    def do_insert(self, arg: str) -> None:
        """insert <record_id>: put a deleted record back into its nearest group (§5.3, §7.1).

        Shows n and the blob hash before → after. If the new hash was seen earlier in this session,
        it says so: `delete X`, `insert X`, `delete X` returns to exactly the same hash."""
        if not (s := self.need_session()):
            return
        rid = arg.strip()
        if not rid:
            raise ValueError("insert needs a record ID that was deleted, e.g. insert doc2015226")
        if rid not in s.index.row_of:
            raise ValueError("insert takes a record ID from the loaded data")
        if (live := s.index.locator.get(rid)) is not None:
            self.console.print(
                f"  [yellow]{escape(rid)} is already live in group {live}[/yellow]: an ID can be "
                "live only once (§3.2 rule 3)"
            )
            return
        gid = int(s.index.labels[s.index.row_of[rid]])
        self.backup({gid})
        g = s.index.groups[gid]
        before, n_before, c_pre = g.blob_hash(), g.n, g.C_S
        self.remember(gid, before, f"before `insert {rid}`")
        s.index.insert(rid)
        s.deleted.discard(rid)
        after = g.blob_hash()
        self.console.print(
            f"  [bold]Inserted[/bold] {escape(rid)} into group {gid} (its nearest group)      "
            f"n {n_before:,} → {g.n:,}\n"
            f"  blob hash  {short(before)} → {short(after)}"
        )
        self.same_as(gid, after)
        self.remember(gid, after, f"after `insert {rid}`")
        if g.committed:
            self.console.print(f"  C_S        {short(c_pre)} → {short(g.C_S)}")
        self.focus = gid
        self.last = {"group": gid, "blob": after}
        self.log("insert <id>", "Inserted", group=gid, n_after=g.n)
        self.note("insert")
        self.hint("insert")

    def do_delete_user(self, arg: str) -> None:
        """delete_user <cohort title> | delete_user <N>: delete a whole cohort (or N random ones).

        A cohort is everything one 'user' contributed (§3.5): here, all passages of one Wikipedia
        article. Then: the survivors check on every touched group, and every other group's blob
        hash must be unchanged."""
        if not (s := self.need_session()):
            return
        arg = arg.strip()
        if not arg:
            raise ValueError("delete_user needs a cohort title or a number, e.g. delete_user 5")
        if arg.isdigit():
            titles = s.cohort_titles()
            pick = self.rng.choice(len(titles), size=int(arg), replace=False)
            chosen = [titles[i] for i in pick]
        else:
            chosen = [arg]
        rids = [rid for c in chosen for rid in s.cohort_members(c)]
        if not rids:
            self.console.print("  [yellow]no records with that cohort title[/yellow]")
            return
        shown = ", ".join(
            f"'{escape(c[:40])}' ({len(s.cohort_members(c))})" for c in chosen[:5]
        ) + (", …" if len(chosen) > 5 else "")
        self.console.print(f"  cohorts: {shown}", highlight=False)
        groups = {s.index.locator[r] for r in rids if r in s.index.locator}
        self.backup(groups)
        before = s.index.group_hashes()
        outcomes = s.index.delete_user(rids)
        touched = {gid for _, o, gid in outcomes if o is Outcome.DELETED and gid is not None}
        removed: dict[int, int] = {}
        for _, o, gid in outcomes:
            if o is Outcome.DELETED and gid is not None:
                removed[gid] = removed.get(gid, 0) + 1
        s.deleted.update(r for r, o, _ in outcomes if o is Outcome.DELETED)
        after = s.index.group_hashes()
        untouched = len(after) - len(touched)
        untouched_changed = sum(after[g] != before[g] for g in after if g not in touched)

        t = Table(title=f"delete_user: {len(chosen)} cohort(s), {len(rids)} records")
        fields = self.fields()
        for col in ["group", "removed", "n after", *fields]:
            t.add_column(col)
        mismatches = 0
        for gid in sorted(touched):
            res = s.index.survivors_check(gid, self.rng)
            mismatches += res != dict.fromkeys(fields, True)
            t.add_row(
                str(gid),
                str(removed[gid]),
                f"{s.index.groups[gid].n:,}",
                *(TICK if res[f] else CROSS for f in fields),
            )
        self.console.print(t)
        n_deleted = sum(o is Outcome.DELETED for _, o, _ in outcomes)
        exact = (
            f"[green]all {len(touched)} exact[/green]"
            if mismatches == 0
            else f"[red]{mismatches} of {len(touched)} NOT exact[/red]"
        )
        moved = "[green]" if untouched_changed == 0 else "[red]"
        self.console.print(
            f"  {n_deleted} deleted ({len(rids) - n_deleted} already absent) from "
            f"{len(touched)} groups: {exact}\n"
            f"  untouched groups changed: {moved}{untouched_changed} of {untouched}[/]"
        )
        if s.index.committed:
            paths = self.save_certificates()
            self.console.print(
                f"  {n_deleted} certificates written (now {len(paths)} in this session); "
                "check them with: cert all"
            )
        self.last = {"touched": touched, "mismatches": mismatches, "untouched": untouched_changed}
        ok = mismatches == 0 and untouched_changed == 0
        self.log(
            f"delete_user {'<title>' if not arg.isdigit() else arg}",
            "PASS" if ok else "FAIL",
            counts={
                "ops": len(rids),
                "deleted": n_deleted,
                "checks": len(touched),
                "mismatches": mismatches,
                "untouched_changed": untouched_changed,
            },
        )
        self.note("delete_user")
        self.hint("delete_user" if s.index.committed else "delete_absent")

    # ------------------------------------------------------------------ prove

    def do_verify(self, arg: str) -> None:
        """verify <g>: the survivors check (§5.5) on group g, every field.

        Builds a brand-new group from only the records still in group g, inserted in a shuffled
        order, and compares it with the live group: S, n, members, C_S and the blob. S is also
        re-added from the member rows by separate code. Equal on every field: EXACT."""
        if not (s := self.need_session()):
            return
        gid = self.group_arg(s, arg, "verify")
        live, rebuilt, res = s.index.survivors_report(gid, self.rng)
        g = s.index.groups[gid]
        fresh_ok = bool(np.array_equal(g.S, fresh_sum(g.vectors, g.members.values())))
        t = Table(
            title=f"survivors check, group {gid}: the live group vs a group rebuilt from its "
            f"{len(live.member_ids):,} survivors only"
        )
        for col in ["field", "what it is", "live group", "rebuilt from survivors", "same?"]:
            t.add_column(col)
        fields = self.fields()
        for f in fields:
            info = guide.FIELD_INFO[f] if f != "blob" or g.committed else "all of it as bytes"
            t.add_row(f, info, *field_values(f, live, rebuilt), TICK if res[f] else CROSS)
        self.console.print(t)
        ok = all(res.values())
        failed = [f for f in fields if not res[f]]
        if ok:
            self.console.print(
                f"  [bold green]EXACT[/]: all {len(fields)} fields equal. Group {gid} is exactly "
                "what its survivors alone would give."
            )
        else:
            self.console.print(f"  [bold red]MISMATCH[/] in {', '.join(failed)}")
            width = max(40, min(self.console.width, 110) - 6)
            for line in diagnose(live, res, g.committed):
                for i, part in enumerate(textwrap.wrap(line, width)):
                    bullet = "•" if i == 0 else " "
                    self.console.print(f"  [red]{bullet} {escape(part)}[/red]", highlight=False)
        self.console.print(
            "  S re-added from the member rows by separate code: "
            f"{'equal' if fresh_ok else '[red]DIFFERENT[/red]'}"
        )
        self.focus = gid
        self.last = {"result": res, "failed": failed}
        self.log(
            f"verify {gid}",
            "PASS" if ok else "FAIL",
            counts={"checks": 1, "mismatches": int(not ok)},
            failed=failed,
        )
        if ok:
            self.note("verify_exact")
            self.hint("verify" if s.index.issued else "verify_plain")
        else:
            self.note("verify_mismatch")
            self.hint("verify_mismatch")

    def do_ghost(self, arg: str) -> None:
        """ghost [g]: SEVER vs a float32 running mean vs soft delete, on a group with deletions.

        The same records are inserted and the same ones deleted, three ways. Without a group
        number it uses the group with the most deletions so far."""
        if not (s := self.need_session()):
            return
        labels = s.index.labels
        if arg.strip():
            gid = self.group_arg(s, arg, "ghost")
            why = ""
        else:
            per_group: dict[int, int] = {}
            for rid in s.deleted:
                g = int(labels[s.index.row_of[rid]])
                per_group[g] = per_group.get(g, 0) + 1
            if not per_group:
                self.console.print(
                    "  [yellow]delete something first (delete / delete_user)[/yellow]"
                )
                return
            gid = max(per_group, key=lambda g: (per_group[g], -g))
            why = f", the group with the most deletions so far ({per_group[gid]})"
        rows = s.order[labels[s.order] == gid]
        mask = np.array([s.ids[r] in s.deleted for r in rows])
        if not mask.any():
            self.console.print(f"  [yellow]no deletions in group {gid} yet[/yellow]")
            return
        rep = ghost_report(
            np.asarray(s.x[rows]),
            np.asarray(s.index.vectors[rows]),
            mask,
            np.random.default_rng(sub_seed(self.seed, b"ghost")),
            cycles=1000,
        ).as_dict()
        self.console.print(f"  group {gid}{why}: the same records inserted and deleted, 3 ways")
        self.console.print(ghost_table(rep))
        errs: dict[int, float] = rep["float_cycle_error"]
        stays = " (never back to 0)" if all(v > 0 for v in errs.values()) else ""
        self.console.print(
            f"  float32 error after {' / '.join(str(k) for k in errs)} delete-and-re-insert "
            f"cycles: {' / '.join(f'{v:.2e}' for v in errs.values())}{stays}"
        )
        self.last = rep
        self.log(f"ghost {gid}", "PASS" if rep["sever_bit_identical"] else "FAIL", ghost=rep)
        self.note("ghost")
        self.hint("ghost")

    def do_stress(self, arg: str) -> None:
        """stress <n>: n seeded random operations (delete, delete again, re-insert), each checked.

        A cheap check after every operation (S equals a fresh sum of the members, n equals the
        member count), the full check every 50 operations and on every touched group at the end."""
        if not (s := self.need_session()):
            return
        if group_module.SABOTAGE:
            self.console.print("  [yellow]turn sabotage off first (sabotage off)[/yellow]")
            return
        text = arg.strip()
        if text and not text.isdigit():
            raise ValueError("stress takes a number of operations, e.g. stress 200")
        n_ops = int(text or 200)
        pool = sorted(s.deleted)
        mismatches = 0
        touched: set[int] = set()
        t0 = time.perf_counter()
        for i in range(n_ops):
            row = int(self.rng.integers(len(s.ids)))
            rid = s.ids[row]
            gid = int(s.index.labels[row])  # the record's §7.1 group
            g = s.index.groups[gid]
            if rid in s.index.locator:
                s.index.delete(rid)
                s.deleted.add(rid)
                pool.append(rid)
                ok = True
            elif pool and self.rng.random() < 0.5:
                rid = pool.pop(int(self.rng.integers(len(pool))))
                if rid in s.index.locator:
                    continue
                gid = s.index.insert(rid)
                g = s.index.groups[gid]
                s.deleted.discard(rid)
                ok = True
            else:  # delete of an absent record: AlreadyAbsent and nothing may change (§5.4)
                s_before, n_before = g.S.copy(), g.n
                outcome, _ = s.index.delete(rid)
                ok = outcome is Outcome.ALREADY_ABSENT
                ok = ok and np.array_equal(g.S, s_before) and g.n == n_before
            touched.add(gid)
            ok = ok and bool(np.array_equal(g.S, fresh_sum(g.vectors, g.members.values())))
            ok = ok and g.n == len(g.members)
            if (i + 1) % 50 == 0:
                ok = ok and all(s.index.survivors_check(gid, self.rng).values())
            mismatches += not ok
        end_fail = sum(not all(s.index.survivors_check(g, self.rng).values()) for g in touched)
        mismatches += end_fail
        colour = "green" if mismatches == 0 else "red"
        self.console.print(
            f"  {n_ops} ops on {len(touched)} groups, cheap check after each, full every 50 and at"
            f" the end: [bold {colour}]{mismatches} mismatches[/] ({time.perf_counter() - t0:.0f}s)"
        )
        self.last = {"mismatches": mismatches}
        self.log(
            f"stress {n_ops}",
            "PASS" if mismatches == 0 else "FAIL",
            counts={"ops": n_ops, "mismatches": mismatches},
        )
        self.note("stress")
        self.hint("stress")

    def do_sabotage(self, arg: str) -> None:
        """sabotage [SB-1|SB-2|SB-3|SB-4|off]: the planted bugs (Build §2.6).

        With no argument, lists them: what each breaks and how to see it here. `sabotage SB-k`
        switches one on (the prompt shows it); `sabotage off` switches it off and rolls back every
        group it changed."""
        choice = arg.strip()
        if not choice:
            t = Table(title="Planted bugs: each must turn a check red")
            for col in ["bug", "what it does", "what it breaks", "how to see it here"]:
                t.add_column(col)
            for bug, (what, breaks, see) in guide.SABOTAGE_BUGS.items():
                style = "yellow" if see.startswith("not here") else "default"
                t.add_row(bug, escape(what), escape(breaks), f"[{style}]{escape(see)}[/]")
            self.console.print(t)
            return
        if not (s := self.need_session()):
            return
        bug = choice.upper()
        if bug in SABOTAGES:
            if group_module.SABOTAGE is None:
                self._backup_locator = dict(s.index.locator)
                self._backup_deleted = set(s.deleted)
            group_module.SABOTAGE = bug
            self._set_prompt()
            what, breaks, see = guide.SABOTAGE_BUGS[bug]
            colour = "yellow" if see.startswith("not here") else "white"
            self.console.print(
                f"  [red bold]SABOTAGE {bug} ON[/]: {escape(what)}\n"
                f"  it breaks: {escape(breaks)}\n"
                f"  [{colour}]to see it: {escape(see)}[/]"
            )
            self.log(f"sabotage {bug}", "INFO")
            self.note("sabotage_on")
            self.hint("sabotage_on")
        elif choice.lower() == "off":
            group_module.SABOTAGE = None
            self._set_prompt()
            for gid, (S, n, members, r_agg, c_s) in self._backup_groups.items():  # noqa: N806
                g: Group = s.index.groups[gid]
                g.S, g.n, g.members, g.r_agg, g.C_S = S, n, members, r_agg, c_s
            if self._backup_locator is not None:
                s.index.locator = self._backup_locator
            if self._backup_deleted is not None:
                s.deleted = self._backup_deleted
            restored = len(self._backup_groups)
            self._backup_groups, self._backup_locator, self._backup_deleted = {}, None, None
            self.console.print(
                f"  [green]sabotage off[/green]: {restored} group(s) rolled back to their state "
                "before the bug ran"
            )
            self.log("sabotage off", "INFO", rolled_back=restored)
            self.note("sabotage_off")
            self.hint("sabotage_off")
        else:
            self.console.print(
                "  usage: sabotage SB-1 | SB-2 | SB-3 | SB-4 | off  (sabotage alone lists them)"
            )

    def do_cert(self, arg: str) -> None:
        """cert [last|all|k]: check certificates with the independent verifier (§11.3).

        The verifier runs as its own process and sees only the certificate files and the public
        keys (anchors.json), never the database. One certificate: every step is shown."""
        if not self.need_session():
            return
        paths = self.save_certificates()
        if not paths or self.cert_dir is None:
            self.console.print("  [yellow]no certificates yet (delete something first)[/yellow]")
            return
        chosen = self.cert_choice(arg, paths, "cert")
        accepted, output = run_verifier(self.cert_dir / "anchors.json", chosen)
        if len(chosen) == 1:
            self.console.print(output.rstrip(), markup=False, highlight=False)
        else:
            bad = [name for name, ok in accepted.items() if not ok]
            colour = "green" if not bad else "red"
            self.console.print(
                f"  verifier (separate process, no database): [bold {colour}]"
                f"{len(chosen) - len(bad)} accepted, {len(bad)} rejected[/] "
                f"{escape(str(bad)) if bad else ''}"
            )
        self.last = {"accepted": accepted}
        ok = all(accepted.values()) and len(accepted) == len(chosen)
        self.log(
            f"cert {arg.strip() or 'last'}",
            "PASS" if ok else "FAIL",
            counts={"certs_checked": len(chosen), "certs_verified": sum(accepted.values())},
        )
        if len(chosen) == 1:
            self.note("cert")
        if not ok:
            self.note("cert_rejected")
        self.hint("verify_mismatch" if group_module.SABOTAGE and not ok else "cert")

    def do_tamper(self, arg: str) -> None:
        """tamper [last|k]: forge a receipt, then verify it: it must be REJECTED.

        Copies a certificate and flips one bit of its deletion number (lsn), as if the receipt were
        reused for another deletion."""
        if not self.need_session():
            return
        paths = self.save_certificates()
        if not paths or self.cert_dir is None:
            self.console.print("  [yellow]no certificates yet (delete something first)[/yellow]")
            return
        src = self.cert_choice(arg, paths, "tamper")[0]
        fake = tampered_copy(src, self.cert_dir / "tampered" / src.name, lsn_byte(src.read_bytes()))
        self.console.print(
            f"  forged copy of {src.name}: its deletion number (lsn) changed by one bit, as if the "
            "receipt were reused for another deletion"
        )
        accepted, output = run_verifier(self.cert_dir / "anchors.json", [fake])
        self.console.print(output.rstrip(), markup=False, highlight=False)
        caught = not accepted.get(fake.name, True)
        self.last = {"accepted": not caught}
        self.log("tamper", "PASS" if caught else "FAIL", counts={"tamper_caught": int(caught)})
        self.note("tamper")
        self.hint("tamper")

    # ------------------------------------------------------------------ record

    def do_ledger(self, arg: str) -> None:
        """ledger [n | session]: the last n run-ledger lines (default 5), or this session's lines.

        One line per check or change, appended by code and never edited: when, the command, its
        outcome, what it did in plain words, and the git commit the code came from (* means the
        code had uncommitted changes). Record IDs are never written (§17)."""
        path = Path(self.ledger.name)
        numbered = list(enumerate(read_entries(path), start=1))
        choice = arg.strip()
        if choice == "session":
            rows = [(i, e) for i, e in numbered if e.get("session") == self.session_id]
            showing = "this session's"
        elif not choice or choice.isdigit():
            k = int(choice) if choice else 5
            rows = numbered[-k:] if k > 0 else []
            showing = f"the last {len(rows)}"
        else:
            raise ValueError("ledger takes a number or `session`, e.g. ledger 14")
        mine = sum(e.get("session") == self.session_id for _, e in numbered)
        t = Table(
            title=f"{self._ledger_path()} (append-only): {len(numbered)} lines, {mine} from this "
            f"session; showing {showing}"
        )
        t.add_column("#", justify="right")
        t.add_column("time (IST)", no_wrap=True)
        t.add_column("command", max_width=22)
        t.add_column("outcome")
        t.add_column("what happened", ratio=1, min_width=36)
        t.add_column("git", no_wrap=True)
        for i, e in rows:
            outcome = str(e.get("outcome", ""))
            style = OUTCOME_STYLE.get(outcome, "white")
            git = str(e.get("git_commit", ""))[:7] + ("*" if e.get("git_dirty") else "")
            command = str(e.get("command", "")).removeprefix("repl ")
            command = command.replace("sever_demo.demo", "full run", 1)
            t.add_row(
                str(i),
                str(e.get("ts_ist", ""))[5:19].replace("T", " "),
                escape(command),
                f"[{style}]{escape(outcome)}[/]",
                escape(describe(e)),
                git,
            )
        self.console.print(t)
        self.console.print(
            "  [dim]PASS / FAIL: a check's verdict\n"
            "  Deleted / Inserted / AlreadyAbsent: what a change did\n"
            "  INFO: a planted bug switched on or off\n"
            "  git: the commit the code came from; * = it had uncommitted changes (git dirty)[/dim]"
        )
        self.note("ledger")
        self.hint("ledger")

    def do_save(self, arg: str) -> None:
        """save <name>: save everything shown since the last save as results/screens/<name>.svg."""
        name = arg.strip() or time.strftime("screen-%Y%m%dT%H%M%S")
        out = RESULTS / "screens" / f"{name}.svg"
        out.parent.mkdir(parents=True, exist_ok=True)
        self.console.save_svg(str(out), title=f"SEVER-DB demo: {name}", clear=True)
        self.console.print(f"  saved {out.relative_to(RESULTS.parent)}")
        self.console.export_text(clear=True)  # keep that line out of the next screenshot

    def do_quit(self, arg: str) -> bool:
        """quit: leave the shell (a planted bug is switched off)."""
        group_module.SABOTAGE = None
        self.console.print(
            f"  bye: {self._session_lines()} ledger lines written in this session "
            f"({self.session_id})"
        )
        return True

    do_EOF = do_quit  # noqa: N815


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sever_demo.repl", description=__doc__)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    p.add_argument("--no-commitments", dest="commitments", action="store_false")
    p.add_argument("--no-notes", dest="notes", action="store_false", help="start with notes off")
    args = p.parse_args(argv)
    with open_ledger(args.ledger) as ledger:  # Overview §13.3: no ledger, no run
        shell = SeverShell(ledger, seed=args.seed, commitments=args.commitments, notes=args.notes)
        shell.keep_going = True
        shell.cmdloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
