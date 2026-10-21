"""The guided tour: the final database used the way an application uses it, start to finish.

Each chapter says what it does and why, does it through the public SDK and tools, and checks the
claim it shows. The run ends with a summary; it exits non-zero if any check failed, and writes
``report.json`` in its work directory (numbers only: no key, ``r_t`` or passage text).
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from sever_db import (
    DuplicateRecord,
    InvalidRecordId,
    NotNormalised,
    SeededNonceForbidden,
    SeverError,
    UserKey,
    WrongDimension,
    prepare_insert,
)

from . import tools
from .data import Corpus, check_encoder
from .session import Session, say

SNIPPET = 96
NEXT = """demo-engine/demo.sh shell   use it yourself: load, ask, forget, verify, crash, ...
demo-engine/demo.sh cli     the same story with the sever-db command-line tool
demo-engine/demo.sh erase   the forensic proof: a scanner given the whole disk and the keys
                            recovers a live record but nothing deleted, and the build that
                            skips key rotation leaks
demo-engine/examples/       short programs to copy into your own backend"""


def chapter(n: int, title: str, why: str) -> None:
    say()
    say(f"{n:>2}. {title}")
    say("    " + "-" * (len(title) + 2))
    for line in why.strip().splitlines():
        say(f"    {line.strip()}")
    if why:
        say()


def snippet(c: Corpus, rid: str) -> str:
    t = c.texts[c.position[rid]].replace("\n", " ")
    return t if len(t) <= SNIPPET else t[: SNIPPET - 1] + "…"


class Tour:
    def __init__(self, root: Path, corpus: Corpus, work: Path, rows: int, dev: bool) -> None:
        self.root = root
        self.c = corpus
        self.rows = rows
        self.s = Session(corpus, work, dev)
        self.work = work
        self.checks: list[dict[str, Any]] = []
        self.numbers: dict[str, Any] = {"data": corpus.name, "rows": rows}

    def check(self, label: str, ok: bool, detail: str = "") -> None:
        self.checks.append({"check": label, "ok": ok})
        say(f"    [{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail else ""))

    # ------------------------------------------------------------------------------------------

    def open(self) -> None:
        chapter(
            1,
            "Open the database",
            """A database is two directories: data/ (encrypted records, the write-ahead log, the
            public log) and keys/ (the key file). Keep keys/ private and backed up apart from the
            data: without it the data cannot be read, which is exactly how deletion works.
            Opening checks the machine first (§12.8–12.9): unencrypted swap, hibernation,
            memory that cannot be locked, a filesystem that does not overwrite in place.""",
        )
        self.s.wipe()
        db = self.s.open()
        if self.s.refused:
            say(f"    The database refused this machine: {self.s.refused}")
            say("    --dev was given, so it opened with the development override, and reports it:")
        overridden, locked = db.startup
        say(f"    startup overrides: {list(overridden) or 'none'}; memory locked: {locked}")
        self.numbers["startup_overrides"] = list(overridden)
        self.check("the database opened, and reports every override it used", True)

    def create(self) -> None:
        chapter(
            2,
            "Create a collection",
            """A collection is built over a partition artefact: fixed group centroids, fitted
            once on separate data (§6.3). The vectors must come from the encoder the artefact
            names (§3.3), or search would compare things from different spaces.""",
        )
        enc = check_encoder(self.c)
        cid = self.s.create()
        st = self.s.live.stats(cid)
        say(f"    encoder (checked against the artefact): {enc}")
        say(f"    collection {cid}: {st['frozen']} frozen groups, dimension {self.c.d}")
        self.check("the collection exists and is empty", st["N"] == 0 and st["frozen"] > 0)

    def insert(self) -> None:
        chapter(
            3,
            "Insert passages, each owned by an account",
            """The application backend gives each account a key (UserKey). For each record,
            prepare_insert quantises the vector, draws a secret blinding value from the OS,
            commits to the vector and signs the commitment; the database stores the record
            encrypted. Here each Wikipedia article is one account that owns its passages.""",
        )
        n, per = self.s.insert_next(self.rows)
        st = self.s.live.stats(self.s.state.cid)
        accounts = len(self.s.accounts())
        say(f"    {n} passages from {accounts} accounts, {per * 1000:.1f} ms per insert")
        say(
            f"    groups: {st['frozen']} frozen, {st['spawned']} spawned; N = {st['N']} records in"
            f" groups, {st['holding']} waiting in the holding area for the next new group (§7.4)"
        )
        self.numbers.update(inserted=n, insert_ms=round(per * 1000, 2), accounts=accounts)
        self.check("every insert was acknowledged", n == self.rows)

    def ask(self) -> None:
        chapter(
            4,
            "Search with real questions",
            """A search returns the nearest records: (record ID, distance). The questions are
            real Natural Questions test queries; a tick marks the passage judged to answer it.""",
        )
        loaded = set(self.c.ids[: self.s.state.loaded])
        answerable = [q for q, a in self.c.answers.items() if a & loaded]
        t0 = time.perf_counter()
        top: dict[int, list[str]] = {}
        for q in answerable:
            top[q] = [h for h, _ in self.s.search(self.c.question_vectors[q], 10)]
        ms = (time.perf_counter() - t0) * 1000 / max(1, len(answerable))
        at1 = sum(1 for q in answerable if top[q][:1] and top[q][0] in self.c.answers[q])
        at10 = sum(1 for q in answerable if set(top[q]) & self.c.answers[q])
        for q in answerable[:3]:
            say(f'    Q: "{self.c.questions[q]}"')
            for rank, rid in enumerate(top[q][:3], 1):
                mark = "✓" if rid in self.c.answers[q] else " "
                say(f"       {rank}. {mark} {snippet(self.c, rid)}")
            say()
        say(f"    {len(answerable)} questions have their answer stored: the answer is first for")
        say(f"    {at1} of them and in the top 10 for {at10} ({ms:.2f} ms per search)")
        self.numbers.update(questions=len(answerable), hit_at_1=at1, hit_at_10=at10)
        self.top = top
        self.check("search returns the stored answers", at10 > 0)

    def disk(self) -> None:
        chapter(
            5,
            "What is on the disk",
            """Only public values are stored in the clear (§13.2): group sizes, commitments,
            centroids, scrambled IDs, the public log and certificates. Passage text, record IDs
            and vectors are encrypted. To show the search below can see, it first runs over a
            naive copy of the same records, as a usual store would keep them.""",
        )
        files = tools.files_under([self.s.data, self.s.keys])
        size = sum(f.stat().st_size for f in files)
        say(f"    {len(files)} files, {size / 1e6:.1f} MB (data/ and keys/)")
        live = self.s.live_ids()
        sample = live[:: max(1, len(live) // 40)][:40]
        idx = self.c.position
        texts = [self.c.texts[idx[r]] for r in sample]
        vecs = [self.c.vectors[idx[r]].astype("<f4").tobytes() for r in sample]
        needles = tools.needles_of(sample, texts, vecs)
        naive = self.work / "naive-store"
        tools.write_naive(naive, sample, texts, vecs)
        seen = tools.count_hits(tools.files_under([naive]), needles)
        hits = tools.count_hits(files, needles)
        for kind in needles:
            say(
                f"    {kind:<13} naive copy: {seen[kind][0]:>3} of {seen[kind][1]} found;"
                f"   SEVER-DB's disk: {hits[kind][0]} of {hits[kind][1]} found"
            )
        self.numbers["plaintext_hits"] = {k: v[0] for k, v in hits.items()}
        self.check(
            "the search finds every record in the naive copy", all(f == n for f, n in seen.values())
        )
        self.check(
            "no record ID, passage text or vector is on the disk in the clear",
            all(f == 0 for f, _ in hits.values()),
        )

    def refuses(self) -> None:
        chapter(
            6,
            "What the database refuses, and the safe retry",
            """Inputs are validated, never repaired (§4, §17); errors are typed and never
            contain an ID, a vector or a key. An insert whose answer was lost is retried with
            the same request: the database recognises it and nothing is stored twice.""",
        )
        c, db, cid = self.c, self.s.live, self.s.state.cid
        user = UserKey.generate()
        unit = self.c.vectors[self.s.state.loaded - 1].astype(np.float64)
        cases: list[tuple[str, type[SeverError], Any]] = [
            (
                "a vector that is not unit length",
                NotNormalised,
                lambda: prepare_insert(cid, "new-1", (unit * 2).tolist(), user),
            ),
            (
                "a vector of the wrong dimension",
                WrongDimension,
                lambda: db.insert(cid, prepare_insert(cid, "new-2", [1.0] + [0.0] * c.d, user)),
            ),
            (
                "a record ID that is a bare number",
                InvalidRecordId,
                lambda: db.insert(cid, prepare_insert(cid, "12345", unit.tolist(), user)),
            ),
            (
                "a second record with a live record's ID",
                DuplicateRecord,
                lambda: db.insert(cid, prepare_insert(cid, c.ids[0], unit.tolist(), user)),
            ),
            ("a seed passed to key generation", SeededNonceForbidden, lambda: UserKey.generate(42)),
        ]
        for label, kind, call in cases:
            try:
                call()
                self.check(f"refused {label}", False, "accepted")
            except kind:
                self.check(f"refused {label}", True, kind.__name__)
        req = prepare_insert(cid, "retry-demo-1", unit.tolist(), user)
        first = db.insert(cid, req)
        again = db.insert(cid, req)
        say(f"    insert: lsn {first.database_lsn}; the same request again: {again}")
        self.check("a retried insert is recognised and stored once", again.retried)
        db.delete(cid, "retry-demo-1")

    def forget(self) -> None:
        chapter(
            7,
            "Delete one person's records",
            """delete_user removes all of one account's records in one transaction: all or
            nothing (§12.5). Each record is subtracted from its group exactly, its group and
            bucket keys are rotated, and the old keys are overwritten before the call returns
            (§15.3). Each deletion returns a certificate, the receipt the person keeps.""",
        )
        acc, ids, q = self._pick_account()
        self.account, self.forgotten, self.question = acc, ids, q
        say(f'    account "{acc}": {len(ids)} records')
        if q is not None:
            say(f'    before: Q: "{self.c.questions[q]}"')
            for rank, rid in enumerate(self.top[q][:3], 1):
                mine = "  <- this account's" if rid in ids else ""
                say(f"       {rank}. {snippet(self.c, rid)}{mine}")
        t0 = time.perf_counter()
        out = self.s.forget(ids)
        ms = (time.perf_counter() - t0) * 1000
        lsns = [d.database_lsn for d in out]
        say(f"    deleted in {ms:.0f} ms; certificates at log positions {lsns}")
        self.numbers.update(forgotten=len(ids), forget_ms=round(ms, 1))
        self.check(
            "every record of the account was deleted, each with a certificate",
            all(d.outcome == "deleted" and d.certificate for d in out),
        )
        handed = self.work / "handed-to-the-person"
        handed.mkdir(exist_ok=True)
        for f in self.s.receipts.glob("*"):
            (handed / f.name).write_bytes(f.read_bytes())
        say(f"    handed over: {len(out)} .cert files and anchors.json -> {handed}")
        self.handed = handed

    def _pick_account(self) -> tuple[str, list[str], int | None]:
        """An account with several stored records, one of which answers a question it was found
        for in chapter 4 (so the "before and after" is visible), else the largest account."""
        accounts = {a: r for a, r in self.s.accounts().items() if len(r) >= 2}
        found = getattr(self, "top", {})
        best: tuple[int, str, int | None] = (0, "", None)
        for q, top in found.items():
            for rid in top[:3]:
                if rid in self.c.answers[q]:
                    acc = self.c.accounts[self.c.position[rid]]
                    if acc in accounts and len(accounts[acc]) > best[0]:
                        best = (len(accounts[acc]), acc, q)
        if not best[1]:
            acc = max(sorted(accounts), key=lambda a: len(accounts[a]))
            return acc, accounts[acc], None
        return best[1], accounts[best[1]], best[2]

    def verify(self) -> None:
        chapter(
            8,
            "Check the receipts offline",
            """The person checks each certificate with sever-verify, a separate program that
            shares no code with the database, using only the certificate and the public trust
            anchors: no database access (§11.3). It checks the commitments, the proof, the log
            inclusion and the witnesses' signatures. A copy with one flipped byte is rejected.""",
        )
        t = tools.build(self.root)
        certs = sorted(self.handed.glob("*.cert"), key=lambda p: int(p.stem))
        codes = [
            tools.run([t.verify, p.name, "--anchors", "anchors.json"], self.handed)[0]
            for p in certs
        ]
        say(f"    sever-verify: {codes.count(0)} of {len(certs)} accepted")
        _, explain = tools.run(
            [t.verify, certs[0].name, "--anchors", "anchors.json", "--explain"], self.handed
        )
        for line in explain.splitlines():
            say(f"      {line}")
        bad = bytearray(certs[0].read_bytes())
        bad[len(bad) // 2] ^= 0x01
        (self.handed / "tampered.cert.bin").write_bytes(bytes(bad))
        code, out = tools.run(
            [t.verify, "tampered.cert.bin", "--anchors", "anchors.json"], self.handed
        )
        reason = json.loads(out).get("reason", "") if out.startswith("{") else out
        say(f"    tampered copy: exit {code}, {reason}")
        (self.handed / "tampered.cert.bin").unlink()
        self.check("every certificate verifies offline", codes == [0] * len(certs))
        self.check("a tampered certificate is rejected", code == 1)

    def gone(self) -> None:
        chapter(
            9,
            "Deleted means gone",
            """No search returns a deleted record, even one made from its own vector. Deleting
            again changes nothing and returns "absent" (§5.4): a retried deletion is safe.""",
        )
        found = [r for r in self.forgotten if self.s.searchable(r)]
        say(f"    searches with each deleted record's own vector: {len(found)} found")
        if self.question is not None:
            q = self.question
            top = [h for h, _ in self.s.search(self.c.question_vectors[q], 10)]
            say(f'    after: Q: "{self.c.questions[q]}"')
            for rank, rid in enumerate(top[:3], 1):
                say(f"       {rank}. {snippet(self.c, rid)}")
            self.check(
                "the question no longer finds the deleted answer",
                not set(top) & set(self.forgotten),
            )
        self.check("no deleted record is found by any search", not found)
        self.check(
            'deleting each one again returns "absent"',
            all(self.s.absent(r) for r in self.forgotten),
        )
        st = self.s.live.stats(self.s.state.cid)
        say(f"    N = {st['N']} records in groups, {st['holding']} waiting in the holding area")
        self.check(
            "the count fell by exactly the deleted records",
            self.s.total() == self.s.state.loaded - len(self.forgotten),
        )

    def restart(self) -> None:
        chapter(
            10,
            "Restart, and pull the plug",
            """Closing and reopening runs recovery and a full invariant check. Then a second
            process inserts records and is killed with SIGKILL mid-stream, as a power cut would:
            every insert it had been told was stored must be there after recovery (§12, §15).""",
        )
        before = self.s.total()
        self.s.close()
        self.s.open()
        self.check("a clean restart keeps every record", self.s.total() == before)
        self.check(
            "deleted records stay deleted after a restart",
            all(self.s.absent(r) for r in self.forgotten),
        )
        before = self.s.total()
        acked, in_flight, killed = crash_insert(self, count=200)
        self.s.open()
        grew = self.s.total() - before
        lost = [r for r in acked if not self.s.stored(r)]
        committed = grew - len(acked) == 1
        self.s.state.loaded += grew
        self.s.save()
        say(
            f"    {'killed' if killed else 'finished'} after {len(acked)} acknowledged inserts;"
            f" after recovery {grew} more records are stored"
            + (" (the insert in flight had committed too)" if committed and in_flight else "")
        )
        self.numbers.update(crash_acked=len(acked), crash_lost=len(lost), crash_killed=killed)
        self.check("the writer was killed in the middle of its inserts", killed)
        self.check(
            "every acknowledged insert is there after recovery",
            acked != [] and lost == [] and grew - len(acked) in (0, 1),
            f"{len(lost)} missing",
        )

    def audit(self) -> None:
        chapter(
            11,
            "Audit the public log",
            """Every insert and deletion is a leaf of an append-only RFC 9162 log, signed by the
            operator and cosigned by witnesses (§10). An auditor checks the whole exported log,
            and that each certificate is in it, with sever-audit (no database access).""",
        )
        t = tools.build(self.root)
        cp = self.s.live.latest_log_checkpoint()
        say(
            f"    log: {cp.tree_size} leaves, epoch {cp.epoch}, {len(cp.cosignatures)} witness"
            " cosignatures"
        )
        auditor = self.work / "auditor"
        auditor.mkdir(exist_ok=True)
        (auditor / "log.json").write_text(self.s.live.export_log(), "utf-8")
        (auditor / "anchors.json").write_text(self.s.live.anchors(), "utf-8")
        args: list[str | Path] = [t.audit, "log.json", "--anchors", "anchors.json"]
        for p in sorted(self.handed.glob("*.cert")):
            args += ["--certificate", p]
        code, out = tools.run(args, auditor)
        say(f"    sever-audit: {out}")
        self.check("the auditor finds nothing wrong", code == 0)

    def next_steps(self) -> None:
        chapter(12, "What next", "")
        for line in NEXT.splitlines():
            say(f"    {line}")

    def run(self) -> int:
        try:
            for step in (
                self.open,
                self.create,
                self.insert,
                self.ask,
                self.disk,
                self.refuses,
                self.forget,
                self.verify,
                self.gone,
                self.restart,
                self.audit,
            ):
                step()
        finally:
            self.s.close()
        self.next_steps()
        failed = [c["check"] for c in self.checks if not c["ok"]]
        say(f"Summary: {len(self.checks) - len(failed)} of {len(self.checks)} checks passed")
        for f in failed:
            say(f"  FAILED: {f}")
        (self.work / "report.json").write_text(
            json.dumps({"numbers": self.numbers, "checks": self.checks}, indent=1), "utf-8"
        )
        say(f"Report: {self.work / 'report.json'}")
        return 1 if failed else 0


def crash_insert(tour: Tour, count: int) -> tuple[list[str], str | None, bool]:
    """Closes the database and lets a child process insert the next ``count`` records, logging
    each acknowledged ID. Once half are acknowledged it is killed with SIGKILL. Returns the
    acknowledged IDs, the ID that was in flight, and whether it was killed before finishing."""
    s = tour.s
    s.close()
    acks = tour.work / "acks.txt"
    acks.unlink(missing_ok=True)
    start = s.state.loaded
    count = min(count, len(tour.c.ids) - start)
    cmd = [
        sys.executable, "-m", "sever_tour", "crash-child", "--data", tour.c.name,
        "--rows", str(len(tour.c.ids)), "--work", str(tour.work),
        "--start", str(start), "--count", str(count),
    ] + (["--dev"] if s.dev else [])  # fmt: skip
    child = subprocess.Popen(cmd, cwd=tour.root, env=os.environ.copy())
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline and child.poll() is None:
        if acks.exists() and len(acks.read_text("utf-8").split()) >= count // 2:
            os.kill(child.pid, signal.SIGKILL)
            break
        time.sleep(0.01)
    killed = child.wait() == -signal.SIGKILL
    acked = acks.read_text("utf-8").split() if acks.exists() else []
    nxt = start + len(acked)
    in_flight = tour.c.ids[nxt] if killed and nxt < start + count else None
    return acked, in_flight, killed


def crash_child(corpus: Corpus, work: Path, start: int, count: int, dev: bool) -> int:
    """The process that is killed: inserts records and logs each one the database acknowledged."""
    s = Session(corpus, work, dev)
    s.open()
    s.state.loaded = start
    cid = s.state.cid
    with (work / "acks.txt").open("a", encoding="utf-8") as acks:
        for i in range(start, min(start + count, len(corpus.ids))):
            req = prepare_insert(
                cid, corpus.ids[i], corpus.vectors[i].tolist(), s.user(corpus.accounts[i])
            )
            s.live.insert(cid, req, passage=corpus.texts[i].encode("utf-8"))
            acks.write(corpus.ids[i] + "\n")
            acks.flush()
            os.fsync(acks.fileno())
    s.close()
    return 0
