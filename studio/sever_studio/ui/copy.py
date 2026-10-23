"""Every word Studio shows, in one place: a short form on screen, a long form behind ⓘ.

Keep short forms to one line. The long form may explain and must name its section.
"""

#: key -> (short, long)
TEXT: dict[str, tuple[str, str]] = {
    "tagline": (
        "Delete a vector, and prove it.",
        "SEVER-DB keeps each group's exact integer sum, so a deletion subtracts exactly; every "
        "deletion yields a signed receipt anyone can check offline; and the keys that could open "
        "deleted data are destroyed.",
    ),
    "claim.idea": (
        "Exact deletion",
        "Deleting a vector returns its group, bit for bit, to the state it would have had if the "
        "vector had never arrived (Part 1, §5).",
    ),
    "claim.database": (
        "Crash-safe",
        "Exactness survives a crash at any point; no acknowledged operation is lost; a deletion "
        "across groups is all or nothing (Part 2, §12).",
    ),
    "claim.receipt": (
        "Checkable receipts",
        "Every deletion yields a certificate anyone can verify offline, with no database access "
        "(Part 3, §11).",
    ),
    "claim.erasure": (
        "Really gone",
        "After a deletion is acknowledged, nothing deleted can be recovered from raw storage, "
        "even with the key file: the keys that could open it are overwritten (Part 4, §13).",
    ),
    "check.data": (
        "Data pinned",
        "Every data file is pinned by SHA-256 (P0). This re-reads every byte against the committed "
        "manifest.",
    ),
    "check.startup": (
        "Machine checked",
        "The database refuses to start where secrets could leak: unencrypted swap, hibernation, "
        "memory that cannot be locked, a file system that does not overwrite in place "
        "(§12.8–12.9). "
        "On a laptop it opens with the development override, and says so.",
    ),
    "check.encoder": (
        "One encoder",
        "The partition, the stored vectors, the questions and your own text all come from the same "
        "model at the same pinned revision; otherwise search would compare different spaces "
        "(§3.3).",
    ),
    "check.groups": (
        "Groups counted",
        "The database's own counts (records in groups, the holding area, frozen and spawned "
        "groups) "
        "checked against the application's index (§5, §7.6).",
    ),
    "map.about": (
        "Each dot is a passage, where its meaning puts it; its colour, the kind of group.",
        "The 384 numbers of each passage are flattened to two (t-SNE) for the picture: near dots "
        "mean similar passages, but distances on the map only approximate the real ones. A frozen"
        " group's centre μ was fitted once, offline, by k-means on SciQ, a set of science "
        "questions (§6); Wikipedia passages are mostly far from those centres, so most of them "
        "fail the drift test (d_M > τ) and go to a spawned group or the bucket (§7.3). A new "
        "record goes to its nearest frozen centre if it passes the drift test; otherwise to the "
        "nearest spawned group with room (2·k·n < 3·N), or else the bucket. A spawned group is "
        "the 200 records that waited together, with no clustering (§7.4): click its ✕ and its "
        "members light up all over the map. Hover a ✕ for the group's count n and the commitment "
        "C_S the engine published; click a dot for its text and why it went where it did.",
    ),
    "map.caption": (
        "A 2-D picture of 384-D distances: groups are not drawn, their members are lit on click.",
        "",
    ),
    "bucket": (
        "Waiting",
        "The holding area: records that fit no group yet. They are stored and can be deleted at "
        "once, but no search reaches them. At exactly 200 they all leave together as one new "
        "group, "
        "whose name is a hash of its members (§7.4–7.5).",
    ),
    "add": (
        "Add yourself",
        "Your text is encoded by the pinned model, signed with your account's key, and stored "
        "encrypted. It lands where the routing rule sends it (§7.3).",
    ),
    "hover.source": (
        "Text from the dataset; stored encrypted.",
        "The database never hands text back (§13.2): what you read here comes from the dataset, or "
        "from what you typed.",
    ),
    "group.frozen": (
        "Frozen group: its centre was fitted once by k-means and never moves (§6).",
        "",
    ),
    "group.spawned": (
        "Spawned group: 200 records that waited together in the bucket, flushed as one, with no "
        "clustering (§7.4). Its centre is their mean when they flushed, then fixed (§7.5).",
        "",
    ),
    "group.note": (
        "Inside the engine, insert: S + x̃, n + 1, C_S + C_t; delete: S − x̃, n − 1, "
        "C_S − C_t (§5.3). S stays encrypted (§13.2); C_S is its public commitment, so a receipt "
        "can prove the "
        "change without showing S. μ never moves: routing and search measure against it (§7.1, "
        "§8.1).",
        "",
    ),
    "hover.source.mine": (
        "Text you typed; stored encrypted.",
        "The database never hands text back (§13.2): what you read here is what Studio kept of "
        "what you typed.",
    ),
    "route.frozen": ("Joined a frozen group", "Close to a frozen group's centroid (§7.1–7.3)."),
    "route.spawn": (
        "Joined a spawned group",
        "Far from every frozen group, so it went to the nearest spawned group with room (§7.3).",
    ),
    "route.holding": (
        "Waiting in the bucket",
        "Far from every frozen group and no spawned group had room: it waits, stored but not "
        "searchable, until the bucket flushes (§7.3–7.4).",
    ),
    "route.flush": (
        "Filled the bucket: new group",
        "It was the 200th: all the waiting records became one new group (§7.4).",
    ),
    "receipt.about": (
        "Checked offline, with no database.",
        "The person keeps two files: the certificate and the public trust anchors. sever-verify, a "
        "separate program sharing no code with the database, checks it in a folder holding only "
        "those (§11.3).",
    ),
    "receipt.limits": (
        "What it can't prove",
        "That the operator kept no copy (no cryptography can prove that, overview L-2); that the "
        "person asked for the deletion (the application decides who may delete, L-27); that the "
        "log "
        "is consistent (the auditor checks that, §11.3).",
    ),
    "log.about": (
        "Every change, in a signed public log.",
        "Each insert and deletion is a leaf of an append-only Merkle tree (RFC 9162), signed by "
        "the operator and cosigned by independent witnesses, so no one is shown a different "
        "history (§10).",
    ),
    "disk.about": (
        "What a thief with the disk would find.",
        "A raw byte search of every file for 40 live records: each ID, two windows of its text, "
        "its float vector, and the integers x̃ = round(x · 2²⁴) the database actually stores "
        "(§4.2), in either byte order. First over an ordinary store of the same records, to show "
        "the search can see each form. Only public values are stored in the clear (§13.2).",
    ),
    "disk.keys": (
        "Why a deleted record cannot be read back: the keys that opened it are gone.",
        "",
    ),
    "crash.about": (
        "Pull the plug mid-write.",
        "A second process inserts records and is killed with SIGKILL half-way, as a power cut "
        "would "
        "stop it. Every insert it was told was stored must be there after recovery (§12, §15.1).",
    ),
    "rules.about": (
        "Bad input is refused, never repaired.",
        "Inputs are validated, never fixed (§4). Errors are typed and never contain an ID, a "
        "vector, a key or text (§17), so they can be logged as they are.",
    ),
    "retry.about": (
        "A retried insert is stored once.",
        "An insert whose answer was lost is sent again with the same request; the database "
        "recognises it (§15.1).",
    ),
    "proof.about": (
        "Each part proves its claim from inside.",
        "Some claims cannot be seen through the SDK, by design. Each part ships a program that "
        "shows its claim from inside; Studio runs it and reads its report.",
    ),
    "proof.idea": (
        "Exact deletion",
        "A cohort is deleted; each touched group equals the state rebuilt from its survivors "
        "alone, "
        "bit for bit (§5). A float running mean and a soft-delete index, given the same deletion, "
        "do not (sever-demo idea).",
    ),
    "proof.durable": (
        "All or nothing",
        "A multi-group deletion crashed just before and just after its commit point, on a "
        "simulated "
        "disk and with a real SIGKILL: after recovery, all deleted or none (§12; sever-demo-p2).",
    ),
    "proof.receipt": (
        "Receipts chain",
        "A person's certificates chain, each starting where the previous ended, and the auditor "
        "finds nothing wrong (§11.3; sever_demo_p3.receipt).",
    ),
    "proof.erase": (
        "Nothing to recover",
        "A forensic scanner with the whole disk and every key it can carve recovers a live record "
        "but nothing deleted. Built with key rotation skipped (SB-24), it finds the deleted data "
        "(§13; scripts/demo-p4.sh). The program counts what it decrypts; it does not yet print the "
        "rebuilt vector (Build 3-4 §2.11 step 4).",
    ),
    "sabotage.about": (
        "Plant a bug; a test must go red.",
        "Each item is the real code with exactly one deliberate bug, switched on by a build flag. "
        "A test that never fails proves nothing (Build §2.6). Compiling takes a few minutes.",
    ),
    "evidence.about": (
        "Read from the project's generated files.",
        "Traceability, proofs that each test can fail, where each expected value comes from, every "
        "gate run with its commit, and the clean-room fairness runs as they ended, failures "
        "included.",
    ),
    "live.tree": (
        "Your receipt climbs the public log.",
        "The receipt carries your record's insert leaf, its place in the log, and the hashes "
        "beside "
        "it on the way up (RFC 9162, §11.2). Studio hashes them itself, with its own code: the top "
        "must equal the root that the operator signed and 4 or more independent witnesses cosigned "
        "(§10.3–10.4). So your insert is provably in the same log everyone else sees.",
    ),
    "live.attacks": (
        "Try to cheat with a receipt.",
        "Each attempt forges or bends a real receipt, or the trust it is checked against, in one "
        "way; sever-verify, a program sharing no code with the database, judges it (§11.3).",
    ),
    "live.attacks.note": (
        "",
        "Every byte of a receipt is signed by the operator, so an outsider's edit stops at step 2. "
        'Steps 3, 5 and 6 guard against the operator itself, who holds that key: "The operator '
        "cheats\" runs Part 3's own forgeries made with it (P3-T2). A valid receipt is not proof "
        "it is yours: check the key inside against your own.",
    ),
    "live.kill": (
        "Kill a deletion mid-way.",
        "A person with many records is deleted in one transaction by a second process, which is "
        "killed with SIGKILL at a random moment. After recovery the database holds all of their "
        "records or none, never some (§12.5). Most kills land before the commit point; Part 2's "
        "own "
        "proof shows a crash just after it (Proof tab).",
    ),
    "live.kill.timeline": (
        "Where each kill landed in the deletion's time: blue, none deleted (before its commit "
        "point); green, all deleted (after it). A half deletion would be red.",
        "",
    ),
    "live.race": (
        "Floats drift; integers don’t.",
        "200 real vectors. One is removed and put back, again and again, so the members never "
        "change. A float32 running mean, as most indexes keep it, slowly changes anyway. SEVER's "
        "sum of Q24 integers (§4.2, §5) returns to exactly the same bits every time. This is a "
        "model "
        "of the arithmetic in Studio; the engine's own proof is Part 1's (Proof tab).",
    ),
    "live.kmeans": (
        "How the frozen groups were made.",
        "k-means, as the partition builder (C-15) runs it: start from k centres chosen by "
        "k-means++, then repeat two steps until nothing changes. Assignment: each row joins its "
        "nearest centre, by Σ(x̂ − μ)². Update: each centre moves to the mean of its rows. The real "
        "partition used k = 128, 10 starts and up to 300 steps on all 13,679 SciQ rows (§6.2).",
    ),
    "live.kmeans.offline": (
        "",
        "This is the offline build step (§6.2), not the database: the engine never runs k-means. "
        "Here it runs small enough to watch, on the reference rows the partition was fitted on "
        "(quantised as §6.2 step 1 says). The picture is one fixed 2-D projection; every distance "
        "is measured in all the dimensions.",
    ),
    "live.race.model": (
        "A model, computed by Studio in numpy, of the arithmetic of §4.2 and §5: not the engine. "
        "The button beside it runs the engine's own proof of the same claim.",
        "",
    ),
    "welcome": (
        "Three things to try",
        "Hover a dot to read it. Add yourself with the + button. Click your star and delete it.",
    ),
}


