# scripts/hpc/steps.sh — the v1.0 run's steps at the laptop sizes of DB-113, sourced by run-all.sh.
#
# phase | name | estimate (minutes) | lock (1 = needs the memory lock) | command
#
# Steps with the same phase run at the same time; the sizes and the pairing come from measured
# costs on this laptop (DB-113, 29 Oct 2026): memory per phase at most about 9 GB of the unit's
# 10 GB; no more busy cores than the laptop has while mutants run (a mutant's 300 s test timeout
# counts against the score); the timing measures (p3-measures, EX-7) never share the CPU with a
# gate. Thresholds are the pre-registered ones; only sizes changed, each named in DB-113:
#   full size     p3-crash, p3-replay (nq-100k), p3-attacks, p4-attacks, both fuzz steps (10^8),
#                 both mutant steps (every mutant), checks, coverage, spikes, p3-measures,
#                 p4-quant-recall (nq-1m), p4-ex8 (nq-1m)
#   scoped        p4-crash: two windows of 300 operations instead of all 20,000 (A: single →
#                 multi-group deletions, seeds 42/123/777; B: multi-group deletions → inserts,
#                 seeds 2024/9999), so every kind of operation is crashed;
#                 p4-replay, p4-forensics, p4-ex6: nq-10k instead of nq-100k, all five seeds;
#                 p4-ex7: nq-10k with all five seeds, and nq-100k with seed 42 (was nq-100k and
#                 nq-1m, all seeds)
# shellcheck disable=SC2034  # STEPS is read by run-all.sh
STEPS=(
  # 1 — the Part 3 crash campaign (5 seeds at once, ≈ 6.5 GB) beside the two attack batteries
  "1|p3-crash|150|0|$G3 p3-crash --data nq-10k --all-seeds --jobs 5"
  "1|p3-attacks|20|0|$G3 p3-attacks --data nq-10k --all-seeds --jobs 2"
  "1|p4-attacks|25|0|$G4 p4-attacks --data nq-10k --all-seeds --jobs 2"
  # 2 — T-3 at nq-100k (2 seeds at once, ≈ 5 GB) beside Part 3's mutants (3 jobs, ≈ 6 cores)
  "2|p3-replay|330|0|$G3 p3-replay --data nq-100k --all-seeds --jobs 2"
  "2|p3-mutants|440|0|env CARGO_BUILD_JOBS=2 $G3 p3-mutants --jobs 3"
  # 3 — the fuzzers (10^8 per target; audit/export is the long pole) beside T-3 on the final build
  "3|p3-fuzz|230|0|$G3 p3-fuzz --runs 100000000"
  "3|p4-fuzz|45|0|$G4 p4-fuzz --runs 100000000"
  "3|p4-replay|45|0|$G4 p4-replay --data nq-10k --all-seeds --jobs 3"
  # 4, 5 — the Part 4 crash campaign, window A then window B (2–3.5 GB per seed)
  "4|p4-crash-a|90|0|$G4 p4-crash --data nq-10k --seed 42 --seed 123 --seed 777 --jobs 3 --crash-from 17694 --limit-ops 17994"
  "5|p4-crash-b|70|0|$G4 p4-crash --data nq-10k --seed 2024 --seed 9999 --jobs 2 --crash-from 18700 --limit-ops 19000"
  "5|p3-spikes|15|0|$G3 p3-spikes"
  # 6 — Part 4's mutants (4 jobs, the whole CPU)
  "6|p4-mutants|270|0|env CARGO_BUILD_JOBS=2 $G4 p4-mutants --jobs 4"
  # 7–9 — the check suites and coverage (each builds with every core), then T-6's second size
  "7|p3-checks|30|0|$G3 p3-checks"
  "8|p4-checks|40|0|$G4 p4-checks"
  "9|p3-coverage|25|0|$G3 p3-coverage"
  "10|p4-coverage|30|0|$G4 p4-coverage"
  "10|p4-quant-recall|20|0|$G4 p4-quant-recall"
  # 11 — timing measures: proof and verification time alone, then EX-7 and EX-8 (one core each)
  "11|p3-measures|15|0|$G3 p3-measures"
  "12|p4-ex7-nq-10k|150|0|$G4 p4-ex7 --data nq-10k --all-seeds"
  "12|p4-ex7-nq-100k|240|0|$G4 p4-ex7 --data nq-100k --seed 42"
  "12|p4-ex8|330|0|$G4 p4-ex8 --seed 42"
  # 13 — the strict mode of spec §12.8 (memory lock, no swap): last, so the owner's one sudo step
  # (owner-sudo.sh) can come as late as possible; these wait for it, they never fail for it
  "13|p4-forensics|180|1|$G4 p4-forensics --data nq-10k --all-seeds --locked-memory"
  "13|p4-ex6|240|1|$G4 p4-ex6 --data nq-10k --all-seeds --locked-memory"
)
