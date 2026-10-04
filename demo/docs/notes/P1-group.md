# `group.py` and `index.py`: exact deletion (§5) and the survivors check (§5.5)

> **Location (4 Oct 2026):** this demo now lives in `demo/` and runs on its own (`demo/README.md`). Paths below are relative to `demo/`; the spec, `CLAUDE.md`, `docs/PROGRESS.md` and `datasets/` are at the repository root (`../`).

Files: [python/sever_demo/group.py](../../python/sever_demo/group.py),
[python/sever_demo/index.py](../../python/sever_demo/index.py). Tests:
[tests/test_group.py](../../tests/test_group.py), [tests/test_index.py](../../tests/test_index.py),
[tests/test_stress.py](../../tests/test_stress.py), [tests/test_sabotage.py](../../tests/test_sabotage.py).
Written by Claude (write mode, 2 Oct). **This is the file the reviewer will question most.**

## One line

Each group stores an exact integer sum `S`, a count `n` and its member list. Deleting subtracts exactly,
so the group ends up identical to one that never saw the deleted record.

## Why

- An average can't be undone exactly in floats; a sum of integers can (`S − x̃` is exact).
- "Identical" needs a precise test. That is the **survivors check**: the live group must equal a group
  rebuilt from the survivors only.

## How it works

`Group` (one group):
- State: `S` (`int64[d]`), `n`, `members` = `{record ID: row}`. Rows point into one shared `int32` array;
  vectors are never copied.
- `insert(rid, row)`: duplicate → `DuplicateRecord`; `n + 1 > 10^6` → `GroupCapacityExceeded`;
  `S += x̃` (widened to `int64`); `n += 1`.
- `delete(rid, row)`: **not a member → `AlreadyAbsent`, nothing changes.** Otherwise `S −= x̃`,
  `n −= 1`, remove the member (no marker left behind).
- `blob()`: canonical bytes. `SEVERC` | version | `d` | `n` | `S` | member count | then each member,
  sorted by ID bytes: length | ID | `x̃`. All big-endian. `blob_hash()` streams it into SHA-256.
- `snapshot()` / `compare(a, b)`: the 4 fields (`S`, `n`, member list, blob) compared one by one.
- `survivors_check(group)`: rebuild from the current members in a **shuffled** order and compare all
  4 fields, **and** check `S` against `fresh_sum` (plain NumPy, no `Group` code) and `n` against the
  member count.

`Index` (all 128 groups): `row_of` (dataset: ID → row), `labels` (row → group), `locator` (live ID →
group). `insert` = validate ID → not live → look up group → group insert. `delete` = locator → group
delete → drop from locator. `delete_user` = `delete` for each record of a cohort. `state_hash` =
SHA-256 of all 128 blob hashes.

## Decisions

| Decision | Why | Spec |
|---|---|---|
| Membership check **before** subtracting | A client retrying after a timeout would otherwise subtract twice | §5.4 |
| Remove the member, keep no marker | A marker is itself the leftover trace | §5.4 |
| Empty group stays (`S = 0, n = 0`) | Groups are never removed or merged | §5.1, §5.4 |
| Blob sorts members by ID bytes | Same members in any insert order → same bytes | §5.5 |
| Magic `SEVERC`, not `SEVERG` | This layout has no `C_S` / `r_agg`; it must not pass as the spec's blob | §5.5 |
| 4 of 5 fields | No commitments (`C_S`) until Part 3. Say it before you're asked | §5.5 |
| `fresh_sum` in the survivors check | Comparing `S` with a rebuild that uses the same `Group` code could hide a bug in that code (see SB-1) | DEMO_PLAN §6 trap |
| `delete(rid, row)` takes the row | Models the client presenting its record. A wrong row → `IntegrityViolation` | — |
| `fresh_sum` adds with `dtype=int64` | Exact, and never makes an `int64` copy of a 100,000-row group | §4.4 |

## Tests: spec-driven, not code-driven (rewritten 2 Oct)

**Rule:** a test's expected answer must come from the spec, never from the code under test.
[tests/spec_oracle.py](../../tests/spec_oracle.py) is a tiny independent model written from the spec
text: plain Python integers, no NumPy, nothing imported from `sever_demo`.

| Oracle function | Spec rule it encodes |
|---|---|
| `group_sum(members, d)` | §5.3: `S` = sum of the members' `x̃` |
| `group_blob(members, d)` | §5.5 layout (demo variant): bytes of a group holding exactly `members` |
| `nearest(x, centroids)` | §7.1: sequential float64 distance, ties to the smaller label |
| `field_diffs(group, members, d)` | §5.5: compare `S`, `n`, member list, blob **each on its own** |

Each test keeps its **own** list of which records should be live, asks the oracle what the group must
look like, and compares with what the code shows (`S`, `n`, member IDs, `blob()`). The code's helpers
(`compare`, `snapshot`, `survivors_check`) never judge the code; they get their own tests.

