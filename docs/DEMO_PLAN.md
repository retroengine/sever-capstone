# SEVER-DB Capstone: 4-Day Demo Plan (1 Oct to 4 Oct 2026, review 5 Oct)

Owner: you. Role of Claude: coach (you write, Claude reviews and quizzes). Assumed review date: **5 Oct 2026**. Correct this if it is wrong.

---

## 0. The honest status (memorise this paragraph)

> "Phase 0 is done: datasets are pinned, embedded and hash-verified. The whole system is designed in a specification, an overview with decisions and targets, and a four-part build plan. I am building Part 1, the exact-deletion index, as a Python reference implementation first. The engine in Rust comes after, checked against this Python version. Nothing in Parts 2 to 4 is built yet."

Rules for what you may claim:

| You may say | You may NOT say |
|---|---|
| Data pipeline works and is hash-verified (you will run `verify` live) | "The system is built" |
| Exact deletion works in my Python prototype, on 1,000,000 real vectors (once you have run it) | "We proved it is secure" |
| The design/spec/plan exist and I can explain the architecture | Any number you did not produce by running code |
| I used AI heavily for the specification and plan drafting, and I am responsible for being able to explain and defend it | That you wrote the spec by hand (if you did not) |
| Targets T-1 to T-6 are pre-registered goals | That any target has been met (none measured yet) |

A smaller project you fully understand beats a bigger one you cannot explain. Every follow-up question is a test of that.

---

## 1. What you are building: the Part 1 core demo

**One claim to demonstrate (Build §0.1, Part 1):** deleting a vector returns its group, bit for bit, to the state it would have had if the vector had never arrived. Averages and soft deletion cannot do this.

### 1.1 In scope

- Load the real data: SciQ reference embeddings and the full `nq_1m` corpus, d = 384, **no scaling down**.
- Check normalisation (§4.1) on every row and report the exact failure count.
- Quantise to Q24 integers (§4.2), `i32`.
- Fit **k = 128** frozen centroids on SciQ with k-means (§6.2 step 2). Frozen-only routing (this is the `spawning_enabled = false` configuration, Build §4.3).
- Groups with exact integer sum `S` (`i64`), count `n`, and member list.
- `insert`, `delete`, idempotent delete (`AlreadyAbsent`), `delete_user` (many records, many groups).
- Canonical group blob + SHA-256 (simplified from §5.5).
- The **survivors check**: group after deletion equals a group rebuilt from survivors only.
- Two baselines to show "the ghost": float running mean, and soft delete.
- Tests (pytest) and three deliberate sabotages that must turn tests red.
- A run ledger (append-only JSONL, auto-written).
- A REPL (`cmd` + `rich`) wrapping a working `demo.py`.
- 8 slides.

### 1.2 Explicitly out of scope (say this up front to your guide)

Drift test (Mahalanobis), holding area and spawning, search, commitments, WAL and crash safety, encryption, certificates, transparency log, Rust. These are Parts 2 to 4 and the Part 1 remainder. Say: "Part 1 core is the MVP, the rest is the roadmap."

### 1.3 Four of the five exactness fields

The spec's equivalence relation has five fields: `S`, `n`, `C_S`, blob, member list (§5.5). The demo has no commitments, so it checks **four** (`S`, `n`, blob, member list). Say this honestly. `C_S` arrives in Part 3.

---

## 2. Concepts you must be able to explain (read in this order)

Read only these. Do not read the rest of the documents before the review.

| # | Read | Goal |
|---|---|---|
| 1 | Overview §1 (Announcement) | The problem, the three-part idea, the "ghost" |
| 2 | Overview §5 (Design in plain words) | The whole system in one page |
| 3 | Spec §1 (System on one page) | The same, with the architecture diagram |
| 4 | Spec §4 (Vector arithmetic) | Normalisation, Q24, bounds, overflow |
| 5 | Spec §5 (Groups, accumulators, exact deletion) | The core of your demo |
| 6 | Spec §3.2 (Record ID rules) | The ID tests |
| 7 | Spec §6.2 (Partition builder, steps 1 and 2 only) | How the centroids are made |
| 8 | Overview §14 (Known limits) | Your honest answers to "what can go wrong" |
| 9 | Overview §8 and Build §0 (phases / four parts / freeze rule) | The roadmap story |

