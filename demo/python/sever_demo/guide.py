"""The words of the demo: help, notes, hints, the glossary and the guided tour (DEMO_PLAN §5.9).

Plain data only, kept apart from repl.py and demo.py so the wording can be read and corrected in one
place. The § references were checked against docs/SEVER-DB_SPECIFICATION.md on 3 Oct 2026.
"""

from dataclasses import dataclass

TITLE = "SEVER-DB · Part 1 demo shell, with a Part 3 preview"
CLAIM = (
    "Deleting a record returns its group, bit for bit, to the state it would have had if the "
    "record had never arrived, and anyone can check the receipt without the database."
)

# help: commands in the order the demo uses them. (usage, what it does)
HELP_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Start",
        [
            ("verify_data", "re-hash every dataset file against the committed manifest"),
            ("load [N]", "check, quantise, route and insert N records (default: all 1,000,000)"),
            ("status", "what is loaded, deleted and certified so far in this session"),
        ],
    ),
    (
        "Look",
        [
            ("stats", "how many records the 128 groups hold"),
            ("group <g>", "one group's state: n, S, C_S and the blob hash"),
            ("ids <g>", "a few live record IDs in group g, to pick one to delete"),
            ("find <record_id>", "which group a record is in, or whether it is gone"),
        ],
    ),
    (
        "Delete",
        [
            ("delete <record_id>", "delete one record: subtract it, write a signed certificate"),
            ("delete_user <title | N>", "delete a whole cohort, or N random cohorts"),
            ("insert <record_id>", "put a deleted record back: its group returns to its old hash"),
        ],
    ),
    (
        "Prove",
        [
            ("verify <g>", "compare group g with a group rebuilt from its survivors only"),
            ("cert [last | all | k]", "check certificates with the independent verifier"),
            ("tamper [last | k]", "forge a certificate (one bit changed) and watch it fail"),
            ("ghost [g]", "SEVER vs a float32 running mean vs soft delete, on one group"),
            ("stress <n>", "n seeded random operations, each followed by a check"),
        ],
    ),
    (
        "Break it on purpose",
        [("sabotage [SB-k | off]", "list the planted bugs, switch one on, or off (rolls back)")],
    ),
    (
        "Record",
        [
            ("ledger [n | session]", "the last n run-ledger lines, or this session's, in words"),
            ("save <name>", "save the screen so far as results/screens/<name>.svg"),
        ],
    ),
    (
        "Guide",
        [
            ("tour [k]", "the demo story in 13 steps; `tour k` jumps to step k"),
            ("next", "run the next tour step"),
            ("explain [word]", "a term in plain words: S, n, blob, C_S, certificate, ..."),
            ("notes on | off", "show or hide the explanation under each result"),
            ("help [command]", "this list, or one command in detail"),
            ("quit", "leave the shell (a planted bug is switched off)"),
        ],
    ),
]

