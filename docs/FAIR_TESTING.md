# Fair testing (binding for every part)

The engine, its tests, its oracle labels and its proofs were all written by one author. A suite
written that way can be self-consistent and still wrong: if the author misread a rule, the code, the
test and the proof agree with each other and everything passes. This document defines the automated
system that tests each part **fairly** (whoever decides what "correct" means has never seen the
code) and **for real** (the real binaries, on real files, with real process kills). It extends
CLAUDE.md §6.3 (declared oracles, proofs); CLAUDE.md §6.4 and overview DB-73 make it binding. Run it with `scripts/fair.sh`; the code is
`python/sever_fair/`; the pre-registered settings are `configs/fair.yaml`.

## 1. The rules (FT-1 … FT-10)

- **FT-1 Clean room.** Every AI session that writes or judges tests runs as a **fresh** headless
  Claude session inside a `bwrap` sandbox whose file system holds only the **room**: the spec
  documents, the part's public API documentation and type stubs, input artefacts, and an empty work
  folder. The repository, the home folder, `~/.claude` (memory, history), the Windows drive and every
  other path are absent, not merely forbidden. Subagents launched from a working session do not
  count as clean: they inherit that session's files and its prompt.
- **FT-2 Isolation is proved, not assumed.** Before every sandboxed session the same sandbox runs a
  canary that tries to reach the repository, the home folder, `~/.claude` and `/mnt`; every probe
  must fail and the room must be present. A run whose canary fails stops.
- **FT-3 Sealed before contact.** The clean-room tester writes its tests against a **sealed engine**:
  the API exists with the right names and signatures, but every call raises `EngineSealed`. It can
  check that its tests import and collect, never what the engine returns. Its tests are then hashed
  (`seal.json`); only the sealed bytes ever run against the real engine.
- **FT-4 No AI in the measurement.** Running sealed tests, applying planted bugs, building and
  scoring are done by the script, never by a model.
- **FT-5 Different judges.** Failures and escaped bugs are judged by a different model from the one
  that wrote the tests (`configs/fair.yaml`, `models`), again in a clean room, with the spec as the
  only authority. A judge reads; it never edits a test.
- **FT-6 Blind planted bugs.** Since DB-75 (`planted_bugs: cargo-mutants`), the blind bugs are the
  mutants of the part's own `cargo-mutants` gate (`gates pN-mutants`): a tool chooses them, nobody
  scored on them chooses them, and it costs no tokens; a run passes only with that gate's PASS in the
  ledger. With `planted_bugs: ai` (the original rule): a fresh session plants `plant_count` behaviour bugs in a copy of the
  source, each citing the § it breaks. Neither the tester nor the builder sees them before scoring.
  A planted bug that both suites miss, and that the judge rules a real spec violation, is a **test
  gap**.
- **FT-7 Random oracle audit.** `oracle_sample` labelled tests of the part's own suite, drawn with OS
  entropy (the draw is recorded), are re-derived from the spec alone by a judge. A disagreement is a
  finding for the owner.
- **FT-8 Pre-registered pass rule.** The pass criteria in `configs/fair.yaml` (`pass`) are fixed
  before a run and change only with a DB-N entry, never after seeing a result (overview §3.4).
- **FT-9 Fixing is separate and guarded.** Findings are fixed in their own worktree and branch,
  never in the checkout under test, one finding at a time: (1) a fresh session writes a regression
  test, which must touch only test paths and must fail on the current code; (2) a fresh session
  writes the smallest fix, which must not touch tests, `golden/`, `freeze/`, `configs/`, sealed
  clean-room tests or a frozen part's files, and must turn the test green with `scripts/ci.sh fast`
  green; (3) a spec change is allowed only with its G-N and DB-N entries in the same commit. The
  script checks each rule from the diff; a fix that breaks one is discarded and the finding goes to
  the owner. Oracle disagreements, frozen-part errata (F-6) and anything rejected go to the owner.
  After fixing, the whole run starts again with new sessions and new tests.
