# B02 · How databases store data and "delete" it

## In simple words

A database must keep data safe even if the power fails in the middle of a write. To do that, it
writes changes to a log first and only then changes its main data, and it is careful about when data
really reaches the disk. Deleting is harder than it looks: most databases only *mark* a record as
deleted and clean it up later, and even after clean-up the old bytes can linger in old files and
freed disk space. This file explains these ideas, because SEVER-DB's Part 2 (crash safety) and Part 4
(erasure) are built on them.

> **Prerequisites.** Files and bytes, what a process is
> ([15_prerequisites §1](../15_prerequisites.md#1-programming-and-systems-basics), [§4](../15_prerequisites.md#4-databases)).
> Glossary: [WAL](../16_glossary.md#wal-write-ahead-log), [fsync](../16_glossary.md#fsync),
> [atomicity](../16_glossary.md#atomicity), [tombstone](../16_glossary.md#tombstone).

## The problem this solves

A program updates two things: it removes a vector from group A and lowers group A's count. The power
fails after the first write and before the second. On restart, the group's member list and its count
disagree. Worse: the program told the user "deleted" before the data reached the disk, and after the
restart the record is back. A database must never show a half-done change and never lose a change it
has confirmed.

## Build up step by step

### Step 1 — Memory is fast but forgets; disk is slow but remembers

Programs work in **RAM** (memory), which is lost on a crash or power cut. A **file** on disk survives.
When a program "writes" a file, the operating system (OS) usually keeps the new bytes in its own
memory (the *page cache*) and writes them to the disk later.

### Step 2 — fsync: "really put it on the disk now"

**`fsync`** (definition: a system call that asks the OS to push a file's pending writes to the storage
device and wait until they are stored) is how a program knows data is durable. A new file also needs
an fsync of its **directory**, or the file's name might vanish after a crash. On Linux, if `fsync`
fails, the dirty pages may already have been dropped, so retrying `fsync` can falsely "succeed";
the safe reaction is to stop and recover from what is on disk. SEVER-DB does exactly this: a failed
fsync aborts the process [DOC: docs/SEVER-DB_SPECIFICATION.md §12.7; DOC: README.md L194-L195].

### Step 3 — Transactions and atomicity

A **transaction** groups several changes so that they happen **all or nothing** (this property is
**atomicity**). "Delete these 5 records of one person" must either delete all 5 or none.

### Step 4 — The write-ahead log (WAL)

A **write-ahead log** (definition: an append-only file where the database writes a description of each
change, and makes it durable, *before* changing its main data) gives atomicity and durability:

1. Write `BEGIN`, the change records, then `COMMIT` to the log.
2. `fsync` the log. **The moment the COMMIT record is durable is the commit point.**
3. Only then change the in-memory/main data, and tell the user "done".

After a crash, **recovery** reads the log: transactions with a durable COMMIT are re-applied;
transactions without one are ignored (as if they never started).

**Illustrative example, not from the repository** — a crash before vs after the commit point:

| Crash happens… | What the log holds | After recovery |
|---|---|---|
| after `BEGIN`, before `COMMIT` is durable | BEGIN, delete r1, delete r2 (no COMMIT) | Nothing deleted. The caller was never told "done". |
| after `COMMIT` is durable, before memory changed | BEGIN, delete r1, delete r2, COMMIT | Both deleted (recovery replays the log). |

A **torn write** is a write cut off part-way by a crash; the last log record may be half-written. A
half-written record at the very end (a *torn tail*) is expected and ignored. A damaged record followed
by valid ones means real corruption, and SEVER-DB refuses to start [DOC: §12.3; README.md L213-L215].

### Step 5 — Checkpoints

If the log only grows, recovery gets slower and slower. A **checkpoint** (definition: a complete,
durable snapshot of the data at one moment) lets the database delete old log segments and start
recovery from the snapshot. SEVER-DB writes its storage checkpoints as atomic images and switches
to the new one by installing a small `MANIFEST` file [DOC: §12.4, §15.6].
(Note: SEVER-DB also has *log checkpoints* in its transparency log — a different thing, see
[B04](B04_cryptography_basics.md) and §0.4 of the spec.)

```mermaid
sequenceDiagram
  participant App
  participant DB as Database
  participant WAL as WAL file
  participant Mem as Memory state
  App->>DB: delete_user([r1, r2])
  DB->>DB: plan (all checks; nothing changed yet)
  DB->>WAL: BEGIN, records, COMMIT
  DB->>WAL: fsync  (commit point)
  DB->>Mem: apply the change
  DB-->>App: acknowledged
```

### Step 6 — Soft delete and tombstones

Many databases delete with a **soft delete**: they set a "deleted" flag (a **tombstone**) and filter
the record out of results. The bytes stay. Later, **compaction** (or `VACUUM` in PostgreSQL) rewrites
files without the dead records. Until then, and in old file copies, the data is still there. In a
vector index there is a second leak: summaries like a centroid or a running mean were computed
**with** the deleted vector and keep its influence — the **ghost**
([B03](B03_floating_point_vs_exact_integers.md)). How real systems do this is cited in
[R02](../research/R02_related_work.md).

### Step 7 — Why deleted bytes linger on disk

Even a "hard" delete leaves copies: in old WAL segments, old checkpoints, free disk blocks that the
filesystem has not reused, and on SSDs in flash cells that the drive's controller remapped. A program
cannot reliably overwrite all of these. This is why SEVER-DB Part 4 uses **crypto-shredding** instead:
store only ciphertext, and destroy the key ([B04](B04_cryptography_basics.md),
[07e](../07e_encryption_and_crypto_shredding.md)).

## Everyday analogy

*Analogy:* A WAL is like writing a task in a diary before you do it. If you faint half-way, you read the
diary when you wake up: a task with "DONE-PLANNED ✓" written under it gets finished; a task without the
tick is crossed out. *Where it stops:* a diary entry can be half-written in a way you can still read;
a torn log record is detected by checksums and simply ignored or treated as corruption.

*Analogy:* A soft delete is like putting a "do not read" sticky note on a page of a book. The page
is still there for anyone who peels off the note.

## How SEVER-DB does it

Part 2's transaction protocol is defined once, in `sever-txn`, as eight steps
[CODE: crates/sever-txn/src/protocol.rs:L1-L16]:

```text
 1  plan            the caller: a ChangeSet and its after-image records (all validation here)
 2  prepare         each participant adds WAL records, store bytes and phase-A actions
 3  append stores   their bytes are made durable (fsync)
 4  phase A         each participant's durable pre-commit actions
 5  WAL             BEGIN, core records, participant records, COMMIT; fsync  ── commit point ──
 6  apply           the caller installs the change under the exclusive lock
 7  phase C         each participant's after_commit
 8  acknowledge     only now does the caller see success (§15.8)
```

- *plan* computes the whole change without touching anything, so every check can fail safely.
- *participants* are plug-ins (later parts add the transparency log and key rotation).
- Step 5 is the commit point: `durable.wal.commit(&wal_records)` [CODE: protocol.rs:L121-L128].
- *apply* happens only after it, so memory is never ahead of the disk [CODE: protocol.rs:L14-L16].

All disk access goes through a **VFS** trait (a *virtual file system*: an interface with `fsync` and
`fsync_dir` methods) [CODE: crates/sever-vfs/src/lib.rs:L116-L146]. The real implementation writes
real files; a simulated one (`SimVfs`) keeps a "current" and a "durable" view so tests can crash the
database at every single file operation. Details in [06_part2_the_database.md](../06_part2_the_database.md).

SEVER-DB never uses tombstones: a deleted record is physically removed from its group, because a
marker would itself be a trace [DOC: §5.4].

## Key points to remember

- `fsync` is the only way to know data is on disk; a failed fsync means stop and recover.
- A WAL makes a group of changes all-or-nothing; the durable COMMIT record is the commit point.
- Recovery replays committed transactions and ignores uncommitted ones.
- Soft delete leaves the data (and, in vector indexes, its influence on summaries) behind.
- Old copies of bytes survive on disk; only destroying the decryption key reliably removes them.

## Check your understanding

1. *What is the commit point in SEVER-DB?* — The moment the WAL's COMMIT record is fsynced (step 5).
2. *A crash happens after COMMIT is durable but before memory changed. Is the deletion lost?* — No;
   recovery replays it.
3. *Why fsync the directory of a new file?* — Otherwise the file's directory entry may be lost.
4. *Why is a tombstone a problem for SEVER-DB?* — It is itself a trace of the deleted record.
5. *Why does SEVER-DB not simply overwrite deleted bytes?* — Copies exist in places a program cannot
   reach (old WAL segments, freed blocks, SSD cells), so it destroys keys instead.
