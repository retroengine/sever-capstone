# `quant.py`: Q24 quantiser (§4.2) and dequantiser (§4.3)

> **Location (4 Oct 2026):** this demo now lives in `demo/` and runs on its own (`demo/README.md`). Paths below are relative to `demo/`; the spec, `CLAUDE.md`, `docs/PROGRESS.md` and `datasets/` are at the repository root (`../`).

File: [python/sever_demo/quant.py](../../python/sever_demo/quant.py). Tests: [tests/test_quant.py](../../tests/test_quant.py).

## One line

Turn each float32 number into an exact integer (`x × 2^24`, rounded half to even, stored as `i32`), so
group sums can be added and subtracted without any rounding error.

## Why

Float sums depend on the order you add in, so "subtract one record" ≠ "rebuild without it".
Integers don't have this problem.

Measured on the first 1,000 NQ vectors: subtract one record from the total vs re-add the other 999
from scratch.

| Record removed | float32: numbers that differ (of 384) | int64: numbers that differ |
|---|---|---|
| row 0 | **286** | **0** |
| row 500 | 292 | 0 |
| row 999 (the last one added) | 10 | 0 |

## How it works

`quantise(x)`:
1. Convert to float64 and multiply by `2^24` (both steps exact).
2. Refuse NaN / ±inf (`ValueError`), **before** casting.
3. `np.rint`: round to nearest, ties to even. This is the **only** rounding step.
4. Refuse anything with `|value| > 2^24 + 16` (`ValueError`).
5. Cast to `int32`.

`dequantise(q)` = `q / 2^24` in float64. Exact; no rounding at all.

Constants: `SCALE = 2**24`, `BOUND = 2**24 + 16 = 16,777,232`.

## Key facts

- **Where the bound comes from:** no number can be bigger than its row's length, which is at most
  `1 + 8·2^-23`. Times `2^24` that is `2^24 + 16`.
- **Ties to even:** `0.5 → 0`, `1.5 → 2`, `2.5 → 2`, `−0.5 → 0`. Ties go up half the time and down half
  the time, so sums don't drift. Example: `0.5 + 1.5 + 2.5 + 3.5 = 8`; half-up gives `1+2+3+4 = 10`;
  half-even gives `0+2+2+4 = 8`.
- **Types:** `i32` for each stored vector, `i64` for group sums, float64 only as a temporary.
  - `i32` fits: `2^24 + 16 < 2^31`. It halves memory (1M rows = 1.5 GB instead of 3 GB).
  - Sums need `i64`: `10^6 × 16,777,232 ≈ 1.68 × 10^13 < 2^44`, far past `i32`'s 2.1 × 10^9, with
    19 bits to spare in `i64` (§4.4).
- **Why not store float32:** above `2^24` it can't hold every integer (16,777,217 becomes 16,777,216).
- **Check, don't fix:** the norm check (§4.1) is what guarantees the bound. The bound check here is a
  second line of defence.

## Decisions

| Decision | Why | Spec |
|---|---|---|
| Scale in float64 | float32 → float64 and × power of two are both exact, so `rint` is obviously the only rounding | §4.2 |
| `np.isfinite` check before the cast | `NaN.astype(int32)` gives a meaningless number with only a warning | §4.1 |
| `np.rint` (ties to even) | Unbiased; and client and engine must use the *same* rule (in Part 3 the client builds its commitment from `x̃`) | §4.2 |
| Refuse beyond the bound, never wrap | Out-of-range values silently become `−2147483648` | §4.2 |
| `max(initial=0)` | An empty array passes instead of crashing | — |
| Error text never contains values | Errors must not leak data | §17 |
| `ValueError`, not a typed `NotNormalised` | Demo shortcut; say so if asked | §17 |

## Measured results (re-run 2 Oct 2026)

On all of `sciq_reference/embeddings.npy` (5,252,736 numbers), NumPy 2.5.3:

| Fact | Value |
|---|---|
| Numbers that are an exact tie (`.5`) after × 2^24 | **5.83%** |
| Numbers already whole after × 2^24 | 5.83% |
| Largest quantisation error | 2.98e-8 = exactly `2^-25` (half a step) |
| Largest `|x|` | 0.297 |
| Median `|x|` | 0.034 |
| float32 vs float64 scaling, then `rint` | **0** differences out of 5,252,736 |
| `[2^31, 2^31+5, 2^32+7].astype(int32)` | all `−2147483648`, only a `RuntimeWarning` |

## Tests (`tests/test_quant.py`, 7 items)

| Test | Proves |
|---|---|
| `test_quant_ties_to_even` | `0.5, 1.5, 2.5, −0.5` (× `2^-24`) → `0, 2, 2, 0`; output is `int32` |
| `test_quant_bound_at_tolerance_edge` | Longest legal row `1 + 8·2^-23` lands **exactly** on `2^24 + 16` and is accepted |
| `test_quant_rejects_beyond_bound` | One float32 step further (`1 + 9·2^-23`) raises |
| `test_quant_rejects_non_finite` ×3 | NaN, +inf, −inf raise |
| `test_dequantise_round_trip_error` | Converting back loses at most `2^-25` |

