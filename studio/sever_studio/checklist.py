"""The reviewer checklist: every feature of the project, the section that defines it, the screen
that shows it, and whether it has been shown passing in this session.

A row is ticked only by its live check (``actions.Studio``), never by hand. The session report
(``report-<utc>.json``) holds the verdicts and numbers only: no key, ``r_t`` or passage text.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Row:
    n: int
    key: str
    title: str
    spec: str
    screen: str


ROWS = [
    Row(1, "data", "The data is pinned and hashed", "P0, overview §10", "Start"),
    Row(
        2,
        "startup",
        "The machine is checked before opening; overrides reported",
        "§12.8–12.9",
        "Start",
    ),
    Row(3, "encoder", "The partition and the vectors name the same encoder", "§3.3, §6.3", "Start"),
    Row(4, "clusters", "Records live in frozen and spawned groups", "§6, §7", "Map"),
    Row(5, "insert", "A durable, signed insert", "§9.3–9.4, §15.1", "Your details"),
    Row(6, "freetext", "Your own text, encoded by the pinned model", "§3.3", "Your details"),
    Row(7, "routing", "Routing: frozen group, spawned group or holding area", "§7.3", "Map"),
    Row(
        8,
        "flush",
        "The holding area flushes at the spawn size; the new group's ID",
        "§7.4–7.5",
        "Bucket",
    ),
    Row(
        9,
        "unsearchable",
        "Records in the holding area are stored but not searched",
        "§7.4, §8",
        "Search",
    ),
    Row(10, "search", "Search with real questions; judged answers found", "§8", "Search"),
    Row(11, "hover", "Each point: its account, group, passage and encoding", "§3, §4", "Map"),
    Row(12, "delete", "Delete: the point goes, the counts stay exact", "§5, §15.3", "Map"),
    Row(13, "absent", 'Deleting again changes nothing: "absent"', "§5.4", "Map"),
    Row(14, "retry", "A retried insert is stored once", "§15.1", "Your details"),
    Row(
        15,
        "refusals",
        "Invalid inputs are refused with typed errors that hold no secret",
        "§4, §17",
        "Refusals",
    ),
    Row(16, "forget", "Forget a person: all their records, all or nothing", "§12.5", "Map"),
    Row(
        17,
        "verify",
        "Each certificate verifies offline, with no database access",
        "§11.3",
        "Receipt",
    ),
    Row(18, "tamper", "One flipped byte: rejected, and the failing step named", "§11.3", "Receipt"),
    Row(19, "limits", "What a certificate does not prove", "overview L-2, L-27", "Receipt"),
    Row(20, "log", "The public log: signed checkpoint and witness cosignatures", "§10", "Log"),
    Row(
        21, "audit", "An auditor checks the whole log and every certificate", "§11.3, §15.4", "Log"
    ),
    Row(22, "disk", "Encrypted at rest: no ID, text or vector on the disk", "§13.2", "Disk"),
    Row(23, "restart", "A restart keeps every record; deleted stays deleted", "§12", "Crash"),
    Row(
        24,
        "crash",
        "A writer killed mid-stream: every acknowledged insert survives",
        "§12, §15.1",
        "Crash",
    ),
    Row(25, "exact", "Deletion returns each group to its survivors-only state", "§5", "Proofs"),
    Row(26, "ghost", "Float means and soft deletes are not exact", "P1-T14", "Proofs"),
    Row(27, "durable", "A crash before or after the commit point: all or nothing", "§12", "Proofs"),
    Row(28, "chain", "A person's certificates chain; the audit finds nothing", "§11.3", "Proofs"),
    Row(
        29, "shred", "A scanner with the whole disk and keys finds nothing deleted", "§13", "Proofs"
    ),
    Row(
        30,
        "leak",
        "Skip key rotation (SB-24) and the scan finds the deleted data",
        "§13.3, SB-24",
        "Proofs",
    ),
    Row(31, "phasec", "A crash between commit and key erase: recovery erases", "§13.4", "Proofs"),
    Row(32, "sabotage", "A planted bug turns a test red", "Build §2.6", "Sabotage"),
    Row(
        33,
        "evidence",
        "Traceability, proofs, oracles, gate runs, fairness runs",
        "Build §2.2, §2.5",
        "Evidence",
    ),
    Row(34, "climb", "A receipt climbs the log tree to the signed root", "§10, §11.2", "Live"),
    Row(35, "attacks", "Every forgery of a receipt is caught", "§11.3", "Live"),
    Row(36, "crashdelete", "A deletion killed part-way: all or nothing", "§12.5", "Live"),
    Row(37, "race", "Float means drift; integer sums stay identical", "§4.2, §5", "Live"),
]
BY_KEY = {r.key: r for r in ROWS}


@dataclass
class Verdict:
    ok: bool
    detail: str
    utc: str


@dataclass
class Checklist:
    verdicts: dict[str, Verdict] = field(default_factory=dict)

    def mark(self, key: str, ok: bool, detail: str = "") -> None:
        if key not in BY_KEY:
            raise KeyError(key)
        self.verdicts[key] = Verdict(ok, detail, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def passed(self) -> int:
        return sum(1 for v in self.verdicts.values() if v.ok)

    def save(self, work: Path, numbers: dict[str, object]) -> Path:
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        path = work / f"report-{stamp}.json"
        rows = []
        for r in ROWS:
            v = self.verdicts.get(r.key)
            rows.append(
                {
                    "n": r.n,
                    "feature": r.title,
                    "spec": r.spec,
                    "shown": v is not None,
                    "ok": v.ok if v else None,
                    "detail": v.detail if v else "",
                    "utc": v.utc if v else "",
                }
            )
        doc = {"passed": self.passed(), "of": len(ROWS), "rows": rows, "numbers": numbers}
        path.write_text(json.dumps(doc, indent=1), "utf-8")
        return path