def short(key: str) -> str:
    return TEXT[key][0]


def long(key: str) -> str:
    return TEXT[key][1]


#: The checklist: each row's short title (≤ 6 words), grouped by the claim it supports.
GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Exact deletion",
        [
            ("data", "Data pinned"),
            ("startup", "Machine checked"),
            ("encoder", "One encoder"),
            ("clusters", "Groups counted"),
            ("hover", "Read a record"),
            ("search", "Search finds answers"),
            ("insert", "Signed insert"),
            ("freetext", "Your own text"),
            ("routing", "Routed to a group"),
            ("unsearchable", "Waiting is unsearchable"),
            ("flush", "Bucket flushes"),
            ("delete", "Delete: dot gone"),
            ("absent", "Delete again: absent"),
            ("forget", "Forget an account"),
            ("exact", "Survivors-only state"),
            ("ghost", "Floats leave a ghost"),
            ("race", "Floats drift, integers don’t"),
        ],
    ),
    (
        "Crash-safe",
        [
            ("refusals", "Bad input refused"),
            ("retry", "Retry stored once"),
            ("restart", "Restart loses nothing"),
            ("crash", "Kill mid-write"),
            ("crashdelete", "Kill mid-delete"),
            ("durable", "All or nothing"),
        ],
    ),
    (
        "Receipts",
        [
            ("verify", "Receipt verifies"),
            ("tamper", "Tampered: rejected"),
            ("limits", "Limits stated"),
            ("log", "Signed log"),
            ("audit", "Audit: clean"),
            ("chain", "Receipts chain"),
            ("climb", "Receipt climbs the log"),
            ("attacks", "Forgeries caught"),
        ],
    ),
    (
        "Really gone",
        [
            ("disk", "Encrypted on disk"),
            ("shred", "Scan finds nothing"),
            ("leak", "Skip rotation: leaks"),
            ("phasec", "Crash, then erased"),
        ],
    ),
    ("Evidence", [("sabotage", "Planted bug caught"), ("evidence", "Generated evidence")]),
]
CHECK_SHORT = {key: title for _, rows in GROUPS for key, title in rows}