### 2.1 Five sentences (write in `docs/notes/P1-idea.md`, your own words, tonight)

1. What is the problem with deleting from a vector database?
2. What is the trick (integers, sums and counts)?
3. Why can an average not be undone but a sum can?
4. What do the four parts add, in order?
5. What is done and what is not?

### 2.2 Key facts, in plain words

- **Embedding:** a list of 384 numbers representing a passage. **Normalised:** length 1.
- **Group (cluster):** a bucket of similar vectors. 128 of them, fixed in advance using SciQ (public data with no user data), never moved.
- **Why fixed groups:** a deletion touches exactly one group, so checking that group is enough.
- **Q24:** `round_half_even(x * 2^24)` stored as `i32`. Integers add and subtract exactly. Floats do not (rounding depends on order).
- **Overflow bound:** `|x̃| <= 2^24 + 16`; with up to 10^6 members the sum is below 2^44, which fits `i64` with 19 bits spare (§4.4).
- **Ties to even:** `0.5 -> 0`, `1.5 -> 2`, `2.5 -> 2`. Unbiased, so no drift accumulates.
- **Ghost:** a deleted record's surviving influence in summaries (centroids) or on disk.
- **Soft delete:** hide the record, keep it in the structure, summaries unchanged.
- **Physical excision:** remove the record from the member list. No markers (§5.4).
- **Idempotent delete:** a second delete of the same ID changes nothing (§5.4). Otherwise a client retry subtracts twice.
- **Survivors check:** the exact meaning of "as if never inserted".
- **Why not graph indexes:** a graph keeps edges shaped by the deleted node (§8.3).

---

## 3. Python curriculum (10 topics)

Method for every topic: read the docs for 10 minutes, **predict the output before running**, run it, then write one line on why it behaved that way. Put the exercises in `scratch/` (not committed) and your one-liners in `docs/notes/P1-python-notes.md`.

Sources: NumPy "absolute beginners" guide, pytest "Get started", Python docs for `hashlib`, `dataclasses`, `re`, `json`, `subprocess`.

| # | Topic | Exercise | Done when you can explain |
|---|---|---|---|
| 1 | NumPy dtypes and overflow | Sum 1,000,000 copies of `16_777_232` in `int32` then `int64` | Why sums are `i64` (§4.4) |
| 2 | Float non-associativity | In float32, compare `(a+b)+c` vs `a+(b+c)`, and sums of the same array in two orders | Why floats cannot be undone exactly |
| 3 | Rounding | `np.round` / `np.rint` on `0.5, 1.5, 2.5, -0.5` vs `np.floor(x+0.5)` | "Ties to even" and why it is unbiased (DB-5) |
| 4 | Bytes and hashing | `hashlib.sha256(arr.astype('>i8').tobytes())`; change dtype / byte order and watch the hash change | Why the spec fixes big-endian (§0.2) |
| 5 | Strings, sorting, regex | Sort strings by UTF-8 bytes. `re.fullmatch(r'[+-]?[0-9]+', s)` on `doc0, 1, 007, -3, +3, ''` | The §3.2 ID rules, and why `fullmatch` not `match` |
| 6 | Classes, dataclasses | A `Group` with `S, n, members` | Mutable default arguments trap |
| 7 | pytest | `assert`, `parametrize`, fixtures, `pytest.raises`, custom marks | Write a failing test, then make it pass |
| 8 | Seeded randomness | `np.random.default_rng(42)`: shuffle, choice, same result on rerun | Reproducibility |
| 9 | Files, time, subprocess | Append one JSON line; `datetime.now(timezone.utc)`; `subprocess.run(["git","rev-parse","HEAD"])` | Writing the ledger function |
| 10 | Loading data | `np.load(path, mmap_mode='r')`; print shape, dtype, min/max norm; read `passages.parquet` columns with pandas/pyarrow | The real shapes (not assumed) |

Extra traps to know:

- NumPy integer arrays silently wrap on overflow. Always check the dtype.
- `np.sum` and `@` do not guarantee a fixed summation order. Sequential order is `np.cumsum(..., axis=-1)[..., -1]` (CLAUDE.md §7). For this demo, integer sums are exact in any order, so it only matters for float baselines and the norm check.
- Never use Python's built-in `hash()` for anything (randomised per run).
- Run everything with `PYTHONHASHSEED=0`.

