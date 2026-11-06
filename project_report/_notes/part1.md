# Part 1 "The Idea" - reader notes

Scope: crates sever-types, sever-quant, sever-partition, sever-index, sever-search, sever-p1, sever-tracekit, sever-spec, sever-explain; Python sever_partition (C-15), sever_refmodel_core (C-18), sever_testkit, sever_demo; spec §2-§8; Build plan §4; golden/p1_*.

Tag key: [CODE: path:Lx-Ly] seen in code; [DOC: path §N] only a doc says it; [INFERRED: why]; [NOT FOUND: what]. All paths are relative to /home/saiki/sever-db. Line numbers were checked with grep -n / sed -n.

Part 1 claim (one sentence): deleting a vector returns its group, bit for bit, to the state it would have had if the vector had never arrived. [DOC: CLAUDE.md §6.1; docs/SEVER-DB_BUILD_PLAN_PART_1-2.md §4.1]
Part 1 is frozen: tag `part-1-frozen` exists [CODE: `git tag` output: part-1-frozen, part-2-frozen-e1, part-2-frozen-e2, part-3-frozen, part-4-frozen, v1.0.0]; hashes in freeze/PART-1.sha256 [CODE: ls freeze].

---

## 0. Crate map and which part owns what

| Crate / package | Role | Part | Evidence |
|---|---|---|---|
| sever-types | IDs, constants, errors, SecretBuf | 1 | [CODE: crates/sever-types/src/lib.rs:1-23] |
| sever-quant | normalisation check, Q24, dequantise | 1 | [CODE: crates/sever-quant/src/lib.rs:1-8] |
| sever-partition | parse/validate `partition.svp` | 1 | [CODE: crates/sever-partition/src/lib.rs:1-6] |
| sever-index | groups, accumulators, routing, flush, plan/apply, blob | 1 | [CODE: crates/sever-index/src/lib.rs:1-8] |
| sever-search | IVF-flat search + pinned kernel (scalar, AVX2) | 1 | [CODE: crates/sever-search/src/lib.rs:1-5] |
| sever-p1 | composition root, `sever-demo` CLI, ghost baselines | 1 | [CODE: crates/sever-p1/src/lib.rs:1-15] |
| sever-tracekit | replay reference-model traces through the Rust index | 1 (test tooling) | [CODE: crates/sever-tracekit/src/lib.rs:1-8]; listed in freeze/PART-1.sha256 (3 lines mention crates/sever-tracekit) |
| sever-spec | proc-macro `#[spec("SR-...")]` that tags tests | 1 (test tooling) | [CODE: crates/sever-spec/src/lib.rs:1-40]; in freeze/PART-1.sha256 (2 lines) |
| sever-explain | "why did this record go there / which groups does a search open" | NOT Part 1. Added 23 Oct 2026 by decision DB-108 for the Studio demo; only built into the `inspect` flavour of sever-py | [CODE: crates/sever-py/Cargo.toml:19 `inspect = ["sever-db/inspect", "dep:sever-explain"]`]; [CODE: crates/sever-explain/Cargo.toml description "DB-108; the inspect build only"]; [NOT FOUND: any line of sever-explain in freeze/PART-1..4.sha256 (grep -c gives 0 for all four)] |
| python/sever_partition | C-15 builder + independent Ledoit-Wolf oracle | 1 | [CODE: python/sever_partition/build.py:1-11] |
| python/sever_refmodel_core | C-18 reference model | 1 | [CODE: python/sever_refmodel_core/__init__.py] |
| python/sever_testkit | seeds, synthetic data, traces, streams, gates, ledger, spec_trace | 1 (extended later) | [CODE: python/sever_testkit/*.py] |
| python/sever_demo | renders the demo JSON as a one-page HTML report | 1 | [CODE: python/sever_demo/render.py:1-8] |

Architecture rule: sever-index, sever-quant, sever-search have no file I/O, clock or random-number source. Confirmed for sever-index: its dependencies are only sever-types, sever-quant, sever-partition, sha2, hmac [CODE: crates/sever-index/Cargo.toml dependencies block]. The scrambling key is handed in [CODE: crates/sever-index/src/scramble.rs:17-27]. sever-p1 (the only crate that touches OsRng) pulls in `rand_core` with `getrandom` [CODE: crates/sever-p1/Cargo.toml dependencies; crates/sever-p1/src/root.rs:3,13-19].

---

## 1. Record IDs (§3.2) and errors (§17)

### 1.1 Record-ID rules
Spec §3.2 [DOC: docs/SEVER-DB_SPECIFICATION.md §3.2, lines 215-233]:
1. UTF-8 string of 1 to 256 bytes (bytes, not characters).
2. Must NOT match `^[+-]?[0-9]+$` (so `1`, `007`, `-3`, `+3` rejected; `doc0`, `nq-1234`, UUIDs accepted). Reason: group contents must not depend on arrival order, so IDs must come from the dataset, not a counter; "a heuristic, not a proof".
3. Must not equal a currently live record's ID in the collection. A deleted ID may be inserted again (new insert).

Where each rule is enforced:
- Rules 1-2: `RecordId::new` / `RecordId::from_bytes` in sever-types [CODE: crates/sever-types/src/id.rs:39-55]; core logic `check_record_id` [CODE: crates/sever-types/src/id.rs:80-95] (length first: `Empty`, `TooLong`; then shape: `CounterShaped`). `is_counter_shaped` [CODE: id.rs:98-101]: strip one leading `+` or `-`, then require non-empty and all `is_ascii_digit` (explicitly NOT `is_numeric`, which would accept digits like U+0663).
- Non-UTF-8 bytes: `from_bytes` returns `NotUtf8` [CODE: id.rs:51-55].
- Rule 3: not in sever-types. `Index::plan_insert` looks the scrambled ID up in the locator (through the `Draft` overlay) and returns `DuplicateRecord { same_commitment }` [CODE: crates/sever-index/src/index.rs:287-295]. In Part 1 `same_commitment` is "identical quantised vector" because `NoExtension::same_commitment` is `live_x == new_x` [CODE: crates/sever-index/src/ext.rs:99-101].
- `RecordId` wipes its bytes on drop (`Zeroize`) and its `Debug` prints only the length [CODE: id.rs:29-35, 73-77]. Ordering is by UTF-8 bytes (Rust `String` ordering) [CODE: id.rs:25-27 derive Ord; doc comment lines 20-24].
- On delete, an ID that breaks rules 1-2 can never be live, so it simply yields `AlreadyAbsent` (not an error) [CODE: index.rs:761-765].
- Python model: `check_record_id` uses `re.compile(r"[+-]?[0-9]+")` with `fullmatch` plus the 1..256 byte-length test [CODE: python/sever_refmodel_core/model.py:107-113, regex at line 23-ish `_COUNTER`].
- Order of checks inside `plan_insert` (§15.1): quantise/normalise first (§4.1), then record-ID rules, then scramble, then "not live", then `ext.admit`, then route, then capacity, then flush [CODE: index.rs:282-331]. The model uses the same order: `check_vector`, `check_record_id`, quantise, duplicate, route, capacity [CODE: model.py:417-441].

### 1.2 Related ID types in sever-types
- `GroupId` enum: `Frozen(FrozenLabel)`, `Spawned([u8;8])`, `Holding` [CODE: id.rs:112-123]. Text forms: `frozen-NNNN` (4 digits, label 0-9999, `FROZEN_LABEL_MAX = 9999`), `spawn-` + 16 lowercase hex, `holding` [CODE: id.rs:146-216; spec §5.1]. `GroupId::parse` is strict (exact 4 digits / exactly 16 lowercase hex) [CODE: id.rs:195-216]. Ordering is by bytes of the text form (not by variant) [CODE: id.rs:226-232; doc id.rs:108-111].
- `CollectionId([u8;16])` [CODE: id.rs:259-270]; `ScrambledId([u8;64])` [CODE: id.rs:285-296].
- `GroupId::to_padded_bytes` returns the form zero-padded to 32 bytes (the stored form of §13.2/§14.3) [CODE: id.rs:154-182].

### 1.3 Error enum (§17) - every variant
All in `sever_types::Error` [CODE: crates/sever-types/src/error.rs:35-86], with `thiserror`. Messages are fixed text; no variant stores a record ID, vector value, key or `r_t` [CODE: error.rs:1-5; tests error.rs:160-168]. The enum deliberately includes variants raised only by later parts so later parts never edit this frozen enum [CODE: error.rs:3-4].

| Variant | file:line | Meaning (spec) | Raised in Part 1? |
|---|---|---|---|
| `WrongDimension` | error.rs:38 | §4.1 step 0, gap G-8/DB-60 | yes (quant) |
| `NonFinite` | error.rs:41 | §4.1 step 1 | yes |
| `NotNormalised` | error.rs:44 | §4.1 step 3: `|norm-1| > 8*2^-23` | yes |
| `InvalidRecordId(InvalidRecordIdReason)` | error.rs:47 | §3.2 rules 1-2 | yes |
| `DuplicateRecord { same_commitment: bool }` | error.rs:51-54 | §3.2 rule 3 | yes |
| `CommitmentMismatch` | error.rs:57 | §9.3 | no (Part 3) |
| `BadUserSignature` | error.rs:60 | §9.8 | no (Part 3) |
| `GroupCapacityExceeded` | error.rs:63 | §5.6: n would exceed 1,000,000 | yes |
| `UnknownCollection` | error.rs:66 | no such collection | no |
| `SeededNonceForbidden` | error.rs:69 | §9.6 | no (Part 3) |
| `PlatformUnsafe { check: &'static str }` | error.rs:72-75 | §12.8/12.9 | only "OS CSPRNG unavailable" in sever-p1 [CODE: crates/sever-p1/src/root.rs:13-19] |
| `IntegrityViolation { invariant: &'static str }` | error.rs:79-82 | §21 invariants, artefact checks | yes (many labels, see below) |
| `DurabilityFailure` | error.rs:85 | §12.7 fsync failure | no (Part 2) |

`InvalidRecordIdReason` variants [CODE: error.rs:11-20]: `Empty` (line 12), `TooLong` (14), `NotUtf8` (16), `CounterShaped` (19). 13 spec rows => 13 variants (test `p1_types_every_spec_17_row_is_a_variant`) [CODE: error.rs:122-156].

`AlreadyAbsent` is NOT an error: it is an `Outcome` [CODE: crates/sever-index/src/changeset.rs:155-166 (enum Outcome)]; spec §5.4.

IntegrityViolation labels Part 1 uses (all fixed strings): "INV-1 (§4.2 bound)" [CODE: quant lib.rs:73-75, 93-95]; "§6.3 artefact truncated / sha256_artefact mismatch / magic / version / d / k_frozen / precision not finite / centroids or tau / trailing bytes / encoder" [CODE: partition lib.rs:55-181]; "§7.2 q < 0" [CODE: route.rs:19-24 area; mahalanobis]; "§7.1 no frozen group", "§7.3 unknown group", "§7.4 spawn target 0", "§5.1 frozen label", "§7.5 spawn ID collision", "INV-4", "INV-5", "INV-6 n", "INV-6 S", "INV-7", "INV-8", "INV-9 mirror" [CODE: index.rs:171-174, 180-184, 243-245, 326-328, 554-611, 845-849].

Python model has a parallel error hierarchy: `SeverError` with `kind` strings; `WrongDimensionError`, `NonFiniteError`, `NotNormalisedError`, `InvalidRecordIdError`, `DuplicateRecordError`, `GroupCapacityExceededError`, `IntegrityViolationError` [CODE: python/sever_refmodel_core/model.py:34-85]. Its `kind` is compared against Rust's `error_kind` (Debug name) in traces [CODE: sever-tracekit lib.rs insert branch, `error_kind(&e) == want`].

---

## 2. Q24 quantisation (§4.1-4.3)

### 2.1 Constants (exact)
[CODE: crates/sever-types/src/constants.rs]
- `DIMENSION_V1 = 384` (line 6); code accepts any `d` that is a multiple of 8 (doc lines 1-3; partition parse line 138).
- `FRACTIONAL_BITS = 24` (9); `SCALE = 1 << 24 = 16_777_216` (12).
- `NORM_TOLERANCE_ULPS = 8` (15); `NORM_TOLERANCE = 8 / 8_388_608.0 = 9.5367431640625e-7` (18) - i.e. 8 * 2^-23, exact because dividing by a power of two. Test asserts `NORM_TOLERANCE == 8.0 * f64::from(f32::EPSILON)` [CODE: constants.rs:84-87].
- `MAX_ABS_QUANTISED = SCALE + 16 = 16_777_232` (55). `MAX_ACCUMULATOR_BITS = 44` (58). `MAX_GROUP_MEMBERS = 1_000_000` (24).

### 2.2 Normalisation check (never normalises) - `check_normalised`
[CODE: crates/sever-quant/src/lib.rs:24-48]
Order:
0. `x.len() != d` -> `WrongDimension` (before anything is read; a NaN in a wrong-length vector still reports dimension) (lines 26-28).
1. any non-finite -> `NonFinite` (30-32).
2. `sum += (f64)v * (f64)v` sequentially from i=0 in float64 (36-41), `norm = sum.sqrt()`. f32->f64 exact and the square of a 24-bit significand fits in 53 bits, so only the additions round.
3. `(norm - 1.0).abs() <= NORM_TOLERANCE` else `NotNormalised` (43-47). Boundary: exactly 8 ULPs above 1.0 passes, 9 fails; below 1.0 spacing halves so 16 steps pass, 17 fail [CODE: quant lib.rs tests 205-232].

### 2.3 Quantisation
- Formula (§4.2): `x~_i = round_half_to_even((f64)x_i * 2^24)`, stored as `i32` [DOC: spec §4.2].
- Per component: `(f64::from(x) * SCALE_F64).round_ties_even() as i64` [CODE: quant lib.rs:55-58]. Both the widening and the multiplication by a power of two are exact; the rounding is the only inexact step.
- `quantise(x, d)` runs `check_normalised` then converts each to `i32` with `i32::try_from(...)`; failure -> `IntegrityViolation "INV-1 (§4.2 bound)"` (never a wrap) [CODE: lib.rs:67-79]. It is the ONLY path from floats to a `QVec` (INV-1: "no bypass") [CODE: lib.rs:4-6, 66].
- `QVec(Box<[i32]>)` [CODE: lib.rs:64]. `QVec::from_stored(values, d)` re-checks dimension and the `|x~| <= 2^24+16` bound for bytes the engine wrote itself [CODE: lib.rs:85-98]. `Debug` prints `QVec(<redacted, d = N>)` [CODE: lib.rs:128-133].
- Bound reasoning: after the check `|x_i| <= norm <= 1 + 8*2^-23`, so `|x~_i| <= 2^24 + 16 = 16,777,232 < 2^31` [DOC: spec §4.2; CODE: lib.rs:71].
- Accumulators: `S_i` is `i64`; with n <= 10^6, `|S_i| <= 1.6777232e13 < 2^44` leaving 19 bits headroom [DOC: spec §4.4; CODE: constants.rs:89-98 test].
- Golden vector: `golden/p1_quant_half_steps.json` (rows with `x_f32_bits`) "produced independently by NumPy" [CODE: quant lib.rs:251-260].
- Python: `arith.quantise` is `np.round(x.astype(float64) * SCALE).astype(int32)` (np.round = half-to-even) [CODE: python/sever_partition/arith.py:128-131]; model `quantise` same [CODE: model.py:102-104].

### 2.4 Dequantisation (§4.3)
- `dequantise_f64`: `x^_i = (f64)x~_i / 2^24`, exact (an i32 has <= 31 significant bits) [CODE: quant lib.rs:111-116, 136-138]. Used for routing.
- `dequantise_f32`: the exact f64 rounded once to nearest even by `as f32` (exact when `|x~| <= 2^24`) [CODE: lib.rs:120-125, 141-143]. Used for the search mirror (§12.6).

---

## 3. The partition artefact `partition.svp` and its builder C-15

### 3.1 Byte layout (all big-endian, fixed width)
[DOC: spec §6.3] confirmed by Python encoder [CODE: python/sever_partition/artefact.py:38-57] and Rust parser [CODE: crates/sever-partition/src/lib.rs:113-181] and by an offset test [CODE: python/sever_partition/tests/test_partition.py ~line 130 "artefact_layout_by_offset"].

| Offset | Size | Field | Notes |
|---|---|---|---|
| 0 | 8 | magic `b"SVDBPART"` | partition lib.rs:12 |
| 8 | 2 | u16be format_version = 1 | lib.rs:14; parse 133 |
| 10 | 2 | u16be d | multiple of 8, > 0 (lib.rs:136-140) |
| 12 | 2 | u16be k_frozen | 1..=10,000 (`MAX_FROZEN_GROUPS = 10_000`, lib.rs:16; check 141-144) |
| 14 | 8 | u64be seed (the RUN seed, not the derived k-means seed) | |
| 22 | 8 | f64be tau (drift threshold, §6.2 step 6) | |
| 30 | 8 | f64be lw_shrinkage | |
| 38 | 8 | u64be m (reference rows) | Python decode reads offset 38 [artefact.py:75] |
| 46 | 32 | sha256_reference | artefact.py:76 |
| 78 | 2 | u16be encoder_len | FIXED_PREFIX = 78 [artefact.py:14-15] |
| 80 | encoder_len | encoder UTF-8, e.g. `repo@commit` | |
| next | 8*k*d | centroids f64be, row-major, label order | |
| next | 8*d*d | precision matrix P f64be, row-major | |
| last | 32 | sha256_artefact = SHA-256 of every preceding byte | |

Total size check: golden small artefact (d=16, k=4) is 2686 bytes [CODE: golden/p1_partition_small.json "bytes": 2686; ls shows p1_partition_small.svp 2686 bytes]. Arithmetic: 80 + encoder("test-encoder@0" = 14) + 8*(4*16) + 8*(16*16) + 32 = 80+14+512+2048+32 = 2686 [INFERRED: summing offsets; matches file size].

### 3.2 Rust parser checks (order)
[CODE: crates/sever-partition/src/lib.rs:113-181]
1. Length >= 32; SHA-256 of all bytes but the last 32 must equal the last 32 ("§6.3 sha256_artefact mismatch"). Done FIRST so no field of a corrupted file is trusted (lines 114-124).
2. Magic, version (1), `d != 0 && d % 8 == 0`, `1 <= k_frozen <= 10_000`.
3. Reads seed, tau, lw_shrinkage, m, sha256_reference, encoder length+bytes (must be UTF-8), centroids `k*d` f64, precision `d*d` f64. `f64s` refuses to allocate more than the remaining bytes can fill (fuzzer finding P1-T12; regression file `golden/p1_regression_artefact_oom.bin`) (lines 92-106).
4. Exact length: trailing bytes rejected (157-159).
5. Precision all finite; centroids all finite; tau finite and `>= 0` (161-166).
All failures are `IntegrityViolation` naming the check, never a value (DB-64, spec §6.3).
Returned `PartitionArtefact { d, k_frozen, seed, tau, lw_shrinkage, m, sha256_reference, encoder, centroids, precision, sha256_artefact }` [CODE: lib.rs:20-43]; helpers `centroid(label)` and `precision_row(a)` return `None` out of range [CODE: lib.rs:184-193].
The artefact hash is recorded in collection metadata and in every ledger entry [DOC: spec §6.3]; the Rust Part 1 code itself just keeps `sha256_artefact`.

### 3.3 How C-15 builds it
File: python/sever_partition/build.py (steps numbered as spec §6.2).
- Inputs: reference embeddings `datasets/processed/sciq_reference/embeddings.npy` (SciQ dataset, float32 m x d), checked against `meta.json` hash `encode.sciq.sha256_rows` or it refuses (exit 2) [CODE: build.py:168-176]. Encoder string = `repo_id@revision` from `meta["pins"]["repos"]["encoder"]` [CODE: build.py:170-171].
- Constants: `SHRINKAGE_TOL = 1e-12`, `THRESHOLD_TOL = 1e-9`, `K_FROZEN_V1 = 128`, `PERCENTILE = 99.0` [CODE: build.py:33-38].
- Step 0: `arith.check_rows_normalised` (every reference row obeys §4.1) [build.py:85; arith.py:116-125, uses `np.cumsum(x64*x64, axis=1)[:, -1]` = sequential].
- Step 1: quantise then dequantise every row; everything later uses X^ in float64 [build.py:88-89].
- Step 2: scikit-learn `KMeans(n_clusters=128, init="k-means++", n_init=10, max_iter=300, tol=1e-4, algorithm="lloyd", random_state=sub_seed(seed,"kmeans") % 2**32)` inside `threadpool_limits(limits=1)` for bit-reproducibility [build.py:91-104]. The `% 2**32` exists because scikit-learn accepts only seeds < 2^32 (DB-57) [DOC: spec §6.2 step 2].
- Step 3: pooled residuals `xhat - centroids[labels]` [build.py:106-107].
- Step 4: ONE `LedoitWolf(assume_centered=False).fit(residuals)` over all stacked rows (not an average of per-group fits) [build.py:119-122].
- Step 5: precision `P = Sigma^-1` by Cholesky: `scipy.linalg.cho_factor` / `cho_solve(factor, eye)` [build.py:59-63, 125].
- Step 6: `tau = np.percentile(mahalanobis_dists, 99.0, method="linear")` where the distances use the engine's summation order (`arith.mahalanobis`) [build.py:66-74, 128].
- Step 7 (independent oracle): `lw_oracle.ledoit_wolf(residuals)` is plain NumPy implementing Ledoit-Wolf 2004 Theorem 1 with no scikit-learn code; the builder raises `OracleDisagreementError` (nothing written) unless shrinkage agrees to 1e-12 and tau (recomputed through the oracle's own Sigma) to 1e-9 [CODE: build.py:130-137; lw_oracle.py:1-34].
- Output: `artefact.encode(...)`; writes `artefacts/partition-seed<seed>.svp` and a summary `.json` (seed, sha256_artefact, bytes, tau, lw_shrinkage, oracle diffs, m, min/max group sizes, encoder, sabotage env) [CODE: build.py:178-201].

Seeds: `SEEDS = (42, 123, 777, 2024, 9999)`; `sub_seed(seed, label) = u64 from first 8 bytes of SHA-256(u64be(seed) || label)` with labels `("kmeans","stream","cohort-order","corpus")` [CODE: python/sever_testkit/seeds.py:9-23]. Seeds feed only data order, synthetic data and k-means - never keys, r_t, nonces or collection_id [CODE: seeds.py docstring; crates/sever-p1/src/root.rs:21-23].
Commands: `PYTHONHASHSEED=0 PYTHONPATH=python uv run python -m sever_partition.build --all-seeds` (or `--seed N`, `--root`, `--out`) [CODE: build.py:1-4, 159-166; CLAUDE.md §9]. Existing outputs in artefacts/: partition-seed{42,123,777,2024,9999}.{svp,json} [CODE: ls artefacts].
Number of groups: 128 frozen groups in v1 (spec §2.2 + `K_FROZEN_V1`); the code accepts 1..=10,000 and any d multiple of 8 (DB-49).
Spawn size: 200 (`SPAWN_TARGET_SIZE`) [CODE: constants.rs:27]; small fixtures use 8 [CODE: crates/sever-p1/src/data.rs:292; python/sever_testkit/streams.py `SPAWN_TARGET = 8`].

Python artefact codec (used by tests and the model): `encode` / `decode` [CODE: artefact.py:38-89]. Differences from the Rust parser, see §14.

Config files: spec §18.2 describes `configs/partition.yaml`; see §14 (file does not exist; values are hard-coded in build.py). The pre-registration is `configs/experiments.yaml` (seeds, datasets, encoder revision, deletion rungs 0.10/0.25/0.50/0.75/0.90, arms, targets T1-T6) [CODE: configs/experiments.yaml:1-60].

Golden: `golden/p1_partition_small.svp` + `.json` = d=16, k=4 artefact from `synthetic.clustered(600, 16, 4, seed=42)`, seed 42, tau 5.5608744..., lw_shrinkage 0.6442497..., m 600, encoder "test-encoder@0", sha256 `2f53a6fe...3bd5` [CODE: golden/p1_partition_small.json]. The Rust test `include_bytes!`s it as an independent cross-check of the byte layout (builder-to-importer) [CODE: partition lib.rs:201-204].

---

## 4. Groups, spawning, routing

### 4.1 Group kinds (§5.1)
[DOC: spec §5.1] and [CODE: crates/sever-index/src/index.rs:45-52 `GroupKind`].
- Frozen: `frozen-NNNN`, created at collection creation from the artefact's centroids (label = row order); has an accumulator; searchable [CODE: index.rs:177-187].
- Spawned: `spawn-` + 16 lowercase hex; created by a holding-area flush; accumulator; searchable.
- Holding area: `holding`, one per collection; NO accumulator, NOT searchable [CODE: index.rs:199 `Group::new(GroupId::Holding, GroupKind::Holding, vec![0.0; d], d)`; apply skips mirror for Holding at index.rs:375-378].
Groups are never removed, merged, renamed or re-fitted (spec). Empty groups stay and still take a probe slot.
Group state `GroupState { s: Vec<i64>, n: u64, ext_public, ext_secret }`, initial S=0,n=0 [CODE: changeset.rs:31-54 (struct 31, `empty` ~42)].

### 4.2 Routing (§7) - `Index::route`
[CODE: index.rs:233-276]; pure function of `(x~, state)` with `k` and `N` before this insert (INV-16). No clock, no counter, no "latest group".
1. `xhat = x.dequantise_f64()`.
2. §7.1 nearest FROZEN group: `sq_dist_f64(xhat, centroid)` sequential f64; strict `<` keeps the smaller label on ties (lines 237-242). `sq_dist_f64` [CODE: crates/sever-index/src/route.rs:10-17].
3. If `spawning_enabled` is false (the frozen-only control arm), go to the nearest frozen group (246-248).
4. §7.2 Mahalanobis `d_M = sqrt(q)` with `delta = x^-mu`, `y_a = sum_b P[a][b]*delta_b` (sequential), `q = sum_a delta_a*y_a` (sequential); `q < 0` -> `IntegrityViolation "§7.2 q < 0"` [CODE: route.rs:21-38]. If `d_M <= tau` -> that frozen group (250-252), "in-distribution".
5. Out-of-distribution: spillover first: spawned groups with room, where "room" is `2*k*n < 3*N` in u128 integers (`has_room`, index.rs:141-143; constant ratio `CAPACITY_MULTIPLIER = (3,2)`, constants.rs:31). Pick the nearest by `sq_dist_f64`, ties to smaller group-ID bytes (`dist == bd && g.id < b.id`) (259-275). If none -> `GroupId::Holding`.
6. Exact integers: `has_room` uses `u128`, so no overflow.

### 4.3 Holding area and flush (§7.4-7.5)
- A record routed to Holding is stored (with its secret) but not added to any accumulator, not in N, not searchable; always deletable at once [DOC: spec §7.4; CODE: index.rs:304-312, 782-785].
- Flush trigger: when `holding.slots.len() + 1 == cfg.spawn_target` (200 in v1, 8 in small fixtures) the same plan calls `draft.flush(slot)` [CODE: index.rs:305-308]. `flush` [CODE: index.rs:840-897]: cohort = all held slots + the new one; `gid = spawn_id(cohort ids)`; fail with `IntegrityViolation "§7.5 spawn ID collision"` if it already exists; sums S/n over the cohort (S += x~ for each), `ext.add`; centroid `mu_i = ((f64)S_i / 2^24) / n` computed once, then frozen (lines 862-867); pushes `CreatedGroup`, a `GroupChange` (before = empty state), a `Put` of the new slot into Holding then `DrainInto { from: Holding, to: gid }`; locator updates; departures from Holding and arrivals into the new group (a flush is a departure for Part 4's key rotation); `N += founders` and `k += 1` (§7.6); outcome `Placed(Spawned(gid))`.
- Spawned group ID: first 8 bytes of `SHA-256( for each id ascending by bytes: u16be(len) || id_bytes )`, shown as 16 hex [CODE: index.rs:147-159 `spawn_id`]. Depends only on membership, not creation order. Golden: `golden/p1_spawn_id.json`.
- Spawned groups have no tau and never spawn further groups; their centroid never moves, even as spillover arrives [DOC: spec §7.5].
- Counters §7.6: N increases on every insert into a frozen/spawned group and by 200 on each flush; decreases on deletion from a frozen/spawned group; unchanged for holding insert/delete. `k` +1 per flush [CODE: index.rs:755 `big_n += 1` in `join`; 784 `big_n -= 1` in `delete`; 891-892 in `flush`].
- Capacity (§5.6): hard cap `n + 1 > MAX_GROUP_MEMBERS` -> `GroupCapacityExceeded` [CODE: index.rs:314-317]; startup/invariant INV-5 `floor(1.5*N/k) <= 1,000,000` [CODE: index.rs:592-597].

### 4.4 scrambled_id and HMAC (§9.7)
- `scrambled_id = HMAC-SHA-512(k_scramble, collection_id || record_id_bytes)`, 64 bytes [DOC: spec §9.7; CODE: crates/sever-index/src/scramble.rs:31-40 (impl `scramble`), struct at 17]. Trait `IdScrambler` = extension point EP-2 [CODE: scramble.rs:9-12].
- `k_scramble` is 64 bytes from the OS CSPRNG, `collection_id` 16 bytes from the OS CSPRNG, both created in the composition root (`new_index`) - sever-index itself has no entropy [CODE: crates/sever-p1/src/root.rs:24-36]. The key sits in `SecretBuf` (zeroed on drop) and the temporary uses `Zeroizing` [CODE: scramble.rs:23-27; root.rs:25].
- `scrambled_id` is the only name used below the API: locator map `HashMap<ScrambledId,(GroupId, usize)>` [CODE: index.rs:136], `Slot.scrambled_id` [CODE: changeset.rs:12-20]. Golden: `golden/p1_scramble.json` (key 00..3f, collection_id 0xaa*16, Python hmac).
- Tracekit uses a fixed test key `[0x5a; 64]` and `CollectionId([0;16])` since scrambled IDs are never compared with the model [CODE: sever-tracekit lib.rs:35, ~line 198].

### 4.5 Cohort
A cohort = the set of records deleted together by `delete_user` (e.g. all passages of one article title). The engine does not store cohorts; the caller supplies the ID list [DOC: spec §3.5]. In code: `Index::plan_delete_many(Vec<DeleteRequest>)` is one atomic ChangeSet [CODE: index.rs:341-347]. In the demo/traces, cohort = Natural-Questions article title, from `ids.jsonl`'s second column [CODE: crates/sever-p1/src/data.rs:156-190; python/sever_testkit/slices.py:1-12; python/sever_testkit/traces.py:70-87].

---

## 5. Exact accumulators, plan/apply, five-field equivalence

### 5.1 Arithmetic (§5.3)
Insert: `S += x~_t; n += 1` (plus, in later parts, `r_agg += r_t; C_S += C_t`). Delete: `S -= x~_t; n -= 1` (and `r_agg`, `C_S` in Part 3). All fields change together (INV-2). In Part 1 only S and n (and the extension, which is `()`) exist.
- Join (insert into frozen/spawned): `*acc += i64::from(v)` per component, `st.n += 1`, `ext.add(...)`, `counters_after.big_n += 1`, then `put` [CODE: index.rs:747-757].
- Subtract (delete): `*acc -= i64::from(v)`, `st.n -= 1`, `ext.remove(...)` [CODE: index.rs:825-836].
- Empty group: when `n` reaches 0, `S` is exactly 0 (and C_S identity, r_agg 0 in later parts). Because S is integer, subtract is the exact inverse of add [DOC: spec §5.4].

### 5.2 Membership check before subtracting; idempotent delete; physical excision
- Membership: `Draft::delete` looks the scrambled ID up (`locate`); if absent it pushes `Outcome::AlreadyAbsent`, changes nothing [CODE: index.rs:767-776]. This prevents a retried delete subtracting twice (SB-3 breaks exactly this).
- `ext.check_removal` runs before the subtraction (EP-1 capability 5; no-op in Part 1) [CODE: index.rs:781].
- Physical excision with no deletion marker: swap-with-last then truncate: `SlotOp::MoveLast { from: last, to: i }` then `SlotOp::Truncate { len: last }`; locator for the moved slot is updated and the deleted ID's locator entry removed [CODE: index.rs:786-816]. In `apply`, Truncate also zero-fills the removed float32 mirror rows before releasing (`tail.fill(0.0)`) and truncates `mirror_ids` (RecordId zeroes itself on drop) [CODE: index.rs:398-411].
- Holding-area deletes also excise (no accumulator change, N unchanged) [CODE: index.rs:782-785].

### 5.3 plan / apply and ChangeSet
- Rule (Build §1.1): every mutation is computed by a pure `plan` returning a `ChangeSet`; all validation is in `plan`; `apply` cannot fail [CODE: index.rs:278-282, 349-353; lib.rs:3-5].
- `plan_insert(&self, InsertRequest<E>) -> Result<ChangeSet<E>, Error>` [CODE: index.rs:282]; `plan_delete(&self, DeleteRequest)` [335]; `plan_delete_many(&self, Vec<DeleteRequest>)` [341]; `apply(&mut self, ChangeSet<E>)` [353] (returns nothing). Wrappers `insert`, `delete`, `delete_many` do plan then apply [446, 457, 469].
- Planning several steps over an unchanged index uses a private `Draft` overlay (`lens`, `moved`, `locator` overrides, `new_slots`) so each step in a `delete_user` sees the state the previous step left [CODE: index.rs:614-722].
- `ChangeSet<E>` fields [CODE: crates/sever-index/src/changeset.rs:169-199]: `created: Vec<CreatedGroup>`, `groups: Vec<GroupChange<E>>` (pre- and post-state per touched group), `slots: Vec<SlotOp<E>>`, `locator: Vec<LocatorOp>`, `counters_before/after: Counters{big_n,k}`, `departures`, `arrivals` (Vec<(GroupId, ScrambledId)>; Part 4 rotates keys exactly for these domains), `outcomes: Vec<Outcome>`. `is_noop()` when nothing changes.
- `SlotOp` variants: `Put{group,index,slot}`, `MoveLast{group,from,to}`, `Truncate{group,len}`, `DrainInto{from,to}` [CODE: changeset.rs:68-105]. `LocatorOp`: `Put`, `Delete` [107-124]. `Placement`: `Frozen`, `Spawned`, `Holding` [144-153]. `Outcome`: `Placed(Placement)`, `Deleted{from}`, `AlreadyAbsent` [155-166].
- EP-3 = ChangeSet: Part 2 logs it before applying, Part 3 builds the certificate from it, Part 4 rotates keys for departures [CODE: changeset.rs:1-4].
- EP-1 `GroupExtension` (capabilities 1-9: GroupPublic, GroupSecret, RecordSecret, Credential types; `admit`, `add`, `remove`, `check_removal`, `blob_region`, `check_group`, `same_commitment`; const `BLOB_MAGIC`) [CODE: crates/sever-index/src/ext.rs:11-73]. Part 1 ships `NoExtension` with magic `SEVERC` and empty region [CODE: ext.rs:77-102].

### 5.4 The five fields of "state equivalence" (§5.5)
Two group states are equivalent iff all five are equal: (1) `S`, (2) `n`, (3) `C_S` (the extension's public state; `()` in Part 1), (4) the canonical blob byte for byte, (5) the member ID list [DOC: spec §5.5; CODE: crates/sever-index/src/blob.rs:152-181 `GroupSnapshot` and `Field` enum {S, N, CommitmentS, Blob, MemberIds}].
- `assert_state_equivalent(a, b) -> Result<(), Field>` compares each independently, in §5.5 order, returning the first differing field [CODE: blob.rs:185-205]. Fields 1,2,3,5 are also inside field 4; the redundancy is deliberate so each can be corrupted alone in the sabotage test.
- Survivors check (the core of Part 1): after deleting, the touched group's snapshot must equal `snapshot_from_members` built from the surviving members' own vectors alone ("as if never inserted") [CODE: blob.rs:207-234; index.rs:527-551 behind feature `test-hooks`; sever-tracekit `survivors_check` at lib.rs:371].
- Insertion-order independence: inserting the same set in any order yields an identical blob (blob sorts members by ID bytes) [DOC: spec §5.5; CODE: blob.rs:21-22]; gate P1-T3 (100 random orders) [DOC: Build §4.8].
- Outside the relation (declared): which groups exist and their centroids, holding contents, WAL history, log leaves, timestamps etc. [DOC: spec §5.5, overview L-3..L-5].

---

## 6. Canonical blob (§5.5) byte layout and its hash

Never stored; generated in memory on demand and wiped after use [DOC: spec §5.5]. `Index::blob(&GroupId)` builds it for frozen/spawned groups (None for holding) [CODE: index.rs:508-513]; `canonical_blob` [CODE: blob.rs:15-41].

```
magic (6 bytes)          b"SEVERC" (core form, Part 1) | b"SEVERG" (full form, from Part 3)
u16be format_version = 1
u16be d
u64be n
i64be x d                S
[extension region]       core form: empty. full form: 32 bytes C_S || 32 bytes r_agg
u64be member_count       (MUST equal n)
per member, ascending by record-ID BYTES:
    u16be id_len || id bytes || i64be x d   (x~ widened from i32)
```
- Core vs full form: DB-47; `E::BLOB_MAGIC` selects the magic and `ext.blob_region` writes the region [CODE: blob.rs:24, 31; ext.rs:21-22, 49-55].
- Strict parser `parse_blob(blob, magic, region_len)`; rejects (with `BlobReject`): wrong magic, version != 1, `member_count != n` (`CountMismatch`), empty ID (`EmptyId`), IDs not strictly ascending (`Unsorted`: unsorted or duplicate), trailing bytes, truncation or non-UTF-8 ID (`Truncated`) [CODE: blob.rs:45-60 (enum), 76-150].
- Golden: `golden/p1_core_blob.json` = Appendix B item 8, d=8, three members `doc-b`, `Doc-A`, `doc-a` (shows byte-order sort: `Doc-A` < `doc-a` < `doc-b`), contains `blob_hex` starting `534556455243 0001 0008 ...` (`SEVERC`, version 1, d = 8) [CODE: golden/p1_core_blob.json].
- The "hash": SHA-256 of the blob. Used in the demo (`sha256 of blob`, `view`) [CODE: crates/sever-p1/src/demo.rs:237-249 (`Sha256::digest(&blob)`)] and in traces (`blob_hash` = `hashlib.sha256(idx.blob(gid)).hexdigest()` [CODE: python/sever_testkit/traces.py:66-67]). Also SHA-256 of S bytes in the demo (`s_bytes`: each i64 as 8 big-endian bytes) [CODE: demo.rs:243-248]. The blob has no embedded hash itself [NOT FOUND: a hash field inside the blob layout]. In Part 3 the full-form blob hash feeds certificates (outside this scope) [DOC: Build 3-4].
- Python model blob: `core_blob(d, s, members)` and `Group.blob()` implement the same layout with magic `SEVERC` [CODE: model.py:200-216]. The Rust and Python blobs are compared by hash after every operation in traces.

---

## 7. Search (§8)

### 7.1 IVF-flat algorithm
[CODE: crates/sever-search/src/lib.rs:56-92 `search`]; spec §8.1.
1. Check query with `check_normalised` (dimension, finite, normalised) (line 62).
2. Rank every frozen+spawned group (holding excluded: `search_groups` iterates only `self.groups`) by `D_g = sum_i ((f64)q_i - mu_i)^2` sequential f64 (`route_dist::sq_dist_f64`, lib.rs:17-26), sorted by `(D_g via total_cmp, group-ID bytes)` (lib.rs:44-53).
3. Probe budget `p = ceil(0.25 * k)` = `k.div_ceil(4)` with k = number of ALL frozen and spawned groups, EMPTY ones included (empty group uses a probe slot) (lib.rs:39-41, 71). `PROBE_COVERAGE = (1,4)` [CODE: constants.rs:34]; e.g. k=128 -> p=32; k=263 -> 66 [CODE: constants.rs:100-106 test]. "nprobe" is therefore not a user parameter in v1; it is always 25 % of k.
4. Scan every member of every probed group using the float32 mirror (`g.rows`, `x^` as f32 from `dequantise_f32`) with `kernel::score(query, row)` (lines 73-78).
5. Top-k: sort by `(score total_cmp, record-ID bytes)` and take `k_results` (lines 80-91). Ties in score break by record-ID bytes. Python equivalent sorts on `(float(scores[i]), id_bytes(ids[i]))` [CODE: model.py:482-508].
- Mirror: per group `mirror_ids: Vec<RecordId>` and `mirror: Vec<f32>` (d floats per row) kept inside sever-index `Group` and exposed as `SearchGroup {id, centroid, ids, rows}` [CODE: index.rs:87-96, 98-106, 516-523]. The Build plan says sever-search owns "Float32 mirror" [DOC: Build §4.4], but the code keeps it in sever-index (see §14).
- Results are approximate (IVF); deletion is exact. Search never writes (§15.5).
- INV-9: a deleted record must not be returned; mirror rows are zeroed on delete [CODE: index.rs:398-411] and `check_invariants` verifies mirror/slot alignment [index.rs:577-585].
- `probed_groups` helper for demos/traces [CODE: lib.rs:95-102]. Why IVF-flat not HNSW: a record lives in exactly one posting list and can be removed exactly; graph indexes keep structural traces [DOC: spec §8.3].

### 7.2 Pinned distance kernel (§8.2)
- Spec: `d` multiple of 8; eight f32 partial sums `L_0..L_7` start at +0.0; for i in 0..d lane `j = i mod 8` does `t = q_i - x_i; L_j = L_j + t*t` with SEPARATE multiply and add (no FMA); final reduction `((L0+L1)+(L2+L3)) + ((L4+L5)+(L6+L7))`. Scalar and SIMD must be bit-identical. AVX2 detected at runtime; scalar fallback; no AVX-512 [DOC: spec §8.2].
- Scalar `score_scalar`: loops `chunks_exact(8)`, lanes updated `*l += t*t` [CODE: crates/sever-search/src/kernel.rs:15-24 (shown as lines 117-127 with an offset in my raw output; true start line 15)]; `reduce` implements the tree [kernel.rs:~9-13].
- Dispatch `score`: on x86_64 `avx2::available()` -> `avx2::score`, otherwise scalar [CODE: kernel.rs:28-36]. `uses_avx2()` [39-48].
- AVX2: `pub(crate) mod avx2` at kernel.rs:~50; `#![allow(unsafe_code)]` at kernel.rs:55 (the single `unsafe` module in Part 1; the crate sets `unsafe_code = "deny"` rather than `forbid` for this reason [CODE: crates/sever-search/Cargo.toml `[lints.rust] unsafe_code = "deny"`]). `available()` uses `std::is_x86_feature_detected!("avx2")` (runtime) [kernel.rs:~64-70]. `score` calls `unsafe { kernel(q, x) }` with SAFETY note [kernel.rs:~72-76]; `#[target_feature(enable = "avx2")] unsafe fn kernel` at kernel.rs:79-80 uses `_mm256_loadu_ps`, `_mm256_sub_ps`, `_mm256_mul_ps`, `_mm256_add_ps` (separate mul then add, line ~90), stores to an `[f32;8]`, and calls the same `reduce` (shared reduction => identical tree).
- A grep for `unsafe` over the other Part 1 crates' src shows only the kernel (and the word "unsafe" inside `PlatformUnsafe`) [CODE: grep -rn unsafe crates/sever-{types,quant,partition,index,search,p1,tracekit,spec,explain}/src].
- P1-T4: scalar and AVX2 must agree on 10^7 random pairs and on every query-vector pair of differential runs. Tracekit `kernel_check` scores each (query, vector) pair with `score_scalar` and the dispatched `score` and compares bits [CODE: crates/sever-tracekit/src/lib.rs:~395-410 `kernel_check`; Report fields `kernel_pairs`, `kernel_mismatches` lines 129-132].
- Python model: `kernel_scores` reproduces the 8-lane layout by `np.cumsum(sq.reshape(m, d//8, 8), axis=1, dtype=float32)[:, -1, :]` then the same reduction tree [CODE: model.py:132-148].

Pinned summation orders in general: sequential loops from i=0, multiply and add as separate IEEE operations (Rust does not contract to FMA on its own) [CODE: route.rs:1-5; kernel.rs comment]; Python uses `np.cumsum(...)[..., -1]` because `np.sum` and `@` are not sequential [CODE: arith.py:1-6; CLAUDE.md §7 "Floats"].

---

## 8. Sabotage register SB-1 .. SB-10

Each is the real code built with exactly one deliberate bug; PASS means at least one test goes red [CODE: tests/sabotage/run.sh:1-6]. Rust: Cargo feature `sabotage-SB-N` ; Python: env `SEVER_SABOTAGE=SB-N`. NOTE: the Rust code uses `cfg!(feature = "sabotage-SB-N")` (a runtime-constant `if`) in most places, not `#[cfg(...)]` attributes; only SB-9 uses true `#[cfg]`/`#[cfg_attr]` gating. Features are declared in sever-index/Cargo.toml (SB-1..5, 7, 8) and sever-search/Cargo.toml (SB-6, SB-9). SB descriptions: [DOC: Build §2.6 table, docs/SEVER-DB_BUILD_PLAN_PART_1-2.md lines 259-268].

| SB | What it breaks | Code location |
|---|---|---|
| SB-1 flip one bit of a group sum | In `apply`, after installing a group's post-state, if `gc.before.n > g.state.n` (a deletion) it XORs 1 into `s[0]` | [CODE: crates/sever-index/src/index.rs:363-369, flag at 364] |
| SB-2 skip count decrement on deletion | `subtract` does not decrement `n` | [CODE: index.rs:831-834, flag at 832] |
| SB-3 subtract twice on a retried deletion | In `Draft::delete`, when the ID is absent and was deleted earlier in the same plan, re-subtract the remembered slot; also records `deleted` after each deletion | [CODE: index.rs:768-773 (flag 769) and 818-820 (flag 818); `deleted` map field index.rs:629-630] |
| SB-4 forget locator update after slot move | In the swap-with-last branch, skips the `LocatorOp::Put` for the moved slot | [CODE: index.rs:796-806, flag at 797] |
| SB-5 keep deleted vector in the search mirror | `Truncate` does not zero-fill / truncate `mirror` and `mirror_ids` | [CODE: index.rs:401-408, flag at 402] |
| SB-6 skip empty groups when filling the probe budget | Search filters out groups with empty `ids` before taking `p` groups | [CODE: crates/sever-search/src/lib.rs:65-70, flag at 69] |
| SB-7 route to "the most recently created group with room" | In spillover loop, picks the last spawned group with room instead of nearest | [CODE: index.rs:265-269, flag at 266] |
| SB-8 holding area before spillover check | After the drift test, returns Holding immediately when OOD | [CODE: index.rs:253-256, flag at 254] |
| SB-9 FMA contraction in SIMD kernel | `available()` also requires FMA; `kernel` gets `#[cfg_attr(feature="sabotage-SB-9", target_feature(enable="fma"))]`; the add/mul pair is replaced with `_mm256_fmadd_ps` | [CODE: crates/sever-search/src/kernel.rs:66 (available), 79 (cfg_attr), 90 (not-SB-9 branch), 96 (SB-9 branch)] |
| SB-10 average per-group Ledoit-Wolf fits instead of one pooled fit | Python, `SEVER_SABOTAGE=SB-10` : step 4 averages per-group `LedoitWolf` covariances and shrinkages; the oracle (step 7) must refuse | [CODE: python/sever_partition/build.py:55-56 (`_sabotage`), 110-118]; must-fail test `test_p1_partition_sb10_per_group_averaging_is_refused` carries `@pytest.mark.mustfail` and expects `OracleDisagreementError` [CODE: python/sever_partition/tests/test_partition.py:122-127] |

Runner: `tests/sabotage/run.sh` loops `for sb in SB-1 SB-2 SB-3 SB-4 SB-5 SB-7 SB-8; do rust "$sb" sever-index`, then SB-6 and SB-9 on sever-search, then `python SB-10 python/sever_partition` (excluding the mustfail-marked test so a normal test fails) [CODE: tests/sabotage/run.sh lines ~44-61 as read]. Tests that catch several: comments in `crates/sever-index/src/tests.rs` at lines 411 (SB-8), 428 (SB-7), 490 (SB-3), 526 (SB-4), 549 (SB-5) and `crates/sever-search/src/tests.rs:131` (SB-6). [NOT FOUND: a comment naming the test that catches SB-1, SB-2, SB-9 in those two files; grep for "SB-" gave only those lines. They are presumably caught by survivors/equivalence tests and the kernel bit-identity test: INFERRED.]
Gate P1-T8: SB-1..SB-10 each turn at least one test red [DOC: Build §4.8].

---

## 9. sever-p1: composition root, demo, ghost baselines

### 9.1 Composition root
- `type P1Index = Index<NoExtension, HmacSha512Scrambler>`; `new_index(artefact, cfg)` draws a 64-byte scrambling key and 16-byte collection ID from `OsRng` and builds the index [CODE: crates/sever-p1/src/root.rs:11, 24-36]. Unlike the core crates, sever-p1 may read files and the clock [CODE: sever-p1 lib.rs:5-6].

### 9.2 `sever-demo idea` command
- Binary `sever-demo` [CODE: crates/sever-p1/Cargo.toml `[[bin]]`]. Usage: `sever-demo idea --data nq-10k|nq-100k|synthetic [--seed N] [--root DIR] [--json PATH]` [CODE: crates/sever-p1/src/bin/sever-demo.rs:11-12]. Defaults: data `nq-10k`, seed 42, root `.` [bin:25-30]. Prints tables and writes the full run as JSON, default `artefacts/demo/idea-<data>-seed<seed>.json` [bin: main, `args.json.unwrap_or_else`]. Exit 0 only if every touched group is exact, no deleted record is returned by search, untouched groups are unchanged, second delete is "already absent" and state unchanged, invariants ok [bin: end of main].
- Commands (documented): `cargo run --release -p sever-p1 --bin sever-demo -- idea --data nq-10k --seed 42` (offline: `--data synthetic`); report page: `PYTHONPATH=python uv run python -m sever_demo.render artefacts/demo/idea-nq-10k-seed42.json` [DOC: CLAUDE.md §9]. render.py writes a self-contained HTML (no network, no scripts) next to the JSON, with two inline-SVG charts [CODE: python/sever_demo/render.py:1-8, 62 `_ghost_chart`, 118 `_n_chart`].
- Data: `load_nq` (`nq-10k` = 10,000 rows, `nq-100k` = 100,000 rows from `datasets/processed/nq_1m/embeddings.npy`, queries from `nq_queries/embeddings.npy`, partition `artefacts/partition-seed<seed>.svp`, IDs+cohorts from `artefacts/nq_1m.ids.jsonl`; spawn target 200; stream in corpus order) [CODE: crates/sever-p1/src/data.rs:193-229]. `load_synthetic`: golden artefact `golden/p1_partition_small.svp` (d=16, 4 groups) + `golden/p1_fixture_vectors.json` (hex float32 rows, 120 in-distribution `syn-ref-NNN` and 120 out-of-distribution `syn-live-NNN`, interleaved; cohort = `cohort-{i % 40}`), spawn target 8, no queries [CODE: data.rs:253-295].
- `run` steps [CODE: crates/sever-p1/src/demo.rs:294-...; step markers in comments]:
  1. Build: insert every row through `Index::insert`; record rejected error kinds, frozen/spawned/k/N/holding counts and out-of-distribution rate (anything not `Placement::Frozen`) [demo.rs:305-340].
  2. Target: choose the cohort touching the most frozen/spawned groups, then the largest, then first title by bytes [demo.rs:357-396].
  3. Before: per touched group `n`, SHA-256 of S, SHA-256 of blob [demo.rs:397-405; `view` 237-249]; queries and each deleted record's own vector are searched (top-10, `TOP_K = 10`, demo.rs:21).
  4. Delete: one `delete_many` (= `delete_user`) [demo.rs:430-440].
  5. After: same columns plus the SHA-256 of the blob rebuilt from the survivors alone (`snapshot_from_members`), with a check mark when equal; also untouched groups unchanged; second delete is `AlreadyAbsent` with state hash unchanged (`state_hash`) [demo.rs:451-520; bin print lines 102-137].
  6. Ghost: see 9.3.
  7. Search: real queries; count of searches that returned a deleted record after deletion (must be 0); an example query with the deleted record's rank before and top-3 after [demo.rs:516+; bin lines 138-165].
  Final: invariants INV-4..INV-9 via `check_invariants` printed as `ok` [bin line ~170].
- Test: `crates/sever-p1/tests/e2e_idea.rs` has `p1_e2e_demo_synthetic_deletion_is_exact`, `..._ghost_rows`, `p1_e2e_flush_at_exactly_the_spawn_target`, `p1_e2e_holding_record_deleted_at_once`, `p1_e2e_delete_absent_is_already_absent`, `p1_e2e_malformed_inputs_typed_errors_without_secrets`, and an ignored `p1_e2e_demo_nq10k` [CODE: e2e_idea.rs:75,94,110,147,178,204,272].

### 9.3 Ghost baselines (measure P1-T14)
File: crates/sever-p1/src/ghost.rs. Both work on the original float32 vectors (like ordinary vector indexes) and get SEVER's group membership so only the delete mechanism differs [CODE: ghost.rs:1-5].
- `SoftDeleteIvf` (ghost.rs:12): delete = tombstone; the record stays in the posting list (`still_stored` true) and the group's centroid (the mean of EVERYTHING ever inserted) keeps its contribution. `summary_distance(group,d)` = Euclidean distance between the mean of all-ever-inserted and the mean of live records [ghost.rs:53-99].
- `RunningMeanIndex` (ghost.rs:24): keeps a float32 running mean per group; insert `mean += (x-mean)/n`; delete `mean = (n*mean - x)/(n-1)` (0 when n reaches 0) [ghost.rs:102-140].
- `running_mean_of(rows, d)`: survivors-only reference (same float32 running mean over surviving records in insertion order); `compare_f32(a,b)` returns (max abs difference, number of components whose bits differ) [ghost.rs:149-175].
- What it shows: soft-delete keeps the deleted vector and a nonzero summary distance; the float running mean no longer matches the survivors-only mean bit for bit (float subtraction is not the inverse of the additions); SEVER's integer sum matches exactly (distance 0, bit-identical) [DOC: Build §4.9 step 6 table]. Tests ghost.rs ~189-246 (`p1_ghost_soft_delete_keeps_the_record_and_its_contribution`, `p1_ghost_running_mean_drifts_from_the_survivors_mean`, `p1_ghost_running_mean_empties_to_zero`).
- Report structs `Ghost`, `GhostGroup` (has `soft_delete_distance`), `GhostSummary` [CODE: demo.rs:158-193].

---

## 10. Reference model C-18 and trace replay

### 10.1 What C-18 implements
`python/sever_refmodel_core/model.py` (542 lines): "slow, in-memory and obviously correct", written from the spec only, never from engine code (DB-4) [CODE: __init__.py; model.py:1-6]. It implements: constants (SCALE = 1<<24, MAX_GROUP_MEMBERS = 1,000,000, SPAWN_TARGET_V1 = 200) [model.py:19-24]; §17 errors; `check_vector` (§4.1 steps 0-3, norm via `np.cumsum(...)[-1]`) [90-99]; `quantise` [102]; `check_record_id` [107]; `scrambled_id` HMAC-SHA-512 [121-123]; `seq_sqdist_f64` [126]; `kernel_scores` [132]; `Group` with Python-int S (unbounded, so overflow cannot hide a bug) and `add/remove/mirror/blob` [151-205]; `core_blob`/`parse_core_blob` [207-260]; `has_room`, `probe_count` [263-270]; `GroupSnapshot`, `assert_state_equivalent` (five fields) [277-325]; `spawn_id` [341-346]; `RefIndex` with `route`, `insert`, `_flush_with`, `delete`, `delete_user`, `search`, `blob`, `stats`, `check_invariants` [349-542].
- Independence: no import of Rust or any engine artefact. It does import `sever_partition.arith` (Mahalanobis, normalisation) and `sever_partition.artefact.Artefact`, i.e. helper code shared with the BUILDER (also written from the spec), not with the engine [CODE: model.py:17-18; INFERRED: shared builder/model arithmetic is a correlated-error risk between C-15 and C-18, but not between model and engine]. Different data structures: dict-of-members vs Rust slot arrays with swap-with-last and locator; Python ints vs i64; NumPy cumsum vs explicit loops/AVX2 intrinsics.
- The model's duplicate-check uses a `where` dict by plain record ID; the Rust engine uses HMAC-scrambled IDs; they are never compared (tracekit comment) [CODE: model.py insert; tracekit lib.rs:32-35].

### 10.2 Trace files
`python/sever_testkit/traces.py` runs a stream through the model and writes JSONL (`format: "sever-trace-1"`) [CODE: traces.py:140-196].
- Header line `{"t":"h", data, seed, artefact path, artefact_sha256, spawning:true, spawn_target, vectors, queries, n_queries, top_k, rungs}`.
- Stream order: corpus rows in a seed-derived permutation (`sub_seed(seed,"stream")`, PCG64) [traces.py write_trace].
- Insert lines `{"t":"i","id","row","p":<placement gid or "holding">,"g":{gid: blob_sha256}}` or `"e": <error kind>` [traces.py:90-100].
- Delete lines `{"t":"d","ids":[...],"o":[gid | "absent"],"g":{touched gid: blob_sha256}}` [traces.py:103-113].
- Checkpoint lines `{"t":"c","rung","stats","g":{every gid: blob hash},"r":[[ [id, f32-bits-hex], ... ] per query]}` - scores compared by raw float32 bit pattern [traces.py:116-137].
- Rungs: cumulative 10/25/50/75/90 % of cohorts (shuffled by `sub_seed(seed,"cohort-order")`), each cohort deleted with one `delete_user` [traces.py:70-87; overview §10.7-10.8]. Commands: `uv run python -m sever_testkit.traces --data nq-10k --seed 42` or `--all-seeds` [traces.py docstring].
- Small synthetic streams (spawn size 8, 24 queries, ID pool of 60, many duplicates/re-inserts/absent deletes): python/sever_testkit/streams.py [CODE: streams.py:1-30, `random_ops` line 88].

### 10.3 How sever-tracekit replays
`replay(trace, root)` [CODE: crates/sever-tracekit/src/lib.rs:175-...]: reads the header; verifies SHA-256 of the artefact file equals `artefact_sha256`; parses it with `PartitionArtefact::parse`; builds `Index<NoExtension, HmacSha512Scrambler>` with `TEST_SCRAMBLE_KEY = [0x5a;64]` and a zero collection ID; opens vector and query `.npy` files (`Npy`, '<f4', C order, 2-D, row-addressable) [lib.rs:47-111]. For each line:
- `"i"`: inserts the same row; compares placement text or error kind with the model; compares the blob hash of every group named in `g` (`compare_hashes`, lib.rs:413).
- `"d"`: `delete_many`; compares each outcome (`from.as_text()` or "absent"); compares hashes of touched groups; runs `survivors_check` for each touched group (blob must equal the blob of a group rebuilt from live members' own quantised vectors; lib.rs:371) .
- `"c"`: compares stats (frozen, spawned, N, k, holding), every group's blob hash, and top-k lists including score bits; counts any returned record that has been deleted (`deleted_returned`); runs `kernel_check` for scalar vs dispatched kernel.
`Report { ops, compared, mismatches, deleted_returned, survivor_groups_checked, survivor_failures, kernel_pairs, kernel_mismatches, first }` [lib.rs:115-135]. Binary: `sever-tracekit replay <trace.jsonl>... [--root DIR]` prints one JSON line per trace, exit 1 on any mismatch (P1-T2), deleted-returned (P1-T5), failed survivors check (P1-T1) or kernel disagreement (P1-T4) [CODE: crates/sever-tracekit/src/main.rs:1-64].
Gate runner: `PYTHONHASHSEED=0 PYTHONPATH=python uv run python -m sever_testkit.gates p1-differential --data nq-10k --all-seeds` (writes the run ledger); other gates: `p1-quant-recall`, `p1-fuzz`, `p1-synthetic`, `p1-spikes`, `p1-coverage`, `p1-mutants`, `p1-checks` [CODE: python/sever_testkit/gates.py:1-35, function table lines 52-566].

Other testkit pieces: `synthetic.clustered(n,d,k,seed,spread=0.15,shift=0.0)` seeded clustered unit rows (normalised in float64, rounded to float32, re-checked against §4.1), `record_ids` [CODE: synthetic.py:12-40]; `slices.py` exports `artefacts/nq_1m.ids.jsonl` (format `sever-ids-1`) because the Rust workspace does not read Parquet (a Parquet reader would pull a second `getrandom`, spec §20.3 check 1) [slices.py:1-12]; `ledger.py` append-only run ledger `docs/RUN_LEDGER.jsonl` [ledger.py:1-18]; `spec_trace.py` builds requirement->test traceability (`docs/TRACE_PART_N.md`) from `spec/requirements.yaml` and `#[spec]` / `@pytest.mark.spec` annotations [spec_trace.py:1-20].

---

## 11. Key public functions and types (signatures)

sever-types
- `RecordId::new(id: impl Into<String>) -> Result<Self, Error>` [id.rs:39]; `RecordId::from_bytes(&[u8]) -> Result<Self, Error>` [51]; `as_str` [58], `as_bytes` [63], `len_bytes` [68].
- `GroupId::frozen(label: u16) -> Option<Self>` [id.rs:148]; `to_padded_bytes(&self) -> ([u8;32], usize)` [154]; `as_text` [185]; `parse(&str) -> Option<Self>` [195].
- `CollectionId::from_bytes([u8;16])` [263]; `ScrambledId::from_bytes([u8;64])` [289].
- `SecretBuf`, trait `SecretMemory`, `SecretRegion`, `HeapProvider`, `install_provider` (EP-4: where secret bytes live; Part 4 installs an mlock provider; installed once, second install refused) [CODE: crates/sever-types/src/secret.rs:19-60 and lib.rs:21-23].
- `Error`, `InvalidRecordIdReason` [error.rs:11, 35]; constants [constants.rs].

sever-quant
- `check_normalised(x: &[f32], d: usize) -> Result<(), Error>` [lib.rs:24]
- `quantise_component(x: f32) -> i64` [55]
- `quantise(x: &[f32], d: usize) -> Result<QVec, Error>` [67]
- `QVec::{from_stored(Vec<i32>, usize), as_slice, dim, dequantise_f64, dequantise_f32}` [85-125]
- `dequantise_component_f64(i32) -> f64` [136], `dequantise_component_f32(i32) -> f32` [141]

sever-partition
- `PartitionArtefact::parse(bytes: &[u8]) -> Result<Self, Error>` [lib.rs:113]; `centroid(usize)`, `precision_row(usize)` [184,190]; consts `MAGIC`, `FORMAT_VERSION`, `MAX_FROZEN_GROUPS` [12-16].

sever-index
- `Index<E: GroupExtension, S: IdScrambler>`; `Index::new(artefact: &PartitionArtefact, cfg: IndexConfig, ext: E, scrambler: S, collection_id: CollectionId) -> Result<Self, Error>` [index.rs:164]
- `route(&self, &QVec) -> Result<(GroupId, bool), Error>` [233]; `plan_insert` [282]; `plan_delete` [335]; `plan_delete_many` [341]; `apply(&mut self, ChangeSet<E>)` [353]; `insert -> Result<Placement,Error>` [446]; `delete -> Result<Outcome,Error>` [457]; `delete_many -> Result<Vec<Outcome>,Error>` [469]; `stats() -> Stats` [479]; `group_ids` [491]; `location(&str) -> Option<GroupId>` [496]; `group_len` [503]; `blob(&GroupId) -> Option<Vec<u8>>` [508]; `search_groups()` [516]; `check_invariants() -> Result<(), Error>` [554] (INV-4..INV-9 plus extension's own); test-hooks only: `group_snapshot` [527], `survivors_snapshot` [543].
- `IndexConfig { spawning_enabled: bool, spawn_target: usize }`, default (true, 200) [index.rs:25-41].
- `has_room(n,k,big_n) -> bool` [141]; `spawn_id(founders) -> GroupId` [147].
- `canonical_blob`, `parse_blob`, `GroupSnapshot`, `Field`, `assert_state_equivalent`, `snapshot_from_members` [blob.rs:15,76,155,170,185,209].
- `route::sq_dist_f64(&[f64],&[f64]) -> f64` [route.rs:10], `route::mahalanobis(xhat, mu, precision) -> Result<f64, Error>` [21].
- `IdScrambler::scramble(&self, &CollectionId, &RecordId) -> ScrambledId` [scramble.rs:9-12]; `HmacSha512Scrambler::new(&[u8;64])` [23].
- `GroupExtension` trait, `NoExtension` [ext.rs:11, 78].

sever-search
- `search(index: &Index<E,S>, query: &[f32], k_results: usize) -> Result<Vec<Hit>, Error>` [lib.rs:56]; `Hit { record_id, score: f32 }` [31]; `probe_count(k) -> usize` [39]; `rank_groups` [44]; `probed_groups` [95]; `kernel::{score_scalar, score, uses_avx2}` [kernel.rs:15,28,39].

sever-p1
- `new_index` [root.rs:24]; `Dataset`, `load_nq`, `load_synthetic` [data.rs:34, 196, 257]; `run(ds: &Dataset) -> Result<Report, DemoError>` [demo.rs:294]; ghost types [ghost.rs].

sever-tracekit: `replay(trace: &Path, root: &Path) -> Result<Report, ReplayError>` [lib.rs:175]; `Npy::open/row` [59, 97].
sever-explain (not Part 1): `explain_route(art, x, spawned, big_n, ...)` [lib.rs:56], `explain_search(query, groups)` [126], structs `Spawned`, `RouteExplanation` (x_tilde, nearest top-`NEAREST`=5 frozen, j_star, d_m, tau, in_distribution, room, destination), `SearchExplanation`. It reuses the frozen crates' own functions (`sever_quant::quantise`, `sever_index::route::{sq_dist_f64, mahalanobis}`, `sever_search::{rank_groups, probe_count}`) and writes only the few decision lines of §7.3 itself [CODE: crates/sever-explain/src/lib.rs:1-60].

Python
- sever_partition: `build.build(x_ref, seed, sha256_reference, encoder, k_frozen=128) -> BuildResult` [build.py:77]; `artefact.encode/decode` [artefact.py:38,60]; `arith.{check_rows_normalised, quantise, dequantise, mahalanobis}` [arith.py:116-163]; `lw_oracle.ledoit_wolf(x) -> (Sigma*, shrinkage)` [lw_oracle.py:~21].
- sever_refmodel_core.model: `RefIndex(art, spawn_target=...)` with `insert/delete/delete_user/search/blob/stats/check_invariants`.

---

## 12. Glossary (meaning, source)

- Q24 : fixed-point format with 24 fractional bits; `x~ = round(x * 2^24)` stored as i32 [spec §4.2].
- `x~` (x-tilde) : quantised integer vector; `x^` (x-hat) : dequantised vector `x~/2^24` [spec §4.3].
- ULP : unit in the last place; tolerance is 8 float32 ULPs at 1.0 = 8*2^-23 [spec §2.2/4.1].
- S : per-group exact `i64` vector sum of members' `x~`; n : member count [spec §5.2].
- C_S, r_agg : Pedersen commitment to the group sum and the aggregated blinding scalar (Part 3; `()` in Part 1) [spec §5.2; ext.rs doc].
- Frozen group : one of k_frozen groups from the offline partition (128 in v1) [spec §5.1].
- Spawned group : group created by a holding-area flush (200 records) [spec §7.4-7.5].
- Holding area : per-collection buffer for out-of-distribution records with nowhere to spill; no accumulator, not searchable [spec §7.4].
- OOD / in-distribution : Mahalanobis distance `d_M > tau` / `<= tau` [spec §7.2].
- tau : drift threshold = 99th percentile of reference Mahalanobis distances (build-time output, never hand-set) [spec §6.2 step 6].
- Mahalanobis distance : `sqrt(delta^T P delta)` with precision matrix P [spec §7.2].
- Ledoit-Wolf shrinkage : covariance estimator that blends the sample covariance with a scaled identity; "pooled" = one fit on stacked residuals [spec §6.2 step 4; lw_oracle.py].
- Precision matrix P : inverse covariance, stored explicitly and used as stored [spec §6.2 step 5].
- Spillover : OOD vector goes to the nearest spawned group that "has room" (`2kn < 3N`) before the holding area [spec §7.3].
- IVF-flat : inverted-file index: centroids select groups; members scanned exhaustively [spec §8].
- Probe budget p : `ceil(0.25*k)` groups scanned per query [spec §8.1].
- Canonical blob : deterministic byte string of a group's state; the object of the exactness claim; never stored [spec §5.5].
- Core form / full form : blob magic `SEVERC` (Part 1, empty extension region) / `SEVERG` (with C_S and r_agg, Part 3) [spec §5.5, DB-47].
- Exactness relation : equivalence on the five fields (S, n, C_S, blob, member IDs) [spec §5.5].
- Survivors check : compare the group after deletion with the group rebuilt from the surviving members alone [Build §4.7 L6; blob.rs:207].
- plan / apply : pure planning step returns a ChangeSet; apply installs it and cannot fail [Build §1.1].
- ChangeSet (EP-3) : full description of one mutation [changeset.rs:169].
- EP-1 GroupExtension, EP-2 IdScrambler, EP-3 ChangeSet, EP-4 SecretMemory : extension points declared by Part 1 [Build §3.3; code refs above].
- scrambled_id : HMAC-SHA-512 of collection_id||record_id under k_scramble; the only record name below the API [spec §9.7].
- Locator : map `scrambled_id -> (group, slot index)` [spec §12.6; index.rs:136].
- Mirror : float32 copy of members' `x^` used by search; zeroed on delete [spec §12.6; index.rs].
- Swap-with-last removal : delete by moving the last slot into the gap and truncating [spec §14.4; index.rs:786-816].
- Cohort : set of records deleted together by `delete_user` [spec §3.5].
- Ghost : what a conventional index leaves behind after a delete (tombstone, float drift) [Build §4.9].
- Oracle (test) : independent source of expected values (Python model, golden file, RFC vector) [CLAUDE.md §6.3].
- SB-N (sabotage) : deliberately broken build used to prove a test can fail [Build §2.6].
- INV-N : numbered invariants of spec §21 (Part 1 owns INV-1, 4-9, 16).
- Trace : JSONL file written by the reference model and replayed by sever-tracekit [traces.py].
- Rung : cumulative deletion level (10/25/50/75/90 % of cohorts) [overview §10.8].
- Gate vs measure : gate must pass; measure is reported as found [CLAUDE.md §6.2].
- P1-Tn : Part 1 test/gate IDs [Build §4.8]. T1 exactness, T2 engine-vs-model, T3 insertion-order, T4 kernels bit-identical, T5 no deleted record returned, T6 builder oracle, T7 quantised recall (measure), T8 sabotage, T9 traceability, T10 coverage, T11 mutation, T12 fuzz, T13 contracts+spikes, T14 ghost (measure).
- G-N / DB-N : spec gap entries / design decision register entries.

---

## 13. Part 1 gates and tests at a glance
[DOC: Build §4.8, lines 678-695] - table above in glossary. Test naming `p1_<area>_<behaviour>` (Rust) [CODE: e.g. `p1_types_*`, `p1_quant_*`, `p1_ghost_*`, `p1_e2e_*`]. Each test is tagged `#[spec("SR-...")]` (Rust) or `@pytest.mark.spec("SR-...")` (Python) [CODE: crates/sever-spec/src/lib.rs; test_partition.py]. Golden files: p1_core_blob.json, p1_fixture_vectors.json, p1_partition_small.{json,svp}, p1_quant_half_steps.json, p1_regression_artefact_oom.bin, p1_scramble.json, p1_spawn_id.json [CODE: ls golden].

---

## 14. Doc-vs-code mismatches (and notable observations)

1. `configs/partition.yaml` and `configs/engine.yaml` are described in spec §18.1-18.2 (and §19.2 layout) but do not exist: `ls configs` shows only `experiments.yaml` and `fair.yaml`. The builder hard-codes the values (`KMeans(...)` args, `K_FROZEN_V1`, tolerances) [CODE: python/sever_partition/build.py:33-38, 94-102; NOT FOUND: any reader of `partition.yaml` (grep -rn "partition.yaml" only hits docs)]. Spec §18.2 parameters equal the hard-coded ones (same k-means args, percentile 99 linear, tolerances 1e-12/1e-9), so behaviour matches; only the config file is absent.
2. Build §4.5 sketches `Index::new(artefact: PartitionArtefact, cfg, ext, scrambler)`, `plan_delete(DeleteRequest<E>)`, and `Index::search(&self, query, k)`. Real code: `new(&PartitionArtefact, cfg, ext, scrambler, collection_id)` (extra `collection_id`), non-generic `DeleteRequest`, and search is a free function `sever_search::search(&Index, query, k)` [CODE: index.rs:164-170, 66-69; search lib.rs:56]. The plan says "exact signatures are fixed at Part 1's design review", so this is an expected refinement, not a bug.
3. Build §4.4 says `sever-search` owns the "Float32 mirror"; the mirror is stored and maintained inside `sever-index` (`Group.mirror`, `mirror_ids`), and sever-search only reads it through `SearchGroup` [CODE: index.rs:98-106, 516-523]. (Needed so one `apply` keeps slots, locator and mirror in step.)
4. Build §4.4 lists `sever-tracekit`'s spec column as "-" and `sever-p1` too; fine. `sever-explain` appears in neither Build §4.4 nor Part 1's freeze list; it was added later (DB-108) [DOC: spec §19.2 line 1869; overview DB-108]. Its docs describe it as "inspect build only".
5. Python `artefact.decode` is laxer than the Rust parser: it does not cap `k_frozen` at 10,000, does not require `tau >= 0`, lets invalid UTF-8 in the encoder raise `UnicodeDecodeError` rather than `ArtefactError`, and does not reject `m`/seed values [CODE: artefact.py:60-89 vs partition lib.rs:136-166]. Rust is the stricter authority (DB-63 requires rejecting k_frozen > 10,000 [DOC: spec §5.1]). Python decode is used by tests/traces only.
6. Spec §7.7 / Build: "the same `(x~, state)` always gives the same destination"; code satisfies it, but note `Index::check_invariants` checks INV-8 only as `N = sum n` (line 589) - it does not verify that `k` equals the group count, although spec INV-8 says "k equals their count" [CODE: index.rs:589-591; DOC: spec §21 INV-8]. In Part 1 `k()` is computed as `groups.len()` (index.rs:212) so it holds by construction [INFERRED].
7. Spec §6.3 says `create_collection` MUST verify `sha256_artefact`, `d`, and finite P. The Part 1 crate implements this in `PartitionArtefact::parse`; there is no `create_collection` in Part 1 (that API is in later parts) [NOT FOUND: `create_collection` in Part 1 crates].
8. Sabotage mechanism: Build §2.6 / CLAUDE.md say "built from the same source with a `sabotage-SB-N` feature flag"; implementation uses `cfg!(feature = ...)` (the sabotage code is compiled into every build and constant-folded away) for SB-1..SB-8 and real `#[cfg]` only for SB-9's intrinsics [CODE: index.rs lines cited in §8; kernel.rs:90,96]. Same behaviour, but the "sabotaged" branches physically exist in release builds.
9. Raw-output caution for later readers: my first look at several files printed with continuous line numbers across concatenated files; all line numbers in this note were rechecked with `grep -n` or per-file `sed -n`, but a few kernel.rs line numbers prefixed with `~` are approximate (the grep-verified ones are 55 [`unsafe_code` allow], 66, 79-80, 90, 96).

Test counts/pass status: [NOT FOUND] - no tests were run (read-only task); do not quote pass counts from these notes.
