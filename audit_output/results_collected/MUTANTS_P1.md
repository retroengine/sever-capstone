# Part 1 mutation survivors (P1-T11)

P1-T11 (Build §4.8) asks for a mutation score of at least 85 % over `sever-quant`, `sever-index`
and `sever-search`, with **every surviving mutant triaged** here. The gate runner
(`gates p1-mutants`) fails if a survivor's text is missing from this file. Tests come from
`sever-quant`, `sever-index`, `sever-search` and `sever-p1`.

Exploratory runs on 6 Oct 2026 (not gate runs; the gate run is in the ledger):

| Run | Tests | Survivors | Score |
|---|---|---|---|
| Wide, commit e5c0cc2 | as committed | 62 | 285 / 347 = 82.1 % |
| Wide, e5c0cc2 + mutant-targeting tests | + 8 tests (index, search) | 28 | 319 / 347 = 91.9 % |
| Targeted, + 3 more tests | `k` counter, `QVec::dim`, INV-5 on N = 42,000 | 22 (expected) | ≈ 325 / 347 = 93.7 % |

The tests added for this triage:
`p1_index_spillover_nearest_and_tie_in_both_orders`, `p1_index_hard_cap_boundary_by_plan`,
`p1_index_mirror_rows_follow_their_records`, `p1_index_apply_ignores_moves_at_the_slot_count`,
`p1_index_inv4_boundary_is_inclusive`, `p1_index_debug_output_is_redacted`,
`p1_index_change_set_counters_match_the_applied_state`, `p1_index_inv5_holds_on_a_larger_index`
and `p1_search_reduction_uses_every_lane`.

## Categories

- **Sabotage-only.** The mutated operand sits behind `cfg!(feature = "sabotage-SB-N")`, which is
  `false` in the real build, so short-circuit evaluation never reaches it. The code is checked by
  P1-T8: each sabotage build must turn a test red (Build §2.6).
- **Equivalent.** No input changes the result.
- **Unreachable.** The mutated branch guards a state that no Part 1 operation can produce, even from a
  forged change set; it is defence in depth. Each entry says when it becomes reachable.
- **Host-equivalent.** Equivalent on the test machine (it has AVX2); it can only differ on a CPU
  without AVX2.

## Survivors

### `sever-index`

1. `crates/sever-index/src/changeset.rs:197:13: replace && with || in ChangeSet<E>::is_noop`.
   **Equivalent.** It changes the result only when `slots` is non-empty and `locator` is empty, or
   the reverse. Every plan writes slot operations and locator operations together: an insert writes
   `Put` + locator `Put`, a deletion writes `MoveLast`/`Truncate` + locator `Delete`, and a flush
   writes `DrainInto` + locator `Put`. The neighbouring `&&` (196:13) is killed by the holding-insert
   case of the `is_noop` test.
2. `crates/sever-index/src/index.rs:271:76: replace < with <= in Index<E, S>::route`.
   **Equivalent.** `dist == bd && g.id <= b.id` differs from `<` only when `g.id == b.id`, and
   group IDs are unique (§7.5, the spawn-ID collision check). The tie order itself is killed in both
   directions by `p1_index_spillover_nearest_and_tie_in_both_orders`.
3. `crates/sever-index/src/index.rs:364:67: replace > with == in Index<E, S>::apply`.
   **Sabotage-only** (SB-1).
4. `crates/sever-index/src/index.rs:364:67: replace > with < in Index<E, S>::apply`.
   **Sabotage-only** (SB-1).
5. `crates/sever-index/src/index.rs:364:67: replace > with >= in Index<E, S>::apply`.
   **Sabotage-only** (SB-1).
6. `crates/sever-index/src/index.rs:366:28: replace ^= with |= in Index<E, S>::apply`.
   **Sabotage-only** (SB-1, inside the guarded block).
7. `crates/sever-index/src/index.rs:366:28: replace ^= with &= in Index<E, S>::apply`.
   **Sabotage-only** (SB-1, inside the guarded block).
8. `crates/sever-index/src/index.rs:391:55: replace && with || in Index<E, S>::apply`.
   **Unreachable.** This is the per-component bounds check of a mirror-row swap in `MoveLast`. The
   outer check has already established `from, to < mirror_ids.len()`, and `apply` keeps
   `mirror.len() == mirror_ids.len() · d`, so both `a` and `b` are always in bounds and the inner
   check is always true. Becomes reachable only if the mirror-length invariant (INV-9) breaks, which
   `check_invariants` reports.