---

## 4. Environment and repository

```
final-vdb/
  python/sever_demo/
    __init__.py
    data.py          # load + verify datasets, norm check, ID check
    quant.py         # Q24 quantiser, dequantiser
    ids.py           # record ID validation (§3.2)
    partition.py     # fit k-means on SciQ, route NQ to nearest centroid
    group.py         # Group: S, n, members; insert, delete; blob + hash
    index.py         # Index: 128 groups, locator, insert/delete/delete_user, state hash
    baselines.py     # float running mean, soft delete
    ledger.py        # append-only JSONL writer
    demo.py          # full run, prints the results table
    repl.py          # cmd + rich shell around demo.py
  tests/
    test_quant.py  test_ids.py  test_group.py  test_index.py
    test_stress.py  test_sabotage.py  test_ledger.py
  docs/notes/        # your own words: P1-idea.md, P1-python-notes.md, P1-quant.md, ...
  docs/RUN_LEDGER.jsonl   # committed, append-only, never hand-edited
```

Setup (WSL, repo root):

```
uv sync
uv add numpy pandas pyarrow scikit-learn rich
uv add --dev pytest ruff mypy
export PYTHONHASHSEED=0
```

Check `pyproject.toml` first: some of these may already be present. Commit `pyproject.toml` and `uv.lock` together.

Rules (from CLAUDE.md §8): do **not** write into `datasets/`. Put caches outside the repo, e.g. `~/.cache/sever/`, and never commit them.

---

## 5. Module specifications (what each piece must do)

### 5.1 `data.py`

- `load_sciq()` and `load_nq()` return memory-mapped float32 arrays, plus the passage ID arrays from the parquet files.
- `check_manifest(root)`: re-run or call the existing verify; print PASS/FAIL. This is your live Phase 0 proof.
- `check_norms(X)`: float64 sequential norm per row; count rows where `|norm - 1| > 8 * 2**-23`; also count non-finite. Process in chunks (1M x 384 float32 is about 1.5 GB). **Report exact counts. Never loosen the tolerance.** If the count is non-zero, report it as a finding.

### 5.2 `quant.py`

- `quantise(X) -> int32 array`: `np.rint(X.astype(np.float64) * 2**24)`, then cast to `int32`. Assert the bound `|x̃| <= 2**24 + 16`.
- `dequantise(Q) -> float64`: `Q / 2**24`.
- Cache the quantised NQ array to `~/.cache/sever/nq1m_q24.npy` so you quantise once.
- Never create a full `int64` copy of the corpus (3 GB). Widen only the slice you sum.

### 5.3 `ids.py`

- `validate_record_id(s) -> None | raises InvalidRecordId`: 1 to 256 UTF-8 **bytes** (not characters), not `fullmatch [+-]?[0-9]+`. Rule 3 (not already live) is the index's job.
- Errors must never contain the ID itself (§17).

### 5.4 `partition.py`

- Sub-seed: first 8 bytes of `SHA-256(u64be(seed) || b"kmeans")` as an unsigned integer, then **mod 2^32** because scikit-learn rejects larger seeds. This is spec gap G-1 in `SPEC_GAPS.md`; mention that you hit and handled it.
- `KMeans(n_clusters=128, init="k-means++", n_init=10, max_iter=300, tol=1e-4, algorithm="lloyd", random_state=...)` on the dequantised SciQ vectors (§6.2 steps 1 and 2).
- `route(Q_chunk, centroids) -> labels`: nearest centroid by Euclidean distance, ties to the smaller label. Chunked matrix multiplication (for example 20,000 rows at a time). Note honestly: the spec pins a sequential summation order (§7.1); the demo uses a faster form, which is fine because routing is deterministic for fixed data, and the exactness claim does not depend on which group a vector lands in.

### 5.5 `group.py`

State per group: `S` (`int64[384]`), `n`, `members` (a dict or set of record IDs mapped to row indices into the global quantised array).

