# SEVER-DB: a guided walk through everything not yet committed

> **Location (4 Oct 2026):** this demo now lives in `demo/` and runs on its own (`demo/README.md`). Paths below are relative to `demo/`; the spec, `CLAUDE.md`, `docs/PROGRESS.md` and `datasets/` are at the repository root (`../`).

Snapshot: **3 Oct 2026**, branch `docs/service-side-custody`, last commit `8a8f7fb`. This guide covers
every file that `git status` lists, in **dependency order**: each file is explained only after
everything it needs. Every number here came from running code. When this guide was written, the tests
were re-run: **218 passed** (84.7 s), of which **36 must-fail tests passed** (`scripts/demo.sh test`,
`… -m mustfail`).

How to read it:

1. Read chapters 0–2 once (the map).
2. Read chapter 3 (Python), then chapters 4–5 (maths and crypto) slowly. Every later chapter leans on them.
3. Then read the file chapters in order. Each one has the same parts: **Job** · **Needs** · **Spec** ·
   **Picture** · **Line by line** · **Example** · **Guarded by** (the tests that would catch a bug).

Links like [group.py:91](../python/sever_demo/group.py#L91) open the file at that line.

---

## Contents

- [0. What `git status` is telling you](#0-what-git-status-is-telling-you)
- [1. The big picture](#1-the-big-picture)
- [2. The dependency map (topological order)](#2-the-dependency-map-topological-order)
- [3. Python, only what this code uses](#3-python-only-what-this-code-uses)
- [4. Maths toolbox](#4-maths-toolbox)
- [5. Crypto toolbox](#5-crypto-toolbox)
- [6. Layer 0: the plan, the rules, the config](#6-layer-0-the-plan-the-rules-the-config)
- [7. `data.py`](#7-datapy-load-and-check-the-data)
- [8. `quant.py`](#8-quantpy-floats-to-exact-integers)
- [9. `partition.py`](#9-partitionpy-128-fixed-groups-and-routing)
- [10. `errors.py`](#10-errorspy-named-errors-and-the-delete-outcome)
- [11. `ids.py`](#11-idspy-record-id-rules)
- [12. `crypto.py`](#12-cryptopy-the-crypto-building-blocks)
- [13. `group.py`](#13-grouppy-the-heart-exact-deletion)
- [14. `posk.py`](#14-poskpy-the-proof-of-knowledge)
- [15. `cert.py`](#15-certpy-the-signed-deletion-certificate)
- [16. `index.py`](#16-indexpy-128-groups-working-together)
- [17. `baselines.py`](#17-baselinespy-the-ghost)
- [18. `ledger.py`](#18-ledgerpy-the-run-record)
- [19. The independent verifier `sever_verify/`](#19-the-independent-verifier-sever_verify)
- [20. `receipts.py`](#20-receiptspy-certificates-to-disk-and-to-the-verifier)
- [21. `demo.py`](#21-demopy-the-full-acceptance-run)
- [22. `repl.py`](#22-replpy-the-live-demo-shell)
- [23. The tests](#23-the-tests)
- [24. The scripts](#24-the-scripts)
- [25. The results](#25-the-results)
- [26. The writing about the code](#26-the-writing-about-the-code)
- [27. Things that don't quite match (yet)](#27-things-that-dont-quite-match-yet)

---

## 0. What `git status` is telling you

Git keeps three copies of each file: the last **commit**, the **staging area** (the "next commit"
box) and your **working folder**. `git status --porcelain` prints two letters per file:

```
 column 1 = staging area vs last commit
 │column 2 = working folder vs staging area
 ││
 M  CLAUDE.md          staged: the change is in the "next commit" box
  M pyproject.toml     changed, not staged yet
 MM docs/DEMO_PLAN.md  part staged, then changed again
  D docs/notes/...     deleted, not staged yet
 ?? README.md          untracked: git has never seen this file
```

Your 88 entries:

| Kind | Count | Files | Chapter |
|---|---|---|---|
| Staged (`M `) | 7 | `CLAUDE.md`, the spec, the overview, both build plans, `TEAM_HANDBOOK.md`, part of `DEMO_PLAN.md` | 6 |
| Modified, unstaged (` M`) | 7 | `.gitignore`, `pyproject.toml`, `PROGRESS.md`, `data.py`, `quant.py`, `test_data.py`, `test_quant.py` | 6, 7, 8, 23, 26 |
| Deleted (` D`) | 2 | `docs/notes/P1-data-facts.md`, `docs/notes/project-demo-notes.md` | 26 |
| New (`??`) | 72 | 13 engine modules, 4 verifier files, 16 test files, 3 test-vector files, 3 scripts, 6 result files, 14 screenshots, 12 docs | 7–26 |

Not in the list, on purpose: `results/certs/` (ignored by `.gitignore`, chapter 6), `~/.cache/sever/`
(outside the repo), `.venv/` and `~/.venvs/sever-demo/` (environments).

---

## 1. The big picture

**The one claim (Part 1):** deleting a vector returns its group, bit for bit, to the state it would
have had if the vector had never arrived. **The Part 3 preview on top:** every deletion produces a
signed receipt that a separate program checks with no access to the database.

```
  datasets/processed/nq_1m           datasets/processed/sciq_reference
  1,000,000 × 384 float32            13,679 × 384 float32 (public, no user data)
            │                                     │
            ▼                                     ▼
  data.py   manifest + norm check (§4.1)     partition.py  k-means → 128 fixed centres (§6.2)
            │                                     │
            ▼                                     │
  quant.py  x̃ = round(x · 2^24) as int32 (§4.2)  │
            │                                     ▼
            ├───────────────────────────►  partition.route: nearest centre for each row (§7.1)
            ▼                                     │
  ids.py    record-ID rules (§3.2)                │
            │                                     ▼
            └──────────────────────►  index.py  ── 128 × group.py
                                         each group keeps:  S (exact integer sum, int64)
                                                            n (count), members (who is in)
                                                            r_agg, C_S (Part 3 preview)
                                         insert:  S += x̃   n += 1   C_S += C_t
                                         delete:  S −= x̃   n −= 1   C_S −= C_t
                                                     │
                                                     ▼
                                 posk.py (proof) + cert.py (Ed25519-signed receipt)
                                                     │  written as files: results/certs/<run>/*.cert
                                                     ▼
                                 sever_verify  (separate process, shares no code)  →  ACCEPTED / REJECTED
```

How do we know a deletion was exact? The **survivors check**: build a brand-new group from only the
records still in it, in a shuffled order, and compare it field by field with the live group. If all
fields are equal, the deleted record left no trace in the group.

---

## 2. The dependency map (topological order)

"B needs A" means B imports A (or runs it). A **topological order** lists files so that everything a
file needs comes before it. This guide follows that order.

```
LAYER 0  plan & rules     DEMO_PLAN.md   spec/overview/build plans (DB-55)   pyproject.toml   .gitignore
            │
LAYER 1  needs nothing    data.py   quant.py   errors.py   crypto.py   baselines.py   ledger.py
         from the project                                                            sever_verify/ristretto.py
            │                 │           │          │
LAYER 2                  partition.py   ids.py    group.py ◄─ crypto, errors        sever_verify/certificate.py
                          ◄─ quant      ◄─ errors posk.py  ◄─ crypto                  ◄─ ristretto
                                                  cert.py  ◄─ crypto                 sever_verify/__main__.py
                                                                                       ◄─ certificate
            │
LAYER 3                  index.py ◄─ group, ids, posk, cert, crypto, errors
                         receipts.py ◄─ runs sever_verify as a separate program (never imports it)
            │
LAYER 4                  demo.py ◄─ everything above
LAYER 5                  repl.py ◄─ demo.py + everything above
            │
LAYER 6  tests           synthetic.py ◄─ quant      spec_oracle.py ◄─ sever_verify.ristretto
                         vectors/*.json             test_*.py ◄─ the module they test (+ the two helpers)
LAYER 7  scripts         demo.sh (runs demo, repl, pytest)   clean_clone_check.sh   rehearsal.txt (drives repl)
LAYER 8  outputs         docs/RUN_LEDGER.jsonl   results/*.json   results/screens/*.svg
LAYER 9  writing         docs/notes/*.md   DEMO_RUNBOOK.md   README.md   PROGRESS.md
```

The same thing as a numbered list (a valid topological sort):

| # | File | Needs | Ch. |
|---|---|---|---|
| 1 | `docs/DEMO_PLAN.md` | — (the plan everything follows) | 6 |
| 2 | spec, overview, build plans, `CLAUDE.md`, `TEAM_HANDBOOK.md` (the DB-55 change) | — | 6 |
| 3 | `pyproject.toml`, `.gitignore` | — | 6 |
| 4 | `python/sever_demo/data.py` | — | 7 |
| 5 | `python/sever_demo/quant.py` | — | 8 |
| 6 | `python/sever_demo/partition.py` | 5 | 9 |
| 7 | `python/sever_demo/errors.py` | — | 10 |
| 8 | `python/sever_demo/ids.py` | 7 | 11 |
| 9 | `python/sever_demo/crypto.py` | — (system libsodium) | 12 |
| 10 | `python/sever_demo/group.py` | 7, 9 | 13 |
| 11 | `python/sever_demo/posk.py` | 9 | 14 |
| 12 | `python/sever_demo/cert.py` | 9 | 15 |
| 13 | `python/sever_demo/index.py` | 7, 8, 9, 10, 11, 12 | 16 |
| 14 | `python/sever_demo/baselines.py` | — | 17 |
| 15 | `python/sever_demo/ledger.py` | — | 18 |
| 16 | `python/sever_verify/ristretto.py` | — (system libsodium) | 19 |
| 17 | `python/sever_verify/certificate.py` | 16 | 19 |
| 18 | `python/sever_verify/__main__.py`, `__init__.py` | 17 | 19 |
| 19 | `python/sever_demo/receipts.py` | 18 (as a separate process) | 20 |
| 20 | `python/sever_demo/demo.py` | 4–15, 19 | 21 |
| 21 | `python/sever_demo/repl.py` | 20 and 4–15, 19 | 22 |
| 22 | `tests/synthetic.py`, `tests/spec_oracle.py`, `tests/vectors/*.json` | 5, 16 | 23 |
| 23 | `tests/test_*.py` (16 files) | their module + 22 | 23 |
| 24 | `scripts/demo.sh`, `clean_clone_check.sh`, `rehearsal.txt` | 20, 21, 23 | 24 |
| 25 | `docs/RUN_LEDGER.jsonl`, `results/*.json`, `results/screens/*.svg` | 24 (they are its outputs) | 25 |
| 26 | `docs/notes/*`, `DEMO_RUNBOOK.md`, `README.md`, `PROGRESS.md` | all of the above | 26 |

Two independence rules you will see enforced again and again:

```
  ENGINE  python/sever_demo   ──X──  never imports  ──X──  python/sever_verify  VERIFIER
  TESTS   tests/spec_oracle.py  takes no expected value from sever_demo (it is written from the spec)
```

A judge must not share code with the thing it judges. If they shared a bug, they would agree with each
other and both be wrong.

---

## 3. Python, only what this code uses

Python runs a file top to bottom. **Indentation** (4 spaces) marks what belongs inside a `def`, `if`,
`for` or `class`. `#` starts a comment. Text in `"""triple quotes"""` right under a `def` or `class` is
its **docstring** (its built-in description).

### 3.1 The language

| You see | It means | Where in this project |
|---|---|---|
| `import numpy as np` | load a library and call it `np` | [data.py:5](../python/sever_demo/data.py#L5) |
| `from sever_demo.errors import Outcome` | take one name out of another `.py` file (a **module**) | [group.py:20](../python/sever_demo/group.py#L20) |
| `SCALE = 2**24` | give a value a name. `**` is "to the power of". ALL_CAPS means "constant, don't change" | [quant.py:4](../python/sever_demo/quant.py#L4) |
| `1_000_000` | underscores only help you read: one million | [group.py:30](../python/sever_demo/group.py#L30) |
| `1 << 22` | shift bits left 22 places = 2^22 = 4,194,304 (4 MiB) | [data.py:69](../python/sever_demo/data.py#L69) |
| `a % b`, `a // b` | remainder, whole-number division: `17 % 5 = 2`, `17 // 5 = 3` | [crypto.py:46](../python/sever_demo/crypto.py#L46) |
| `x ^ y` | **XOR** (bit flip where bits differ). Not "power" | [group.py:108](../python/sever_demo/group.py#L108) |
| `def f(x: int) -> str:` | define a function. `: int` and `-> str` are **type hints**: notes for readers and for `mypy`, not checked while running | everywhere |
| `x: int \| None = None` | `x` is an int or nothing; if not given, it is `None` (nothing) | [data.py:77](../python/sever_demo/data.py#L77) |
| `"abc"`, `f"{n:,} rows"` | text. An **f-string** fills `{…}` from variables; `:,` adds thousands commas (`1,000,000`) | [demo.py:207](../python/sever_demo/demo.py#L207) |
| `b"SEVERG"`, `bytes(32)` | **bytes**: raw 8-bit values, not text. `bytes(32)` = 32 zero bytes | [crypto.py:19](../python/sever_demo/crypto.py#L19) |
| `[1, 2]` `(1, 2)` `{"a": 1}` `{1, 2}` | **list** (changeable), **tuple** (fixed), **dict** (key → value), **set** (no duplicates) | |
| `xs[2:5]`, `xs[-1]`, `xs[::-1]` | items 2, 3, 4 (end excluded); last item; reversed | [crypto.py:68](../python/sever_demo/crypto.py#L68) |
| `[f(v) for v in xs if ok(v)]` | build a list in one line (**comprehension**) | [posk.py:52](../python/sever_demo/posk.py#L52) |
| `for i, v in enumerate(xs):` | loop, getting position `i` and item `v` | [receipts.py:23](../python/sever_demo/receipts.py#L23) |
| `zip(a, b, strict=True)` | walk two lists side by side; `strict` = error if lengths differ | [crypto.py:105](../python/sever_demo/crypto.py#L105) |
| `sorted(xs, key=lambda c: c.encode("utf-8"))` | sort by a computed value; `lambda` is a tiny unnamed function | [demo.py:254](../python/sever_demo/demo.py#L254) |
| `while chunk := f.read(n):` | `:=` (**walrus**) stores and tests in one step: loop while reading returns something | [data.py:69](../python/sever_demo/data.py#L69) |
| `with open(p, "rb") as f:` | open a file, use it, and close it automatically, even on error. `"rb"` = read bytes, `"a"` = append | [data.py:68](../python/sever_demo/data.py#L68) |
| `try: … except E: … finally: …` | run; if error type `E` happens, handle it; `finally` runs no matter what | [demo.py:472](../python/sever_demo/demo.py#L472) |
| `raise X("msg") from None` | signal an error; `from None` hides the error that caused it | [ids.py:22](../python/sever_demo/ids.py#L22) |
| `assert cond` | stop with `AssertionError` if `cond` is false. Tests are built from these | tests |
| `class Group:` + `def __init__(self, …)` | a blueprint for objects. `__init__` runs when you write `Group(...)`. `self` is "this object" | [group.py:54](../python/sever_demo/group.py#L54) |
| `class InvalidRecordId(ValueError):` | a new kind of `ValueError` (**inheritance**: it is everything a `ValueError` is, plus a new name) | [errors.py:11](../python/sever_demo/errors.py#L11) |
| `@dataclass(frozen=True)` | a **decorator**: writes `__init__` for the listed fields; `frozen` = read-only afterwards | [group.py:41](../python/sever_demo/group.py#L41) |
| `@cache` | remember answers: a second call with the same input returns the stored result | [crypto.py:139](../python/sever_demo/crypto.py#L139) |
| `@property` | a method you read like a field: `report.accepted`, no `()` | [certificate.py:55](../python/sever_verify/certificate.py#L55) |
| `yield piece` | a **generator**: hands out pieces one at a time instead of building one big list | [group.py:155](../python/sever_demo/group.py#L155) |
| `class Outcome(Enum)` | a fixed set of named values | [errors.py:31](../python/sever_demo/errors.py#L31) |
| `{**d, "k": v}` / `f(*xs)` | copy dict `d` and add a key / spread a list into separate arguments | [receipts.py:33](../python/sever_demo/receipts.py#L33) |
| `if __name__ == "__main__":` | run this block only when the file is run directly, not when imported | [data.py:114](../python/sever_demo/data.py#L114) |
| `x is None`, `x is Outcome.DELETED` | "is the very same object"; used for `None` and enum values | [index.py:116](../python/sever_demo/index.py#L116) |

### 3.2 NumPy (fast arrays of numbers)

An **array** is a grid of numbers that all have one type (its **dtype**).

```
 x = np.load("embeddings.npy", mmap_mode="r")
 x.shape  → (1000000, 384)      1,000,000 rows (passages) × 384 columns (numbers)
 x.dtype  → float32

           column 0   column 1  …  column 383
 row 0   [ 0.0123,   -0.0412,   …,  0.0071 ]   ← one embedding, length 1
 row 1   [ …                               ]
   ⋮
 axis=1 means "along a row" (across its 384 columns); axis=0 means "down a column"
```

| dtype | Size | Holds | Used for |
|---|---|---|---|
| `float32` | 4 bytes | about 7 decimal digits | the stored embeddings |
| `float64` | 8 bytes | about 16 digits | temporary maths (norms, routing) |
| `int32` | 4 bytes | −2,147,483,648 … 2,147,483,647 | quantised vectors `x̃` |
| `int64` | 8 bytes | about ±9.2 × 10^18 | group sums `S` |
| `">i8"` | 8 bytes | int64 written **big-endian** | the canonical blob bytes |

| You see | It means |
|---|---|
| `a * a` | multiply every number by itself (element by element) |
| `a.astype(np.int64)` | a converted copy |
| `mask = off > TOL`, then `off[mask]` | a True/False array, then "keep only the True positions" |
| `~mask`, `m1 & m2`, `m1 \| m2` | not, and, or, element by element |
| `np.load(p, mmap_mode="r")` | don't read 1.5 GB at once: map the file and read pages when touched; `"r"` makes writing impossible |
| `np.random.default_rng(42)` | a random generator with a **seed**: the same "random" sequence on every run |
| `rng.permutation(n)` | the numbers 0 … n−1 in a shuffled order |
| `a[:, None]` | turn a flat list into a column so shapes line up (**broadcasting**) |
| `a @ b` | matrix product |

---
## 4. Maths toolbox

### 4.1 Why a float sum cannot be "un-added"

A float keeps only about 7 significant digits (float32), so almost every addition **rounds**. The
rounding depends on what was added before, so subtracting a value does not undo adding it.

Worked example (run in NumPy, float32):

```
 a = 0.1   b = 0.2   c = 0.3                      (all float32)

 total        = (a + b) + c        = 0.6
 total − b    = 0.40000004         ← "delete b" by subtracting
 a + c        = 0.4                ← "as if b never arrived"
 equal?       False                ← a ghost of b is left behind (0.00000004)

 Same numbers as Q24 integers (×2^24, rounded):
 a = 1,677,722   b = 3,355,443   c = 5,033,165
 (a + b + c) − b = 6,710,887
 a + c           = 6,710,887       ← equal, always, in any order
```

Integer addition never rounds (as long as nothing overflows), so `S − x̃` is **exactly** the sum
without `x̃`. That is the whole project in one line.

### 4.2 Q24: turning a float into an exact integer (spec §4.2)

```
 x̃ = round_half_to_even( x × 2^24 )      stored as int32          ("quantise")
 x̂ = x̃ / 2^24                            float64, exact            ("dequantise")
```

`2^24 = 16,777,216`. Multiplying by a power of two only changes a float's exponent, so it is exact;
the rounding is the **only** step that changes the value.

| x (float32) | x × 2^24 | x̃ (int32) | x̂ = x̃ / 2^24 | error |
|---|---|---|---|---|
| 0.012345599941909313 | 207,124.796875 | **207,125** | 0.012345612049102783 | 1.2e-8 |
| −0.25 | −4,194,304.0 | **−4,194,304** | −0.25 | 0 |
| 0.5 × 2^-24 | 0.5 | **0** (tie → even) | 0 | |
| 1.5 × 2^-24 | 1.5 | **2** (tie → even) | | |
| 2.5 × 2^-24 | 2.5 | **2** (tie → even) | | |

- **Error bound:** rounding moves a value by at most half a step: `|x̂ − x| ≤ 2^-25 ≈ 2.98 × 10^-8`.
- **Ties to even:** an exact `.5` goes to the even neighbour. Half of the ties go up and half go down,
  so sums don't drift upward. (`0.5 + 1.5 + 2.5 + 3.5 = 8`: half-up gives `1+2+3+4 = 10`, half-even
  gives `0+2+2+4 = 8`.)
- **Why it fits in int32:** a unit vector has every `|x_i| ≤ 1`. The norm check allows a length up to
  `1 + 8·2^-23`, so `|x̃_i| ≤ (1 + 8·2^-23)·2^24 = 2^24 + 16 = 16,777,232`, far below `2^31 − 1 ≈ 2.1 × 10^9`.
- **Why sums need int64:** a group may hold up to 10^6 members (§5.6):

```
 10^6 × 16,777,232 = 16,777,232,000,000  <  2^44 = 17,592,186,044,416  <  2^63 (int64 limit)
 int32 would overflow at 2,147,483,647: after only 128 maximal vectors.
```

### 4.3 Bytes: big-endian, little-endian, two's complement

A number becomes bytes in a fixed order. The spec (§0.2) fixes the order so that every machine
produces the same bytes, and therefore the same hash.

```
 int64 3, big-endian  (">q", ">i8"):   00 00 00 00 00 00 00 03   most significant byte first
 int64 −1, big-endian:                 ff ff ff ff ff ff ff ff   two's complement: −1 is "all ones"
 scalar 12, 32 bytes little-endian:    0c 00 00 … 00             least significant byte first
```

Rule of the spec: **integers big-endian; crypto scalars 32 bytes little-endian; points 32 bytes.**

`struct.pack` format codes used in this code: `>` big-endian, `B` u8 (1 byte), `H` u16 (2), `I` u32
(4), `Q` u64 (8), `q` i64 (8). Example: `struct.pack(">HHQ", 1, 2, 2)` = `00 01 | 00 02 | 00 00 00 00 00 00 00 02`.

### 4.4 Hashes: fingerprints of bytes

A **hash** (SHA-256: 32 bytes, SHA-512: 64 bytes) turns any bytes into a fixed-size fingerprint. Change
one bit of the input and about half the output bits change:

```
 SHA-256("abc") = ba7816bf8f01cfea414140de5dae2223…
 SHA-256("abd") = a52d159f262b2c6ddb724a61840befc3…     one letter changed → unrelated output
```

Nobody can find two inputs with the same SHA-256 in practice. So "same hash" is used as "same bytes".

Where hashes are used here:

| Use | Hash | Where |
|---|---|---|
| Data files unchanged since P0 | SHA-256 of each file vs `datasets/MANIFEST.sha256` | `data.check_manifest` |
| Group state fingerprint | SHA-256 of the canonical blob | `Group.blob_hash` |
| Whole-index fingerprint | SHA-256 of the 128 blob hashes | `Index.state_hash` |
| Run results unchanged | SHA-256 of the result file, stored in the ledger | `ledger.sha256_file` |
| Seeds | `sub_seed = first 8 bytes of SHA-256(u64be(seed) ‖ label)` | `partition.sub_seed` |
| Proof challenge | SHA-512, reduced mod ℓ | `posk.challenge` |

**Seeds from one seed (Overview §10.6).** One project seed (42) gives every random step its own,
independent seed:

```
 sub_seed(42, b"kmeans") = 6,253,519,680,516,510,792
 kmeans_seed(42)         = that mod 2^32 = 1,360,647,240     (scikit-learn wants < 2^32: gap G-1)
 other labels: b"stream" (insert order), b"cohort-order", b"check", b"ghost", b"stress", b"tamper", b"repl"
```

Seeds are used **only** for data order, test data and k-means, never for keys, `r_t` or nonces (those
come from the operating system).

### 4.5 Nearest centre (routing, spec §7.1)

Each group has a **centroid** μ (a centre point). A vector goes to the group whose centre is closest:

```
 distance²(x, μ) = Σ_i (x_i − μ_i)²                     the spec's way: one term at a time, in order
                 = ‖x‖² − 2·(x·μ) + ‖μ‖²                the demo's fast way: three matrix operations

 toy, 2-D:  x = (1, 0)   μ_0 = (0, 1)   μ_1 = (0.9, 0.1)
            d²(x, μ_0) = 1 + 1 = 2         d²(x, μ_1) = 0.01 + 0.01 = 0.02   → group 1
```

The two formulas are equal in exact maths, but floats round differently, so a near-tie could be decided
differently. Ties go to the smaller group number.

### 4.6 The float running mean (the baseline, "the ghost")

A common way to keep a group summary is a running **mean** (average) in float32:

```
 insert x:  n ← n + 1;   m ← m + (x − m) / n
 delete x:  m ← (m·n − x) / (n − 1);   n ← n − 1

 toy (float32): insert 0.1, 0.7, 0.2 → delete 0.7
   result after delete       = 0.14999998
   mean of 0.1 and 0.2 only  = 0.15          → not equal: the ghost of 0.7
```

The error is tiny, but it is not zero, and that's the point: nobody can prove from a float summary that
a record left no trace.

---

## 5. Crypto toolbox

### 5.1 Clock arithmetic (mod)

`a mod p` is the remainder after dividing by `p`. Numbers wrap around like a clock:
`(95 + 10) mod 101 = 4`. All crypto here works "mod" a big number.

### 5.2 The group ristretto255

Think of a **group** as a set of "points" with three operations:

```
 P + Q          add two points (easy)
 P − Q          subtract (easy)
 k·P            P + P + … + P, k times (easy, even for huge k, by doubling)
 given P, k·P → find k        ← INFEASIBLE (the "discrete logarithm" problem)
```

ristretto255 is such a group, built on Curve25519. Facts the code relies on:

| Fact | Value / meaning |
|---|---|
| Every point is 32 bytes | one **canonical** encoding per point; other 32-byte strings are rejected (§9.9) |
| The **identity** (the "zero" point) | 32 zero bytes: `P + identity = P` |
| The group order **ℓ** | `2^252 + 27742317777372353535851937790883648493` ≈ 7.24 × 10^75. `ℓ·P = identity` for every P |
| **Scalars** | the k in k·P. Because `ℓ·P = identity`, only `k mod ℓ` matters, so scalars live in `0 … ℓ−1` |
| `0·P` | the identity. (libsodium refuses `0·P`, so the code returns the identity itself, CLAUDE.md §7) |

**Negative numbers as scalars (§4.5).** `S_i` can be negative. `−1` becomes `ℓ − 1`, because
`(ℓ − 1)·G = ℓ·G − G = −G`. In general `scalar(v) = v mod ℓ` for `v ≥ 0`, else `ℓ − (|v| mod ℓ)`.

**Wide reduction.** A random scalar is made from **64** random bytes (512 bits) reduced mod ℓ. Using
twice as many bits as ℓ makes every scalar almost exactly equally likely.

### 5.3 Generators nobody has a secret about (§9.2)

A commitment needs public points `H, G_0, …, G_383` such that **nobody knows** any relation between
them (like "H = 5·G_0"). The trick: make each one from a hash of a public label:

```
 H   = from_uniform_bytes( expand_message_xmd_sha512( b"H",               DST_GEN, 64 ) )
 G_i = from_uniform_bytes( expand_message_xmd_sha512( b"G" ‖ u32be(i),    DST_GEN, 64 ) )
 DST_GEN = b"PROJECT_SEVER_V1_RISTRETTO255_SHA512_NUMS"     ("nothing up my sleeve")
```

`expand_message_xmd` (RFC 9380) stretches a message into uniform random-looking bytes with SHA-512:

```
 b_0 = SHA512( 128 zero bytes ‖ msg ‖ u16be(len) ‖ 0x00 ‖ DST ‖ len(DST) )
 b_1 = SHA512( b_0 ‖ 0x01 ‖ DST ‖ len(DST) )
 b_i = SHA512( (b_0 XOR b_{i−1}) ‖ i ‖ DST ‖ len(DST) )      for more output
 output = first `len` bytes of b_1 ‖ b_2 ‖ …                   (for 64 bytes: just b_1)
```

`from_uniform_bytes` (RFC 9496) maps 64 bytes to a point. Nobody chose the points, so nobody knows their
relations. A **DST** (domain separation tag) is a fixed label at the start of a hash input, so that a hash
made for one purpose can never be confused with a hash made for another (§2.3).

### 5.4 The Pedersen commitment: a sealed, addable envelope

```
 C = r·H + x·G            x = the value,   r = a random secret ("blinding"),   G, H = public points
```

| Property | Plain words | Why |
|---|---|---|
| **Hiding** | `C` tells you nothing about `x` | for every guess of `x` there is some `r` giving the same `C`, and `r` is random |
| **Binding** | you can't open `C` later as a different `x` | that would reveal the secret relation between H and G (a discrete log) |
| **Additive** | `C(x₁, r₁) + C(x₂, r₂) = C(x₁ + x₂, r₁ + r₂)` | the points just add |

**Toy, mod 101, with G = 7 and H = 13.** "Points" are numbers mod 101, and `k·P` is ordinary
multiplication mod 101. This is insecure: you'll see below how it breaks. It only shows the arithmetic:

| | x | r | C = 7x + 13r mod 101 |
|---|---|---|---|
| record a | 5 | 20 | **93** |
| record b | 9 | 33 | **88** |
| group a + b | 14 | 53 | **80** = (93 + 88) mod 101 ✓ |

Delete a: the group is now b alone, `C_post = 88`. Anyone can check `88 + 93 = 80 (mod 101)` without
knowing any x or r.

**Why the toy is insecure, and why that matters.** In mod 101 you can divide: `H = 13 = 74·7 = 74·G`.
Knowing that relation (`h = 74`), someone can open the envelope 93 as a different value: `x' = 6` with
`r' = 35` also gives `7·6 + 13·35 = 497 = 93 (mod 101)`. Binding is broken. In ristretto255, finding
`h` with `H = h·G` is the discrete-log problem, which is infeasible, and §5.3 makes sure nobody chose `h`.

### 5.5 SEVER's commitments (spec §9.3)

One generator per dimension:

```
 record t:   C_t = r_t·H   + Σ_i scalar(x̃_i)·G_i             r_t random per record (§9.4)
 group:      C_S = r_agg·H + Σ_i scalar(S_i)·G_i             r_agg = Σ r_t over current members, mod ℓ

 because commitments add:   C_S = Σ_{t in group} C_t

 delete t:   C_S_post = C_S_pre − C_t
 anyone can check:   C_S_post + C_t = C_S_pre          ("public transition check", step 6a)
```

```
  before                         delete record t                     after
 ┌──────────────────────┐                                       ┌──────────────────────┐
 │ S      = Σ x̃         │   S      −= x̃_t                        │ S      = Σ x̃ − x̃_t    │
 │ n                    │   n      −= 1                          │ n − 1                │
 │ r_agg  = Σ r         │   r_agg  −= r_t (mod ℓ)                │ r_agg − r_t          │
 │ C_S    = C(S, r_agg) │   C_S    −= C_t                        │ C(S − x̃_t, r_agg−r_t)│
 └──────────────────────┘   all four move together (INV-2)       └──────────────────────┘
```

This only works because `S` is an **exact integer**: you can't commit to a float average and later match
it exactly.

### 5.6 The proof of knowledge (spec §9.5)

**The gap it closes.** An operator could publish `C_S_post = C_S_pre − C_t` **without deleting
anything**: the public check would still pass. So the operator must also prove it **knows the
contents** of `C_S_post` (the real `S_post` and `r_post`), without revealing them.

**The proof (Schnorr, generalised to many secrets by Okamoto):**

```
 secrets:  r_post, s_0 … s_383                 (s_i = scalar(S_post_i))       385 secrets
 1. pick fresh random nonces  k_r, k_0 … k_383
 2. A   = k_r·H + Σ k_i·G_i                      "a commitment to the nonces"
 3. c   = SHA-512( DST_POSK ‖ C_S_post ‖ A ‖ ctx ) mod ℓ        the challenge
 4. z_r = k_r + c·r_post  (mod ℓ),   z_i = k_i + c·s_i  (mod ℓ)
 proof = A ‖ z_r ‖ z_0 ‖ … ‖ z_383          32 + 32 + 32·384 = 12,352 bytes

 verifier checks:   z_r·H + Σ z_i·G_i  ==  A + c·C_S_post
```

**Why the check works:** `z·G = (k + c·s)·G = k·G + c·(s·G)`. Summed over all generators, the left side
is `A + c·C_S_post`. Only someone who knows the secrets can produce z values that fit **every** possible
c, and the k values hide the secrets.

**Toy, mod 101** (secrets x = 9, r = 33, so C = 88; nonces k_x = 4, k_r = 10; pretend c = 3):

```
 A   = 7·4 + 13·10            = 158 → 57
 z_x = 4 + 3·9 = 31           z_r = 10 + 3·33 = 109 → 8
 check:  7·31 + 13·8 = 321 → 18        A + c·C = 57 + 3·88 = 321 → 18   ✓
```

**Fiat–Shamir.** In the original (interactive) proof, the verifier picks `c` at random after seeing
`A`. Fiat–Shamir replaces the verifier with a hash: `c = hash(statement ‖ A ‖ context)`. The prover
can't choose `c` because any change to `A` changes `c` unpredictably.

**Why nonces must never repeat.** Two proofs with the same nonces and different challenges give away
the secret:

```
 z₁ = k + c₁·x,   z₂ = k + c₂·x   →   x = (z₂ − z₁) / (c₂ − c₁)
 toy: c₁ = 3 → z₁ = 31,  c₂ = 5 → z₂ = 49  →  x = 18 / 2 = 9   ← the secret, recovered
```

Reusing nonces once would leak a whole group's sum. That's why nonces come fresh from the OS, never from
a seed.

**The context `ctx` (152 bytes)** = `C_S_pre (32) ‖ C_t (32) ‖ scrambled_id (64) ‖ u64be lsn (8) ‖
collection_id (16)`. It goes into the challenge, so a proof made for one deletion fails in any other
certificate (a "replay").

### 5.7 Ed25519 signatures (RFC 8032)

A **signature** proves that the holder of a secret key approved exact bytes. Anyone with the public key
can check it, and changing one bit of the message makes the check fail.

```
 keypair:   secret key a (from 32 random bytes),  public key A = a·B
 sign(M):   R = r·B (r derived from the key and M),  S = r + SHA-512(R ‖ A ‖ M)·a
 verify:    S·B == R + SHA-512(R ‖ A ‖ M)·A
```

It is itself a Schnorr-style proof ("I know a"). Ed25519 is **deterministic**: the same key and message
always give the same signature, which is why the RFC test vectors can pin it exactly. Here the
operator signs `DST_CERT ‖ certificate body`.

### 5.8 HMAC: the scrambled record ID (spec §9.7)

```
 scrambled_id = HMAC-SHA-512( k_scramble, collection_id ‖ record_id_bytes )     64 bytes
```

An **HMAC** is a hash with a secret key mixed in. Without `k_scramble`, nobody can tell which record a
certificate is about, or build a list of deleted IDs. With the key, the operator can show an auditor
which record it was. The certificate never contains `doc5`, only its 64-byte scrambled form.

### 5.9 What a certificate proves, and what it can't

| A valid certificate shows | No certificate can show |
|---|---|
| the group's commitment moved by exactly `C_t` (6a) | that the operator kept no copy (no cryptography can) |
| the operator knows the contents of the new state (6b) | that the user personally approved the deletion (the service holds the keys: DB-55, L-27) |
| the operator signed all of it (2) | (preview only) that the record was logged at insert: steps 3–5 need the transparency log, which is not built |

---
## 6. Layer 0: the plan, the rules, the config

### 6.1 `docs/DEMO_PLAN.md` (staged + further edits): the plan everything follows

**Job.** The 4-day plan (1–4 Oct) for the 5 Oct review: what to build, what to claim, how to test,
what to say. Every code file in this guide exists because a section of this plan asked for it.

**Its sections, in one line each:**

| § | Says | Status on 3 Oct |
|---|---|---|
| 0 | The honest status paragraph + a "may say / may NOT say" table | updated: Part 3 preview, who wrote what |
| 1 | The one claim; in scope; out of scope; 5 of 5 exactness fields | 1.3 changed from "four of five" to "five of five" |
| 2 | What to read (9 items), the five sentences, key facts | five sentences still open (`P1-idea.md`) |
| 3 | 10 Python exercises | not tracked in git (`scratch/`) |
| 4 | Folder layout and setup | matches the code, except `verifier/` moved to `python/sever_verify` |
| 5 | What each module must do (5.1–5.9) | all built; chapters 7–22 |
| 6 | Tests T1–T14, sabotage SB-1–SB-3, the full-data run | all built, plus SB-4; chapter 23 |
| 7 | The ghost table format | built; chapter 17 |
| 8 | The 6–8 minute demo script | made concrete in `DEMO_RUNBOOK.md` |
| 9 | Slides: now 9, published as an artifact | done |
| 10 | Q&A bank: 20 questions + 8 new ones on the Part 3 preview (21–28) | rehearse aloud: open |
| 11 | Day-by-day schedule | |
| 12 | What to cut if late; what never to cut | nothing was cut |
| 13 | Risks | all mitigations used (cache, mmap, chunking, G-1) |
| 14 | Definition of done | see the checklist below |
| 15–16 | After the review; working rules with Claude | |

**What changed in this working tree (vs the last commit):** §0 adds who wrote which code and the Part 3
preview claims; §1.2 no longer lists commitments and certificates as out of scope; §1.3 becomes "five of
five fields"; §8 points to the runbook; §9 grows to 9 slides (new slide 5, "The receipt"); Q&A 15 and
17 are corrected to the measured facts ("the error did **not** grow"); Q&A 21–28 are added.

**From plan to code: where each test of §6 lives.**

| Plan | What it checks | Test (file) | Ch. |
|---|---|---|---|
| T1 | ties to even | `test_quant_ties_to_even` (+ negative ties) | 8 |
| T2 | bound `2^24 + 16` | `test_quant_bound_at_tolerance_edge`, `…_rejects_beyond_bound` | 8 |
| T3 | norm check | 5 tests in `test_data.py` | 7 |
| T4 | ID rules | `test_ids_valid` ×9, `test_ids_invalid` ×8 | 11 |
| T5 | insert then delete = before | `test_insert_then_delete_restores_state` (+ from empty) | 13 |
| T6 | idempotent delete | `test_delete_absent_is_idempotent` | 13 |
| T7 | duplicate live ID | `test_duplicate_live_id_rejected` | 13 |
| T8 | survivors check | `test_survivors_check_after_random_deletes` | 13 |
| T9 | blob order-independent | `test_blob_order_independent` | 13 |
| T10 | empty group persists | `test_empty_group_persists` | 13 |
| T11 | multi-group `delete_user` | `test_delete_user_multi_group` | 16 |
| T12 | 2,000 random operations | `test_stress_random_ops` | 23 |
| T13 | ledger append-only | `test_ledger_appends_and_never_rewrites` | 18 |
| T14 | the float ghost | `test_float_baseline_is_not_exact` | 17 |
| SB-1…3 | each bug turns a test red | `test_sabotage.py` (+ SB-4) | 23 |

**§14 Definition of done, checked against the files on 3 Oct:**

| Item | State |
|---|---|
| Five sentences in your own words | **open**: `P1-idea.md` has a 4-line draft |
| Data facts recorded | done (`notes/P1-data.md`) |
| T1–T14 pass | done: 218 passed when this guide was written |
| SB-1–SB-3 turn tests red, revert to green | done (36 must-fail tests pass), plus SB-4 |
| Full run, 0 mismatches | done (ledger line 19), but `git_dirty: true` |
| Ghost table with measured numbers | done |
| Ledger entries committed | **open**: 63 lines exist, not committed |
| REPL works | done (14 rehearsal screenshots) |
| Slides with real numbers | done (9) |
| Q&A answered aloud twice | **open (you)** |
| Demo runs from a fresh clone | **open**: the script exists; it needs a commit to test |
| Backup recording + screenshots | screenshots done; recording **open** |
| `PROGRESS.md` updated; tag `demo-v0` | draft written; tag **open** |
| You can explain every line | **this guide** |

### 6.2 The design documents (all staged): one design change, DB-55

The spec, the overview, both build plans, `CLAUDE.md` and `TEAM_HANDBOOK.md` were edited together for
**one decision**, recorded as **DB-55, "service-side custody of `r_t` and user keys" (2 Oct 2026)**.
This is what the branch name `docs/service-side-custody` refers to.

```
 BEFORE (DB-18)                                     AFTER (DB-55)
 ─────────────                                      ─────────────
 user device                                        user app (thin): sends text, signs in
   holds the user key and every r_t                   holds no SEVER-DB secret
   "possessing r_t = the right to delete"                     │ text
        │ insert(x, r_t, C_t, signature)                      ▼
        ▼                                           application backend (e.g. the AI server)
 engine                                               embeds text (pinned encoder)
   stores r_t only for holding-area records           prepare_insert: quantise, draw r_t, C_t, sign
   delete(record_id, r_t)                             holds every account's signing key
   checks r_t opens C_t,                              authenticates the account, then calls delete
   else AuthorisationFailed                                   │ insert(…, r_t, C_t, sig) / delete(id)
                                                              ▼
                                                    engine
                                                      stores r_t for EVERY record, encrypted under
                                                      the record key (has_rt = 1 always)
                                                      delete(record_id): no r_t argument
                                                      recomputes C_t from stored x̃ and r_t:
                                                      an integrity check → IntegrityViolation
```

| Effect | Where |
|---|---|
| Three parties: user app, application backend, engine | spec §1, §3.3; overview §5 |
| `r_t` drawn by the backend, stored by the engine for every record, erased with the record key | spec §2.1, §9.4, §13.2, §13.5, §14.4 |
| `delete` takes no `r_t`; `AuthorisationFailed` removed; the `C_t` recheck is an integrity check | spec §15.3, §16.1, §17 |
| Flush keeps `has_rt = 1` and no longer re-encrypts the payload | spec §14.4, §15.2 |
| Certificate format, log leaf format and verifier unchanged | spec §11 |
| What a certificate proves is restated ("Proves / Does not prove" box) | overview §1.2; spec §11.3 |
| New limit **L-27** (the operator holds every key, so signatures don't constrain a dishonest operator); L-16 retired; DB-18 superseded; DB-21, DB-22 qualified | overview §6.8, §14 |
| `CLAUDE.md`: one wording change ("each record's `r_t`") | §5 |
| `TEAM_HANDBOOK.md`: problem statement reworded; every line reference updated to the new line numbers | Part A |

**Why it matters for the demo code:** the demo already behaves like DB-55. Its index draws every `r_t`
and keeps it (there is no separate backend in the demo), and `delete(rid)` takes no `r_t`.

### 6.3 `pyproject.toml` (modified): the project's settings

| Section | Meaning |
|---|---|
| `[project]` | name, Python 3.13 only, and the libraries: numpy 2.5, scikit-learn 1.9, pyarrow 25.0, pandas, rich (coloured tables) |
| `[dependency-groups] dev` | tools for development only: pytest, pytest-cov, hypothesis, ruff, mypy, import-linter, mutmut, pytest-benchmark |
| `[tool.uv]` | `package = false` (not an installable package); `link-mode = "copy"` (the repo is on `/mnt/c`, so hard links are impossible) |
| `[tool.pytest.ini_options]` | `pythonpath = ["python"]` lets tests `import sever_demo`; `--strict-markers` turns an unknown mark into an error; the two allowed marks: `mustfail`, `spec` |
| `[tool.ruff]`, `[tool.ruff.lint]` | the linter: line length 100, which rule families to check |
| `[tool.mypy]` | strict type checking |

**The change:** `allowed-confusables = ["ℓ"]` (ruff warns that `ℓ` looks like `l`; here it is the spec's
own symbol), and `per-file-ignores` for `repl.py` and `demo.py` (rule E402 "import not at top of file":
those two files must fix the import path *before* importing `sever_demo`, chapter 21).

### 6.4 `.gitignore` (modified)

Two lines added: `results/certs/` is never committed. The certificates are public by design, but each
belongs to one session's keys, which existed only in memory and are gone. (The existing `*.cert` rule
already covers them; the folder rule makes the reason explicit.)

---

## 7. `data.py`: load and check the data

**Job.** Prove the data is the data that P0 pinned (manifest check), check that every row has length 1
(norm check, §4.1: *check, never fix*), and read record IDs and cohorts. **Needs:** nothing from the
project. **Spec:** §4.1. **Written by:** you (Day 1); tidied by Claude on 3 Oct (names, type hints,
formatting); `check_manifest` and `load_ids_and_cohorts` added on Day 2.

**The diff in this working tree:** `X` renamed `x` (Python convention: lowercase for variables), type
hints added, formatting by ruff, two new functions (`check_manifest`, `load_ids_and_cohorts`). The
behaviour of `check_norms` is unchanged.

**Picture: the norm check on one chunk**

```
 rows start … stop (20,000 rows) as float64
   │
   ├─ isfinite? ── no ──► non_finite += 1   (and the row is not length-tested)
   │
   ▼ yes
 square each number → running sum left to right (cumsum) → last column = Σ x_i² → √ = length
   │
   ▼
 off = |length − 1|  >  TOL (8·2^-23 ≈ 9.5e-7) ?  ── yes ──► bad_length += 1
```

**Line by line** ([data.py](../python/sever_demo/data.py))

| Lines | Code | What it does |
|---|---|---|
| 1–7 | `import hashlib` … `import pyarrow.parquet as pq` | tools: SHA-256 (`hashlib`), file paths (`Path`), the type hint `Any`, NumPy, NumPy's type hints, and the Parquet reader |
| 9 | `REPO = Path(__file__).resolve().parents[2]` | `__file__` is this file's path. `.resolve()` makes it absolute. `parents[0]` = `sever_demo/`, `[1]` = `python/`, `[2]` = the repo root. Paths then work from any folder |
| 10 | `PROCESSED = REPO / "datasets" / "processed"` | `/` joins path parts |
| 12 | `TOL = 8 * 2**-23` | the tolerance: 8 float32 steps at 1.0 ≈ 9.54e-7 |
| 16 | `def check_norms(x, chunk_rows=20_000) -> dict` | takes a float array (1M × 384), returns a report |
| 17–21 | `n_rows = x.shape[0]` … `bad_row_numbers = []` | the counters start at 0 |
| 23 | `for start in range(0, n_rows, chunk_rows):` | `start` = 0, 20,000, 40,000, …: one chunk at a time (all at once in float64 would be about 9 GB) |
| 24 | `stop = min(start + chunk_rows, n_rows)` | the last chunk may be shorter |
| 25 | `chunk = np.asarray(x[start:stop], dtype=np.float64)` | copy the chunk as float64: the spec computes norms in float64 |
| 27 | `finite = np.isfinite(chunk).all(axis=1)` | one True/False per row: True if all 384 numbers are ordinary numbers (no NaN, no ±inf) |
| 28 | `non_finite += int((~finite).sum())` | `~` flips True/False; summing booleans counts the Trues |
| 30 | `squares = chunk * chunk` | square every number |
| 31 | `total = np.cumsum(squares, axis=1)[:, -1]` | running totals along each row; the last column is the sum, added strictly **left to right**. (`np.sum` may add in another order, and float results depend on order; the spec pins this order so Python and Rust agree on edge rows) |
| 32 | `length = np.sqrt(total)` | the length of each row |
| 34 | `off = np.abs(length - 1.0)` | how far from 1 |
| 35–37 | `off_ok = off[finite]` … `worst = max(...)` | the worst `off` over finite rows only (a NaN would poison `max`) |
| 39 | `too_far = finite & (off > TOL)` | finite rows that are too long or short. Non-finite rows are excluded, so each bad row is counted once |
| 40 | `bad_length += int(too_far.sum())` | count them |
| 41–44 | `if len(bad_row_numbers) < 10: …` | keep the first 10 bad row numbers. `np.flatnonzero` gives positions of True; `+ start` turns a chunk position into a real row number. Row numbers only, never values (§17) |
| 46–52 | `return {...}` | the report: rows, non_finite, bad_length, worst_abs_diff, first_bad_rows |
| 55 | `def check_manifest(datasets=REPO / "datasets") -> list[str]:` | re-hash every data file, return the ones that don't match |
| 61 | `for line in (…/"MANIFEST.sha256").read_text(…).splitlines():` | each manifest line is `<sha256>␣␣<relative path>` |
| 62 | `expected, rel = line.split("  ", 1)` | split at the two spaces, once |
| 64–66 | `if not path.exists(): mismatches.append(rel); continue` | a missing file is a mismatch; `continue` jumps to the next line |
| 67–70 | `h = hashlib.sha256()` … `h.update(chunk)` | hash the file 4 MiB at a time (`1 << 22`), so a 1.5 GB file never sits in memory |
| 71–72 | `if h.hexdigest() != expected:` | different fingerprint → mismatch |
| 76–85 | `load_ids_and_cohorts(parquet_path, rows=None)` | read only the `id` and `cohort` columns (never the passage text), optionally only the first `rows` rows; return two lists of strings |
| 88–90 | `_short(value, limit=70)` | cut long text to 70 characters for printing (`_` at the start = "private helper") |
| 93–111 | `describe_dataset(...)` | the Day 1 report: shape, dtype, Parquet rows and columns, "rows match", 3 sample rows, the norm check |
| 114–127 | `if __name__ == "__main__":` | when run as `python data.py`, describe all three datasets |

**Example (2-D toy):** row `(0.6, 0.8)`: squares `(0.36, 0.64)`, cumsum `(0.36, 1.0)`, length 1.0,
off 0 → good. Row `(0.6, 0.9)`: length √1.17 = 1.0817, off 0.0817 > TOL → `bad_length`. Row `(NaN, 0.8)` →
`non_finite`.

**Real result** (full run, 2 Oct): SciQ 13,679 rows and NQ 1,000,000 rows, **0 non-finite, 0 bad
length**; worst NQ row 1.836e-7 off (1.54 float32 steps of the 8 allowed).

**Guarded by:** `test_data.py` (7): good rows pass; NaN, +inf, −inf each counted once, at the right
row; `1 + 2·TOL` rejected; `1 + 0.5·TOL` accepted; a bad row in the third chunk is reported as row 7,
not 1 (catches a missing `+ start`). The tolerance is **written out in the test**, not imported, so
loosening the code's tolerance can't loosen the test.

---

## 8. `quant.py`: floats to exact integers

**Job.** `x̃ = round_half_to_even(x · 2^24)` as int32 (§4.2), and back (§4.3). **Needs:** nothing.
**Written by:** you (Day 1). **The diff:** formatting only (comment spacing). The maths is in §4.2 above.

**Line by line** ([quant.py](../python/sever_demo/quant.py))

```python
SCALE = 2**24          # 16,777,216: "Q24" means "times 2^24"
BOUND = 2**24 + 16     # 16,777,232: the largest |x̃| a row inside the §4.1 tolerance can produce

def quantise(x: npt.ArrayLike) -> npt.NDArray[np.int32]:
    scaled = np.asarray(x, dtype=np.float64) * SCALE
    #  float32 → float64 is exact, and × a power of two is exact, so nothing has rounded yet.

    if not np.isfinite(scaled).all():
        raise ValueError("quantise: non-finite component")
    #  NaN or inf cast to int32 gives a meaningless number (only a warning), so refuse first.
    #  The message never contains the vector's values (§17).

    rounded = np.rint(scaled)
    #  np.rint = round to nearest, ties to even (the IEEE 754 default). The ONLY rounding step.

    if np.abs(rounded).max(initial=0) > BOUND:
        raise ValueError("quantise: component beyond 2^24 + 16")
    #  initial=0 lets an empty array pass instead of crashing. Refuse rather than wrap around
    #  (2^31 cast to int32 silently becomes −2,147,483,648).

    return rounded.astype(np.int32)

def dequantise(q: npt.ArrayLike) -> npt.NDArray[np.float64]:
    return np.asarray(q, dtype=np.float64) / SCALE      # exact: an int32 / 2^24 fits a float64
```

**Example:** `quantise([[0.0123456, -0.25]])` → `[[207125, -4194304]]`; `dequantise` gives back
`0.012345612…` (error 1.2e-8 ≤ 2^-25) and exactly `−0.25`.

**Measured** (all 5,252,736 SciQ numbers): 5.83% are exact ties; the largest error is exactly `2^-25`.

**Guarded by:** `test_quant.py` (9): ties `0.5→0, 1.5→2, 2.5→2, −0.5→0`; negative ties `−1.5→−2,
−2.5→−2, −3.5→−4`; a row of length `1 + 8·2^-23` lands exactly on the bound and is accepted; one step
more is refused; NaN/±inf refused; round-trip error ≤ 2^-25; shape kept. The tests now check the error
**message** (`match="beyond"`), so a different error can't pass by accident.

---

## 9. `partition.py`: 128 fixed groups and routing

**Job.** Fit 128 group centres on SciQ with k-means (§6.2 steps 1–2), then send each NQ vector to its
nearest centre (§7.1). **Needs:** `quant.py`. **Written by:** Claude (Day 2).

**Why SciQ and not NQ?** NQ plays the "user data". Centres fitted on it would carry every user's
influence, so they would themselves be a ghost after a deletion. SciQ is public and never deleted, so
the centres never have to change. Fixed centres also mean one deletion touches exactly one group.

**Picture**

```
 SciQ 13,679 × 384 ──quantise→dequantise──► k-means (k = 128, seed 1,360,647,240) ──► centroids 128 × 384
                                                                                        │
 NQ x̃ (1M × 384, int32) ──20,000 rows at a time──► dequantise ──► distance² to all 128 ──► argmin ──► label
```

**Line by line** ([partition.py](../python/sever_demo/partition.py))

| Lines | Code | What it does |
|---|---|---|
| 7–14 | imports | SHA-256, `struct`, NumPy, scikit-learn's `KMeans`, our quantiser |
| 16 | `K_FROZEN = 128` | the number of frozen groups (§6.2) |
| 19–21 | `sub_seed(seed, label)` | `struct.pack(">Q", seed)` = the seed as 8 bytes big-endian; append the label; SHA-256; take the first 8 bytes as an unsigned integer (Overview §10.6). See §4.4 above |
| 24–26 | `kmeans_seed(seed)` | `sub_seed(seed, b"kmeans") % 2**32`: scikit-learn crashes on seeds ≥ 2^32 (gap **G-1**, still needs a decision entry) |
| 29–31 | `def fit_centroids(x_ref, seed, k=128)` | returns a 128 × 384 float64 array; row j is the centre of group j |
| 34 | `x_hat = dequantise(quantise(x_ref))` | step 1: fit on exactly what the engine routes (the integer grid), not on the raw floats |
| 36–44 | `km = KMeans(n_clusters=k, init="k-means++", n_init=10, max_iter=300, tol=1e-4, algorithm="lloyd", random_state=…)` | step 2, the **pinned** call: every parameter is written in the spec so the result is reproducible. `n_init=10` = try 10 starts, keep the best |
| 45–46 | `km.fit(x_hat)`; `return …cluster_centers_` | run it; return the centres as float64 |
| 49–51 | `def route(q, centroids, chunk_rows=20_000)` | one group label per quantised row |
| 59 | `c_sq = np.einsum("ij,ij->i", centroids, centroids)` | `‖μ_j‖²` for each centre. `einsum("ij,ij->i")` = "multiply element by element, sum each row" |
| 60 | `labels = np.empty(q.shape[0], dtype=np.int64)` | an output slot per row |
| 62 | `x = dequantise(q[start : start + chunk_rows])` | 20,000 rows back to float64 (exact) |
| 63 | `dist = ‖x‖²[:, None] − 2·(x @ centroids.T) + c_sq[None, :]` | a 20,000 × 128 table of squared distances, using `‖x−μ‖² = ‖x‖² − 2x·μ + ‖μ‖²` (§4.5). `[:, None]` and `[None, :]` line the shapes up |
| 65 | `labels[...] = np.argmin(dist, axis=1)` | the column of the smallest distance in each row. `argmin` returns the **first** minimum, so ties go to the smaller label (§7.1) |

**The honest shortcut** (said in the docstring): the spec computes distances one term at a time, in
order. The demo uses matrix products, which round differently, so a near-tie *could* go to another group
than the Rust engine would pick. This does not affect exactness: exactness is about one group's sum
before and after a delete, and the same vector always gets the same label (routing is a **pure
function** of `(x̃, centroids)`: no clock, no counter).

**Real result** (full run): group sizes min **74**, median **2,252**, max **161,376** (16% of NQ in one
group), 0 empty. Very uneven, because SciQ (science questions) and NQ (Wikipedia) are different kinds of
text. Part 1's drift test and spawning (not built) exist for this.

**Guarded by:** `test_partition.py` (6): `sub_seed` matches the formula written out by hand for all 5
seeds and 3 labels; `kmeans_seed` = sub-seed mod 2^32; `fit_centroids` equals a `KMeans` call with the
spec's parameters written in the test; an exactly equidistant point goes to the smaller label (both
orders); the fast `route` equals the oracle's slow sequential §7.1 loop on 300 rows; routing rows
together, alone, or reversed gives the same labels.

---

## 10. `errors.py`: named errors and the delete outcome

**Job.** Give each failure the spec's name (§17), and define the result of a delete (§5.4). **Needs:**
nothing. **Written by:** Claude (Day 2).

| Lines | Code | What it does |
|---|---|---|
| 1 | `# ruff: noqa: N818` | tells the linter not to demand an `…Error` suffix: these names are the spec's |
| 8 | `from enum import Enum` | for `Outcome` |
| 11–28 | `class InvalidRecordId(ValueError): """…"""` and 4 more | five new error **types**: `InvalidRecordId` (§3.2 rules 1–2), `DuplicateRecord` (rule 3), `NotNormalised` (§4.1), `GroupCapacityExceeded` (§5.6), `IntegrityViolation` (§21). The body is only a docstring: each is a `ValueError` with its own name, so `except ValueError` still catches all of them |
| 31–35 | `class Outcome(Enum): DELETED = "Deleted"; ALREADY_ABSENT = "AlreadyAbsent"` | the two results of a delete. `AlreadyAbsent` is **not an error**: deleting something absent is a normal, safe retry (§5.4) |

**The rule behind them (§17):** no error message may contain a record ID, a vector value, a key, `r_t`
or passage text. Error messages end up in logs, and a log line with a deleted person's ID would be the
very trace this project removes. Group sizes may appear.

---

## 11. `ids.py`: record ID rules

**Job.** Check §3.2 rules 1 and 2 on every insert. Rule 3 ("not already live") needs the index, so it
is checked there. **Needs:** `errors.py`. **Written by:** Claude (Day 2).

```python
MAX_ID_BYTES = 256                                   # §3.2 rule 1
_BARE_INTEGER = re.compile(r"[+-]?[0-9]+")           # §3.2 rule 2: optional sign, then only digits
#   [0-9], not \d: \d also matches other scripts' digits (e.g. Arabic-Indic ١٢), the spec doesn't.
#   re.compile prepares the pattern once.

def validate_record_id(rid: str) -> None:
    try:
        size = len(rid.encode("utf-8"))              # count BYTES, not characters: "€" is 3 bytes
    except UnicodeEncodeError:                       # a lone surrogate ("\ud800") has no UTF-8 form
        raise InvalidRecordId("record ID is not valid UTF-8") from None
        #   "from None" hides the original error, whose text would show the bad character (§17)
    if not 1 <= size <= MAX_ID_BYTES:                # chained comparison: 1 ≤ size ≤ 256
        raise InvalidRecordId(f"record ID must be 1 to {MAX_ID_BYTES} UTF-8 bytes")
    if _BARE_INTEGER.fullmatch(rid):                 # the WHOLE string must match to be rejected
        raise InvalidRecordId("record ID must not be a bare decimal integer")
```

**Why rule 2 exists:** a counter ID (`1`, `2`, `3`, …) would leak the arrival order into the canonical
blob, which sorts members by ID. One value can't prove it's a counter, so the spec bans the *shape*.

**Why `fullmatch`:** `re.match` only checks the start, so it would reject `12abc` wrongly; a pattern
`^[0-9]+$` would match `"12\n"`, because `$` also matches just before a final newline.

| Valid | Invalid |
|---|---|
| `doc0`, `nq-1234`, a UUID, 256 × `a`, 85 × `€` (255 bytes), `"12\n"`, `١٢`, `1.5`, `0x1F` | `1`, `007`, `-3`, `+3`, `""`, 257 × `a`, 100 × `€` (300 bytes), `"\ud800"` |

**Real result:** all 1,000,000 NQ IDs (`doc0`, `doc1`, `doc6`, …): **0 rejected**, all unique.

**Guarded by:** `test_ids.py` (18 = the 17 cases above + "the error text never contains the ID").

---
## 12. `crypto.py`: the crypto building blocks

**Job.** Every crypto operation the engine needs: scalars mod ℓ, point add/subtract/multiply, the
generators, Pedersen commitments, Ed25519 keys and signatures. **Needs:** the system library
**libsodium 1.0.18** (nothing from the project). **Spec:** §2.1, §4.5, §9.1–9.4, §9.8. **Written by:**
Claude (3 Oct, Part 3 preview). Read chapter 5 first.

**The rule it follows (§9.1): don't write your own crypto.** The group maths and the signatures come from
libsodium, a widely used C library. The only thing written here is `expand_message_xmd`, which is a
recipe of SHA-512 calls, not group maths, and it is pinned to the RFC 9380 test vectors.

**ctypes in one paragraph.** libsodium is compiled C code, not Python. `ctypes` lets Python call it. A C
function takes pointers to memory, so Python must say what each argument is (`argtypes`) and what comes
back (`restype`). The pattern used everywhere below is: make an empty 32-byte box with
`ctypes.create_string_buffer(32)`, let the C function write the answer into it, read it back with `.raw`.
libsodium returns `0` for success and a negative number for failure.

**Line by line** ([crypto.py](../python/sever_demo/crypto.py))

| Lines | Code | What it does |
|---|---|---|
| 18 | `L = 2**252 + 27742317777372353535851937790883648493` | ℓ, the group order (§2.1). Python integers have no size limit, so this 253-bit number is exact |
| 19 | `IDENTITY = bytes(32)` | the identity point: 32 zero bytes (§0.2) |
| 20 | `DST_GEN = b"PROJECT_SEVER_V1_RISTRETTO255_SHA512_NUMS"` | the label for making generators (§2.3) |
| 22–24 | `_path = ctypes.util.find_library("sodium")` … `raise ImportError` | find `libsodium.so` on the system; a clear error if it's missing |
| 25–27 | `_lib = ctypes.CDLL(_path)`; `_lib.sodium_init()` | load it; libsodium must be initialised once |
| 28–40 | `_SIGNATURES = {…}`; `for _name, _args in …: …argtypes = _args; …restype = c_int` | declare the 7 C functions used: `c_char_p` = "pointer to bytes", `c_ulonglong` = a 64-bit length, `c_void_p` = any pointer (`None` passes NULL) |
| 43–47 | `def scalar(v)` | §4.5: `v mod ℓ` if `v ≥ 0`, else `ℓ − (|v| mod ℓ)`. So `scalar(−1) = ℓ − 1` |
| 50–52 | `def scalar_bytes(k)` | a scalar as 32 bytes **little-endian** (§0.2) |
| 55–57 | `def wide_reduce(b)` | 64 bytes, little-endian, → integer mod ℓ (`from_bytes_mod_order_wide`) |
| 60–62 | `def random_scalar()` | §9.4: 64 bytes from the OS random source (`os.urandom`), reduced wide. **No seed parameter exists**, on purpose |
| 65–68 | `def random_scalars(count)` | the same, many at once (one OS read of `64·count` bytes, cut into 64-byte pieces). Used for 1,000,000 `r_t` values |
| 71–73 | `def is_valid_point(p)` | 32 bytes long and accepted by libsodium as a canonical encoding (§9.9) |
| 76–80 | `def point_add(p, q)` | `P + Q`. libsodium refuses an invalid point → `ValueError("invalid point")` |
| 83–87 | `def point_sub(p, q)` | `P − Q` |
| 90–99 | `def mul(k, p)` | `k·P`. First `k %= L`. libsodium returns an error whenever the result would be the identity (so it refuses `0·P`), but the spec requires `0·P = identity` (a zero component, an empty group). So: if `k == 0` or `P` is the identity, return `IDENTITY` without calling libsodium |
| 102–108 | `def msm(scalars, points)` | multi-scalar multiplication `Σ k_i·P_i`: start at the identity, add `k_i·P_i` one by one, skip zero terms |
| 111–127 | `def expand_message_xmd_sha512(msg, dst, len_in_bytes)` | RFC 9380 §5.3.1, exactly the formula in §5.3 above: `ell` = number of 64-byte blocks; `dst_prime = dst ‖ len(dst)`; `b_0`, `b_1`, then `b_i = SHA512((b_0 XOR b_{i−1}) ‖ i ‖ dst_prime)`; cut to length |
| 130–136 | `def from_uniform_bytes(b)` | 64 uniform bytes → a point (RFC 9496 §4.3.4; libsodium calls it `from_hash`) |
| 139–147 | `@cache def generators(d)` | §9.2: `H` from `b"H"`, `G_i` from `b"G" ‖ u32be(i)`. `@cache` means the 385 points are computed once per `d`, then reused |
| 150–153 | `def commit(values, r)` | §9.3: `r·H + Σ scalar(v_i)·G_i`. Used for a record's `C_t` (values = `x̃`, r = `r_t`) and a group's `C_S` (values = `S`, r = `r_agg`) |
| 156–161 | `def ed25519_keypair()` | a signing key pair from 32 OS-random bytes. Kept in memory only |
| 164–168 | `def ed25519_public_from_seed(seed)` | **test only**: rebuilds the RFC 8032 key pairs from their published seeds |
| 171–175 | `def ed25519_sign(secret_key, message)` | a 64-byte signature ("detached" = the signature alone, not glued to the message) |

**Example** (run while writing this guide): `point_add(commit([1,2],5), commit([3,−1],7)) ==
commit([4,1],12)` → `True` (commitments add). `commit([0,0], 0) == IDENTITY` → `True` (an empty group's
commitment is the identity).

**Guarded by:** `test_crypto.py` (74 cases), which checks this file **and** the verifier's separate
implementation against the same published vectors: the first 16 multiples of the generator (RFC 9496
A.1) plus a walk that adds the generator 16 times, 29 invalid encodings that must be rejected (A.2),
7 `from_uniform_bytes` cases (A.3) plus one test where 4 different inputs give the same point, 10 `expand_message_xmd` cases (RFC 9380 K.3), 3 Ed25519 cases (RFC
8032 §7.1, including "a changed bit fails"). Plus: `0·B` = identity, `ℓ·B` = identity, the §4.5
scalar mapping for `0, 1, −1, 2^44, −2^44`, the 385 generators are valid, distinct and identical in both
implementations, commitments add, an empty commitment is the identity, OS randomness differs each call.

---

## 13. `group.py`: the heart, exact deletion

**Job.** One group: the exact integer sum `S`, the count `n`, the member list, and (Part 3 preview)
`r_agg` and `C_S`. Insert, delete, the canonical blob, and the survivors check. **Needs:** `crypto.py`,
`errors.py`. **Spec:** §4.4, §5.1–5.6, §9.3. **Written by:** Claude (Day 2; commitments 3 Oct). This
is the file a reviewer will question most.

### 13.1 The picture

```
              one shared int32 array of ALL quantised vectors (1,000,000 × 384)
              row 0  [ 207125, -4194304, … ]
              row 1  [ … ]                       ◄───────────────┐ groups store ROW NUMBERS,
                ⋮                                                │ never copies of vectors
 Group 3 ─────────────────────────────────────────────────────────┤
   S        int64[384]   exact sum of its members' rows           │
   n        4,606                                                 │
   members  { "doc2015226": <row>, "doc273331": <row>, … } ───────┘   record ID → row
   r_agg    Σ r_t of its members, mod ℓ          (secret; Part 3 preview)
   C_S      32-byte point = r_agg·H + Σ S_i·G_i  (public; Part 3 preview)
```

### 13.2 Line by line ([group.py](../python/sever_demo/group.py))

**Constants and the sabotage switch (lines 27–38)**

| Lines | Code | What it does |
|---|---|---|
| 27 | `MAGIC_DEMO = b"SEVERC"` | first bytes of the blob **without** commitments: deliberately *not* the spec's magic, so the 4-field demo blob can't be mistaken for the spec's |
| 28 | `MAGIC_SPEC = b"SEVERG"` | with commitments: exactly the spec's §5.5 layout |
| 29 | `FORMAT_VERSION = 1` | |
| 30 | `MAX_MEMBERS = 1_000_000` | §5.6 hard cap; keeps `|S_i| < 2^44` (§4.2 above) |
| 31 | `_BLOB_BATCH = 1024` | members per piece when streaming the blob |
| 38 | `SABOTAGE: str \| None = None` | the **one** switch for the deliberate bugs. `None` = no bug. Tests and `--sabotage` set it to `"SB-1"` … `"SB-4"` |

**`Transition` (lines 41–51).** A frozen record of what one deletion did: `c_t`, `c_s_pre`, `c_s_post`
(public), and `r_post`, `s_post` (secret: the new `r_agg` and `S`), plus `emptied`. The index uses it
**once** to build the proof, then throws it away.

**`__init__` (lines 55–70): a new, empty group (§5.2)**

```python
def __init__(self, vectors, blinding=None):
    if vectors.ndim != 2 or vectors.dtype != np.int32:          # must be a 2-D int32 table
        raise ValueError("vectors must be a 2-D int32 array")
    self.vectors = vectors                 # the shared table (not copied)
    self.d = int(vectors.shape[1])         # 384 in the real data, 16 or 2 in tests
    self.S = np.zeros(self.d, dtype=np.int64)   # S = 0, as int64 (§4.4)
    self.n = 0                             # n = 0
    self.members: dict[str, int] = {}      # record ID → row
    self.blinding = blinding               # row → r_t; owned by the index; never shown or stored
    self.committed = False                 # are commitments switched on?
    self.r_agg = 0                         # r_agg = 0
    self.C_S = IDENTITY                    # C_S = identity
    self.last_transition = None            # filled by a committed delete
```

**`start_commitments` (lines 72–84): switch commitments on, in one step.** `r_agg = Σ r_t` over the
members, mod ℓ; `C_S = commit(S, r_agg)`. The spec adds each `C_t` one record at a time; for 1,000,000
records that would take about 20 hours (≈70 ms each), so a loaded group's `C_S` is computed once. It is
the **same value**, because commitments add: `Σ C(x̃_t, r_t) = C(Σ x̃_t, Σ r_t) = C(S, r_agg)`. Every
insert and delete **after** this point updates `C_S` record by record.

**`_record_commitment(row)` (lines 86–89):** looks up this record's `r_t` and returns
`(r_t, C_t = commit(x̃, r_t))`.

**`insert(rid, row)` (lines 91–108)**

```python
if rid in self.members:                       # §3.2 rule 3: an ID is live only once
    raise DuplicateRecord("record ID is already live")        # message has no ID (§17)
if self.n + 1 > MAX_MEMBERS:                  # §5.6 cap
    raise GroupCapacityExceeded(f"group already holds {self.n} members")   # sizes may appear
r_t, c_t = self._record_commitment(row) if self.committed else (0, IDENTITY)
#   "plan, then apply": everything that can fail is computed BEFORE any field changes
self.S += self.vectors[row].astype(np.int64)  # S ← S + x̃  (widened to int64 first)
self.n += 1                                   # n ← n + 1
self.members[rid] = row                       # remember who is in
if self.committed:
    self.C_S = point_add(self.C_S, c_t)       # C_S ← C_S + C_t
    self.r_agg = (self.r_agg + r_t) % L       # r_agg ← r_agg + r_t  (mod ℓ)
if SABOTAGE == "SB-1" and self.n == 1:        # SB-1: flip the lowest bit of S[0] on the FIRST insert
    self.S[0] ^= 1
```

**`delete(rid, row)` (lines 110–138)**

```python
if SABOTAGE != "SB-3":                        # SB-3 skips this whole check
    if rid not in self.members:               # §5.4: membership check BEFORE subtracting
        return Outcome.ALREADY_ABSENT         #       absent → nothing changes
    if self.members[rid] != row:              # the presented vector must be the member's own
        raise IntegrityViolation("presented vector does not match the stored member")
r_t, c_t = self._record_commitment(row) if self.committed else (0, IDENTITY)
c_s_pre = self.C_S                            # remember C_S before
self.S -= self.vectors[row].astype(np.int64)  # S ← S − x̃
if SABOTAGE != "SB-2":                        # SB-2 skips n −= 1
    self.n -= 1
self.members.pop(rid, None)                   # PHYSICAL excision: no "deleted" marker is kept
if self.committed:
    self.C_S = point_sub(self.C_S, c_t)       # C_S ← C_S − C_t
    if SABOTAGE != "SB-4":                    # SB-4 skips r_agg −= r_t
        self.r_agg = (self.r_agg - r_t) % L
    self.last_transition = Transition(        # what this deletion did, for the certificate
        c_t=c_t, c_s_pre=c_s_pre, c_s_post=self.C_S, r_post=self.r_agg,
        s_post=tuple(int(v) for v in self.S), emptied=self.n == 0)
return Outcome.DELETED
```

Why each check matters:

| Check | Without it |
|---|---|
| membership check before subtracting | a client retrying after a timeout subtracts the vector twice (SB-3 shows this) |
| `members[rid] != row` | a caller could subtract a different vector than the one stored |
| physical removal, no marker | a "deleted" flag is itself a leftover trace |
| all fields change together | a half-applied delete would leave a group that matches no real state |

**The canonical blob (lines 140–177).** One fixed byte layout of the whole group state, so that "equal
state" can be tested as "equal bytes".

```
 offset  bytes        field                      d = 2 example (members "a"→(2,3), "b"→(1,−1))
 0       6            "SEVERG"                   53 45 56 45 52 47
 6       2   u16be    format version = 1         00 01
 8       2   u16be    d                          00 02
 10      8   u64be    n                          00 00 00 00 00 00 00 02
 18      8·d i64be    S                          …03  …02            (S = (3, 2))
         32           C_S        ┐ only with     commit([3,2], 12)
         32           r_agg (LE) ┘ commitments   0c 00 … 00          (r_agg = 5 + 7 = 12)
         8   u64be    member_count (MUST = n)    …02
 then, per member, sorted by ID BYTES:
         2   u16be    id length                  00 01
         len          id bytes                   61 ("a")
         8·d i64be    x̃ (widened from int32)     …02  …03
                                                 00 01 | 62 ("b") | …01 | ff ff ff ff ff ff ff ff (−1)
```

| Lines | Code | What it does |
|---|---|---|
| 140–142 | `sorted_members()` | members as `(ID as UTF-8 bytes, row)`, sorted by the bytes. Sorting is what makes the blob **independent of insertion order** |
| 153–155 | `magic = …; yield magic + struct.pack(">HHQ", 1, d, n)` | the header (`yield` hands it out as the first piece) |
| 156 | `yield self.S.astype(">i8").tobytes()` | `S` as big-endian int64 bytes |
| 157–158 | `yield self.C_S + scalar_bytes(self.r_agg)` | only when committed |
| 159 | `yield struct.pack(">Q", len(members))` | member count. SB-2 makes this differ from `n` |
| 160–167 | `for start in range(0, len(members), 1024): …` | 1,024 members per piece: look up their rows in one go, convert to big-endian int64, glue `id_len ‖ id ‖ x̃` for each |
| 169–170 | `blob()` | all pieces joined (used in tests on small groups) |
| 172–177 | `blob_hash()` | SHA-256 fed piece by piece. Group 118 holds 161,376 members, about 3 KB each, so its blob is about 0.5 GB: it is **never built whole**, only streamed through the hash |

**Snapshot and compare (lines 179–213).** `snapshot()` freezes a moment: `S` as bytes, `n`, the sorted
ID list, the blob hash, `committed`, `C_S`. `compare(a, b)` compares **each field on its own** and returns
e.g. `{"S": True, "n": False, …}`: five fields with commitments, four without. Fields 1, 2, 3 and 5 are
also inside the blob; the spec wants the redundancy (§5.5): if one comparison had a bug, the others would
still catch the corruption.

**`fresh_sum(vectors, rows)` (lines 216–221).** `S` recomputed with plain NumPy (`vectors[rows].sum(axis=0,
dtype=int64)`), **no `Group` code**. A check must never compare `S` with something derived from `S`.

**`rebuild(...)` (lines 224–241).** A brand-new group holding the given members, inserted in a
**shuffled** order (`rng.permutation`); with `committed`, its `C_S` is then computed in one step, a
different path from the live group's record-by-record point arithmetic.

**`survivors_check(group, rng)` (lines 244–257): the exact meaning of "as if never inserted".**

```
  live group after deletions                         rebuilt from the survivors only
  ┌──────────────────────────┐                       ┌──────────────────────────┐
  │ S, n, members, C_S, blob │ ◄── compare 5 fields ─► │ same members, SHUFFLED   │
  └──────────────────────────┘     each on its own    │ insert order, fresh C_S  │
               │                                      └──────────────────────────┘
               ├── S == fresh_sum(rows)   (plain NumPy, no Group code)
               └── n == len(members)
  all True  ⇒  the deleted records left no trace in this group
```

Why the extra two checks? `rebuild` uses the same `Group.insert`. If `insert` had a bug (SB-1), the
rebuilt group would have the same bug and the two could agree. `fresh_sum` shares no code with `Group`.

### 13.3 Example: delete restores the past (the test's own numbers)

```
 vectors: row 0 = (1, −1), row 1 = (2, 3)            d = 2
 insert "b" (row 0)  → S = (1, −1), n = 1
 insert "a" (row 1)  → S = (3,  2), n = 2, members {b, a}
 delete "b"          → S = (2,  3), n = 1, members {a}
 a group that only ever saw "a":  S = (2, 3), n = 1, members {a}   → identical, byte for byte
 delete "b" again    → AlreadyAbsent, nothing changes
```

### 13.4 The four planted bugs (each changes exactly one place)

| Bug | Line | What it does | Caught by |
|---|---|---|---|
| SB-1 | 107–108 | flips the low bit of `S[0]` on a group's first insert (only the first: two flips could cancel out) | T5 from empty, T8, T11, T12, committed T8 |
| SB-2 | 122–123 | skips `n −= 1` | T5, T8, T11, T12, committed T8; blob's `member_count ≠ n` |
| SB-3 | 112 | skips the membership check: a retry subtracts twice | T6 |
| SB-4 | 128 | skips `r_agg −= r_t`. `C_S` still moves by `C_t`, so the **public check passes**; the blob (`r_agg` inside) differs and the **proof fails** | committed T5 and T8; `test_sabotage_sb4_breaks_the_proof` |

SB-4 is the key teaching point of the Part 3 preview: a bug in the hidden bookkeeping that the public
equation can't see, but the proof of knowledge can.

**Guarded by:** `test_group.py` (17) and `test_group_commitments.py` (9), see chapter 23.

---
## 14. `posk.py`: the proof of knowledge

**Job.** After a deletion, prove the operator knows `(r_post, S_post)` inside `C_S_post`, without revealing
them (§9.5). The maths is in §5.6 above. **Needs:** `crypto.py`. **Written by:** Claude (3 Oct).

**A stated deviation:** the spec derives nonces from a Merlin transcript mixing the secret, the statement
and OS randomness (§9.6), so that even a broken random source can't repeat a nonce. Merlin has no
Python version here, so the nonces are 64 OS-random bytes each. They are still never seeded and never
reused (a test checks that two proofs of the same statement differ).

**Line by line** ([posk.py](../python/sever_demo/posk.py))

```python
DST_POSK = b"SEVERDB_POSK_V1"          # §2.3 domain string, 15 bytes
CTX_LEN = 152

def context(c_s_pre, c_t, scrambled_id, database_lsn, collection_id) -> bytes:
    if (len(c_s_pre), len(c_t), len(scrambled_id), len(collection_id)) != (32, 32, 64, 16):
        raise ValueError("context field has the wrong length")      # fixed widths only
    ctx = c_s_pre + c_t + scrambled_id + struct.pack(">Q", database_lsn) + collection_id
    #     32      + 32  + 64           + 8 (u64 big-endian)              + 16   = 152 bytes
    assert len(ctx) == CTX_LEN
    return ctx
#  Every field is fixed width, so plain gluing is unambiguous: no field can "borrow" bytes of the next.

def challenge(c_s_post, a, ctx) -> int:
    preimage = DST_POSK + c_s_post + a + ctx        # 15 + 32 + 32 + 152 = 231 bytes
    assert len(preimage) == 15 + 32 + 32 + CTX_LEN
    return wide_reduce(hashlib.sha512(preimage).digest())    # c = SHA-512(…) as a scalar mod ℓ

def prove(r_post, s_post, c_s_post, ctx) -> bytes:
    d = len(s_post)                                  # 384
    h, g = generators(d)                             # H, G_0 … G_383
    secrets = [r_post % L] + [scalar(int(v)) for v in s_post]    # 385 secrets
    nonces = random_scalars(d + 1)                   # k_r, k_0 … k_383, fresh from the OS
    a = msm(nonces, (h, *g))                         # A = k_r·H + Σ k_i·G_i
    c = challenge(c_s_post, a, ctx)                  # Fiat–Shamir: c from a hash, not a person
    z = [(k + c * x) % L for k, x in zip(nonces, secrets, strict=True)]   # z = k + c·secret
    return a + b"".join(scalar_bytes(v) for v in z)  # A ‖ z_r ‖ z_0 … z_383
```

**Size:** `32 + 32 + 32·384 = 12,352` bytes at d = 384 (a test checks it).

**Guarded by:** `test_posk.py` (13): the context is 152 bytes in spec order and rejects a wrong length;
the challenge equals SHA-512 of the formula written in the test; swapping `A` and `C_S_post` changes the
challenge; an honest proof verifies (d = 16 and d = 384); two proofs of one statement differ (fresh
nonces); flipping a bit in `A`, `z_r`, `z_0` or the last `z` fails; changing any of the five context
fields fails (no replay); a wrong `r_post` or `S_post` can't produce a valid proof; a non-canonical
scalar (`z + ℓ`, same value mod ℓ) is rejected. The **verifier's** code does the checking, not this file.

---

## 15. `cert.py`: the signed deletion certificate

**Job.** Pack one deletion's public facts into the §11.1 format and sign it with the operator's Ed25519
key. **Needs:** `crypto.py`. **Written by:** Claude (3 Oct).

**TLV encoding (§11.1).** Each field is **T**ag (1 byte) ‖ **L**ength (4 bytes, big-endian) ‖
**V**alue. Example: `tlv(9, b"\xaa\xbb")` = `09 | 00 00 00 02 | aa bb`. A strict reader can tell exactly
where each field starts and ends.

**Line by line** ([cert.py](../python/sever_demo/cert.py))

| Lines | Code | What it does |
|---|---|---|
| 16 | `DST_CERT = b"SEVERDB-CERT-V1"` | the signature's domain string (§2.3) |
| 19–30 | `@dataclass(frozen=True) class DeletionFacts` | the 8 public values one deletion produces |
| 33–35 | `def tlv(tag, value)` | `struct.pack(">BI", tag, len(value)) + value`: u8 tag, u32be length, then the value |
| 38–54 | `def body(f, epoch=0)` | a dict tag → value for tags 1–13, then all 13 TLVs glued **in ascending tag order, each once** |
| 57–60 | `def issue(f, operator_secret_key, epoch=0)` | `body ‖ tlv(0xFF, Ed25519(DST_CERT ‖ body))`: the signature covers every byte before it |

**The certificate, field by field (sizes at d = 384):**

| Tag | Field | Bytes | In the preview |
|---|---|---|---|
| 1 | `C_t`, the deleted record's commitment | 32 | ✓ |
| 2 | `C_S_pre`, group commitment before | 32 | ✓ |
| 3 | `C_S_post`, group commitment after | 32 | ✓ |
| 4 | proof of knowledge | 12,352 | ✓ |
| 5 | user insert signature | 0 | **empty**: needs the transparency log |
| 6 | log inclusion proof of the insert | 0 | **empty** |
| 7 | witness cosignatures | 0 | **empty** |
| 8 | key epoch (u32be) | 4 | always 0: one operator key per session |
| 9 | scrambled record ID (HMAC) | 64 | ✓ the real ID never appears |
| 10 | `database_lsn` (u64be) | 8 | this session's deletion counter (no log yet) |
| 11 | group emptied by this deletion? | 1 | ✓ |
| 12 | deletion kind (0 = from a group) | 1 | always 0 (no holding area) |
| 13 | `collection_id` | 16 | ✓ |
| — | 13 TLV headers × 5 bytes | 65 | |
| 0xFF | `FF ‖ 00 00 00 40 ‖` 64-byte signature | 69 | ✓ |
| | **total** | **12,676** | every certificate in the full run is exactly this size |

The spec's full certificate is about 14.1 KB; the difference is tags 5–7.

**Guarded by:** `test_cert.py` (19), chapter 23.

---

## 16. `index.py`: 128 groups working together

**Job.** Hold the 128 groups, know which group each live record is in, and offer `insert`, `delete`,
`delete_user` (a whole cohort). With commitments on: draw every `r_t`, hold the keys, and turn every
deletion into a signed certificate. **Needs:** `group`, `ids`, `posk`, `cert`, `crypto`, `errors`.
**Spec:** §3.2, §3.5, §5, §7, §9.3–9.8, §11. **Written by:** Claude (Day 2; commitments 3 Oct).

### 16.1 The picture

```
 FIXED (the dataset)                               LIVE (changes)
 vectors  1,000,000 × 384 int32 (shared)           groups[0 … 127]   Group objects (§5.1: never removed)
 row_of   {"doc0": 0, "doc1": 1, "doc6": 2, …}     locator           {live record ID → group number}
 labels   row → group number (from route, §7.1)

 SECRET, in memory only (Part 3 preview)           PUBLIC
 blinding  r_t for every row (OS random)           collection_id (16 random bytes)
 _signing_key   operator's Ed25519 secret          operator_public_key
 _k_scramble    64 random bytes (HMAC key)         issued   every certificate, in lsn order
                                                   next_lsn deletion counter
```

`row_of` (ID → row) answers "which vector is this record?". `labels` (row → group) answers "which group
should it be in?". `locator` (ID → group) answers "is it live right now, and where?".

### 16.2 Line by line ([index.py](../python/sever_demo/index.py))

| Lines | Code | What it does |
|---|---|---|
| 28–36 | `__init__(vectors, ids, labels, k)`; length check | the three inputs must have one entry per row |
| 40–42 | `self.row_of = {rid: row for row, rid in enumerate(ids)}`; uniqueness check | a dict comprehension: ID → row. If two rows share an ID the dict is shorter → refuse |
| 43 | `self.groups = [Group(vectors) for _ in range(k)]` | 128 empty groups sharing the one vector table (`_` = "I don't need the loop number") |
| 44 | `self.locator = {}` | nothing is live yet |
| 46–53 | Part 3 fields | empty until `enable_commitments` |
| 55–67 | `enable_commitments()` | `random_scalars(1,000,000)` → one `r_t` per row (§9.4); `collection_id = os.urandom(16)` (§3.1); `_k_scramble = os.urandom(64)` (§9.7); an Ed25519 key pair (§9.8, epoch 0); then each group gets the `blinding` list and computes its `C_S` (`start_commitments`). Nothing secret is printed, logged or written |
| 69–72 | `scrambled_id(rid)` | §9.7: `HMAC-SHA-512(k_scramble, collection_id ‖ ID bytes)`, 64 bytes |
| 74–81 | `anchors()` | the public "trust anchors" a verifier needs: the format, `d`, and the operator public key for epoch 0 (as hex). Saved as `anchors.json` |
| 83–102 | `_certify(gid, rid)` | builds one certificate, see the flow below |
| 104–112 | `insert(rid)` | `validate_record_id` (§3.2 rules 1–2) → `if rid in self.locator: DuplicateRecord` (rule 3, across **all** groups) → `row = row_of[rid]` → `gid = labels[row]` → `groups[gid].insert(rid, row)` → `locator[rid] = gid` → return `gid` |
| 114–125 | `delete(rid)` | `gid = locator.get(rid)` (`.get` returns `None` if absent) → absent: `(ALREADY_ABSENT, None)`, no certificate → else group delete → remove from locator → with commitments, certify and append to `issued` |
| 127–129 | `delete_user(rids)` | one `delete` per record, in order; returns `[(rid, outcome, gid), …]`. `(rid, *self.delete(rid))` spreads the pair into a triple |
| 131–133 | `group_hashes(gids=None)` | `{gid: blob hash}` for chosen groups (all if `None`) |
| 135–140 | `state_hash()` | SHA-256 over the 128 blob hashes in group order: one fingerprint for the whole index |
| 142–146 | `survivors_check(gid, rng)`, `sizes()` | pass-throughs to the group; the list of `n` |

### 16.3 A committed delete, step by step

```
 index.delete("doc5")
   │  gid = locator["doc5"]                     absent? → AlreadyAbsent, no certificate (§5.4)
   ▼
 groups[gid].delete("doc5", row_of["doc5"])     S −= x̃, n −= 1, member removed,
   │                                            C_S −= C_t, r_agg −= r_t  →  Transition
   ▼
 del locator["doc5"]
   ▼
 _certify(gid, "doc5")
   t = last_transition, then set to None       r_post and S_post are used once, then dropped
   sid = HMAC-SHA-512(k_scramble, collection_id ‖ b"doc5")                       64 B
   lsn = next_lsn; next_lsn += 1               0, 1, 2, … in this session
   ctx = C_S_pre ‖ C_t ‖ sid ‖ u64be(lsn) ‖ collection_id                         152 B
   proof = posk.prove(r_post, S_post, C_S_post, ctx)                              12,352 B
   certificate = cert.issue(facts, _signing_key)                                  12,676 B
   ▼
 issued.append(certificate); last_certificate = certificate
```

**Guarded by:** `test_index.py` (6): every record sits in the group the oracle's §7.1 rule picks, and
each group is exact; a cohort spread over at least 2 groups deletes, every touched group equals its
survivors and every other group's blob is byte-identical; retrying the cohort gives `AlreadyAbsent` for
all and changes nothing; a live ID can't be inserted twice; `"007"` is refused; duplicate dataset IDs
are refused. Plus the certificate tests (chapter 23).

---
## 17. `baselines.py`: the ghost

**Job.** Run two common ways of deleting on the same data as SEVER, and measure the trace each one
leaves (DEMO_PLAN §5.7). **Needs:** nothing from the project. **Written by:** Claude (Day 2). The
formulas are in §4.6 above.

| Method | Delete does | What is left |
|---|---|---|
| SEVER | `S −= x̃`, `n −= 1`, remove the member | nothing: `S` equals the survivors' sum, difference **0** |
| float32 running mean | `m ← (m·n − x) / (n − 1)` | rounding error: not bit-identical to the mean built without the record |
| soft delete | mark the record as deleted | the record itself, still stored, and its full share of the summary |

**Line by line** ([baselines.py](../python/sever_demo/baselines.py))

| Lines | Code | What it does |
|---|---|---|
| 16–18 | `F32 = npt.NDArray[np.float32]` etc. | short names for array types (type hints only) |
| 21–37 | `class FloatRunningMean` | `m` (float32 mean) and `n`. `insert`: `n += 1; m = m + (x − m)/n`. `delete`: if it is the last record, `m` becomes zeros; else `m = (m·n − x)/(n − 1)`; then `n −= 1`. `np.float32(...)` keeps every step in float32 |
| 40–46 | `exact_mean(x)` | the "truth": the survivors' mean in float64, summed **sequentially** (`np.cumsum(…)[-1]`), divided by the count. An empty input gives zeros |
| 49–62 | `@dataclass class GhostReport` | the measured numbers, one field each; `as_dict()` turns it into a dict for JSON |
| 65–71 | `ghost_report(x, q, deleted, rng, cycles=1000)` | `x` = the group's float32 rows in insertion order; `q` = the same rows quantised; `deleted` = True/False per row |
| 80–86 | SEVER side | insert every `q` row into an int64 `s`, subtract the deleted ones, compare with the survivors' sum computed directly. `sever_diff` = largest difference (expected 0) |
| 90–100 | float side | the same insert-all-then-delete with `FloatRunningMean`; compare with (a) `exact_mean` of the survivors (`float_diff`) and (b) a running mean that only ever saw the survivors (`float_same`: bit-identical or not) |
| 104–112 | error growth | 1,000 times: delete a random survivor and insert it again. The true mean never changes, so any movement is pure rounding error. Record the error after 1, 10, 100 and 1,000 cycles |
| 115–116 | soft delete | its summary is the mean of **everything**, deleted included: `Σ q / (count · 2^24)`. `soft_distance = ‖mean_all − mean_survivors‖₂` (the straight-line distance) |

**Real results** (full run, group 118: 161,376 members, 7 deleted):

| Method | Deleted record still stored | Summary vs survivors-only | Bit-identical? |
|---|---|---|---|
| SEVER (integer `S`) | no | **0** | **yes** |
| float32 running mean | no | 2.004e-7 max abs | no |
| soft delete | yes (7) | 2.031e-5 L2 | no |

Float error after 1, 10, 100, 1,000 delete/re-insert cycles: 2.00e-7, 1.99e-7, 2.00e-7, 1.99e-7.
**It did not grow.** DEMO_PLAN expected growth; the data says flat, so the claim is "not bit-identical",
never "it grows" or "it's huge". In the rehearsal shell (group 100: 60,683 members, 10 deleted): float
2.126e-7, soft delete 1.125e-4 with 10 records still stored.

**Guarded by:** `test_baselines.py` (4): the float mean after deletes is not equal to the never-inserted
mean; the same operations on a real `Group` equal the oracle's survivors group; soft delete keeps all 100
deleted records and its distance equals the formula computed in the test; one insert then one delete
gives back zeros.

---

## 18. `ledger.py`: the run record

**Job.** Append one JSON line per run to `docs/RUN_LEDGER.jsonl`, written by code, never by hand
(DEMO_PLAN §5.8, Overview §13.3). **Needs:** nothing. **Written by:** Claude (Day 2).

**JSON Lines** = one complete JSON object per line, so a file can only grow at the end.

| Lines | Code | What it does |
|---|---|---|
| 24–27 | `REPO`, `LEDGER_PATH`, `MANIFEST_PATH`, `IST = ZoneInfo("Asia/Kolkata")` | where things are; India's time zone for the second timestamp |
| 30–36 | `open_ledger(path)` | open in **append mode** (`"a"`) **before the run starts**. If it can't be opened, the error propagates and the run never starts (Overview §13.3: no ledger, no run). `newline="\n"` = the same line ending on every OS |
| 39–42 | `append(handle, entry)` | `json.dumps(entry, sort_keys=True, ensure_ascii=True) + "\n"`, then `flush()` (push it to disk now). `sort_keys` makes the bytes independent of the order the fields were added in |
| 45–50 | `sha256_file(path)` | SHA-256 of a file, 4 MiB at a time |
| 53–55 | `_git(*args)` | runs `git <args>` and returns its output (`check=True`: a git error stops the run) |
| 58–76 | `run_context(command, seed, sabotage)` | the fields known at the start: UTC and IST time, the command, the git commit, `git_dirty` (true if `git status --porcelain` prints anything, i.e. the code that ran is **not** exactly the commit), seed, the manifest's SHA-256, Python/NumPy/OS versions, the sabotage switch |
| 79–83 | `read_entries(path, last=None)` | read the lines back (the shell's `ledger` command) |
| 86–174 | `describe(entry)` (added 3 Oct) | one plain sentence for any line, old or new: "Deleted 57 records (5 cohorts) across 15 groups; 15 of 15 groups exact; 0 other groups changed." Built only from the command's name and number arguments, the outcome, the counts and group numbers, so it **cannot** contain a record ID. A line that already has a `summary` returns it |
| 177–203 | `_describe_run` | the same for a full run (`demo.py`): operations, checks, mismatches, certificates; or where it stopped early |

**Fields added 3 Oct** (older lines lack them): `kind` (how to read `outcome`: `check` → PASS/FAIL,
`action` → Deleted/Inserted/AlreadyAbsent, `setting` → INFO, `run`), `summary` (from `describe`),
`session` (the shell's start time, so `ledger session` can show one sitting), and for shell deletes
`group`, `n_after`, `cert`; for verifies `failed`; for `sabotage off` `rolled_back`.

**A real line** (ledger line 19, the full run, shortened):

```json
{"command": "sever_demo.demo --seed 42", "commitments": true,
 "counts": {"certs_issued": 912, "certs_verified": 912, "certs_rejected": 0, "checks": 2155,
            "mismatches": 0, "ops": 2085, "tamper_caught": 10, "untouched_changed": 0, …},
 "git_commit": "8a8f7fb6…", "git_dirty": true, "outcome": "PASS", "rows_loaded": 1000000,
 "result_file": "results/p1-demo-2026-10-02T215008Z.json", "result_sha256": "…",
 "sabotage": "none", "seed": 42, "total_s": 771.1, "ts_ist": "2026-10-03T03:20:08+05:30", …}
```

`git_dirty: true` is honest but weak evidence: the code wasn't committed yet. The fix is in the plan:
commit, re-run, commit the new line.

**Guarded by:** `test_ledger.py` (6): two runs give two lines and the first line's bytes never change
(T13); key order doesn't change the bytes; the start-of-run fields exist and UTC and IST are the same
instant; a ledger path that is a folder stops the run; `describe` gives the expected sentence for old
lines, new shell lines and full runs (passed, sabotaged, stopped early).

---

## 19. The independent verifier `sever_verify/`

**Job.** Check a certificate with **nothing but the file and the operator's public key**: no database,
no engine code (§11.3). **Needs:** only libsodium. **Written by:** Claude (3 Oct), separately from
`crypto.py` on purpose; a test (`test_architecture.py`) fails if either package imports the other.

```
 anchors.json  ─┐
 000000.cert   ─┼─► python -m sever_verify ─► parse (§11.1) ─► step 1 … step 8 ─► ACCEPTED / REJECTED
                │      (its own process,                                         exit code 0 / 1
                │       its own crypto code)
 engine code  ──X──  never loaded (a test runs it and checks that no sever_demo module was imported)
```

### 19.1 `ristretto.py`: the verifier's own crypto ([file](../python/sever_verify/ristretto.py))

The same building blocks as chapter 12, retyped with different names (`ORDER` for ℓ, `times` for
`mul`, `add`, `linear_combination` for `msm`, `expand_xmd_sha512`, `from_uniform`, `generator_table`,
`to_scalar`, `commitment`), plus `ed25519_verify`. It has **no** signing and **no** randomness: a
verifier only checks. Notable lines:

| Lines | Code | What it does |
|---|---|---|
| 18–39 | `class _Sodium` and `_SODIUM = _Sodium()` | load libsodium once and declare the 5 C functions it uses |
| 54–62 | `times(k, p)` | `k·P` with the same zero rule: `0·P` returns the identity |
| 65–70 | `linear_combination(terms)` | `Σ k_j·P_j`. "Variable time is fine": a verifier's inputs are public, so timing leaks nothing |
| 75 | `blocks = -(-length // 64)` | ceiling division: `−(−65 // 64) = 2` (a common Python trick) |
| 119–124 | `ed25519_verify(pk, message, signature)` | wrong sizes → `False`; else libsodium's `crypto_sign_verify_detached`, which also rejects non-canonical and small-order inputs |

Both implementations pass the same RFC vectors and produce the same 385 generators, byte for byte.

### 19.2 `certificate.py`: parse and check ([file](../python/sever_verify/certificate.py))

**`parse(data, d)` (lines 61–103): strict reading.** For tags 1 to 13, in order: there must be at least
5 bytes left; the tag byte must be exactly the expected tag (so a missing, repeated or out-of-order tag
fails); the value must be fully present; fixed-size fields must have their allowed length:

```
 tag:      1    2      3      4             5      8   9    10   11   12   13
 allowed:  32   0/32   0/32   0/(64+32·d)   0/64   4   64   8    1    1    16      (6, 7: any)
```

Then the trailer must be exactly `FF 00 00 00 40` + 64 signature bytes, with **nothing after it**.
Anything else raises `ParseError`.

**`Report` (lines 48–58).** A list of `(step, status, detail)`. `accepted` (a `@property`) is True only if
at least one step ran and **no step is FAIL**. `NOT CHECKED` is not a failure, and it is never shown as
a pass.

**`verify_proof(proof, c_s_post, ctx, d)` (lines 111–120).** Split the proof into `A` and `d + 1` values
`z`; `A` must be a valid point and every `z` must be `< ℓ` (canonical, §9.9); recompute
`c = SHA-512(DST_POSK ‖ C_S_post ‖ A ‖ ctx) mod ℓ`; accept iff `z_r·H + Σ z_i·G_i == A + c·C_S_post`.

**`verify(data, anchors)` (lines 123–168): the steps of §11.3.**

| Step | Check | Preview |
|---|---|---|
| 1 | strict parse; `C_t`, `C_S_pre`, `C_S_post` are canonical points; `C_t` is not the identity | PASS / FAIL (a parse failure stops here) |
| 2 | Ed25519 signature over `DST_CERT ‖ tags 1–13`, with the anchor key for the certificate's epoch | PASS / FAIL |
| 3 | the insert is in a signed log | **NOT CHECKED** (tags 5–7 empty; a certificate with them filled would FAIL, not pass) |
| 4 | at least 4 of 5 witnesses cosigned | **NOT CHECKED** |
| 5 | ordering: deletion after the insert in the log | **NOT CHECKED** |
| 6a | `C_S_post + C_t == C_S_pre` (public transition check) | PASS / FAIL |
| 6b | the proof of knowledge, with `ctx` rebuilt from tags 2, 1, 9, 10, 13 | PASS / FAIL |
| 6c | "group emptied" flag is 1 exactly when `C_S_post` is the identity | PASS / FAIL |
| 7 | (only for deletion kind 1, the holding area) tags 2–4 empty, tag 11 = 0 | not used by the demo |
| 8 | accept only if nothing FAILed | `ACCEPTED` / `REJECTED` |

Because `ctx` is rebuilt **from the certificate's own fields**, changing the lsn, the scrambled ID, the
collection or `C_S_pre` breaks the proof (step 6b), even if someone could re-sign it.

### 19.3 `__main__.py` and `__init__.py`

`__init__.py` is empty: its presence makes the folder an importable **package**. `__main__.py` is what
`python -m sever_verify <anchors.json> <file.cert> …` runs: fewer than 2 arguments → print usage, exit
code 2; one certificate → print every step (`✓` PASS, `✗` FAIL, `-` NOT CHECKED) and the verdict; several
→ one line each and a summary. Exit code **0** if every certificate is accepted, **1** otherwise, so
other programs can use the result.

**Real output** (rehearsal screenshot 05):

```
certificate 000000.cert, 12,676 bytes
  ✓ PASS        1 parse, canonical points, C_t not identity
  ✓ PASS        2 operator signature (DST_CERT)  (epoch 0)
  - NOT CHECKED 3 insert inclusion in a signed log  (transparency log not built (preview))
  - NOT CHECKED 4 witness cosignatures (>= 4 of 5)  (transparency log not built (preview))
  - NOT CHECKED 5 ordering: lsn > insert leaf index  (transparency log not built (preview))
  ✓ PASS        6a C_S_post + C_t = C_S_pre
  ✓ PASS        6b proof of knowledge of C_S_post (§9.5)
  ✓ PASS        6c group emptied <=> C_S_post is identity
ACCEPTED
```

---

## 20. `receipts.py`: certificates to disk and to the verifier

**Job.** Write certificates as files, run the verifier on them **as a separate program** (the way an
outsider would), and make forged copies. **Needs:** the verifier, but only as a program to run; it
never imports it. **Written by:** Claude (3 Oct).

| Lines | Code | What it does |
|---|---|---|
| 18–28 | `write_receipts(folder, anchors, certificates)` | write `anchors.json`, then `000000.cert`, `000001.cert`, … (`f"{lsn:06d}"` = 6 digits with leading zeros). An existing file is never overwritten |
| 31–39 | `run_verifier(anchors, certs)` | build the command `[python, "-m", "sever_verify", anchors, *certs]` with `PYTHONPATH=python` and run it with `subprocess.run` (start a program, wait, capture its output). Exit code other than 0 or 1 means the verifier itself broke → error |
| 40–48 | (same) | read the verdicts from its printed output: one certificate → does the output end with `ACCEPTED`; several → each line `name: ACCEPTED/REJECTED` |
| 51–57 | `tampered_copy(src, dst, position)` | copy a certificate and flip the lowest bit of one byte (`^= 0x01`): a forged or damaged receipt |

**Guarded by:** the certificate tests and the shell tests (chapter 23); every full run uses it.

---
## 21. `demo.py`: the full acceptance run

**Job.** The full-data run of DEMO_PLAN §6.2: every step on 1,000,000 real vectors, a PASS/FAIL verdict,
a result file and a ledger line. **Needs:** every module above. **Written by:** Claude (Day 2; step 9
on 3 Oct). Run it with `scripts/demo.sh run` (about 13 minutes).

### 21.1 The picture: ten steps, each one can stop the run

```
 open the ledger (no ledger → no run)
   │
   1 manifest: 9 files re-hashed ─────────────── any mismatch → stop
   2 norm check §4.1: SciQ + NQ ──────────────── any failure → stop      (check, never fix)
   3 ID check §3.2: 1,000,000 IDs ────────────── any rejection → stop
   4 centroids (cached) → quantise (cached) → route → insert all rows in "stream" order
  4b commitments: r_t for every record, C_S for every group
   5 delete_user on 10 cohorts (Wikipedia titles) ──► 85 records from 23 groups
   6 survivors check on the 23 touched groups (5 fields); the 105 untouched: blob hash unchanged?
     retry cohort 1 → all AlreadyAbsent, nothing changed?
   7 ghost table on the largest touched group
   8 stress: 2,000 seeded operations, cheap check after each, full check every 50 and at the end
   9 certificates: write all, verify all in a separate process, 10 forged copies must all fail
   │
 finally (even after a crash): write results/p1-demo-<time>.json, append one ledger line
```

### 21.2 Block by block ([demo.py](../python/sever_demo/demo.py))

| Lines | What it does |
|---|---|
| 18–21 | **The import-path fix.** Run as a plain file (`python demo.py` inside `python/sever_demo/`), Python puts *that* folder on the import path and `__package__` is empty, so `import sever_demo` would fail. These lines put `python/` on the path instead. That's why the other imports come after them (the E402 exception in `pyproject.toml`) |
| 55–65 | constants: the cache folder `~/.cache/sever` (never inside `datasets/`, CLAUDE.md §8); `results/`, `results/certs/`; the data paths; `FULL_CHECK_EVERY = 50`; the field names; `TAMPERED = 10` |
| 67 | `console = Console()`: `rich` prints coloured text and tables |
| 70–75 | `manifest_hash(rel)`: look up one file's SHA-256 in the manifest |
| 78–96 | `cached_quantised`: quantise the 1.5 GB NQ file **once**, 50,000 rows at a time, into `~/.cache/sever/nq_1m_q24_<hash>.npy`. The name contains the source file's hash, so changed data can never reuse an old cache. It writes to `….partial.npy` first and then renames it (`tmp.replace(path)`): a crash can never leave a half-written file under the real name |
| 99–105 | `cached_centroids(seed)`: the 128 centres, fitted once per seed and data hash |
| 112–132 | `class Run`: the run's time stamp, a stopwatch per step (`step` prints elapsed time and, under it, the step's "why" line from `guide.RUN_WHY`; `done` records the step's duration) |
| 135–180 | `size_table`, `ghost_table`: the two `rich` tables shown on screen |
| 183–270 | `evidence_table` (added 3 Oct): what the run shows, in plain words: each claim (data pinned, inputs valid, deleting exact, nothing else moves, retry harmless, every check passes, every receipt verifies, forgeries caught), its evidence from the counts, and ✓ / ✗. The ghost row says *measure*, not ✓: it is reported as found, never a gate (Build §2.5). Steps that never ran say *not run* |
| 273–289 | `run()` starts: all counters at 0; 5 fields with commitments, 4 without |
| 291–331 | steps 1–3: each prints PASS/FAIL and **returns early** on any failure |
| 333–344 | step 4: `route` gives every row its group; `default_rng(sub_seed(seed, b"stream")).permutation(n)` gives a seeded insertion order; insert every ID |
| 346–354 | step 4b: `index.enable_commitments()` |
| 356–377 | step 5: all cohort names sorted by UTF-8 bytes, shuffled with the `cohort-order` sub-seed, the first 10 taken; their records deleted with `delete_user`; touched groups collected. Every record is live, so any outcome other than `DELETED` counts as a mismatch |
| 379–419 | step 6: `survivors_check` on each touched group (any False field = a mismatch); `untouched_changed` = untouched groups whose blob hash differs from before; then the retry of cohort 1 |
| 421–441 | step 7: `rows_g = order[labels[order] == gid_g]` = this group's rows **in their insertion order**; a True/False mask of which were deleted; `ghost_report` |
| 443–500 | step 8: see below |
| 507–545 | step 9, `check_certificates`: `write_receipts`, `run_verifier` on all; then 10 certificates chosen with the `tamper` sub-seed, one random bit flipped in each, `run_verifier` again: all must be rejected |
| 548–562 | `main()`: the command-line options `--seed 42`, `--rows`, `--cohorts 10`, `--stress 2000`, `--sabotage none\|SB-1…SB-4`, `--no-commitments`, `--ledger` |
| 565–575 | open the ledger **first**; fill the start-of-run fields; switch on the sabotage if asked (and print a red warning: "this run must FAIL") |
| 577–600 | `try`: run, then decide **PASS** only if manifest, norm, ID, mismatch and untouched counts are all 0, the stress step ran, and (with commitments) every certificate verified and all 10 forgeries were caught |
| 601–604 | `except`: outcome `ERROR`, and only the error's **type** is recorded, because a message could hold data (§17); then the error is raised again |
| 605–624 | `finally` (runs even after an error): timings, the result JSON, its SHA-256 into the entry, the plain `summary` sentence, **one ledger line**, sabotage off |
| 626–635 | print the evidence table, the verdict and the ledger line's sentence; exit code 0 for PASS, 1 otherwise |

**Step 8, the stress loop (lines 443–500).** A seeded random generator picks one of three operations
each time:

```
 u = random number in [0, 1)
 u < 0.2 and some deleted IDs exist  → delete one of them again: must be AlreadyAbsent, S and n unchanged
 u < 0.6 and some deleted IDs exist  → re-insert one of them (it is live again)
 otherwise                           → delete a random dataset ID (if it was live, remember it as deleted)

 after every operation, on the group it touched:   S == fresh_sum(members)  and  n == len(members)
 every 50th operation:                            the full survivors check (all fields, incl. the blob)
 at the end:                                      the full check on every group the stress touched
```

The full blob check is expensive on big groups (about 0.5 GB of hashing for group 118), so it runs
every 50 operations, not after each one. The DEMO_PLAN asks for exactly this split.

### 21.3 The real result (2 Oct 2026, 21:50 UTC, seed 42, commitments on) → **PASS**

| Step | Result | Time |
|---|---|---|
| 1 manifest | 9 files, 0 mismatches | 49.7 s |
| 2 norms | 13,679 + 1,000,000 rows, 0 failures, worst 1.836e-7 | 63.6 s |
| 3 IDs | 1,000,000, 0 rejected, all unique | 1.5 s |
| 4 build | 128 groups: min 74, median 2,252, max 161,376 | 31.0 s |
| 4b commitments | 1,000,000 `r_t`; 128 `C_S` | 9.4 s |
| 5 delete_user | 10 cohorts → 85 records from 23 groups | 14.1 s |
| 6 survivors | **23 / 23** groups pass all 5 fields; **0 of 105** untouched groups changed; retry: all AlreadyAbsent | 22.3 s |
| 7 ghost | SEVER 0; float32 2.0e-7 (flat); soft delete 7 still stored | 24.9 s |
| 8 stress | 2,000 ops (827 delete, 390 delete-absent, 783 re-insert), **0 mismatches**; final full check on 92 groups, 0 failures | 464.1 s |
| 9 certificates | **912 issued, 912 accepted**, 12,676 bytes each; **10 / 10 forgeries rejected** | 88.4 s |
| **total** | | **771.1 s** |

The numbers add up: operations `2,085 = 85 + 2,000`; certificates `912 = 85 (step 5) + 827 (stress
deletes)`; checks `2,155 = 23 (step 6) + 2,000 (cheap) + 40 (every 50th) + 92 (end)`.

---

## 22. `repl.py`: the live demo shell

**Job.** An interactive shell (`sever>` prompt) around the same code `demo.py` uses, for the live demo
(DEMO_PLAN §5.9). Every state-changing or checking command writes a ledger line. Since 3 Oct it also
guides: a 13-step tour, a plain-words note and a "→ next" hint after every result, grouped `help`, and
`explain <word>`. **Needs:** `demo.py`, `guide.py` and everything they need. **Written by:** Claude
(Day 3; Part 3 commands and guidance on 3 Oct).

**How `cmd.Cmd` works.** Python's standard `cmd` module reads a line such as `delete doc2015226`, takes
the first word, and calls the method `do_delete("doc2015226")`. Each `do_…` method's docstring is
its `help <command>` text. `cmdloop()` repeats this until a method returns `True` (`quit`).

**`guide.py`: the words, no logic.** Every sentence the shell adds lives in
[guide.py](../python/sever_demo/guide.py), so wording can be read and corrected in one place:
`HELP_GROUPS` (commands in demo order), `NOTES` (the note under each result), `NEXT_HINT` (what to type
next), `FIELD_INFO` (the plain meaning of each §5.5 field), `SABOTAGE_BUGS`, `GLOSSARY` and `ALIASES`
(for `explain`, each term with its spec section), `TOUR` (13 `TourStep`s mirroring DEMO_RUNBOOK §B)
and `RUN_WHY` (the "why" line under each step of `demo.py`).

**The one rule the guidance must not break.** The runbook's numbers (57 records, 15 groups, …) come
from the shell's seeded random generator, which only `verify` (the rebuild shuffle), `delete_user N`
and `stress` use. Nothing new draws from it, and `verify` draws exactly as before
(`survivors_report` does the same single rebuild as `survivors_check`). So the same commands in the
same order, typed or run by the tour, give the same numbers. A test runs the tour and the typed
commands side by side and compares them.

### 22.1 Helpers ([repl.py](../python/sever_demo/repl.py))

| Lines | What it does |
|---|---|
| 29–34 | the same import-path fix as `demo.py` |
| 89–114 | `TICK`/`CROSS`, the bug names, `KIND` (which ledger `kind` each command writes) and the colour of each outcome in the `ledger` table |
| 117–120 | `short(value)`: the first 16 hex characters of a hash or point, for the screen |
| 123–128 | `lsn_byte(cert)`: find the position of the **last byte of tag 10** (`database_lsn`). It walks the TLVs of tags 1–9 (`pos += 5 + length`), then skips tag 10's 5-byte header and 7 of its 8 value bytes. Flipping that byte's lowest bit changes the lsn by one, as if the receipt were reused for another deletion |
| 131–145 | `cached_norm_report`: the norm check's result, cached under the file's manifest hash (so it only applies to those exact bytes, which `verify_data` re-checks). This keeps `load` fast live. `demo.py` always recomputes |
| 148–163 | `field_values`: one §5.5 field of the live and rebuilt snapshots as short text, for the `verify` table |
| 166–189 | `diagnose`: plain words for a failed survivors check. If **only the blob** differs with commitments on, every visible field matches, so the difference must be the hidden `r_agg` (the SB-4 lesson); its value is never printed |
| 192–216 | `@dataclass class Session`: everything a loaded index needs: the index, IDs, cohorts, float32 rows (for the ghost), insertion order, seed, the set of IDs deleted in this session, and a cohort → IDs lookup built on first use |
| 222–260 | `SeverShell.__init__`: the ledger handle, the seed, a `Console(record=True)` (it remembers everything printed, so `save` can write it as an SVG), a seeded random generator (sub-seed `repl`), `self.last` (read by tests), notes on/off, a session ID, the group in focus, the blob hashes seen so far, the tour position, and the sabotage backups |
| 263–268 | `_set_prompt`: `sever> `, or `sever [SB-4 ON]> ` while a bug is on. With piped input the prompt is empty and `precmd` echoes each command through the console instead, so screenshots show what was typed |
| 278–287 | `log(command, outcome, …)`: one ledger line as `repl <command>`, with `kind`, `session` and `summary` (from `ledger.describe`). A delete is logged as `delete <id>`, **never** with the real ID (§17) |
| 289–309 | `note(key)` prints guide.NOTES[key], wrapped, after a `┊`; `hint(key)` prints `→ next: …`, or `next (step k)` while a tour runs. Both only while notes are on; hints wait while `next` runs a multi-command step |
| 316–324 | `group_arg`: a group number, or an error that says what to type (`verify needs a group number, e.g. verify 3`) |
| 326–337 | `remember` / `same_as`: blob hashes seen this session per group; when a hash comes back, print "the same blob hash as before `delete doc3`" |
| 339–346 | `backup(gids)`: while a sabotage is on, save each touched group's `S` (a copy), `n`, members (a copy), `r_agg` and `C_S` **before** the broken code runs |
| 374–394 | `tour_values`: the tour's group (3, as in the runbook) and its first two live IDs, chosen once and kept, so step 9's retry deletes step 4's record |
| 396–419 | `preloop` prints the banner (the claim, how to start); `precmd` echoes piped commands |
| 421–435 | `onecmd`: catches `ValueError` and `IndexError`, prints the type and message, carries on. Started from `main()` (`keep_going`), it also survives any other error with a one-line message; tests leave it off so bugs still fail loudly |
| 437–449 | `emptyline` (Enter does nothing); `default` (an unknown word: "did you mean verify?") |

### 22.2 The commands

| Command | Does | Ledger line |
|---|---|---|
| `tour [k \| off]` | the 13 steps, ✓ done, ▶ next; `tour k` jumps (tour 2 skips the slow data check) | — |
| `next` | one tour step: a rule `Step k of 13 · title`, a **Say:** line, its commands (echoed, run through `onecmd`), a **Look for:** line. Refuses politely without a loaded index | the commands' own |
| `help [cmd]` | commands grouped Start / Look / Delete / Prove / Break it / Record / Guide; one command's docstring | — |
| `explain [word]` | a term in plain words with its § (case and aliases ignored; close matches suggested) | — |
| `notes on\|off` | show or hide notes and hints | — |
| `status` | loaded / live / deleted records, certificates, bug, tour step, this session's ledger lines | — |
| `verify_data` | re-hash the data files against the manifest | PASS/FAIL |
| `load [N]` | norm check (cached), ID check, quantise (cached), route, insert N rows (default all), group-size table; with commitments: all `r_t`, all `C_S`, a certificate folder `results/certs/repl-<time>/` | PASS/FAIL |
| `stats` | the size table and the 5 largest groups | — |
| `group <g>` | `n`, the SHA-256 of `S`, the blob hash, `C_S`: the "before" values | — |
| `ids <g>` | the first 5 live IDs of a group (to pick one to delete) | — |
| `find <id>` | live in which group, or deleted (no marker left), or not loaded | — |
| `delete <id>` | delete one record: `n` before → after, blob hash before → after; with commitments `C_S` before → after and the `C_t` it moved by, the public check `C_S_post + C_t = C_S_pre`, and the certificate file (`C_t` is read from bytes 5–36: tag 1's value after its 5-byte header) | `Deleted` / `AlreadyAbsent` |
| `insert <id>` | put a deleted record back; says when the blob hash equals one seen earlier (delete, insert, delete returns to the exact same hash) | `Inserted` |
| `delete_user <title \| N>` | delete one cohort by title, or N random cohorts (titles shown); per touched group: records removed, `n` after, ✓/✗ per field; untouched groups that changed | PASS/FAIL |
| `verify <g>` | the survivors check: a table of each field's live value vs the rebuilt-from-survivors value, ✓/✗, `EXACT` or `MISMATCH` with a plain diagnosis, plus `S` vs a fresh sum | PASS/FAIL |
| `ghost [g]` | the three-way ghost table; by default on the group with the most deletions (and it says so) | PASS/FAIL |
| `stress <n>` | n seeded random operations, cheap check after each, full check every 50 and at the end. Refuses while a sabotage is on | PASS/FAIL |
| `sabotage` | (no argument) a table of SB-1…SB-4: what each does, breaks, and how to see it here. SB-1 and SB-3 **cannot** show in the shell: SB-1 fires only on an empty group's first insert, and SB-3's retry is stopped earlier by the index's locator | — |
| `sabotage SB-1…SB-4` | switch one planted bug on (and remember the locator and deleted set); the prompt shows it | INFO |
| `sabotage off` | switch it off and **roll back** every group the bug touched to its saved state, plus the locator and deleted set | INFO |
| `cert [last\|all\|k]` | run the independent verifier (separate process) on certificates; a legend says what steps 1, 2, 6a–6c mean and why 3–5 are NOT CHECKED | PASS/FAIL |
| `tamper [last\|k]` | copy a certificate, change its lsn by one bit (`lsn_byte`), verify it: must be REJECTED | PASS if caught |
| `ledger [n\|session]` | the last n lines, or this session's: #, time, command, outcome, **what happened** (from `describe`), git commit (`*` = dirty), with a legend | — |
| `save <name>` | everything printed since the last save → `results/screens/<name>.svg` (the "saved" line itself is kept out of the next screen) | — |
| `quit` (or Ctrl-D) | sabotage off, say how many ledger lines this session wrote, leave | — |

**A real run of `tamper last`** (screenshot 06): the forged copy fails **step 2** (the signature no
longer matches the bytes) **and step 6b** (the proof is bound to the lsn through `ctx`), so it is
`REJECTED`. **A real run with SB-4** (screenshot 12): `C_S` ✓ but blob ✗ (`r_agg` inside it is wrong), the
public check still "holds", the diagnosis names the hidden `r_agg`, and the certificate fails 6b:
`REJECTED`.

---
## 23. The tests

**233 tests in 16 files, all passing** (re-run 3 Oct after the guidance work, 152.7 s). **38** of them
are must-fail tests: they pass only if a planted bug or a forgery is caught.

### 23.1 pytest in two minutes

```python
def test_quant_ties_to_even():                      # pytest runs every function named test_…
    halves = np.array([[0.5, 1.5, 2.5, -0.5]], dtype=np.float32) * 2.0**-24
    assert quantise(halves).tolist() == [[0, 2, 2, 0]]   # a false assert = a failed test

@pytest.mark.parametrize("bad_value", [np.nan, np.inf, -np.inf])   # run once per value (3 tests)
def test_quant_rejects_non_finite(bad_value):
    with pytest.raises(ValueError, match="non-finite"):   # passes only if this error is raised
        quantise(...)
```

| Tool | Meaning | Example |
|---|---|---|
| `tmp_path` | a fresh empty folder for this test, deleted afterwards | `test_ledger.py` |
| `monkeypatch.setattr(module, "NAME", value)` | change a module's value for this test only, then put it back | switching on `SABOTAGE` |
| `@pytest.fixture` + `yield` | a set-up function: tests that name it get its result; code after `yield` cleans up | `shell` in `test_repl.py` |
| `@pytest.mark.mustfail` | a label; `pytest -m mustfail` runs only these (`--strict-markers` rejects unknown labels) | 36 tests |

### 23.2 The two rules that make the tests mean something

1. **Expected values come from the spec, never from the code under test.** `tests/spec_oracle.py` is a
   small model written from the spec text: plain Python integers, no NumPy, nothing imported from
   `sever_demo`. Each test keeps its **own** list of which records should be live, asks the oracle what
   the group must look like, and compares.
2. **Spec constants are written out in the test**, not imported (`SPEC_TOL = 8 * 2**-23`,
   `BOUND = 2**24 + 16`, `ELL = 2**252 + …`). If someone loosened the code's value, an imported value
   would loosen the test with it.

Proof that rule 1 matters (from `notes/P1-group.md`, 2 Oct): three bugs planted in `group.py` (S written
little-endian; `compare()` always "equal"; members sorted by row instead of ID) passed the old,
code-driven tests but turned **12**, **1** and **12** of the new tests red.

### 23.3 The helpers

| File | What it gives the tests |
|---|---|
| [synthetic.py](../tests/synthetic.py) | small fixtures (Build §2.7): `D = 16`, `K = 4` groups, `SEED = 42`; `unit_rows(n)` = n random length-1 float32 rows; `quantised_rows(n)`; `record_ids(n)` = `doc0, doc1, …` |
| [spec_oracle.py](../tests/spec_oracle.py) | `group_sum` (§5.3), `group_blob` (the demo layout, §5.5), `nearest` (§7.1: sequential float64, ties to the smaller label), `observed` / `expected` / `field_diffs` (the 4 fields, each on its own); and for the Part 3 preview `committed_blob` and `committed_field_diffs` (all 5 fields). Its `C_S` comes from the **verifier's** code, which shares nothing with the engine |
| [vectors/rfc9496_ristretto255.json](../tests/vectors/rfc9496_ristretto255.json) | published ristretto255 answers: 16 multiples of the generator, 29 invalid encodings, 7 + 4 `from_uniform_bytes` inputs |
| [vectors/rfc9380_expand_xmd_sha512.json](../tests/vectors/rfc9380_expand_xmd_sha512.json) | 10 `expand_message_xmd` answers (RFC 9380 K.3) |
| [vectors/rfc8032_ed25519.json](../tests/vectors/rfc8032_ed25519.json) | 3 Ed25519 key/signature answers (RFC 8032 §7.1) |

A **test vector** is a published input with its correct output. Matching it proves the code computes the
standard function, not something that only looks like it.

### 23.4 Every test file

| File | Tests | What it proves | Ch. |
|---|---|---|---|
| `test_data.py` | 7 | norm check: good rows pass, NaN/±inf counted once, the tolerance edge on both sides, row numbers across chunks | 7 |
| `test_quant.py` | 9 | ties to even (both signs), the bound, NaN/±inf, round trip ≤ 2^-25, shape | 8 |
| `test_partition.py` | 6 | sub-seeds, G-1, the pinned k-means, ties, fast = sequential routing, pure function | 9 |
| `test_ids.py` | 18 | 9 valid, 8 invalid IDs; no ID in the error text | 11 |
| `test_crypto.py` | 74 | both crypto implementations against RFC 9496, 9380, 8032; zero scalar; §4.5 mapping; generators; additivity | 12 |
| `test_group.py` | 18 | see below | 13 |
| `test_group_commitments.py` | 9 | see below | 13 |
| `test_posk.py` | 13 | the proof: format, challenge, honest proofs verify, every kind of tampering fails | 14 |
| `test_index.py` | 6 | routing to the oracle's group, multi-group `delete_user` (T11), retry, duplicates | 16 |
| `test_baselines.py` | 4 | the float ghost (T14), SEVER exact on the same data, soft delete keeps the records | 17 |
| `test_ledger.py` | 6 | append-only (T13), key order, start fields, no ledger → no run, `describe` | 18 |
| `test_cert.py` | 19 | see below | 15, 19 |
| `test_stress.py` | 2 | see below | 21 |
| `test_sabotage.py` | 14 | see below | 13 |
| `test_architecture.py` | 2 | the verifier never imports the engine, and the engine never imports the verifier: it reads each file's `import` lines with Python's own parser (`ast`) | 19 |
| `test_repl.py` | 26 | see below | 22 |

**`test_group.py` (18):** a new group is the oracle's empty group, with `S` as int64; the blob for
d = 2 equals bytes **written out by hand**, byte by byte; T5 insert-then-delete restores all fields (also
from empty); T6 a second delete is `AlreadyAbsent` and changes nothing (also for a never-inserted ID);
T7 a live duplicate is refused; an ID can be re-inserted after deletion; a delete with the wrong row
raises `IntegrityViolation`; T8 after 20 random deletes the group equals the oracle's survivors group;
T9 100 shuffled insert orders give the oracle's blob every time; T10 deleting everything gives the
empty group, which still works; IDs read back out of the blob are in UTF-8 byte order (`Z, a, ab, b, é`);
n = 1,000,000 is allowed and the next insert refused; error messages never contain the ID; `compare`
flags exactly the one corrupted field, for each field; `survivors_check` catches `S` off by one;
`survivors_report` gives the same verdict and leaves the random generator where `survivors_check`
does (so the shell's numbers don't move).

**`test_group_commitments.py` (9):** `start_commitments` gives the oracle's `C_S` and the `SEVERG`
layout; insert-then-delete restores the blob, `C_S` and `r_agg`; random deletes match the oracle on all 5
fields and **every** deletion satisfies `C_S_post + C_t = C_S_pre`, with `C_t` recomputed by the
verifier's code; a repeated delete changes nothing; an emptied group has `C_S` = identity and
`r_agg` = 0; the committed blob equals hand-written bytes (with `r_t` = 5 and 7, `r_agg` = 12);
corrupting only `C_S` is flagged as `C_S`; `survivors_check` returns 5 fields; no blinding values → refuse.

**`test_cert.py` (19):** a certificate from a real deletion is accepted with exactly the expected step
statuses (1, 2, 6a, 6b, 6c PASS; 3, 4, 5 NOT CHECKED); the layout and total size match §11.1; `tlv`
matches the hand-written encoding; the strict parser rejects a missing, repeated or out-of-order tag, a
wrong length, trailing bytes and a missing trailer (6 cases); **flipping any single byte** (every 37th,
plus the last and the signature's first) is rejected; a different operator key fails step 2. Then four
attacks re-signed with a key the test holds (so the signature is valid and the other checks must catch
them): `C_t` = identity fails step 1; claiming "nothing changed" fails 6a or 6b; reusing the proof with
another lsn fails 6b; a false "emptied" flag fails 6c. Emptying a group is disclosed (flag 1, `C_S_post`
= identity, accepted). SB-4 passes 6a but fails 6b. A certificate contains no `r_t`, no `r_agg` and no
`doc5`. The command-line verifier, run as its own process, accepts the file, rejects a 1-bit change
(exit code 1), and **loads no engine module** (the test checks Python's list of loaded modules).

**`test_stress.py` (2):** T12: 2,000 seeded operations (delete, delete-absent, re-insert) on 300 records;
after **every** operation the touched group is compared with the oracle; every kind of operation must
happen more than 100 times; the group sizes add up to the live count. A second test: 600 operations
with commitments, all 5 fields after each, and every certificate accepted (more than 100 of them).

**`test_sabotage.py` (14): how a must-fail test works.**

```
 for each (bug, named test) pair, 13 pairs:
     monkeypatch: group.SABOTAGE = "SB-2"           ← switch the bug on, for this test only
     with pytest.raises(AssertionError):            ← this test PASSES only if …
         test_group.test_insert_then_delete_restores_state()   … the named test FAILS
 plus: SABOTAGE is None by default
```

The 13 pairs: SB-1 → T5 from empty, T8, T11, T12, committed T8; SB-2 → T5, T8, T11, T12, committed T8;
SB-3 → T6; SB-4 → committed T8, committed T5. A planted bug that no test catches would mean a missing
test (Overview §9.2: a test that never fails proves nothing).

**`test_repl.py` (26)** drives the real shell on synthetic data, with a temporary ledger: `delete` then
`verify` is exact, the retry is `AlreadyAbsent`, the ledger shows `Deleted, PASS, AlreadyAbsent` and
never `doc3`; `delete_user` by title is exact on every group; `sabotage SB-2` turns `verify` red,
`sabotage off` rolls back to the exact earlier blob; `ghost` shows SEVER exact; `stress 300` has 0
mismatches; `group`, `ledger`, `save` work; typos print `ValueError` / `IndexError` instead of
crashing. With commitments: a delete writes `000000.cert` and the verifier accepts it; `tamper` is
rejected with steps 2 and 6b failing; 8 cohort certificates all verify; SB-4 shows `C_S` ✓ and blob ✗,
its certificate is rejected, and `off` restores the group; no `r_t` ever appears in the ledger or on
screen; `repl.py` and `demo.py` run as plain files.

Added 3 Oct (guidance): every command is in `help`; `explain` finds terms by alias and suggests close
ones; `notes off` hides notes and hints; **the tour and the same commands typed give identical ledger
lines, groups and certificate count**; `next` refuses without a loaded index; delete → insert returns
the exact blob hash (and the shell says so); SB-2's `verify` shows `n` not moving and names the count,
SB-4's names the hidden `r_agg` without printing it (both must-fail); errors say what to type; an
unexpected error stops a test but not the live shell; `save` doesn't leak into the next screenshot;
every new ledger line has `kind`, `session` and a `summary` equal to `describe`, and no record ID.

---
## 24. The scripts

### 24.1 `scripts/demo.sh`: one entry point for everything

**Why it exists:** the project's `.venv` lives on `/mnt/c` (the Windows drive), where every file read
crosses the Windows–Linux bridge. Importing scikit-learn took **63 s** there and **3.4 s** (1.0 s warm)
from `~/.venvs/sever-demo` on the Linux side (measured 2 Oct). The script builds and uses that second
environment from the same `uv.lock`; the project's `.venv` is untouched.

```bash
#!/usr/bin/env bash                        # run this file with bash
set -euo pipefail                          # -e stop at the first error; -u an unset variable is an
                                           #  error; pipefail: a failure inside a pipe counts
cd "$(dirname "$0")/.."                    # go to the repo root, wherever the script was called from
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/sever-demo" PYTHONHASHSEED=0 PYTHONPATH=python
                                           # uv uses the fast environment; fixed hash seed; python/ importable
cmd="${1:-repl}"                           # the first argument, or "repl" if none
shift || true                              # drop it; the rest ("$@") is passed on
case "$cmd" in
  setup) exec uv sync --frozen ;;          # install exactly what uv.lock says (never update it)
  repl)  exec uv run python -m sever_demo.repl "$@" ;;
  run)   exec uv run python -m sever_demo.demo "$@" ;;
  test)  exec uv run pytest -q "$@" ;;
  *)     echo "usage: …" >&2; exit 2 ;;    # anything else: usage on the error stream, exit code 2
esac                                       # exec = replace this shell with the command
```

### 24.2 `scripts/clean_clone_check.sh`: does the committed code work on a fresh copy?

```
 SRC  = this repo           WORK = a new temp folder (deleted at exit, always: `trap 'rm -rf …' EXIT`)
 1. git clone SRC → WORK/repo          only COMMITTED files come along (it warns if SRC has uncommitted work)
 2. link the three data folders        the data is never in git; the manifest check proves the bytes
 3. uv sync --frozen → WORK/venv       a brand-new environment, from uv.lock only
 4. pytest                             all tests
 5. smoke run: 50,000 rows, 100 stress ops, ledger in WORK (the real ledger is not touched)
 6. "CLEAN CLONE OK"
```

**Status:** it can only test what is committed. Today the code isn't committed, so the real check is
still open (PROGRESS: "passes on the working tree, simulated").

### 24.3 `scripts/rehearsal.txt`: the scripted demo

39 shell commands, fed to the shell with `scripts/demo.sh repl < scripts/rehearsal.txt`. After each
step a `save NN-name` writes what was shown as `results/screens/NN-name.svg`. Because the shell's random
choices are seeded, the same commands in the same order give the same numbers.

---

## 25. The results

### 25.1 `docs/RUN_LEDGER.jsonl`: 63 lines, written by code

| Lines | When (UTC, 2 Oct) | What | Outcome |
|---|---|---|---|
| 1 | 20:12 | smoke run, 50,000 rows, no commitments | PASS (220 ops, 254 checks, 0 mismatches) |
| 2 | 20:18 | the same with `--sabotage SB-2` | **FAIL, 140 mismatches**, as required |
| 3 | 20:21 | **full run, 1,000,000 rows, no commitments** | PASS (2,085 ops, 2,155 checks, 0 mismatches, 475.7 s) |
| 4–16 | 21:02–21:03 | first shell rehearsal: verify_data, load, delete, verify, delete_user 5, retry, ghost, SB-2 red then green, stress 200 | as expected (SB-2 `verify` FAIL, everything else PASS) |
| 17 | 21:39 | smoke run with commitments | PASS: 63 certificates, 63 accepted |
| 18 | 21:42 | 20,000 rows with `--sabotage SB-4` | **FAIL**: 31 mismatches, **37 certificates, 0 accepted** |
| 19 | 21:50 | **full run with commitments** (chapter 21) | **PASS**: 912 / 912 certificates, 10 / 10 forgeries caught, 771.1 s |
| 20–40 | 22:05–22:08 | shell rehearsal with commitments | as expected |
| 41–61 | 22:12–22:14 | the scripted rehearsal that made the 14 screenshots | as expected |
| 62–63 | 22:40–22:43 | warm-up `load` and `verify_data` | PASS |

Every line has `git_dirty: true`. A sabotage run is supposed to say FAIL: that FAIL is the evidence that
the tests can see the bug.

### 25.2 `results/p1-demo-*.json`: six result files

Each one is `{"ledger_entry": …, "results": {norms, group_sizes, survivors, retry_ok, ghost, stress,
certificates}}`, and its SHA-256 is in its ledger line, so it can't be changed unnoticed.

| File | Ledger line | Run |
|---|---|---|
| `p1-demo-2026-10-02T201235Z.json` | 1 | smoke, PASS |
| `p1-demo-2026-10-02T201802Z.json` | 2 | SB-2, FAIL (as required) |
| `p1-demo-2026-10-02T202108Z.json` | 3 | full, no commitments, PASS |
| `p1-demo-2026-10-02T213959Z.json` | 17 | smoke with commitments, PASS |
| `p1-demo-2026-10-02T214236Z.json` | 18 | SB-4, FAIL (as required) |
| `p1-demo-2026-10-02T215008Z.json` | 19 | **full with commitments, PASS: the headline result** |

### 25.3 `results/screens/01…14.svg`: the backup screenshots

Made by the shell's `save` command during the scripted rehearsal (not hand-made). Open them in a browser.

| # | Shows (real text from the screenshot) |
|---|---|
| 01 | `PASS: 9 files re-hashed, 0 mismatches (75s)` |
| 02 | norm checks 0 failures; `ID check §3.2: 1,000,000 IDs, 0 rejected`; sizes 74 / 2,252 / 161,376; commitments for 1,000,000 records, 128 groups |
| 03 | group 3: n = 4,606, hash of `S`, blob hash, `C_S`; live IDs `doc2015226, doc273331, …` |
| 04 | `Deleted from group 3 (n = 4,605)`; blob and `C_S` before → after; `public check C_S_post + C_t = C_S_pre: holds`; `000000.cert (12,676 bytes)`; `verify 3`: five ✓, **EXACT** |
| 05 | the verifier: steps 1, 2, 6a, 6b, 6c ✓; 3–5 NOT CHECKED; **ACCEPTED** |
| 06 | the forged copy (lsn changed by one bit): ✗ step 2, ✗ step 6b, **REJECTED** |
| 07 | `delete_user 5`: 57 records, 15 groups all ✓ (including groups of 153,302 and 161,374); `untouched groups changed: 0 of 113`; `58 accepted, 0 rejected` |
| 08 | the same delete again: `AlreadyAbsent: no group touched, nothing changed` |
| 09 | the ghost (group 100: 60,683 members, 10 deleted): SEVER 0 / yes; float32 2.126e-07 / no; soft delete yes (10) / 1.125e-04 / no |
| 10 | SB-2 on: `n` ✗ and blob ✗ (n = 4,605 but 4,604 members), **MISMATCH** |
| 11 | `sabotage off: 1 group(s) rolled back`; **EXACT** |
| 12 | SB-4 on: `C_S` ✓ but blob ✗; the public check "holds"; certificate step 6b ✗, **REJECTED** |
| 13 | `sabotage off`; **EXACT** |
| 14 | the last 20 ledger lines as a table |

Not in git (on purpose): `results/certs/<run>/` with `anchors.json`, the `.cert` files and the
`tampered/` copies (chapter 6.4).

---

## 26. The writing about the code

| File | Status | What it is |
|---|---|---|
| `README.md` | new | the front page: the claim, the layout, how to run it, the latest full run |
| `docs/DEMO_RUNBOOK.md` | new | §A before the review (commit, test, run, clean clone, warm caches, tag); §B the live script with what you'll see and what to say for each of 15 steps; §C what to do when something breaks; §D words to avoid ("proved secure", "the error grows", "Part 3 is done", …) |
| `docs/PROGRESS.md` | modified | where things stand (Claude's draft, marked for you to confirm) |
| `docs/notes/README.md` | new | the index of the notes and the commands |
| `docs/notes/P1-idea.md` | new | **your** five sentences: still a 4-line draft |
| `docs/notes/P1-data.md` | new | `data.py`; replaces the two deleted notes below |
| `docs/notes/P1-quant.md` | new | `quant.py`, with 11 trap questions |
| `docs/notes/P1-ids.md` | new | `ids.py`, `errors.py` |
| `docs/notes/P1-group.md` | new | `group.py`, `index.py`, the oracle, sabotage. **Read this one first** |
| `docs/notes/P1-partition.md` | new | `partition.py` |
| `docs/notes/P1-ledger-baselines.md` | new | `ledger.py`, `baselines.py` |
| `docs/notes/P1-demo-run.md` | new | both full runs and their findings |
| `docs/notes/P1-commitments.md` | new | the Part 3 preview, with toys mod 101 and 6 trap questions |
| `docs/notes/P1-data-facts.md` | **deleted** | your Day 1 printout of the three datasets; its facts now live in `P1-data.md` |
| `docs/notes/project-demo-notes.md` | **deleted** | your Day 1 notes on normalisation; merged into `P1-data.md` |

Each `P1-*.md` note has the same sections: one line, why, how it works, decisions, measured results,
tests, trap questions (answers folded away), open fixes.

---

## 27. Things that don't quite match (yet)

Found while writing this guide. None breaks a test, but each one is a question a reviewer could ask.

| # | What | Where | Suggested fix |
|---|---|---|---|
| 1 | The plan still says "three deliberate sabotages", "8 slides", "four fields", "four ticks", and its `sabotage` command lists only SB-1–SB-3. Q&A 9 still lists commitments and certificates as not covered | DEMO_PLAN §1.1, §5.9, §8 step 5, §10 Q9 | update to 4 sabotages, 9 slides, 5 fields; Q9: "previewed, not built properly" |
| 2 | The shell's `help sabotage` text lists SB-1–SB-3, but SB-4 works | [repl.py:520](../python/sever_demo/repl.py#L520) | add SB-4 to the docstring |
| 3 | `P1-group.md` says the sabotage file has 10 cases (SB-1–SB-3); it has 13 (plus SB-4) | `docs/notes/P1-group.md` | update the count |
| 4 | `P1-partition.md` lists 5 tests and describes one as "k-means twice gives the same centroids"; there are 6, and that test compares with a `KMeans` call written out in the test | `docs/notes/P1-partition.md` | update the list |
| 5 | `NotNormalised` is defined but never raised; `quant.py` raises plain `ValueError` | [errors.py:19](../python/sever_demo/errors.py#L19) | known Day 1 shortcut (P1-quant.md); say so if asked |
| 6 | Certificates issued while a sabotage was on (`000058.cert`, `000059.cert` in the rehearsal) stay in the session's folder after `sabotage off`; the rollback restores only the groups in memory | `repl.py` `do_sabotage` | fine for a demo; know the answer |
| 7 | Every ledger line has `git_dirty: true` | `docs/RUN_LEDGER.jsonl` | commit, re-run `scripts/demo.sh run`, commit the new line (runbook §A) |
| 8 | CLAUDE.md §7 names a top-level `verifier/`; the demo's verifier is `python/sever_verify` | CLAUDE.md §7 | already an open question (G-5) in PROGRESS |
| 9 | Gap G-1 (k-means seed mod 2^32) is handled in code, but its decision entry is not written | `SPEC_GAPS.md`, overview §6 | write the DB entry |
| 10 | Spec §4.1 says correct data lands "within 1 ULP"; the worst real row is 1.54 | spec §4.1 | a candidate gap entry (your decision) |
| 11 | `check_manifest` and `load_ids_and_cohorts` have no unit test | `data.py` | a test with a temporary manifest |

---

## Glossary (one line each)

| Word | Meaning |
|---|---|
| embedding | a list of 384 numbers that represents a passage's meaning |
| normalised | length exactly 1 (within 8 float32 steps) |
| quantise / Q24 | `x̃ = round(x · 2^24)` as an integer |
| group, centroid | a bucket of similar vectors; its centre point |
| `S`, `n` | a group's exact integer sum and count |
| canonical blob | the group state as one fixed byte layout |
| survivors check | live group == a group rebuilt from the survivors only, field by field |
| idempotent | doing it twice is the same as doing it once (`AlreadyAbsent`) |
| ghost | a deleted record's leftover influence |
| sabotage / must-fail | a planted bug that a named test must catch |
| oracle | a separate, simple model that gives the expected answers |
| scalar, point, ℓ | a number mod ℓ; a group element (32 bytes); the group's order |
| `r_t`, `r_agg` | a record's random blinding value; a group's total of them |
| `C_t`, `C_S` | a record's commitment; a group's commitment |
| proof of knowledge | proof that you know the secrets inside a commitment, without showing them |
| Fiat–Shamir | making the challenge a hash, so no live verifier is needed |
| nonce | a one-time random number; reusing it leaks secrets |
| Ed25519 | the signature scheme used for certificates |
| HMAC, scrambled ID | a keyed hash; the record ID hidden behind it |
| TLV | tag ‖ length ‖ value, a strict binary format |
| test vector | a published input with its correct output |
| lsn | "log sequence number": here, the session's deletion counter |
| ledger | the append-only record of runs |
| `git_dirty` | the code that ran differs from the commit |