- **FT-10 Freeze needs a fair pass.** `scripts/freeze.sh N` refuses unless the ledger holds a PASS
  fairness run for part N whose owned files hash to the current ones. The sealed clean-room tests of
  the passing run are kept in `tests/cleanroom/pN/` with a manifest; the Fast tier checks the
  manifest (`fair.sh check`), and the tests run in the slow tier (they need the release CLI).

## 2. One run

| Stage | Who | Sees | Produces |
|---|---|---|---|
| 0 prepare | script | the commit (clean tree) | release CLI and native module, room, two Python environments (sealed, real) |
| 1 write | tester (fresh, sandbox) | room, sealed engine | `work/tests/*.py`, `work/NOTES.md` |
| 2 seal | script | — | `seal.json` (SHA-256 of every file) |
| 3 run | script (sandbox, no network) | sealed tests, real engine | `results/cleanroom.xml` |
| 4 triage | judge (fresh, sandbox) | spec, sealed tests, failures | each failure: `ENGINE_BUG`, `TEST_ERROR` or `SPEC_GAP` |
| 5–7 (with `planted_bugs: ai` only; DB-75 uses the cargo-mutants gate) | | | |
| 5 plant | planter (fresh, sandbox) | spec, source copy (no clean-room tests) | `bugs/NN.patch` + `NN.json` |
| 6 score | script | — | each bug: applied?, builds?, caught by own suite?, by clean room? |
| 7 escapes | judge (fresh, sandbox) | spec, the escaped patch | `TEST_GAP` or `EQUIVALENT` |
| 8 oracle audit | judge (fresh, sandbox) | spec, one test at a time | `AGREE`, `DISAGREE` or `CANNOT_DERIVE` |
| 9 report | script | — | `docs/audit/FAIRNESS_P<N>.md`, run ledger entry (PASS/FAIL) |

`scripts/fair.sh cycle <part>` runs a run, fixes its findings (FT-9), and repeats with fresh sessions
up to `fix_rounds` times. It stops at the first PASS or when only owner findings remain.

## 3. What this guarantees, and what it cannot

Guaranteed by construction: the tester never saw the code, the tests or the builder's notes; the
tests were fixed before the engine answered; no model touched the measurement; planted bugs were
unseen by those who are scored on them; the pass rule was fixed beforehand; every fix is red-first
and diff-checked. Not guaranteed: every session runs a Claude model, so a misreading that all of
them share survives (different models for tester and judge reduce this, they do not remove it); and
a wrong spec is tested faithfully. One machine runs everything, so power-loss durability beyond what
WSL's virtual disk provides is a stated limit, not a result.

## 4. Cost control (DB-74)

Cost controls decide **when a command stops, never what is tested**: the models, the number of
planted bugs and audited tests, the pass rule and the scopes are unchanged, and they alone make up
the FT-8 digest, so a stopped run resumes where it stopped.

- **Nothing starts without `--yes`.** `fair.sh run|cycle|resume|fix` first prints the sessions it
  will start, a typical cost (from past runs) and an upper bound (the per-session caps), and exits.
- **Caps.** Each session runs with `--max-budget-usd` (`budget.session_usd`); one command starts no
  new session once it has spent `budget.command_usd`. A session stopped by its cap stops the run
  before anything is sealed or reported; `resume` continues it, and the tester or planter picks up
  the files the cut-off session left.
- **Usage limit.** On the plan's usage limit the command stops (`on_usage_limit: stop`); it never
  waits for the reset unless the owner sets `wait`.
- **Resume, don't redo.** Finished stages are never repeated: a resumed run keeps its sealed tests
  and its planted bugs.

## 5. Setup (once)

The sandbox gets no access to `~/.claude`, so it needs its own credential: run `claude setup-token`
once and put `CLAUDE_CODE_OAUTH_TOKEN=...` (or `ANTHROPIC_API_KEY=...`) in
`~/.config/sever-fair/auth.env` with mode 600. `scripts/fair.sh doctor` checks the sandbox, the
canary and the credential without starting a session.