# The note printed under a command's output (when notes are on). {braces} are filled in by repl.py.
NOTES: dict[str, str] = {
    "verify_data": (
        "Every data file was hashed with SHA-256 and compared with datasets/MANIFEST.sha256, "
        "committed when the data was prepared. 0 mismatches: the data is byte for byte what was "
        "pinned."
    ),
    "load": (
        "Each vector was checked to have length 1 (§4.1: checked, never fixed), turned into "
        "whole numbers by multiplying by 2^24 (§4.2), and sent to the nearest of 128 fixed groups "
        "(§7.1). A group keeps exact integer totals: the sum S and the count n."
    ),
    "load_commitments": (
        "Each record also got a secret random number r_t, and each group a sealed fingerprint C_S "
        "of its sum (§9.3, §9.4). The secrets stay in this process's memory: never shown, never "
        "written."
    ),
    "stats": (
        "Real text is not spread evenly, so group sizes differ a lot. Size does not matter for "
        "exactness: every group is updated by the same integer arithmetic."
    ),
    "group": (
        "These are group {g}'s values now, before anything changes. S is the exact integer sum of "
        "its vectors, n the count, C_S a sealed fingerprint of S, and the blob hash covers every "
        "field and every member, byte for byte (§5.5)."
    ),
    "ids": (
        "Record IDs come from the dataset, never from a counter (§3.2). Pick one to delete: the "
        "next screen shows exactly what changes."
    ),
    "delete": (
        "The record's integers were subtracted from S, n went down by one, and its ID left the "
        "member list. No 'deleted' flag is kept anywhere (§5.3, §5.4)."
    ),
    "delete_commit": (
        "C_S moved by exactly this record's own fingerprint C_t, so anyone can check "
        "C_S_post + C_t = C_S_pre with public numbers only (§9.3). The certificate carries that "
        "check, a proof and the operator's signature."
    ),
    "delete_sabotaged": (
        "A planted bug is on, so this delete may have gone wrong in a way the lines above do not "
        "show. The next check should catch it."
    ),
    "delete_absent": (
        "Deleting twice must not subtract twice: the record is no longer a member, so nothing "
        "changes and no certificate is written (§5.4). That is what makes a retry after a timeout "
        "safe."
    ),
    "insert": (
        "The record's integers were added back to its nearest group (§5.3, §7.1). When the new "
        "hash equals an earlier one, the group is bit for bit what it was then: insert and delete "
        "undo each other exactly."
    ),
    "delete_user": (
        "A 'user' here is a cohort: all passages from one Wikipedia article (§3.5). Each touched "
        "group was compared with a rebuild from its survivors; every other group's blob hash was "
        "compared with its hash from before the deletion."
    ),
    "verify_exact": (
        "A brand-new group was built from only the surviving records, in a shuffled order. The "
        "live group equals it on every field, so it is exactly as if the deleted records had never "
        "arrived (§5.3, §5.5)."
    ),
    "verify_mismatch": (
        "The live group is not what its survivors alone would give. In real use that is a bug "
        "that must never ship; here it is the planted bug being caught."
    ),
    "cert": (
        "The verifier is a separate program with no database: it reads only the certificate and "
        "the public keys (§11.3). 1: the file is well-formed. 2: the operator signed exactly these "
        "bytes. 6a: the public fingerprints add up. 6b: the operator proved it knows the group's "
        "new state (§9.5). 6c: the 'group emptied' flag is honest. Steps 3-5 need the public log, "
        "which is not built yet, so they say NOT CHECKED instead of pretending to pass."
    ),
    "cert_rejected": (
        "A failed step means the certificate was changed after it was signed, or the deletion it "
        "describes did not happen as stated. An auditor would not accept it."
    ),
    "tamper": (
        "Step 2 fails because the signature covers every byte, so one changed bit breaks it. Step "
        "6b fails because the proof is tied to this deletion's number (lsn), so it cannot be "
        "reused for another deletion (§9.5)."
    ),
    "ghost": (
        "SEVER keeps an integer sum, so subtracting is exact: difference 0. A float32 running mean "
        "rounds on every update, so after a delete it is close but not equal, and the error stays. "
        "Soft delete only hides records: they are still stored."
    ),
    "stress": (
        "After every operation a cheap check (S equals a fresh sum of the members' vectors, n "
        "equals the number of members); every 50 operations and at the end, the full check on all "
        "fields."
    ),
    "sabotage_on": (
        "A planted bug is on. Run the same checks as before: they should turn red. A check that "
        "has never failed proves nothing, so this shows the checks can fail."
    ),
    "sabotage_off": (
        "The bug is off, and every group it touched was put back to its state before the bug ran."
    ),
    "ledger": (
        "Every check and every change in this shell is appended by code, with the git commit and "
        "the dataset hash. Lines are never edited, and no line holds a record ID (§17)."
    ),
}

# The hint after a command: (what to type next, why). {g} is the group in focus.
NEXT_HINT: dict[str, tuple[str, str]] = {
    "verify_data": ("load", "load the one million vectors"),
    "load": ("group 3", "look at one group before deleting anything"),
    "stats": ("group 3", "look at one group"),
    "group": ("ids {g}", "see a few records in it"),
    "ids": ("delete <one of those IDs>", "delete one record"),
    "find": ("delete <record_id>", "delete it"),
    "find_gone": ("insert <record_id>", "put it back and watch the group's old hash return"),
    "delete": ("verify {g}", "prove the group is exact"),
    "delete_sabotaged": ("verify {g}", "the planted bug should turn a check red"),
    "delete_absent": ("ghost", "see the trace other methods leave behind"),
    "insert": ("verify {g}", "the group is exact with the record back in"),
    "delete_user": ("cert all", "check every receipt"),
    "verify": ("cert last", "check the receipt with the independent verifier"),
    "verify_plain": ("delete_user 5", "delete five whole cohorts at once"),
    "verify_mismatch": ("sabotage off", "remove the bug and roll its damage back"),
    "cert": ("tamper last", "forge the receipt and watch it fail"),
    "tamper": ("delete_user 5", "delete five whole cohorts at once"),
    "ghost": ("sabotage SB-4", "plant a bug and watch the checks catch it"),
    "stress": ("ledger", "see everything this session did"),
    "sabotage_on": ("delete <record_id>, then verify {g}", "watch the bug get caught"),
    "sabotage_off": ("verify {g}", "exact again"),
    "ledger": ("quit", "or keep exploring: help"),
    "status": ("help", "every command"),
    "tour": ("help", "the tour is finished; every command"),
}