- `insert(id, row)`: reject duplicates; `S += Q[row]` (widened to int64); `n += 1`.
- `delete(id)`: if the ID is not a member, return `AlreadyAbsent` and change nothing (§5.4). Otherwise `S -= Q[row]; n -= 1`; remove the member.
- `blob()`: simplified canonical form. Magic `b"SEVERC"`, `u16be version`, `u16be d`, `u64be n`, `i64be x d` for `S`, `u64be member_count`, then per member **ascending by ID UTF-8 bytes**: `u16be id_len || id bytes || i64be x d (x̃)`. Use big-endian dtypes (`'>i8'`).
- `blob_hash()`: SHA-256 of the blob. Stream it in pieces so a 7,800-member group (about 24 MB) never builds a second giant copy.
- `empty group` stays forever (`S = 0`, `n = 0`).

### 5.6 `index.py`

- 128 groups; a locator dict `id -> group_id`.
- `insert(id, row)`: validate ID, check not live, route, insert.
- `delete(id)`: locator lookup, group delete, locator update.
- `delete_user(ids)`: process a list across groups; return per-record outcomes.
- `state_hash()`: hash of all group blob hashes in group order (used to prove "nothing else changed").
- `build_survivors(group_id)`: a fresh `Group` built from the current members of that group **in shuffled insertion order**, used by the survivors check.

### 5.7 `baselines.py`

Two comparison structures, run on the same operations:

1. **Float running mean (float32):** on insert `m <- m + (x - m)/n`; on delete `m <- (m * n - x) / (n - 1)`. Compare against the survivors-only mean computed in float64 from the same vectors. Report the max absolute difference and whether it is bitwise equal.
2. **Soft delete:** the record is flagged but stays in the structure; the sum/centroid keeps its contribution. Report the distance between the group's stored summary and the survivors-only summary.

**Honesty rule:** the float error will probably be small (order 1e-7 in float32). Your claim is "not bit-identical, and it accumulates over many operations", **not** "huge". Report the numbers as measured. Also show the error growing over, say, 1,000 insert/delete cycles. Overstating will cost credibility.

SEVER row in the table: `S` and `n` identical, difference exactly 0.

### 5.8 `ledger.py`

One JSON line appended per run to `docs/RUN_LEDGER.jsonl`. Fields:

```
ts_utc, ts_ist, command, git_commit, git_dirty (bool),
seed, dataset_manifest_sha256, rows_loaded, k_groups,
outcome ("PASS" | "FAIL"), counts {ops, checks, mismatches, norm_failures},
result_file, result_sha256, platform {python, numpy, os}, sabotage ("none" | "SB-1" ...)
```

Rules:

- Written by code, never by hand.
- If the ledger cannot be written, the run does not start (Overview §13.3).
- Append mode only. Never edit the file.
- A sabotage run logs `sabotage != "none"` and `FAIL`.
- Commit the ledger. The git commit timestamp is independent evidence of when runs happened.

### 5.9 `repl.py` (`cmd.Cmd` + `rich`)

| Command | Does |
|---|---|
| `verify_data` | Runs the manifest check; prints PASS/FAIL |
| `load [N]` | Loads N rows (default all 1,000,000), norm check, quantise, route, build groups; prints stats table |
| `stats` | Group count, min/median/max size, total N |
| `group <id>` | n, SHA-256 of `S`, blob hash |
| `delete <record_id>` | Group touched; before/after hashes; outcome |
| `delete_user <title or n random>` | Multi-group deletion |
| `verify <group_id>` | Survivors check, prints each of the four fields with a tick or cross |
| `ghost` | The three-way comparison table |
| `stress <n>` | n seeded random operations, each followed by a check |
| `sabotage <off|SB-1|SB-2|SB-3>` | Turns on one deliberate bug |
| `ledger [n]` | Shows the last n ledger entries |
| `quit` | Exit |

Every state-changing or checking command writes a ledger entry automatically. **Build `demo.py` first. The REPL is a wrapper.**

---

## 6. Test plan (write each test BEFORE its code)

Naming: `test_<area>_<behaviour>`. Mark with `@pytest.mark.spec("SR-...")` if you add IDs (optional for the demo; record the § in a comment instead).

Test data: unit tests use **tiny synthetic data** (d = 16, 4 groups, under 2 seconds total). This follows Build §2.7 and is not scaling down the demo. The demo, the headline claim and ledger entries use the full data.

