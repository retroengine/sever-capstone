"""Story mode: the whole project told in chapters, in the order a reviewer should see it.

Each chapter names its screen, what to say, what to point at, and the checklist rows it shows.
"Do it" runs the chapter's step; the presenter can also click around freely at any time.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Chapter:
    title: str
    screen: str
    say: str
    look: str
    rows: tuple[str, ...]


CHAPTERS = [
    Chapter(
        "The claim",
        "start",
        "Deleting a vector should leave the database exactly as if it never arrived, and anyone "
        "should be able to check that without access to the database. Averages cannot be undone "
        "exactly; integer sums can.",
        "The four claims at the top, one per part.",
        (),
    ),
    Chapter(
        "The data is pinned",
        "start",
        "Every data file is pinned by SHA-256. This re-reads every byte and checks it against "
        "the committed manifest.",
        "0 mismatches.",
        ("data",),
    ),
    Chapter(
        "The machine is checked first",
        "start",
        "The database refuses to start where secrets could leak: unencrypted swap, memory that "
        "cannot be locked. This laptop is refused; the demo opens with the development override, "
        "and the database itself reports that it did.",
        "The refusal, then the overrides listed.",
        ("startup",),
    ),
    Chapter(
        "One encoder for everything",
        "start",
        "The partition, the stored vectors, the questions and whatever you type all come from "
        "one model at one pinned revision; otherwise search would compare different spaces.",
        "Three names, the same.",
        ("encoder", "clusters"),
    ),
    Chapter(
        "The data as a map",
        "map",
        "Ten thousand real Wikipedia passages, each a dot coloured by its group. Filled dots are "
        "frozen groups, rings are groups spawned from the holding area. Hover any dot: its text, "
        "its account and its 384 numbers.",
        "Hover a few dots; the card names the group.",
        ("clusters", "hover"),
    ),
    Chapter(
        "Your own details",
        "map",
        "Type a name and a sentence. It is encoded by the same model, signed with your account's "
        "key, stored encrypted, and lands where the routing rule sends it: a frozen group, a "
        "spawned group with room, or the holding area.",
        "The white star, and the sentence saying why it went where it went.",
        ("insert", "freetext", "routing"),
    ),
    Chapter(
        "The holding area",
        "map",
        "Out-of-distribution records with nowhere to go wait in the holding area: stored and "
        "deletable, but no search reaches them. At exactly 200 they all leave together as one new "
        "group, whose name is a hash of its members.",
        "Search for a waiting record: not found. Then fill until it flushes: the dots fly out.",
        ("unsearchable", "flush"),
    ),
    Chapter(
        "Search",
        "map",
        "A real test question; the beam goes to the ten nearest records; a tick marks the passage "
        "judged to answer it. Then the same over every question.",
        "Type #12 (or any question) and Search.",
        ("search",),
    ),
    Chapter(
        "Delete one record",
        "map",
        "Click your record and delete it. It is subtracted from its group exactly; its keys are "
        "rotated and the old ones overwritten before the call returns; a certificate comes back. "
        "Deleting again changes nothing: a retry is safe.",
        "The dot vanishes; the count drops by one; then 'absent'.",
        ("delete", "absent"),
    ),
    Chapter(
        "Forget a person",
        "map",
        "A whole account across many groups, in one transaction: all of it or none of it.",
        "Click any dot, Forget the account: all its dots go together.",
        ("forget",),
    ),
    Chapter(
        "The receipt",
        "receipt",
        "The person keeps the certificate. A separate program, sharing no code with the "
        "database, checks it with only the public anchors. Flip one byte and it is rejected, and "
        "it says which check failed. And what it cannot prove: that no copy was kept.",
        "ACCEPT, then REJECT with the step, then the limits.",
        ("verify", "tamper", "limits"),
    ),
    Chapter(
        "The public log",
        "log",
        "Every insert and deletion is a leaf of a signed, append-only log, cosigned by "
        "independent witnesses. An auditor replays all of it.",
        "Five witnesses; the auditor: 0 findings.",
        ("log", "audit"),
    ),
    Chapter(
        "Encrypted at rest",
        "disk",
        "A raw byte search over the disk, as a thief with a copy would run it: everything found "
        "in an ordinary store, nothing in SEVER-DB's.",
        "40/40 against 0/40.",
        ("disk",),
    ),
    Chapter(
        "Restart, and pull the plug",
        "crash",
        "A clean restart loses nothing. Then a writer is killed in the middle of its inserts: "
        "every insert it was told was stored is there after recovery.",
        "0 missing.",
        ("restart", "crash"),
    ),
    Chapter(
        "Inside the engine",
        "proofs",
        "What the SDK cannot show: each touched group equals its survivors-only rebuild; floats "
        "and soft deletes leave a ghost; a crash at the commit point is all or nothing; and a "
        "scanner with the whole disk and keys finds nothing deleted, unless key rotation is "
        "skipped.",
        "Exact ✓, ghost > 0, all or nothing, 0 findings against the SB-24 leak.",
        ("exact", "ghost", "durable", "chain", "shred", "leak", "phasec"),
    ),
    Chapter(
        "Planted bugs",
        "sabotage",
        "Every guarantee has a test, and every test has been shown able to fail: plant one bug "
        "and watch a test go red.",
        "SB-24 (or any): red.",
        ("sabotage",),
    ),
    Chapter(
        "The evidence",
        "evidence",
        "Everything here is read from files the project's tools generated: traceability, proofs "
        "that each test can fail, oracles, every gate run with its commit, fairness runs "
        "including the failed ones.",
        "Then save the session report: every row of the checklist with its verdict.",
        ("evidence",),
    ),
]