# verify: the plain meaning of each of the §5.5 fields.
FIELD_INFO: dict[str, str] = {
    "S": "exact integer sum of the vectors",
    "n": "how many records",
    "members": "sorted list of record IDs",
    "C_S": "sealed fingerprint of S",
    "blob": "all of it as bytes (incl. hidden r_agg)",
}

# sabotage: (what the bug does, what it breaks, how to see it in this shell)
SABOTAGE_BUGS: dict[str, tuple[str, str, str]] = {
    "SB-1": (
        "flip the lowest bit of S[0] when a group gets its first member",
        "S and the blob",
        "not here: it only fires on a group's first insert, and after `load` no group is "
        "empty; the tests cover it",
    ),
    "SB-2": (
        "skip n -= 1 on delete",
        "n and the blob",
        "delete a record, then verify its group",
    ),
    "SB-3": (
        "skip the group's membership check on delete",
        "a retried delete would subtract twice",
        "not here: the index's locator stops a retry before it reaches the group (a second "
        "line of defence); the tests cover the group on its own",
    ),
    "SB-4": (
        "skip r_agg -= r_t on delete (C_S still moves by C_t)",
        "the blob (r_agg is inside it) and the proof",
        "delete, verify (blob ✗), cert last (6b ✗); the public check 6a still passes",
    ),
}

