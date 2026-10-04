# `ids.py` and `errors.py`: record ID rules (§3.2) and typed errors (§17)

> **Location (4 Oct 2026):** this demo now lives in `demo/` and runs on its own (`demo/README.md`). Paths below are relative to `demo/`; the spec, `CLAUDE.md`, `docs/PROGRESS.md` and `datasets/` are at the repository root (`../`).

Files: [python/sever_demo/ids.py](../../python/sever_demo/ids.py),
[python/sever_demo/errors.py](../../python/sever_demo/errors.py). Tests:
[tests/test_ids.py](../../tests/test_ids.py). Written by Claude (write mode, 2 Oct).

## One line

Before a record goes in, check its ID: 1 to 256 **bytes** of UTF-8, and not a bare number like `007`.

## Why

- Rule 2 exists because group contents must not depend on arrival order. A counter ID (`1`, `2`, `3`…)
  would leak the arrival order into the canonical blob, which sorts by ID. The spec can't detect a
  counter from one value, so it bans the *shape* of a counter (§3.2 "why rule 2 exists").
- Rule 3 (not already live) needs the index, so `index.py` checks it, not `ids.py`.

## How it works: `validate_record_id(rid)`

1. Encode to UTF-8. A lone surrogate (`"\ud800"`) can't be encoded → `InvalidRecordId`.
2. Byte length must be 1..256 (rule 1).
3. `re.fullmatch(r"[+-]?[0-9]+", rid)` matches → `InvalidRecordId` (rule 2).

The errors in `errors.py` are the spec's names (§17): `InvalidRecordId`, `DuplicateRecord`,
`NotNormalised`, `GroupCapacityExceeded`, `IntegrityViolation`. Each is a `ValueError`. **No message
contains an ID or a vector value.** `Outcome.DELETED` / `Outcome.ALREADY_ABSENT` is a *result*, not an
error (§5.4).

## Decisions

| Decision | Why | Spec |
|---|---|---|
| Count bytes, not characters | `"€" × 100` is 100 characters but 300 bytes; the limit is about storage | §3.2 rule 1 |
| `[0-9]`, not `\d` | `\d` also matches other scripts' digits (Arabic-Indic `١٢`), which the spec pattern does not | §3.2 rule 2 |
| `fullmatch`, not `match` / `^…$` | `match` only checks the start (`"12abc"` would match `[0-9]+`). `$` matches before a final `"\n"`, so `^[0-9]+$` matches `"12\n"` | CLAUDE.md §7 |
| Spec names, no `Error` suffix | The names are normative; ruff's N818 is switched off for that one file, with the reason | §17 |
| `from None` on the re-raise | Hides the `UnicodeEncodeError`, whose text would show the bad character | §17 |

## Measured

All 1,000,000 NQ IDs: **0 rejected**, 1,000,000 unique (full run, 2 Oct 20:21 UTC). IDs look like `doc0`, `doc6`.

## Tests (`tests/test_ids.py`, 18 items)

| Valid | Invalid |
|---|---|
| `doc0`, `nq-1234`, a UUID, 256 × `a`, 85 × `€` (255 bytes), `"12\n"`, `١٢`, `1.5`, `0x1F` | `1`, `007`, `-3`, `+3`, `""`, 257 × `a`, 100 × `€` (300 bytes), `"\ud800"` |

Plus: the error text for `"4815162342"` does not contain `4815162342`.

## Trap questions

**1. "Why is `1.5` a valid ID but `15` isn't?"**
<details><summary>Answer</summary>
The rule bans only the shape of a counter: optional sign, then digits, nothing else. `1.5` has a dot, so
it can't be an insertion counter. The rule is a heuristic, not a proof (§3.2 says so).
</details>

**2. "Would `re.match(r"[+-]?[0-9]+", "12abc")` reject `12abc`?"**
<details><summary>Answer</summary>
Yes, wrongly: `match` only needs the *start* to match. `fullmatch` needs the whole string, so `12abc` is
accepted, as it should be.
</details>

**3. "Can the same ID be inserted twice?"**
<details><summary>Answer</summary>
Not while it's live (`DuplicateRecord`, rule 3). After it's deleted, yes: that is a new insert (§3.2).
</details>

**4. "Why must an error never contain the ID?"**
<details><summary>Answer</summary>
Error messages end up in logs. If a person asks for their data to be deleted, a log line holding their
record ID would be a leftover trace, the exact thing this project removes (§17).
</details>

## Open fixes

- `quant.py` still raises plain `ValueError`, not `NonFinite` / `NotNormalised` (Day 1 shortcut).