| # | Test | Checks | Spec |
|---|---|---|---|
| T1 | `test_quant_ties_to_even` | `0.5, 1.5, 2.5, -0.5` (scaled by 2^-24) quantise to `0, 2, 2, 0` | §4.2 |
| T2 | `test_quant_bound` | `|x̃| <= 2^24 + 16` for normalised inputs at the tolerance edge | §4.2 |
| T3 | `test_norm_rejects_bad` | NaN, +/-inf, norm just beyond `8*2^-23` rejected; norm just inside accepted | §4.1 |
| T4 | `test_ids_valid_and_invalid` | Valid: `doc0`, UUID. Invalid: `1`, `007`, `-3`, `+3`, empty, 257 bytes. Multibyte: a 100-char string of 3-byte characters (300 bytes) is rejected | §3.2 |
| T5 | `test_insert_then_delete_restores_state` | Round trip: `S`, `n`, members, blob hash equal to before | §5.3 |
| T6 | `test_delete_absent_is_idempotent` | `AlreadyAbsent`, state hash unchanged | §5.4 |
| T7 | `test_duplicate_live_id_rejected` | Second insert of a live ID rejected | §3.2 rule 3 |
| T8 | `test_survivors_check_after_random_deletes` | Incremental `S` equals `S` recomputed fresh from members, AND blob hash equals a rebuilt-from-survivors group built in a different order | §5.5 |
| T9 | `test_blob_order_independent` | Same member set, 100 shuffled insertion orders, identical blob hash | §5.5, P1-T3 |
| T10 | `test_empty_group_persists` | Delete all members: `S = 0`, `n = 0`, group still exists | §5.4 |
| T11 | `test_delete_user_multi_group` | Cohort across several groups: each touched group passes survivors check, untouched groups' hashes unchanged | Build E2E-1.4 |
| T12 | `test_stress_random_ops` | 2,000 seeded ops (insert, delete, delete-absent, re-insert), zero mismatches | P1-T1 |
| T13 | `test_ledger_appends_and_never_rewrites` | Two runs give two lines; earlier line bytes unchanged | Overview §13.3 |
| T14 | `test_float_baseline_is_not_exact` | The float32 running mean differs from the survivors-only mean after a delete sequence (this documents the ghost) | Overview §1.2 |

**Trap in the survivors test (T8):** if you compare `S` against a value derived from `S`, the test proves nothing. Recompute from the member rows with fresh code, and compare blob hashes between the live group and a freshly built one.

### 6.1 Sabotage (must-fail) tests

Switchable via a module flag, each must turn a named test red. Use `@pytest.mark.mustfail`.

| ID | Bug | Must turn red |
|---|---|---|
| SB-1 | Flip one bit of `S` after an insert | T8 and T5 |
| SB-2 | Skip `n -= 1` on delete | T5, T8 |
| SB-3 | Remove the membership check (a retried delete subtracts twice) | T6 |

If a sabotage leaves everything green, **a test is missing**. That is your finding. Add one. Revert each sabotage afterwards and re-run to confirm green.

### 6.2 Full-data acceptance run (the ledger-worthy run)

On all 1,000,000 NQ vectors, k = 128, seed 42:

1. Manifest verified.
2. Norm check: failures reported (target: whatever the data says; report it).
3. ID check on all 1M IDs: rejections reported.
4. Build groups; print size distribution.
5. Pick a cohort (all passages sharing a Wikipedia `title`, if the column exists; else a random sample of 1,000 IDs) and `delete_user`.
6. Survivors check on every touched group: 0 mismatches.
7. Stress: 2,000 ops. **Cost warning:** a full blob hash of a 7,800-member group is about 24 MB of hashing. Run the cheap check (`S`, `n`, member list) after every op, and the full blob-hash check every 50 ops and at the end for all touched groups. Say so in your slide.
8. Ghost table.
9. Ledger entry written, committed.

Repeat for the other four seeds `[123, 777, 2024, 9999]` only if time allows (the real plan uses all five; one seed is acceptable for the review, but state "seed 42 only").

---

## 7. The ghost table (what the slide shows)

Format (values are filled by your run, not by you):

```
method              deleted record still stored   summary vs survivors-only        bit-identical?
SEVER (integer S)   no                            0 (S, n, blob hash identical)    yes
float running mean  no                            <measured max abs diff>          <measured>
soft delete         yes                           <measured distance>              no
```