# explain: term -> (plain words, spec section). Looked up without regard to case.
GLOSSARY: dict[str, tuple[str, str]] = {
    "vector": (
        "A list of 384 numbers that stands for one passage of text; passages with similar meaning "
        "get similar vectors. Every vector must have length 1.",
        "§4.1",
    ),
    "quantise": (
        "Multiply each number by 2^24 and round to the nearest whole number (ties go to even). "
        "Whole numbers add and subtract with no rounding error, which is what makes exact deletion "
        "possible.",
        "§4.2",
    ),
    "group": (
        "A bucket of similar vectors. There are 128, fixed before any data arrives (fitted on a "
        "separate dataset, SciQ). Each vector goes to the nearest group and stays there. Groups "
        "are never removed.",
        "§5.1, §6, §7.1",
    ),
    "routing": (
        "Choosing a vector's group: the nearest of the fixed group centres. It depends only on the "
        "vector, with no clock and no counter, so the same vector always lands in the same group.",
        "§7, §7.1",
    ),
    "S": (
        "The group's sum: all its members' whole-number vectors added up, as 64-bit integers. "
        "Deleting a record subtracts its vector exactly.",
        "§4.4, §5.3",
    ),
    "n": ("How many records the group holds. Insert adds 1, delete takes 1 away.", "§5.3"),
    "members": (
        "The list of record IDs in the group, sorted by their bytes. A deleted ID is removed from "
        "the list, not marked: a 'deleted' marker would itself be a leftover trace.",
        "§5.4",
    ),
    "blob": (
        "The whole group written out as bytes: n, S, C_S, the hidden r_agg, then every member's ID "
        "and vector in sorted order. Its SHA-256 hash is a fingerprint of everything, so two "
        "groups with the same blob hash are identical, bit for bit.",
        "§5.5",
    ),
    "survivors check": (
        "The test of the claim: build a brand-new group from only the records still present, in a "
        "shuffled order, and compare it with the live group on all five fields: S, n, members, "
        "C_S and the blob. The `verify` command runs it.",
        "§5.5",
    ),
    "AlreadyAbsent": (
        "What deleting a record that is not there returns. Nothing is subtracted and nothing "
        "changes, so a retry after a timeout cannot subtract a vector twice.",
        "§5.4",
    ),
    "r_t": (
        "A secret random number given to each record (its 'blinding value'). It hides the vector "
        "inside the record's fingerprint C_t. Never shown, never logged.",
        "§9.4",
    ),
    "r_agg": (
        "The group's total of its members' r_t values, secret like r_t. It changes with every "
        "insert and delete, and it sits inside the blob, so the blob check sees it even though no "
        "screen shows it.",
        "§5.2, §5.3",
    ),
    "C_t": (
        "One record's sealed fingerprint (a Pedersen commitment). It fixes the vector without "
        "revealing it, because r_t hides it.",
        "§9.3",
    ),
    "C_S": (
        "The group's sealed fingerprint of its sum S. Fingerprints add: deleting a record moves "
        "C_S by exactly C_t, so anyone can check C_S_post + C_t = C_S_pre with public numbers "
        "only.",
        "§9.3",
    ),
    "proof": (
        "In each certificate the operator proves it knows the numbers inside the new C_S (S and "
        "r_agg) without revealing them. The proof is tied to this one deletion, so it cannot be "
        "copied into another certificate. Verifier step 6b.",
        "§9.5",
    ),
    "certificate": (
        "The deletion receipt: C_t, C_S before and after, the proof, a scrambled record ID, the "
        "deletion number (lsn) and the operator's signature over all of it. It shows the group's "
        "accounting moved by exactly that record. No certificate can show that no copy was kept.",
        "§11.1, §11.3",
    ),
    "verifier": (
        "A separate program that checks a certificate using only the file and the public keys, "
        "with no database. It shares no code with the database, and runs as its own process here.",
        "§11.3",
    ),
    "lsn": (
        "The deletion's sequence number (in the full system, its position in the public log; in "
        "this preview, the certificate's number). It is signed and bound into the proof, so a "
        "receipt cannot be reused for a different deletion.",
        "§11.1 tag 10, §9.5",
    ),
    "scrambled id": (
        "The record ID passed through a keyed hash (HMAC-SHA-512), so a reader of the public "
        "receipts cannot list deleted IDs, while the operator can still prove which record a "
        "certificate is about.",
        "§9.7",
    ),
    "cohort": (
        "All records deleted together by delete_user, for example everything one person "
        "contributed. In this demo: all passages from one Wikipedia article.",
        "§3.5",
    ),
    "ghost": (
        "What other methods leave behind after a deletion. A float running mean keeps rounding "
        "error from the deleted record; soft delete keeps the record itself. SEVER leaves neither "
        "in the group's accounting.",
        "Overview §1.2",
    ),
    "soft delete": (
        "Marking a record 'deleted' and hiding it, but keeping it stored. Common in databases; the "
        "deleted data is still there.",
        "§5.4",
    ),
    "sabotage": (
        "A planted bug (SB-1 to SB-4), switched on by hand to show that the checks can fail. A "
        "check that has never failed proves nothing.",
        "Build §2.6",
    ),
    "ledger": (
        "docs/RUN_LEDGER.jsonl: one line per check or change, appended by code with the time, git "
        "commit, dataset hash and result. Never edited; never holds a record ID.",
        "Overview §13.3, §17",
    ),
    "git dirty": (
        "The code that ran had changes not yet committed, so the commit hash alone does not pin "
        "it. Shown as * after the commit in the ledger.",
        "DEMO_PLAN §5.8",
    ),
}
ALIASES: dict[str, str] = {
    "q24": "quantise",
    "quantize": "quantise",
    "centroid": "routing",
    "sum": "S",
    "count": "n",
    "member": "members",
    "survivors": "survivors check",
    "verify": "survivors check",
    "exact": "survivors check",
    "idempotent": "AlreadyAbsent",
    "retry": "AlreadyAbsent",
    "blinding": "r_t",
    "commitment": "C_S",
    "posk": "proof",
    "6b": "proof",
    "cert": "certificate",
    "receipt": "certificate",
    "scrambled_id": "scrambled id",
    "user": "cohort",
    "delete_user": "cohort",
    "dirty": "git dirty",
    "sb": "sabotage",
}


@dataclass(frozen=True)
class TourStep:
    """One step of the guided story. {g} is the demo group, {a} and {b} its first two live IDs."""

    title: str
    say: str
    commands: tuple[str, ...]
    look_for: str
    needs_session: bool = True
    needs_commitments: bool = False


