# B05 · Software testing concepts

## In simple words

Testing is how we gain confidence that code does what the specification says. A single kind of test is
never enough: each kind catches a different kind of mistake. This file explains each technique SEVER-DB
uses, with a tiny example, and why "the author tests their own code" is a problem the project had to
solve.

> **Prerequisites.** Functions, inputs and outputs. Glossary: [oracle](../16_glossary.md#oracle-test-oracle).

## The problem this solves

Suppose you write `def mean(xs): return sum(xs) / len(xs)` and test it with `[1, 2, 3]`. The test passes.
It never tries `[]` (division by zero). And if you misread the spec ("median, not mean"), your test
shares your misreading. Good testing attacks both problems.

## Build up step by step

| Technique | Definition | Illustrative example (not from the repository) | SEVER-DB use |
|---|---|---|---|
| **Unit test** | checks one function on chosen inputs | `assert quantise(0.5) == 8388608` | L1, e.g. `p1_quant_ties_to_even_by_hand` |
| **Property-based test** | checks a rule on many generated inputs | "for every list, `sorted(sorted(x)) == sorted(x)`" | L2: proptest (Rust), Hypothesis (Python) |
| **Test oracle** | the source of the expected answer | the spec table, or an independent implementation | declared per test: A, B, B-shared, C, D ([10](../10_testing_methodology.md)) |
| **Differential test** | run two independent implementations, compare outputs | a slow Python sort vs a fast C sort | engine vs reference model via traces (L4) |
| **Model-based / stateful** | random *sequences* of operations against a simple model | random push/pop on a stack vs a Python list | `test_p1_stateful_engine_matches_model` (L5) |
| **Metamorphic test** | relation between two runs | inserting in any order gives the same blob | L6, insertion-order independence; survivors check |
| **Contract test** | every implementation of an interface passes one shared suite | every `Vfs` implementation | L7, EP contract suites |
| **Fuzzing** | feed huge numbers of random/mutated inputs to find crashes | random bytes to a file parser | L11, cargo-fuzz, 10⁸ runs per parser |
| **Mutation testing** | change the code slightly (`<` → `<=`); good tests should fail | the mutant `return a - b` for `add` must be caught | L12, cargo-mutants |
| **Sabotage (must-fail)** | a hand-made, meaningful bug that a test must catch | skip a count decrement on delete (SB-2) | SB-1 … SB-30 |
| **Coverage** | which lines/branches the tests execute | 90 % lines run | gates ≥ 90 % / ≥ 95 % |
| **Spec traceability** | map every spec rule to tests | `SR-4.1-3` → `p1_quant_tolerance_boundaries` | 293 SR IDs, `docs/TRACE_PART_*.md` |
| **Crash / fault injection** | stop the program at chosen moments, check recovery | kill during a write | `SimVfs` crash campaigns |
| **Red proof** | a patch that breaks one rule must turn its labelled test red | CLAUDE.md §6.3 | tests/proofs/ |

**Mutation score** = caught mutants / (caught + missed + timeouts). Example: 325 caught, 22 missed →
325/347 = 93.7 % (Part 1's real numbers, [11](../11_results.md)).

### Why one author testing their own code is a problem

If the same person (or AI) writes code and tests, the tests inherit the same reading of the spec. If the
reading is wrong, both are wrong together and every test passes. Remedies: write expected values from the
spec by hand (oracle A), use independently written models (oracle B), and — SEVER-DB's addition — **fair
testing**: fresh AI sessions in a sandbox that see only the spec and public API, write tests against a
sealed engine, are judged by a different model, and must also catch planted bugs.

## Everyday analogy

*Analogy:* Unit tests are checking each brick; property tests are checking every brick from a lorry;
differential tests compare your wall with a neighbour's built from the same plan; fuzzing is throwing
rocks; mutation testing is secretly loosening bricks to see if inspectors notice.
*Where it stops:* all of these check against the plan; a wrong plan needs a different reviewer.

## How SEVER-DB does it

Full description: [10_testing_methodology.md](../10_testing_methodology.md).

## Key points to remember

- Every test needs an independent oracle; "the code says so" is not one.
- A test that never fails proves nothing — hence sabotage, mutation and red proofs.
- Differential testing against an independent model is the project's main oracle.
- Fair testing counters the single-author problem.

## Check your understanding

1. *What is the difference between mutation and sabotage?* — Mutations are automatic small changes; sabotage items are hand-chosen meaningful bugs.
2. *Why is coverage alone not enough?* — Code can run without any assertion checking it.
3. *What is a metamorphic relation?* — A rule linking outputs of two related runs.