Report the exact measured numbers. If the float baseline difference is 1e-8, say 1e-8.

---

## 8. Demo script (6 to 8 minutes, practise until it is boring)

1. **(30 s)** One-sentence problem and the claim.
2. **(45 s)** `verify_data`: Phase 0 proof, real and hash-verified.
3. **(60 s)** Start the REPL; point at the new ledger line. `load` (full data): stats table.
4. **(60 s)** `group 3`: before hashes.
5. **(60 s)** `delete <id>`, then `verify 3`: after hash equals survivors-only, four ticks.
6. **(60 s)** `delete_user` across several groups: all ticks; other groups unchanged.
7. **(45 s)** Delete the same record again: `AlreadyAbsent`, state hash unchanged.
8. **(60 s)** `ghost`: the comparison table.
9. **(60 s)** `sabotage SB-2` then `verify`: red. `sabotage off`: green.
10. **(30 s)** `ledger`, then `git log --oneline -5`: timestamped, committed record.
11. **(30 s)** Roadmap slide: Parts 2 to 4, honest limits.

**Backup plan:** a screen recording of one full successful run, and screenshots of each step. If a live run fails or hangs, switch without apology.

---

## 9. Slides (8)

1. **Title + one-sentence claim.**
2. **Problem:** the ghost; the three ways deletion fails (soft delete, rebuild cost, disk copies).
3. **The idea:** sums and counts in integers; why averages cannot be undone (small numeric example).
4. **Architecture:** the four parts and what each adds; the freeze rule in one line.
5. **What is done:** Phase 0 data (counts, hashes), spec and plan, the Part 1 demo.
6. **Demo results:** survivors check, ghost table, sabotage red/green, ledger.
7. **Honest limits:** what is not built; what the design cannot do (Overview §14: SSD firmware, dishonest operator, service-held keys (L-27), index shape persists, witnesses simulated, no independent crypto review).
8. **Roadmap:** Part 1 remainder, Parts 2 to 4, Rust engine, timeline (about 8 months full time in the plan).

---

## 10. Q&A bank (answer each in 2 to 3 sentences, aloud)

1. Why integers and not floats? *Integer add/subtract is exact; float rounding depends on order so subtraction does not restore the old value.*
2. What is Q24 and can it overflow? *Multiply by 2^24, round to nearest even, store as i32. Bound 2^24+16 per component; with 10^6 members the sum stays below 2^44 in i64.*
3. Why round half to even? *Unbiased, so no systematic drift accumulates in sums.*
4. Why fixed groups instead of re-clustering? *Re-clustering would move every vector's group; fixed groups mean one deletion touches exactly one group.*
5. Why is SciQ the reference set and NQ the live set? *Groups must be fitted on data that contains no user data; mixing would contaminate the measurements.*
6. What is "exact deletion" precisely? *Group state (sum, count, blob, member list, and later commitment) equals a group built from the survivors only.*
7. What if the same record is deleted twice (client retry)? *Idempotent: `AlreadyAbsent`, no change. Otherwise the vector would be subtracted twice.*
8. Why remove records physically instead of marking them? *A marker is itself a leftover trace.*
9. What does your demo not cover? *Drift/spawning, search, commitments, crash safety, encryption, certificates. They are Parts 2 to 4 and the Part 1 remainder.*
10. Why four parts in this order? *Each adds one claim on the frozen previous part. Durability before receipts, receipts before erasure, because encryption wraps whatever bytes earlier parts define.*
11. What is the freeze rule? *When a part passes its gate, its files are hashed and tagged; later parts extend through declared extension points and never edit it. A bug is fixed only through a logged erratum.*
12. Why Rust for the engine? *Memory safety and secure wiping of secrets, no garbage collector; Python is used for the oracle and tooling.*
13. Why a Python reference model? *A slow, obviously correct second implementation catches engine bugs by byte-for-byte comparison.*
14. How do you know your tests detect bugs? *Sabotage: I break the code on purpose and show tests go red.*
15. Is the float baseline really that bad? *It is not bit-identical and the error accumulates; it is small per operation. The point is exactness, not magnitude.*
16. What can still leak even with this design? *Operator copies, SSD firmware, index shape persists, metadata (Overview §14).*
17. What did you write and what did AI write? *Be truthful: AI drafted the spec/plan under my direction; I wrote the demo code and tests and can defend every line (only say the last part if true by Oct 5).*
18. What are the pre-registered targets? *T-1 to T-6 are goals fixed before measurement; none are claimed yet.*
19. How do you know the data is intact? *SHA-256 manifest, re-verified live.*
20. What is the next step after the review? *Finish Part 1 (partition builder oracle, routing with drift/spawn, search), then the Rust engine checked against the Python model.*

