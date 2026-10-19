# SEVER-DB: the engine demo

**The final database, used the way an application uses it**: open it, store real passages that
belong to accounts, search them with real questions, delete one person's records, hand them a
receipt they can check with no access to the database, restart, pull the plug, audit the public log,
and look at the disk. Everything goes through the public SDK (`sever_db`), the command-line tool
(`sever-db`) and the two independent checkers (`sever-verify`, `sever-audit`). Nothing here reaches
inside the engine.

This is not `../demo/`. That folder is the Python prototype shown at the review on 5 Oct 2026; this
one drives the real Rust engine of Part 4. Nothing outside this folder depends on it (DB-97).

## Contents

| | |
|---|---|
| [Run it](#run-it) | setup, then one command per demo |
| [The tour](#the-tour) | twelve chapters, each with the claim it checks |
| [The shell](#the-shell) | use the database yourself |
| [The command line](#the-command-line) | the same story with `sever-db` |
| [The forensic proof](#the-forensic-proof) | a scanner given the whole disk, keys included |
| [Use it in your own application](#use-it-in-your-own-application) | the API, the rules, the errors |
| [What is in this folder](#what-is-in-this-folder) | files, and the demo's own tests |

## Run it

WSL2 (Ubuntu) or Linux, from the repository root. Needs `uv` and the Rust toolchain (pinned by
`rust-toolchain.toml`).

```bash
demo-engine/demo.sh setup        # once: Python env, the SDK, sever-verify, sever-audit, sever-db
demo-engine/demo.sh tour         # the guided tour on 5,000 real passages (~4 min)
demo-engine/demo.sh shell        # use it yourself; type help
demo-engine/demo.sh cli          # the command-line tool, offline (~10 s)
demo-engine/demo.sh erase        # the forensic proof on simulated disks (two release builds the first time)
demo-engine/demo.sh examples     # the two example programs in examples/
demo-engine/demo.sh test         # the demo's own tests, offline (lint, types, 4 tests)
demo-engine/demo.sh clean        # delete demo-engine/work/ (every demo database, key and receipt)
```

**The data.** `tour` and `shell` use the pinned Natural Questions passages, questions and their
judged answers in `datasets/processed/` (P0; not in git, a few GB; verified by
`datasets/MANIFEST.sha256`, built by `scripts/data-preparation/`, see the top-level README). Without
them, add `--data synthetic`: the golden fixture (`d = 16`, 4 groups, 240 vectors) runs everything
offline. `--rows N` changes how many passages the tour stores.

**Your machine will be refused, and that is a feature.** The database will not start where secrets
could leak (§12.8–12.9): unencrypted swap, hibernation, memory that cannot be locked, a filesystem
that does not overwrite in place (tmpfs, btrfs, ZFS, NFS). WSL and most laptops have plain swap, so
`demo.sh` passes `--dev`: the demo shows the refusal, then opens with the development override,
which the database reports in its startup record. `SEVER_STRICT=1 demo-engine/demo.sh tour` leaves
the override out (for a machine with encrypted swap and `ulimit -l unlimited`). The databases live
in `demo-engine/work/` because `/tmp` is often tmpfs.

## The tour

`demo-engine/demo.sh tour` runs twelve chapters. Each says what it does and why, does it, and checks
its claim; the run ends with a summary and writes `demo-engine/work/tour-nq/report.json` (numbers
and verdicts only: no key, `r_t` or passage text).

| # | Chapter | What it shows | Checked |
|---|---|---|---|
| 1 | Open the database | two directories, `data/` and `keys/`; the startup checks and the override report | opens, reports its overrides |
| 2 | Create a collection | a collection over the partition artefact; the encoder check (§3.3) | 128 frozen groups, empty |
| 3 | Insert passages | 5,000 passages, each owned by an account (its article), each signed by that account's key | every insert acknowledged |
| 4 | Search with real questions | three questions with their top results, the judged answer ticked; answer rank over all questions | answers are found |
| 5 | What is on the disk | a raw byte search of every file for record IDs, passage text and vectors, beside a naive copy of the same records | naive copy: all found; SEVER-DB: none |
| 6 | What the database refuses | five invalid inputs and their typed errors; a retried insert | each refused; the retry stored once |
| 7 | Delete one person's records | `delete_user` on one account; the question it answered, before | all deleted, each with a certificate |
| 8 | Check the receipts offline | `sever-verify --explain` in a folder holding only the receipts and the public anchors; a flipped byte | all accepted; the tampered copy rejected |
| 9 | Deleted means gone | searches with each deleted record's own vector; the same question, after; deleting again | never found; `"absent"`; the count is exact |
| 10 | Restart, and pull the plug | a clean restart; then a second process inserting is killed with `SIGKILL` halfway | every record kept; every acknowledged insert there |
| 11 | Audit the public log | the signed log checkpoint and its witnesses; `sever-audit` over the exported log and the receipts | no findings |
| 12 | What next | the other demos | |

**A run on the owner's laptop** (19 Oct 2026, WSL2, 5,000 passages, with a test job running beside
it): 24 of 24 checks passed. 34.6 ms per insert (each one durable: encrypted, logged, signed and
synced before it returns), 0.85 ms per search. Of the 3,452 questions, the judged answer came first
for 3,178 and was in the top 10 for 3,410. The account "Roman Empire" (5 passages) was deleted in
215 ms with 5 certificates, all accepted offline. The writer was killed after 100 acknowledged
inserts; after recovery all 100 were there. The disk search found 0 of 40 record IDs, 0 of 80 text
windows and 0 of 40 vectors (the naive copy: all of them).

## The shell

`demo-engine/demo.sh shell` opens a database in `demo-engine/work/shell-nq/` that stays between
sessions (`reset` starts again). Questions are the 3,452 real test questions, picked by number or by
words in them: free text would need the encoder model itself, which this environment does not
install.

```text
sever> load 2000                    insert the next 2,000 passages with their accounts and text
sever> questions chicago fire       list matching questions with their numbers
sever> ask chicago fire season 4    search with the first matching question (✓ = the judged answer)
sever> show doc6                    a record: its account, whether it is in a group or still waiting
sever> accounts chicago             accounts with live records, largest first
sever> forget Chicago Fire (season 4)   delete the account's records; receipts in work/…/receipts
sever> ask chicago fire season 4    the answer is gone
sever> verify                       sever-verify --explain on the latest receipt
sever> tamper                       flip a byte of a copy and verify it: rejected
sever> crash                        a second process inserts and is killed; recovery; count the survivors
sever> disk | stats | log | audit | restart | delete ID | like ID | receipts | reset | quit
```

`demo-engine/demo.sh shell -c "load 100; ask 3; quit"` runs commands without a prompt.

## The command line

`demo-engine/demo.sh cli` runs [`cli-tour.sh`](cli-tour.sh): an account key, a database and a
collection, six inserts, a search, a `delete-user` with its six certificates, a search that no longer
finds them, a repeated delete (`"absent"`), each receipt checked by `sever-verify` in its own folder,
a tampered copy rejected, and `sever-audit` over the exported log. Every `sever-db` command opens the
database (recovery and the full invariant check run first), does one thing, prints one JSON line and
closes:

```text
sever-db <command> --data DIR --keys DIR [--d N] [--allow-unsafe-memory] [--allow-unsafe-fs]
  user-key --out FILE | create --artefact FILE | insert --cid HEX --id ID --vector JSON --user-key FILE
  [--passage TEXT] | search --cid HEX --vector JSON [--k N] | delete --cid HEX --id ID
  | delete-user --cid HEX --ids JSON | certificate --lsn N | anchors [--out FILE]
  | export-log [--out FILE] | latest-checkpoint | stats --cid HEX | drop --cid HEX | checkpoint | verify
```

## The forensic proof

Encryption at rest is chapter 5. The stronger claim (Part 4) is that **after a deletion is
acknowledged, nothing deleted can be recovered even by someone holding the whole disk and the key
file**, because the keys that could open it were overwritten (crypto-shredding). `demo-engine/demo.sh
erase` runs Part 4's demo (`scripts/demo-p4.sh`, Build 3-4 §2.11). On simulated disks laid out as
one image, the forensic scanner `sever-scan` uses every key it can carve from the image and recovers
a live record, which shows it can see. A person's records are deleted with verified certificates and the
scan finds nothing of them. Then the same run on the build that skips group-key rotation (SB-24)
leaks the deleted vector, and a crash between the commit and the key erase is finished by recovery.
The same scan on a real ext4 disk image is experiment EX-2.

## Use it in your own application

Build the SDK once (`demo-engine/demo.sh setup` does it), then copy from
[`examples/quickstart.py`](examples/quickstart.py) (the whole cycle in a page) and
[`examples/backend.py`](examples/backend.py) (a small service: key store, account index, retries,
typed errors, a "forget me" receipt bundle).

```python
from sever_db import Database, UserKey, prepare_insert

user = UserKey.generate()  # per account; store user.secret_bytes() yourself
with Database.open("/srv/sever/data", "/srv/sever/keys") as db:
    cid = db.create_collection("artefacts/partition-seed42.svp")  # once; keep the cid
    request = prepare_insert(cid, "doc-1", vector, user)  # keep it until acknowledged
    db.insert(cid, request, passage=b"the text")  # retry with the same request
    hits = db.search(cid, query_vector, k=10)  # [(record_id, distance), ...]
    deletion = db.delete(cid, "doc-1")  # .certificate: the receipt
    deletions = db.delete_user(cid, ["doc-2", "doc-3"])  # one person, all or nothing
    anchors = db.anchors()  # JSON, for sever-verify
```

| Call | Does | Spec |
|---|---|---|
| `Database.open(data, keys, d=384, allow_unsafe_fs=False, allow_unsafe_memory=False)` | opens, recovering or creating; `db.startup` lists the overrides used | §12.8–12.9, §16.2 |
| `create_collection(artefact, spawn_target=200, spawning_enabled=True, store_passages=True)` | a collection over a partition artefact; returns its ID | §6.3 |
| `prepare_insert(cid, record_id, vector, user)` | quantises, draws `r_t` from the OS, commits and signs; `r_t` is never readable | §4.2, §9.3–9.4, §9.8 |
| `insert(cid, request, passage=None)` | stores the record encrypted; `Receipt(database_lsn, placement, retried)` | §15.1 |
| `search(cid, query, k=10)` | the `k` nearest records in groups (not those still in the holding area) | §8 |
| `delete(cid, record_id)` / `delete_user(cid, ids)` | `Deletion(outcome, database_lsn, certificate)`; `"absent"` if not live | §15.3, §12.5 |
| `certificate(lsn)`, `anchors()`, `export_log()` | a stored certificate; the verifier's trust anchors; the log for an auditor | §11, §15.4 |
| `latest_log_checkpoint()`, `inclusion_proof(i, n)`, `consistency_proof(m, n)` | the signed log head with its cosignatures; RFC 9162 proofs | §10 |
| `stats(cid)`, `group_sizes(cid)`, `collections()`, `drop_collection(cid)`, `checkpoint()`, `close()` | counts (`N` excludes the holding area), groups, housekeeping | §5, §16.2 |

**The rules your data must follow.** Vectors are float32 of unit length, `d = 384`, made by the
encoder the partition artefact names (`sentence-transformers/all-MiniLM-L6-v2` at the pinned
revision); the database validates and never normalises for you. Record IDs are 1–256 UTF-8 bytes,
not a bare integer such as `12345`, and unique among live records. A new record waits in the holding
area, stored but not yet searchable, until 200 such records form a new group (§7.4). The data and key
directories must be on ext4 or XFS. Keep `keys/` private and backed up apart from `data/`: losing it
makes the data unreadable, which is exactly how deletion works. No call accepts a seed, nonce or
random generator (`SeededNonceForbidden`).

**Errors** are typed (all subclasses of `SeverError`) and never contain a record ID, a vector or a
key, so they can be logged as they are: `WrongDimension`, `NonFinite`, `NotNormalised`,
`InvalidRecordId`, `DuplicateRecord` (its first argument says whether the commitment matched, which
means a retry of a committed insert), `CommitmentMismatch`, `BadUserSignature`,
`GroupCapacityExceeded`, `UnknownCollection`, `SeededNonceForbidden`, `PlatformUnsafe`,
`IntegrityViolation`, `DurabilityFailure`.

## What is in this folder

| Path | What |
|---|---|
| `demo.sh` | the entry point (above) |
| `sever_tour/` | the tour (`tour.py`), the shell (`shell.py`), the backend they share (`session.py`: key store, inserts, deletions, receipts), the data (`data.py`), the tools and the disk search (`tools.py`) |
| `cli-tour.sh` | the command-line story |
| `examples/` | `quickstart.py`, `backend.py` |
| `tests/` | the demo's own tests: the tour passes every check, a whole shell session, both examples, the command-line story (all offline) |
| `work/` | the demo databases, keys and receipts (not in git; `demo.sh clean`) |

It uses the repository's environment (`.venv`, built by `uv sync`) and the SDK built into it. Its
Python is checked by the repository's `ruff` settings and by `mypy --strict` (`demo.sh test`).