- `−0.5 → 0` catches "round half away from zero"; `0.5 → 0` catches `floor(x + 0.5)`.
- **Sabotage done:** with `floor(x + 0.5)` the ties test went red (`[[1, 2, 3, 0]]`), and green again
  after reverting. Also red: no bound check, `<` instead of `<=`, `int64` output, wrong scale.
- The NaN test exists because a NaN slipped through the bound check in the first draft.

## Trap questions

**1. "With round-half-up, would deletion still be exact?"**
<details><summary>Answer</summary>
**Yes.** Exactness comes from integer add/subtract: you subtract the same integer you added. The rounding
rule affects accuracy (half-up pushes sums upward) and agreement (client and engine must match).
</details>

**2. "Why did removing row 999 differ in only 10 numbers, but row 0 in 286?"**
<details><summary>Answer</summary>
Row 999 was added last, so "rebuild without it" repeats exactly the same 999 additions. Only the final
add-then-subtract differs. Removing row 0 changes the order of every later addition, so the rounding
differs almost everywhere. Either way float32 is not exact; integers give 0 in every case.
</details>

**3. "float32 has 24 bits and your numbers reach `2^24 + 16`. Doesn't float32 scaling break?"**
<details><summary>Answer</summary>
No (0 differences in 5.25M numbers). Precision is *relative*. × `2^24` only changes the exponent. Near
1.0 the float32 spacing is `2^-23`, which scales to 2, so top values are even integers like `2^24 + 16`,
which float32 stores exactly. We use float64 because the spec says so and it makes "one rounding" obvious.
</details>

**4. "What's inside a float32?"**
<details><summary>Answer</summary>
1 sign bit, 8 exponent bits, 23 stored fraction bits + 1 hidden bit = 24 significant bits. It is **not**
a whole part plus a decimal part.
</details>

**5. "Does `quantise` reject a row that isn't normalised?"**
<details><summary>Answer</summary>
**Not in general.** 384 numbers each equal to 0.1 give length ≈ 1.96, but every number is small, so
`quantise` accepts it. The norm check must run **before** `quantise` on every insert.
</details>

**6. "If the norm check always runs first, why keep the bound check?"**
<details><summary>Answer</summary>
Other code may call `quantise` directly (tests, later modules, a mistake). Without the check, a bad value
silently becomes `−2147483648`. The check costs one `max`.
</details>

**7. "Do ties really happen, or is ties-to-even theoretical?"**
<details><summary>Answer</summary>
5.83% of SciQ numbers are exact ties. Whether a number lands on `.5` depends on its size. For
`0.25 ≤ |x| < 0.5` the scaled spacing is 0.5, so half are ties. For `|x|` around 0.03 (the median) the
scaled spacing is 1/16, so about 1 in 16 are ties, about 6%.
</details>

**8. "How much precision does Q24 lose?"**
<details><summary>Answer</summary>
At most `2^-25` ≈ 3e-8 per number, and the data hits exactly that. For a median-sized number (0.034)
that's about 1e-6 relative. The effect on search quality is a separate measure (P1-T7), not run yet.
</details>

**9. "What if someone passes float64 instead of float32?"**
<details><summary>Answer</summary>
`quantise` accepts it and rounds once. A client that first stored it as float32 rounds twice and could
get a different `x̃`. The spec's input is float32 (§4.1); the demo doesn't check the dtype. Known shortcut.
</details>

**10. "Why Q24 and not Q31?"**
<details><summary>Answer</summary>
`(1 + 8·2^-23) · 2^31 > 2^31`, so the largest value wouldn't fit in `i32`. Q24 matches float32's 24 bits
near 1.0 and leaves 7 bits of room in `i32`.
</details>

**11. "How do you know your tests catch bugs?"**
<details><summary>Answer</summary>
Sabotage: broke the rounding on purpose, the ties test went red, reverted, green. A test that has never
failed proves nothing (Overview §9.2).
</details>

## Open fixes

Done on 3 Oct 2026 (by Claude): `pytest.raises` now checks the message (`match=`), new tests
`test_quant_negative_ties_to_even` (−1.5 → −2, −2.5 → −2, −3.5 → −4) and `test_quant_keeps_shape`,
fixture seed 0 → 42, `X`/`Q` renamed to `x`/`q`, formatting. Now 9 tests.

| Still open | Fix |
|---|---|
| No dtype check (float64 accepted) | Demo shortcut (trap 9) |
| `ValueError` instead of the spec's typed `NonFinite` / `NotNormalised` | Demo shortcut (§17) |