# DEMO_RUNBOOK §B rows 2-14, in the same order, so the seeded numbers match the runbook.
TOUR: list[TourStep] = [
    TourStep(
        "Check the data",
        "The data is pinned and hashed. This re-checks every byte against the committed manifest.",
        ("verify_data",),
        "PASS, 0 mismatches.",
        needs_session=False,
    ),
    TourStep(
        "Load one million vectors",
        "One million real passages, turned into whole numbers, sent to 128 fixed groups; each "
        "group gets a sealed fingerprint.",
        ("load",),
        "0 failures, 0 rejected, and the group sizes.",
        needs_session=False,
    ),
    TourStep(
        "Look at one group before",
        "This is group {g} before we delete anything.",
        ("group {g}", "ids {g}"),
        "n, and the first IDs: the first one is deleted next.",
    ),
    TourStep(
        "Delete one record",
        "One record out. Its numbers leave the group's sum, the fingerprint moves by exactly the "
        "record's own fingerprint, and a signed receipt is written.",
        ("delete {a}",),
        "n down by exactly one; 'public check ... holds'.",
    ),
    TourStep(
        "Prove it is exact",
        "The live group is compared with one built only from the survivors, on all five fields.",
        ("verify {g}",),
        "five ✓ and EXACT.",
    ),
    TourStep(
        "Check the receipt, with no database",
        "A separate program, with no database, checks the receipt. It says honestly what it "
        "cannot check yet: the public log.",
        ("cert last",),
        "1, 2, 6a, 6b, 6c ✓; 3-5 NOT CHECKED; ACCEPTED.",
        needs_commitments=True,
    ),
    TourStep(
        "Forge a receipt",
        "Reuse the receipt for another deletion by changing its number: the signature and the "
        "proof both fail.",
        ("tamper last",),
        "✗ on 2 and 6b; REJECTED.",
        needs_commitments=True,
    ),
    TourStep(
        "Delete five people's data",
        "Five whole cohorts, across many groups: every touched group exact, no other group "
        "changed by one byte, every receipt valid.",
        ("delete_user 5", "cert all"),
        "all ✓; 'untouched groups changed: 0'; all accepted, 0 rejected.",
    ),
    TourStep(
        "Retry the first delete",
        "A retry after a timeout must not subtract twice.",
        ("delete {a}",),
        "AlreadyAbsent: nothing changed.",
    ),
    TourStep(
        "The ghost",
        "Floats are close but not identical. Soft delete still has the records. SEVER is exact.",
        ("ghost",),
        "SEVER 0 and 'yes'; float32 not 0; soft delete still stores the records.",
    ),
    TourStep(
        "Plant a bug in the hidden bookkeeping",
        "Bug SB-4 forgets to subtract the secret r_t. The public check cannot see it; the blob and "
        "the proof can.",
        ("sabotage SB-4", "delete {b}", "verify {g}", "cert last"),
        "C_S ✓ but blob ✗; certificate 6a ✓ but 6b ✗, REJECTED.",
        needs_commitments=True,
    ),
    TourStep(
        "Remove the bug",
        "Bug off, state rolled back, exact again.",
        ("sabotage off", "verify {g}"),
        "'1 group(s) rolled back' and EXACT.",
    ),
    TourStep(
        "The record of everything",
        "Every command was logged with the commit and the data hash, and says what it did.",
        ("ledger session",),
        "one line per check or change, PASS/FAIL, in plain words.",
        needs_session=False,
    ),
]

# demo.py: why each step of the full acceptance run exists (printed under the step's name).
RUN_WHY: dict[str, str] = {
    "1": "The data must be exactly the pinned data, or no number below means anything.",
    "2": "Every vector must have length 1; bad ones are reported, never fixed (§4.1).",
    "3": "IDs come from the dataset, never from a counter, so arrival order cannot leak (§3.2).",
    "4": "Fixed groups, whole-number vectors, a seeded arrival order: S and n per group (§5.3).",
    "4b": "Each record gets a secret r_t, each group a sealed fingerprint C_S (§9.3, §9.4).",
    "5": "Delete whole cohorts: everything one 'user' contributed, across many groups (§3.5).",
    "6": "The claim: each touched group equals a rebuild from its survivors; no other group moves.",
    "7": "The same deletions with a float32 mean and with soft delete, for comparison: the ghost.",
    "8": "Random inserts and deletes, each followed by a check: exactness has to last.",
    "9": "Every receipt checked by the separate verifier; forged copies must all be rejected.",
}