9. `crates/sever-index/src/index.rs:391:38: replace < with <= in Index<E, S>::apply`.
   **Unreachable**, as 8.
10. `crates/sever-index/src/index.rs:391:60: replace < with <= in Index<E, S>::apply`.
    **Unreachable**, as 8. (The outer `<` checks on lines 384 and 387 are killed by
    `p1_index_apply_ignores_moves_at_the_slot_count`.)
11. `crates/sever-index/src/index.rs:578:17: replace && with || in Index<E, S>::check_invariants`.
    **Unreachable.** INV-9 compares three things: the length of `mirror_ids`, the IDs pairwise, and
    the length of `mirror`. `apply` is the only writer of `slots`, `mirror_ids` and `mirror`, and
    every slot operation (`Put`, `MoveLast`, `Truncate`, `DrainInto`) changes all three together,
    including on a forged change set. So the three conditions are never split: once the length of
    `mirror` is right, the length of `mirror_ids` is right too. The whole check is still killed: the
    SB-5 sabotage build (mirror rows kept after a deletion) makes it fire.
12. `crates/sever-index/src/index.rs:582:17: replace && with || in Index<E, S>::check_invariants`.
    **Unreachable**, as 11. Equal lengths with different IDs would need a slot operation that moves an
    ID without its row, and there is none.
13. `crates/sever-index/src/index.rs:594:13: replace > with == in Index<E, S>::check_invariants`.
    **Unreachable in Part 1 sizes.** For INV-5's bound `⌊1.5·N/k⌋` to reach 10^6, the average group
    must hold more than 666,666 records, so N > 2.6 M with the smallest partition (k = 4). Part 1's
    largest run is nq-100k. Building such an index in a test costs minutes and gigabytes. The
    mutants that can fire falsely on a moderate index (`/`→`*` at 593:41 and `*`→`/` at 593:15) are
    killed by `p1_index_inv5_holds_on_a_larger_index`.
14. `crates/sever-index/src/index.rs:594:13: replace > with >= in Index<E, S>::check_invariants`.
    **Unreachable in Part 1 sizes**, as 13.
15. `crates/sever-index/src/index.rs:593:41: replace / with % in Index<E, S>::check_invariants`.
    **Unreachable in Part 1 sizes.** `(3N) mod (2k)` is below `2k`, so it exceeds 10^6 only when
    k > 500,000 groups; DB-63 caps frozen groups at 10,000.
16. `crates/sever-index/src/index.rs:593:15: replace * with + in Index<E, S>::check_invariants`.
    **Unreachable in Part 1 sizes.** `(3 + N)/(2k)` is weaker than the real bound, so it can only
    miss a violation, and that needs N > 2.6 M (see 13).
17. `crates/sever-index/src/index.rs:593:46: replace * with + in Index<E, S>::check_invariants`.
    **Unreachable in Part 1 sizes.** `3N/(2 + k)` is weaker than the real bound for k ≥ 2, as 16.
18. `crates/sever-index/src/index.rs:731:35: replace + with * in Draft<'a, E, S>::put`.
    **Unreachable in Part 1.** The draft records the group's new length as `index` instead of
    `index + 1`. Only a second `put` into the same group in the same plan reads that length, and no
    Part 1 plan does that: an insert puts once, a flush puts once into the holding area and then
    drains it, and a deletion never puts. It becomes reachable in Part 2 when a transaction carries
    several inserts (§15.1). **Part 2 must add a test for two inserts into one group in one change
    set.**

### `sever-search`

19. `crates/sever-search/src/lib.rs:69:57: delete ! in search`.
    **Sabotage-only** (SB-6: `!cfg!(…SB-6) || !g.ids.is_empty()`; the left side is `true` in the
    real build).
20. `crates/sever-search/src/kernel.rs:40:5: replace uses_avx2 -> bool with true`.
    **Host-equivalent.** The test machine has AVX2, so `true` is the real answer. On a CPU without
    AVX2 it would execute AVX2 instructions. The kernel choice itself is checked by P1-T4: scalar and
    AVX2 must agree bit for bit (508 M pairs on nq-10k, 0 mismatches).
21. `crates/sever-search/src/kernel.rs:66:9: replace avx2::available -> bool with true`.
    **Host-equivalent**, as 20.
22. `crates/sever-search/src/kernel.rs:67:58: replace && with || in avx2::available`.
    **Sabotage-only** (SB-9: the line runs only in the sabotage build).

## Follow-ups

- Part 2: a test that puts two records into one group in one change set (survivor 18).
- Part 4 or a CI runner without AVX2: run the search suite there once (survivors 20, 21).