Use `quiz` mode with Claude on Oct 3 evening and Oct 4.

---

## 11. Day-by-day schedule (IST)

### Day 1: Thursday 1 Oct (now to 23:00): understand + foundations

| Time | Task |
|---|---|
| 18:15 to 19:30 | Read the concept list (Section 2), items 1 to 5. Write the 5 sentences in `docs/notes/P1-idea.md` |
| 19:30 to 19:45 | Break. Dinner |
| 19:45 to 21:15 | Python exercises #1 to #8. Notes in `docs/notes/P1-python-notes.md` |
| 21:15 to 21:45 | Exercise #10 (data inspection). Print shapes, dtypes, norm range, ID column, count of out-of-tolerance rows. Paste the output to Claude |
| 21:45 to 22:45 | Write T1 to T3 tests, then `quant.py` until green |
| 22:45 to 23:00 | Update `docs/PROGRESS.md`; commit with a conventional message |

**Gate:** tests T1 to T3 green; 5 sentences written; data facts printed; you can explain every line of `quant.py`.

### Day 2: Friday 2 Oct: core build (the heaviest day)

| Time | Task |
|---|---|
| 08:00 to 08:30 | Quiz yourself on Day 1 concepts |
| 08:30 to 09:30 | Exercise #9 (ledger function). Write `ledger.py` + T13. Run once, review the output line |
| 09:30 to 11:00 | T4 (ids) then `ids.py`; run the ID check on all 1M IDs |
| 11:00 to 13:00 | T5 to T7, T10, then `group.py` (insert, delete, blob, hash) |
| 13:00 to 14:00 | Lunch / rest |
| 14:00 to 15:30 | T8, T9 then survivors-check and order-independence |
| 15:30 to 17:00 | `partition.py`: fit k-means on SciQ (k = 128), route 1M NQ vectors in chunks, cache quantised array |
| 17:00 to 18:30 | `index.py`, T11, `delete_user` |
| 18:30 to 19:00 | Break |
| 19:00 to 20:30 | T12 stress test (cheap check each op, full hash every 50 ops); `baselines.py`, T14 |
| 20:30 to 21:30 | Sabotage tests SB-1 to SB-3; each must go red; revert; re-run green |
| 21:30 to 22:30 | `demo.py`: the full-data acceptance run (Section 6.2); first ledger entry; commit it |
| 22:30 to 23:00 | Update `PROGRESS.md`; send Claude your code for review |

**Gate:** `pytest` green; all three sabotages go red; `demo.py` runs end to end on full data and prints the ghost table; a ledger line exists and is committed.

### Day 3: Saturday 3 Oct: presentation layer

| Time | Task |
|---|---|
| 08:00 to 09:00 | Apply review feedback from Claude; fix findings |
| 09:00 to 11:30 | `repl.py` with `cmd` + `rich`; every command writes to the ledger |
| 11:30 to 13:00 | Slides 1 to 5 |
| 13:00 to 14:00 | Lunch / rest |
| 14:00 to 15:30 | Slides 6 to 8; paste real numbers from the ledger |
| 15:30 to 17:00 | First full timed demo rehearsal (aloud); note stumbles |
| 17:00 to 18:30 | Q&A drill: `quiz` mode with Claude (questions in Section 10) |
| 18:30 to 19:00 | Break |
| 19:00 to 20:30 | Clean clone test: `git clone` to a new folder, `uv sync`, run `demo.py`. Fix anything that breaks |
| 20:30 to 21:30 | Record a backup screen recording and screenshots |
| 21:30 to 22:00 | Update `PROGRESS.md`, commit |

**Gate:** the demo works from a fresh clone; slides done; one timed rehearsal done.

### Day 4: Sunday 4 Oct: polish only

