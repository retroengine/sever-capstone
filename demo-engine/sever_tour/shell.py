"""The demo shell: use the database yourself. The database and the backend's state persist in the
work directory, so you can quit and come back; ``reset`` starts again from nothing.

Questions are the 3,452 real NQ test queries (their vectors were made by the pinned encoder);
pick one by number or by words in it. Free text would need the encoder itself, which this
environment does not install.
"""

import cmd
import json
import shlex
from pathlib import Path

from . import tools
from .data import Corpus
from .session import Session, say
from .tour import SNIPPET, Tour, crash_insert

INTRO = """SEVER-DB demo shell. Type help, or try:
  load 1000        insert the next 1,000 passages        ask chicago fire   search with a question
  accounts fire    accounts whose name has "fire"         forget <account>   delete its records
  verify           check the latest receipt offline       crash              kill a writer, recover
"""


class Shell(cmd.Cmd):
    prompt = "sever> "

    def __init__(self, root: Path, corpus: Corpus, work: Path, dev: bool) -> None:
        super().__init__()
        self.root = root
        self.c = corpus
        self.s = Session(corpus, work, dev)
        self.intro = INTRO
        self._open()

    def _open(self) -> None:
        self.s.open()
        if self.s.refused:
            say(f"(development override in use: {self.s.refused})")
        self.s.create()
        self._status()

    def _status(self) -> None:
        st = self.s.live.stats(self.s.state.cid)
        say(
            f"collection {self.s.state.cid}: {st['N'] + st['holding']} live records"
            f" ({st['N']} in {st['frozen']} frozen + {st['spawned']} spawned groups,"
            f" {st['holding']} in the holding area), {len(self.s.state.receipts)} receipts"
        )

    def _snip(self, rid: str) -> str:
        t = self.c.texts[self.c.position[rid]].replace("\n", " ")
        return t if len(t) <= SNIPPET else t[: SNIPPET - 1] + "…"

    def onecmd(self, line: str) -> bool:
        try:
            return super().onecmd(line)
        except Exception as e:  # the shell reports and goes on; §17 errors carry no secret
            say(f"error: {type(e).__name__}: {e}")
            return False

    def emptyline(self) -> bool:
        return False

    # -- the commands ----------------------------------------------------------------------------

    def do_load(self, arg: str) -> None:
        """load [N]: insert the next N passages (default 500) with their accounts and text."""
        n, per = self.s.insert_next(int(arg or 500))
        say(f"inserted {n} ({per * 1000:.1f} ms each)")
        self._status()

    def do_questions(self, arg: str) -> None:
        """questions WORDS: list questions containing the words (number, then the text)."""
        words = arg.lower().split()
        hits = [q for q, t in enumerate(self.c.questions) if all(w in t.lower() for w in words)]
        for q in hits[:15]:
            say(f"  {q:>5}  {self.c.questions[q]}")
        say(f"{len(hits)} questions match" + (" (first 15 shown)" if len(hits) > 15 else ""))

    def do_ask(self, arg: str) -> None:
        """ask N | ask WORDS: search with question number N, or the first question with the
        words. Prints the top 5; a tick marks the judged answer."""
        if arg.strip().isdigit():
            q = int(arg)
        else:
            words = arg.lower().split()
            qs = self.c.questions
            match = [i for i, t in enumerate(qs) if all(w in t.lower() for w in words)]
            if not match:
                say("no question has those words (try: questions WORDS)")
                return
            q = match[0]
        say(f'Q{q}: "{self.c.questions[q]}"')
        answers = self.c.answers.get(q, frozenset())
        for rank, (rid, dist) in enumerate(self.s.search(self.c.question_vectors[q], 5), 1):
            mark = "✓" if rid in answers else " "
            say(f"  {rank}. {mark} {dist:.3f}  [{rid}] {self._snip(rid)}")
        stored = answers & set(self.s.live_ids())
        if answers and not stored:
            say("  (its judged answer is not stored: not loaded yet, or deleted)")

    def do_like(self, arg: str) -> None:
        """like RECORD-ID: the records nearest to a stored record (more like this)."""
        rid = arg.strip()
        for rank, (h, dist) in enumerate(self.s.search(self.c.vectors[self.c.position[rid]], 6)):
            if rank:
                say(f"  {rank}. {dist:.3f}  [{h}] {self._snip(h)}")

    def do_show(self, arg: str) -> None:
        """show RECORD-ID: its account, whether it is live, and its passage (from the dataset)."""
        rid = arg.strip()
        i = self.c.position[rid]
        if rid in self.s.state.deleted:
            where = "deleted"
        elif i >= self.s.state.loaded:
            where = "not loaded"
        elif self.s.searchable(rid):
            where = "live, in a group"
        else:
            where = "live, waiting in the holding area (searched once 200 make a group, §7.4)"
        say(f"[{rid}] account: {self.c.accounts[i]}; {where}")
        say(self.c.texts[i])

    def do_accounts(self, arg: str) -> None:
        """accounts [WORDS]: accounts with live records (filtered by words in the name)."""
        words = arg.lower().split()
        acc = {
            a: r for a, r in self.s.accounts().items() if r and all(w in a.lower() for w in words)
        }
        for a in sorted(acc, key=lambda a: (-len(acc[a]), a))[:20]:
            say(f"  {len(acc[a]):>3}  {a}")
        say(f"{len(acc)} accounts" + (" (largest 20 shown)" if len(acc) > 20 else ""))

    def do_forget(self, arg: str) -> None:
        """forget ACCOUNT: delete every live record of the account in one transaction."""
        ids = self.s.accounts().get(arg.strip().strip("\"'"), [])
        if not ids:
            say("no live records for that account (names are exact; see: accounts WORDS)")
            return
        out = self.s.forget(ids)
        say(
            f"deleted {sum(d.outcome == 'deleted' for d in out)} records; receipts: "
            + ", ".join(f"{d.database_lsn}.cert" for d in out if d.database_lsn is not None)
        )
        self._status()

    def do_delete(self, arg: str) -> None:
        """delete RECORD-ID: delete one record (again: "absent")."""
        d = self.s.forget([arg.strip()])[0]
        say(f"{d.outcome}" + (f"; receipt {d.database_lsn}.cert" if d.database_lsn else ""))

    def do_receipts(self, arg: str) -> None:
        """receipts: the certificates handed out so far."""
        say(" ".join(f"{n}.cert" for n in self.s.state.receipts) or "none yet")
        say(f"in {self.s.receipts} (with anchors.json)")

    def _cert(self, arg: str) -> str | None:
        name = arg.strip() or (f"{self.s.state.receipts[-1]}.cert" if self.s.state.receipts else "")
        if not name or not (self.s.receipts / name).exists():
            say("no such receipt (see: receipts)")
            return None
        return name

    def do_verify(self, arg: str) -> None:
        """verify [N.cert]: check a receipt offline with sever-verify (default: the latest)."""
        if name := self._cert(arg):
            t = tools.build(self.root)
            _, out = tools.run(
                [t.verify, name, "--anchors", "anchors.json", "--explain"], self.s.receipts
            )
            say(out)

    def do_tamper(self, arg: str) -> None:
        """tamper [N.cert]: flip one byte of a copy of the receipt and verify the copy."""
        if name := self._cert(arg):
            t = tools.build(self.root)
            b = bytearray((self.s.receipts / name).read_bytes())
            b[len(b) // 2] ^= 0x01
            bad = self.s.receipts / "tampered.bin"
            bad.write_bytes(bytes(b))
            args: list[str | Path] = [t.verify, bad.name, "--anchors", "anchors.json"]
            code, out = tools.run(args, self.s.receipts)
            bad.unlink()
            say(f"exit {code}: {out}")

    def do_audit(self, arg: str) -> None:
        """audit: export the public log and check it, and every receipt, with sever-audit."""
        t = tools.build(self.root)
        (self.s.work / "log.json").write_text(self.s.live.export_log(), "utf-8")
        (self.s.work / "anchors.json").write_text(self.s.live.anchors(), "utf-8")
        args: list[str | Path] = [t.audit, "log.json", "--anchors", "anchors.json"]
        for n in self.s.state.receipts:
            args += ["--certificate", self.s.receipts / f"{n}.cert"]
        say(tools.run(args, self.s.work)[1])

    def do_log(self, arg: str) -> None:
        """log: the latest signed log checkpoint and its witness cosignatures."""
        cp = self.s.live.latest_log_checkpoint()
        say(
            f"tree size {cp.tree_size}, root {cp.root.hex()[:16]}…, epoch {cp.epoch}, "
            f"{len(cp.cosignatures)} cosignatures"
        )

    def do_stats(self, arg: str) -> None:
        """stats: counts, and the ten largest groups."""
        say(json.dumps(self.s.live.stats(self.s.state.cid)))
        sizes = sorted(self.s.live.group_sizes(self.s.state.cid), key=lambda g: -g[1])[:10]
        say("largest groups: " + ", ".join(f"{g} {n}" for g, n in sizes))

    def do_disk(self, arg: str) -> None:
        """disk: the files on disk, and a raw search of them for live records' text and IDs."""
        files = tools.files_under([self.s.data, self.s.keys])
        say(f"{len(files)} files, {sum(f.stat().st_size for f in files) / 1e6:.1f} MB")
        live = self.s.live_ids()
        sample = live[:: max(1, len(live) // 40)][:40]
        texts = [self.c.texts[self.c.position[r]] for r in sample]
        vecs = [self.c.vectors[self.c.position[r]].astype("<f4").tobytes() for r in sample]
        hits = tools.count_hits(files, tools.needles_of(sample, texts, vecs))
        for kind, (found, n) in hits.items():
            say(f"  {kind:<13} {found} of {n} found in the clear")

    def do_restart(self, arg: str) -> None:
        """restart: close the database cleanly and open it again (recovery, invariant check)."""
        self.s.close()
        self._open()

    def do_crash(self, arg: str) -> None:
        """crash: a second process inserts the next passages and is killed with SIGKILL; then
        recovery runs, and every insert it was told was stored is checked."""
        tour = Tour(self.root, self.c, self.s.work, self.s.state.loaded, self.s.dev)
        tour.s = self.s
        before = self.s.total()
        acked, _, killed = crash_insert(tour, count=200)
        self.s.open()
        grew = self.s.total() - before
        lost = [r for r in acked if not self.s.stored(r)]
        self.s.state.loaded += grew
        self.s.save()
        say(
            f"{'killed' if killed else 'finished'} after {len(acked)} acknowledged inserts;"
            f" {grew} more records after recovery; acknowledged but missing: {len(lost)}"
            + (" (the insert in flight had committed too)" if grew == len(acked) + 1 else "")
        )
        self._status()

    def do_reset(self, arg: str) -> None:
        """reset: delete this shell's database, keys and receipts, and start again."""
        self.s.wipe()
        self._open()

    def do_quit(self, arg: str) -> bool:
        """quit: close the database and leave."""
        self.s.close()
        return True

    do_exit = do_quit
    do_EOF = do_quit  # noqa: N815 (cmd's name for end of input)


def run(root: Path, corpus: Corpus, work: Path, dev: bool, script: str | None) -> int:
    sh = Shell(root, corpus, work, dev)
    if script is None:
        try:
            sh.cmdloop()
        except KeyboardInterrupt:
            sh.s.close()
        return 0
    for line in script.split(";"):
        if line.strip():
            say(f"{sh.prompt}{line.strip()}")
            if sh.onecmd(" ".join(shlex.split(line))):
                return 0
    sh.s.close()
    return 0
