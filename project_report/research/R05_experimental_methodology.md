# R05 · Experimental methodology

> **Prerequisites.** [11](../11_results.md), [10](../10_testing_methodology.md).

## Datasets and embeddings (pre-registered 27 Sep 2026)

| Role | Dataset (pinned revision) | Notes |
|---|---|---|
| Reference set (fits the frozen groups) | `allenai/sciq` @ 2c94ad3e… | text = support, else question; CC BY-NC 3.0 [DOC: README L487-L489] |
| Live corpus | `BeIR/nq` @ b7253e6c… | text = title + ' ' + text; slices nq-10k, nq-100k, nq-1m; CC BY-SA 3.0 |
| Queries | `BeIR/nq-qrels` @ 519acd4e… (test) | 3,452 queries, 4,201 judgements |
| Encoder | `sentence-transformers/all-MiniLM-L6-v2` @ 1110a243… | 384-dimensional |

[CODE: datasets/PINS.json; configs/experiments.yaml:L10-L19]. Data files are not in git; integrity via
`datasets/MANIFEST.sha256`. Cohorts = all passages of one article title (simulated "users", L-22).

## Protocol

Five seeds `[42, 123, 777, 2024, 9999]`; sub-seed `first8(sha256(u64be(seed) ‖ label))` for k-means,
stream order and cohort order only [CODE: configs/experiments.yaml:L5-L8]. Deletion rungs 10 / 25 / 50 /
75 / 90 % of cohorts; stream fractions 25 / 50 / 75 / 100 %. Four arms in EX-6: `sever_db`,
`frozen_only`, `soft_delete_ivf`, `rebuild_ivf` (FAISS `IndexIVFFlat`, nlist matched to SEVER's group
count) [CODE: experiments.yaml:L24-L30]. Metrics: Recall@10/100 against brute force over the original
float32 vectors (holding area excluded), nDCG@10, drift = standard deviation of Recall@10 across rungs
(ddof 0 primary), balance as coefficient of variation [CODE: L31-L39]. Statistics: Welch t-test
(α = 0.005, two-sided), TOST equivalence (δ = 0.005, "likely underpowered at n = 5"), 10,000-resample
percentile bootstrap [CODE: L50-L54].

## Pre-registered targets

`T1_crash_violations: 0`, `T2_forensic_findings: 0`, `T3_engine_vs_reference_mismatches: 0`,
`T4_honest_accept: 1.0`, `T4_attack_accept: 0.0`, `T5_max_drift_stddev_per_seed: 0.005`,
`T6_min_quantised_recall10: 0.999` [CODE: configs/experiments.yaml:L41-L48]. Outcomes: T-1…T-4 and T-6
met; **T-5 not met** ([11](../11_results.md)).

## Gates, measures, interim checks

- **Gate**: pass/fail with a fixed threshold; a miss is a bug (Build §2.5).
- **Measure**: recorded as found; never a reason to change code or rerun.
- **Interim check**: laptop evidence before the final run; never reported as the gate (DB-94).
- Every run is appended to `docs/RUN_LEDGER.jsonl` with commit, platform, dirty paths and result hash.

## Hardware

Planned: college HPC at full size (DB-111). Actual: the owner's laptop — Intel Core Ultra 5 226V,
8 cores, 16 GB, WSL2 Ubuntu 24.04 with 12 GB — with scoped sizes fixed in advance by cost (DB-113)
[DOC: Overview DB-113]. Ledger platform: x86_64, WSL2 kernel 6.6.114.1, AVX2/FMA [DATA: line 224].

## Threats to validity

Five seeds only (L-20); scoped sizes (nq-10k for forensics/EX-6/P4 replay); one machine; simulated users
(L-22); EX-8 missing; WSL host memory behaviour (L-8).
