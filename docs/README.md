# Documents

## Sources of truth (in priority order, CLAUDE.md §2)

| Document | Role |
|---|---|
| [`SEVER-DB_SPECIFICATION.md`](SEVER-DB_SPECIFICATION.md) | **Normative**: what the software must do, byte for byte (cite as §N) |
| [`SEVER-DB_PROJECT_OVERVIEW.md`](SEVER-DB_PROJECT_OVERVIEW.md) | Why: the decision register (DB-N), targets (T-N), experiments (EX-N), limits |
| [`SEVER-DB_BUILD_PLAN_PART_1-2.md`](SEVER-DB_BUILD_PLAN_PART_1-2.md), [`SEVER-DB_BUILD_PLAN_PART_3-4.md`](SEVER-DB_BUILD_PLAN_PART_3-4.md) | How it is built: parts, freeze rule, test plans, gates |
| [`SPEC_GAPS.md`](SPEC_GAPS.md) | Every place the spec was unclear, and the decision that closed it (G-N) |
| [`../ERRATA.md`](../ERRATA.md) | Fixes to frozen parts (E-N) |
| [`PROGRESS.md`](PROGRESS.md) | Where the project stands, and what is next |

## Evidence (generated, never edited by hand)

| Document | What |
|---|---|
| [`RUN_LEDGER.jsonl`](RUN_LEDGER.jsonl) | Every gate and measure run, with its commit and result file in `../results/` |
| [`TRACE_PART_1.md`](TRACE_PART_1.md) … [`TRACE_PART_4.md`](TRACE_PART_4.md) | Requirement → test matrices (spec-trace) |
| [`PROOFS_P2.md`](PROOFS_P2.md), [`PROOFS_P3.md`](PROOFS_P3.md), [`PROOFS_P4.md`](PROOFS_P4.md) | Red proofs: each test label can fail (CLAUDE.md §6.3) |
| [`TEST_ORACLES_P2.md`](TEST_ORACLES_P2.md), [`TEST_ORACLES_P3.md`](TEST_ORACLES_P3.md) | Where every expected value comes from |
| [`MUTANTS_P1.md`](MUTANTS_P1.md), [`MUTANTS_P2.md`](MUTANTS_P2.md) | Triage of every surviving mutant |
| [`audit/`](audit/) | Fair-testing runs (CLAUDE.md §6.4) |
| [`COMMIT_MAP.txt`](COMMIT_MAP.txt) | Old → new commit hashes after the 6 Oct history rewrite (the ledger cites the old ones) |

## Guides

| Document | For |
|---|---|
| [`PART_1_WALKTHROUGH.md`](guides/PART_1_WALKTHROUGH.md) | Part 1's code and tests, explained in plain words |
| [`SOUNDNESS.md`](SOUNDNESS.md) | The argument behind the deletion proof (§9.5) |
| [`FAIR_TESTING.md`](FAIR_TESTING.md) | The clean-room AI testing system (FT-1 … FT-10) |
| [`TEAM_HANDBOOK.md`](guides/TEAM_HANDBOOK.md) | Teammates doing documentation and review work |
| [`TRACEABILITY.md`](TRACEABILITY.md) | Where the traceability matrices are |