| Test | Proves | Spec |
|---|---|---|
| `group_initial_state` | New group: `S = 0` (as `int64`), `n = 0`, empty blob | §5.2, §4.4 |
| `blob_golden_bytes` | Blob for d = 2, two members, **written out byte by byte by hand** | §5.5 |
| T5 `insert_then_delete_restores_state` (+ from empty) | All 4 fields back to before, and equal to the oracle | §5.3 |
| T6 `delete_absent_is_idempotent` (+ never inserted) | `AlreadyAbsent`, nothing changes | §5.4 |
| T7 `duplicate_live_id_rejected` | Rejected, nothing changes | §3.2 rule 3 |
| T8 `survivors_check_after_random_deletes` | 20 random deletes → equals oracle group of the survivors | §5.3, §5.5 |
| T9 `blob_order_independent` | 100 insert orders → every blob equals the oracle's bytes | §5.5 |
| T10 `empty_group_persists` | Delete all → oracle's empty group; still usable | §5.4 |
| `blob_members_sorted_by_utf8_bytes` | IDs read back from the blob: `Z, a, ab, b, é` | §3.2 |
| `capacity_cap_is_one_million` | n = 1,000,000 allowed, the next insert refused (limit written in the test) | §5.6 |
| `errors_never_contain_the_record_id` | `DuplicateRecord`, `IntegrityViolation` messages | §17 |
| `compare_catches_each_field_on_its_own` | Corrupt one field at a time → only that field is flagged | §5.5 |
| `survivors_check_flags_a_corrupted_sum` | The demo's checker agrees with the oracle, and catches `S` off by 1 | §5.5 |
| T11 `delete_user_multi_group` | Touched groups = oracle survivors; others byte-identical | §3.5, E2E-1.4 |
| `insert_routes_to_nearest_centroid` | Every record is in its §7.1 group (oracle), each group exact | §7.1 |
| T12 `stress_random_ops` | 2,000 ops, oracle check of the touched group after **every** op | P1-T1 |

### Proof that the rewrite matters (2 Oct)

Three bugs were planted in `group.py` one at a time, then reverted (file hash checked):

| Planted bug | Old tests (reasoned, **not run**: they were replaced) | New tests (**run**) |
|---|---|---|
| `S` written little-endian in the blob | pass (every blob changes the same way) | **12 red** (golden bytes, oracle) |
| `compare()` always says "equal" | pass (T5–T8 used `compare`) | **red** (`compare_catches_each_field`) |
| Members sorted by row, not ID bytes | 1 red (the sort-order test); the rest pass | **12 red** |

### Sabotage (must-fail, `tests/test_sabotage.py`, 10 cases)

| Bug | One place in `group.py` | Turns red |
|---|---|---|
| SB-1 | Flip the low bit of `S[0]` on a group's first insert | T5 (from empty), T8, T11, T12 |
| SB-2 | Skip `n −= 1` | T5, T8, T11, T12 |
| SB-3 | Skip the membership check | T6 |

Each case switches the bug on, calls the named test, and **passes only if that test fails**. Full demo
run with `--sabotage SB-2` (50,000 rows): **FAIL, 140 mismatches** (smoke run, 2 Oct).

## Trap questions

**1. "Why does SB-1 flip the bit only on the *first* insert?"**
<details><summary>Answer</summary>
Flipping on every insert can cancel itself out: two flips of the same bit can land back on the true
value, so the bug would hide by chance. One flip per group is always wrong by exactly 1.
</details>

**2. "Why isn't comparing with a rebuilt group enough? Why also `fresh_sum` / the oracle?"**
<details><summary>Answer</summary>
The rebuilt group uses the same `Group.insert` code. If that code is broken (SB-1), the rebuild is broken
the same way and the two can still agree. `fresh_sum` (in the demo) and `spec_oracle.py` (in the tests)
use no `Group` code at all. A judge must not share code with the thing it judges.
</details>

**2b. "How do you know your oracle is right?"**
<details><summary>Answer</summary>
It's tiny (about 60 lines), written straight from the spec text, and it agrees with a blob written out
byte by byte by hand (`blob_golden_bytes`). If the code and the oracle disagree, one of them misreads
the spec, and the test makes you find out which.
</details>

**3. "What happens if you delete a record that was never inserted?"**
<details><summary>Answer</summary>
`AlreadyAbsent`, nothing changes. Same as deleting twice.
</details>

**4. "Is the member list really a separate check? It's inside the blob."**
<details><summary>Answer</summary>
Yes, on purpose. §5.5 compares each field on its own, although `S`, `n` and the members are also inside
the blob. If one comparison had a bug, the others would still catch the corruption.
</details>

**5. "What does SB-3 *not* show in the full demo, and why?"**
<details><summary>Answer</summary>
The index checks its locator first: a deleted ID isn't there, so the retry never reaches the group. SB-3
is caught at the group level (T6). The index's own retry test passes either way.
</details>

**6. "How big is the biggest group, and does that matter?"**
<details><summary>Answer</summary>
161,376 members (full run). Exactness doesn't care. Cost does: the blob and the survivors check grow with the
group, which is why the stress run does the cheap check every op and the full one every 50 ops.
</details>

## Open fixes

- No requirement IDs yet: `spec/requirements.yaml` doesn't exist, so tests cite § numbers in comments.
- `blob()` doesn't refuse `member_count ≠ n`; a parser would have to (§5.5). Only SB-2 can cause it.
