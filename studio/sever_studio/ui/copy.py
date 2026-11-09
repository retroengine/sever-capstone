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
        "Each dot is a passage, where its meaning puts it; a frozen group's in its own colour, a"
        " spawned group's grey until lit.",
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
    "live.kmeans.ratio": (
        "D to its own centre ÷ D to the nearest other centre (below 1: nearer its own)",
        "",
    ),
    "map.caption3": (
        "A 3-D picture of 384-D distances: drag to turn it. Click a ✕ in 2-D to light a group.",
        "",
    ),
    "map.laying3": (
        "Laying the passages out in 3-D, once (t-SNE with three axes; a few minutes on NQ)…",
        "",
    ),
    "map.caption": (
        "A 2-D picture of 384-D distances. Each frozen group has its own colour; a spawned group"
        " is grey until you point at or click its ✕.",
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
        "Text from the dataset; the database stores it encrypted.",
        "The database keeps every passage encrypted on disk (§13.2) and hands it back only through "
        "passage() (§16.1, the inspect build). The map's text comes from the dataset; the "
        "Assistant reads every passage it shows with passage().",
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
        "Text you typed; the database stores it encrypted.",
        "What you read here is Studio's own copy of what you typed; the database keeps it "
        "encrypted (§13.2) and the Assistant reads it back with passage() (§16.1).",
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
        "the operator and cosigned by five witnesses, so no one is shown a different history "
        "(§10). In v1 the witnesses are simulated: the database itself holds their keys and "
        "cosigns (§10.4); real independent witnesses are future work (overview L-7). The ✓ "
        "beside each witness means it is listed in the checkpoint; the auditor checks the "
        "signatures (§11.3).",
    ),
    "disk.about": (
        "What a thief with the disk would find.",
        "A raw byte search of every file for 40 live records: each ID, two windows of its text, "
        "its float vector, and the integers x̃ = round(x · 2²⁴) the database actually stores "
        "(§4.2), in either byte order. First over an ordinary store of the same records, to show "
        "the search can see each form. Only public values are stored in the clear (§13.2).",
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
    "evidence.about": (
        "Read from the project's generated files.",
        "Traceability, proofs that each test can fail, where each expected value comes from, every "
        "gate run with its commit, and the clean-room fairness runs as they ended, failures "
        "included.",
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
    "live.kmeans": (
        "How the frozen groups were made.",
        "The same algorithm as the partition builder (C-15), one start: k centres chosen by "
        "k-means++, then two steps repeated until nothing changes. Assignment: each row joins its "
        "nearest centre, by Σ(x̂ − μ)². Update: each centre moves to the mean of its rows. The real "
        "partition used k = 128, the best of 10 starts and up to 300 steps on all 13,679 SciQ "
        "rows (§6.2).",
    ),
    "live.kmeans.offline": (
        "",
        "This is the offline build step (§6.2), not the database: the engine never runs k-means. "
        "Here it runs small enough to watch, on the reference rows the partition was fitted on "
        "(quantised as §6.2 step 1 says). The picture is one fixed 2-D projection; every distance "
        "is measured in all the dimensions.",
    ),
    "assistant.about": (
        "Acme Notes",
        "A notes app on SEVER-DB. Store a few notes, ask about them, then ask to be forgotten.",
    ),
    "assistant.you": (
        "",
        "Each note is encoded by the pinned model, signed with your account's key and stored with "
        "its text, encrypted (§3.4, §13.2). It goes where the routing rule sends it (§7.3). "
        "A note far from every group waits in the holding area: stored, not searchable, until "
        "enough gather to become a new group (§7.4). Let other users write fills it.",
    ),
    "assistant.ask": (
        "",
        "Your question is encoded and searched (§8); the engine opens the groups nearest it and "
        "returns the best matches. Each passage is read from the database with passage() (§16.1), "
        "so text that was deleted cannot be shown. "
        "With GROQ_API_KEY set, your question and the retrieved passages are sent to Groq "
        "(openai/gpt-oss-20b), which writes the answer. What Groq receives is outside the "
        "database: SEVER-DB can neither delete it nor prove anything about it. Without a key the "
        "passages are shown as they are (AI off).",
    ),
    "assistant.forget": (
        "",
        "All your notes are deleted in one transaction, all or nothing (§12.5), and you get one "
        "receipt per note (§11). The report then checks what is left, and runs the same steps on "
        "an ordinary vector store (Chroma) holding the same notes.",
    ),
    "assistant.map": (
        "★ your notes · lines: what a question found",
        "",
    ),
    "forget.notes": (
        "",
        "What this shows and what it does not. The files searched are the database's own (and "
        "Chroma's folder), byte by byte, for your notes' IDs, text and vectors. The raw-disk "
        "result, with deleted blocks carved from the whole device, is gate P4-T1 (see Evidence). "
        "The witnesses that cosign the log are simulated in v1 (§10.4, overview L-7). A receipt "
        "cannot prove the operator kept no copy (L-2). What Groq received is outside the "
        "database.",
    ),
    "disk.raw": (
        "",
        "This searches the database's files. Carving deleted blocks from the whole raw device, "
        "with every key the scanner can find, is gate P4-T1 (forensic erasure, §13), run on a "
        "16 GiB image: see Evidence for its result.",
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
        "The company app",
        [
            ("assistant", "Answers from passages"),
            ("gone", "Forget me: nothing left"),
            ("compare", "Beside an ordinary store"),
        ],
    ),
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
        ],
    ),
    (
        "Crash-safe",
        [
            ("refusals", "Bad input refused"),
            ("retry", "Retry stored once"),
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
            ("attacks", "Forgeries caught"),
        ],
    ),
    ("Really gone", [("disk", "Encrypted on disk")]),
    ("Evidence", [("evidence", "Generated evidence")]),
]
CHECK_SHORT = {key: title for _, rows in GROUPS for key, title in rows}