| Time | Task |
|---|---|
| 09:00 to 10:30 | Bug fixes only. **No new features after 12:00** |
| 10:30 to 12:00 | Rehearsal 2 (timed, aloud, full) |
| 12:00 to 13:00 | Lunch |
| 13:00 to 14:30 | Q&A drill round 2 with Claude; write the answers you stumbled on |
| 14:30 to 16:00 | Rehearsal 3, including a deliberate failure (practise the backup switch) |
| 16:00 to 17:00 | Tag `demo-v0`; final clean-clone run; print or save slides as PDF |
| 17:00 to 18:00 | Prepare the laptop: charge, close apps, font size large, terminal theme readable |
| Evening | Rest. Sleep before 23:00 |

### Day 5: Monday 5 Oct: review

Arrive early. Run the demo once before she arrives. Keep the backup recording open on another screen.

---

## 12. Priority and cut order

If you fall behind, cut in this order (earliest first):

1. REPL polish (keep a plain script)
2. Stress count (2,000 to 500)
3. Extra seeds (stay on seed 42)
4. Slide polish
5. `delete_user` (keep single delete)

**Never cut:** the survivors check, order independence, idempotent delete, the sabotage demonstration, the ledger, and the live manifest verify.

Stop rule: if something takes more than 90 minutes without progress, stop and ask Claude a specific question (what you tried, what you expected, what happened).

---

## 13. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Full 1M data is slow on `/mnt/c` | Cache quantised array in `~/.cache/sever/`; use `mmap_mode='r'`; chunk the routing |
| RAM pressure (about 3 GB for arrays) | Quantise to `int32`; never make a full `int64` copy; groups hold row indices not vector copies |
| Real embeddings fail the norm check | Report the count; do not loosen the tolerance; this is a finding |
| Record IDs in the parquet differ from assumed | Inspect columns tonight (exercise #10); handle before building |
| k-means is slow or seed errors | Use `seed mod 2**32` (G-1); SciQ is only 13,679 rows |
| Blob hashing too slow in stress | Cheap check each op, full hash every 50 ops and at end |
| Demo crashes live | Backup recording + screenshots |
| Over-claiming | Section 0 table; use only numbers from the ledger |
| Burnout | Sleep before midnight; Day 4 evening is rest |
| "Juggling" habit | One task at a time; only the capstone gets your best hours until 5 Oct; LeetCode capped at 1 hour/day |

---

## 14. Definition of done (check before 5 Oct)

- [ ] 5-sentence explanation written in your own words
- [ ] Data facts printed and recorded (shapes, dtypes, norm failures, ID rejections)
- [ ] Tests T1 to T14 pass
- [ ] SB-1 to SB-3 each turn a test red, and revert to green
- [ ] Full-data run (1,000,000 vectors, k = 128, seed 42) completes with 0 survivors-check mismatches
- [ ] Ghost table with measured numbers
- [ ] Ledger entries exist, are committed, and are never hand-edited
- [ ] REPL works (or the script fallback works)
- [ ] 8 slides done with real numbers
- [ ] Q&A bank answered aloud, twice
- [ ] Demo runs from a fresh clone
- [ ] Backup recording + screenshots saved
- [ ] `PROGRESS.md` updated; commit tagged `demo-v0`
- [ ] You can explain every line of code you show

---

## 15. After the review (not before)

1. Finish Part 1 properly: partition builder with the independent Ledoit-Wolf oracle, drift test, holding area and spawning, search, trace files.
2. Settle spec gaps G-1 to G-5 in `SPEC_GAPS.md` with decision entries.
3. Learn Rust (Rust Book chapters 1 to 6, 8, 9, 11), then write `sever-types`, `sever-quant`, `sever-index`, differential-tested against your Python model.
4. Parts 2 to 4 follow the build plan.

## 16. Working rules with Claude

- Default mode is **coach**: you write, Claude reviews and asks questions.
- Say "write it" only when truly stuck; Claude will then ask you two questions to confirm you can explain it.
- Each work block ends with something you can explain without notes. If you cannot explain it, it is not done.
- Never claim a test passes without running it.
- Send Claude: printed data facts (tonight), your 5 sentences (tonight), code for review (end of Day 2), rehearsal feedback (Day 3 and 4).
