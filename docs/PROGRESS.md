# Progress

Updated at the end of every session (CLAUDE.md §3.3). Newest session first in the log.

> **Draft written by Claude on 7 Oct 2026, for you to confirm** (CLAUDE.md §3.3). Parts 1 and 2 are
> built in write mode (your temporary rule: build everything first, study the code after). Read it
> before committing and change anything that is not how you see it.

## Now

- **Phase (19 Oct 2026):** Parts 3 and 4 are **built**; every interim laptop check passes (Part 3:
  crash from op 17,000, the nq-100k replay of seed 42, attacks on five seeds, coverage, checks,
  measures, spikes, fuzz 10^7; Part 4: the crash check in three windows per seed, SB-24 … SB-30,
  traceability 68/68 with 84 proofs). Parts 1 and 2 are frozen (`part-2-frozen-e2` tagged and
  pushed).
- **Next (the owner):** the one full run of every pre-registered gate and measure on a VM
  (DB-94): `bash scripts/vm/setup.sh`, re-login, `setsid nohup bash scripts/vm/run-all.sh >
  traces/vm-run.out 2>&1 &` (about 1–2 days on 32 cores; `traces/vm-summary.log`). Then, if every
  gate passes: fair testing (`scripts/fair.sh`, the owner's go and budget), `scripts/freeze.sh 3` and
  `4`, and the tags `part-3-frozen`, `part-4-frozen` / `v1.0.0`. `main` already holds the built
  tree (fast-forwarded on 20 Oct 2026 after GitHub's fast tier and the laptop's `full-checks` and
  Part 4 smoke passed), so the VM runs on `main`. A gate that fails on the VM is a bug: fix it (red
  test first), rerun that gate and everything after it.
- **After v1.0 (owner, 19 Oct 2026): the v1.1 layout.** One folder per kind: `rust/` (the crates,
  `verifier/`, `audit/`, `fuzz/p1` … `p4`, `spikes/`), `python/`, `tests/` (every cross-cutting suite
  and the proofs), `docs/spec`, `docs/guides`, `docs/evidence` (with the ledger and generated reports;
  the tools' output paths change with them). Parts 1 and 2 are frozen in place, so this is erratum
  E-3: spec §19.2 amended with a gap and a decision, new freeze manifests and tags
  (`part-1-frozen-e3`, `part-2-frozen-e3`), and every gate and fair-testing run of Parts 1–4 repeated
  on the moved files. Until then the layout is as in README "Layout".
- **Gate and measure runners:** `python -m sever_testkit_p3.gates` and `python -m
  sever_testkit_p4.gates` (P4-T1 … T15: `p4-crash`, `p4-replay`, `p4-attacks`, `p4-forensics`,
  `p4-checks`, `p4-coverage`, `p4-mutants`, `p4-fuzz`, `p4-ex6`, `p4-quant-recall`, `p4-ex7`,
  `p4-ex8`) over `python/sever_experiments` (EX-2, EX-6, EX-7, EX-8; DB-96).
- **Decisions this round:** DB-94 (interim checks; Part 4's crash windows), DB-95 (an emptied group's
  proof is not context-bound; closes G-34), DB-96 (EX-2 on `fuse2fs` with `allow_unsafe_fs`; the
  evaluation's builds; closes G-35), DB-97 (`demo-engine/`, the final database in use; closes G-36).
- **Fair-testing bug hunts (20 Oct 2026, DB-98; $11.58):** Part 3 105/115 pass, Part 4 145/146.
  Three real issues to fix next, by hand following FT-9's steps (owner: low cost), then G-37…G-39
  and DB-99: (1) a new database's `anchors()` lists no witness keys: `sever-p3/src/witnesses.rs`
  creates a witness's epoch key only at its first cosignature; fix: in `load`, create and record
  each witness's epoch-0 key (both parts use this module). (2) `placement` is Rust debug text
  (`Frozen(GroupId(frozen-0000))`, `Holding`) in `sever-py`, `sever-py-p3`, `sever-db` and
  `sever-db-p3` (`format!("{p:?}")`); fix: the §5.1 text form (`GroupId` `Display`, `holding`),
  amend §16.2, update `sever_demo_p3/receipt.py` and `sever_experiments/ex6.py` (they test
  `"Holding"`). (3) A damaged last COMMIT whose log leaf was already stored opens with 5 leaves
  and 4 records; fix: at open, check the last log leaf against the engine (an insert leaf's record
  must be live unless its collection was dropped; a deletion leaf's record must be absent; records
  carry `insert_leaf_index`), else `IntegrityViolation` (INV-15); amend §12.3/§19.
- **After the bug hunt (21 Oct 2026; DB-103, DB-104).** `bughunt-2026-10` merged (BH-5 and the
  rest, DB-102). Part 3's root now stops serving after an `IntegrityViolation` and refuses a
  replaced data directory, as Part 4's does (PR3-F06, PR3-F07 proven). The frozen Part 2 fixes are
  errata E-4 … E-6, applied with E-3 after v1.0 (L-28). P4-T3 now closes and reopens a copy after
  every recovery (`reopen_mismatches`, zero-gated). Evidence, seed 42, ops 17,000–17,010:
  `sever-crashkit-p4 campaign --oracle traces/p2-oracle-nq-10k-seed42.jsonl --seed 42 --method
  snapshot --crash-from 17000 --limit-ops 17010` gives `reopen_mismatches` 0 (550 points) on the
  fixed build and 137 with PR4-E22's patch applied (the BH-5 fix switched off), where `refusals`
  stays 0: the old campaign could not see BH-5. Laptop checks before the VM run: `scripts/ci.sh
  full-checks` on `c092727`, 42/42 steps PASS (sabotage SB-1 … SB-30, msrv, deny, docs, ignored
  and slow tests); every demo exits 0 (demo-engine test, tour 24/24 at 5,000 rows, shell, cli,
  examples, erase; scripts/p1-demo.sh, p2-demo.sh, p3-demo.sh, demo-p4.sh with 0 findings on the
  real build; demo/ setup and test); a fuzz smoke of all 17 targets, 90 s each (about 5·10^8 runs,
  0 crashes, no ledger entry: the gates' 10^8-run campaigns are the VM's). `e5a600e`: GitHub CI
  green.
- **The 5,000-row tour failure (20–21 Oct 2026; DB-101, G-41, G-42; branch
  `p4-fix-delete-checkpoint`, pushed, GitHub CI green, not merged).** Not an engine regression: two
  `demo.sh tour` runs (two windows) shared `demo-engine/work/tour-nq`. The second run's wipe deleted
  the first run's open database; the first wrote to unlinked files, read the second run's leaf
  store by path at its delete (the read error was swallowed into `§15.3 insert leaf`), and its
  `close()` wrote a checkpoint and `MANIFEST` into the second run's directory (`§12.3 WAL shorter
  than the checkpoint`). Fixed: the store's own check is reported (G-41, Part 3); the final build
  stops serving after an `IntegrityViolation` and never writes into a replaced data directory
  (G-42, Part 4, `Opened::serve`/`close`); the demo locks each work directory (`.<name>.lock`
  beside it); chapter 5's naive copy is raw text (JSON escapes had hidden 4 of 80 windows).
  Proofs PR3-F05, PR4-F03, PR4-F04 hold; PR3-M09 and PR4-D07 were regenerated. On `0078fc5`:
  fast tier 36/36, tour 24/24 on 5,000 rows, crash windows from op 17,000 (Part 3: 1,569 points,
  Part 4: 4,307 points, 0 mismatches), every demo command exits 0. The failing state is kept in
  `demo-engine/work/evidence-tour-nq`.
- **Merged (21 Oct 2026):** `p4-fix-delete-checkpoint`, then `bughunt-2026-10`, are on `main`; the
  VM runs on `main`.
- **The engine demo (19 Oct 2026):** `demo-engine/demo.sh tour` (12 chapters on 5,000 NQ passages:
  24 of 24 checks pass), `shell`, `cli`, `erase`, `examples`, `test` (6 offline tests pass). Run
  one tour or shell per work directory: a second one is refused (DB-101).
- **Working copy:** `~/sever-db` on the WSL ext4 disk (the `C:` copy is a backup).
- **Git:** Claude commits (conventional messages, no AI attribution) and pushes to `origin` (owner,
  19 Oct 2026). `main` and `p3-gates` are fast-forwarded together once GitHub's fast tier and the
  laptop's `full-checks` pass on the commit (owner, 19 Oct 2026); the VM runs on `main`.
- **Unattended runs:** `scripts/jobq.sh` (service `sever-jobq`), side jobs `scripts/ops/sidejobs.sh`
  (service `sever-sidejobs`), memory guard `scripts/oomguard.sh` (service `sever-oomguard`); the
  interim and gate runners are in `scripts/ops/`.

## Fair testing (8 Oct 2026)

Built the automated fair-testing system (`docs/FAIR_TESTING.md`, FT-1 … FT-10; CLAUDE.md §6.4;
DB-73): fresh Claude sessions in a `bwrap` clean room write tests against a sealed engine, the tests
are hashed and run by a script, a different model triages, blind planted bugs are scored, a random
oracle audit, red-first guarded fixes, repeat. A dry run with stub agents passed every stage
(`docs/audit/FAIRNESS_P2_DRY.md`). The owner's sandbox credential is set up (`fair.sh doctor` all ok).

Part 2 was frozen (23ac9be, tag `part-2-frozen`) before FT-10 existed, so its fairness run is an
audit of frozen code: a test gap is fixed by new test files; an engine bug or any change to a frozen
file is reported for an erratum (F-6, owner). From Part 3 on, `scripts/freeze.sh N` refuses without
a PASS on the exact owned files.

## Erratum E-1 (15 Oct 2026): Part 2 SDK deadlock, found by the clean room

The sealed clean-room tests of fair-testing run 20261008T164154Z-p2-42fc06df (written by a fresh
Opus session from the spec alone) ran against the engine with no AI: 254 passed, 1 skipped (opt-in,
a million inserts), and 1 **deadlocked**: the Python SDK took the engine mutex while holding the GIL,
so threads searching one `Database` during `delete_user` hung forever (§12.5). Fixed as erratum E-1
(`ERRATA.md`): red test first (a494354), fix in `crates/sever-py-p2`, red proof PR-ERR1 PROVEN,
`scripts/ci.sh fast` 16/16, `gates p2-checks` PASS on 1e64226 (ledger), clean-room suite on the
fixed engine 255 passed / 0 failed / 1 skipped (ledger). Freeze manifest updated (248 files); tag
`part-2-frozen-e1`. The AI planter, judges and oracle audit of that run were not run (owner's token
budget, DB-74); `docs/audit/FAIRNESS_P2.md` is the void run of 8 Oct (usage limit).

Fair testing now takes its blind bugs from the `cargo-mutants` gate (DB-75, owner 15 Oct 2026).

## Part 4, The Erasure — design review (18 Oct 2026, branch `p4-prep`)

Prepared while Part 3's gates run, in a separate worktree (since merged into `p3-gates`) so the running gates'
working copy and ledger lines are untouched. No Part 4 code; nothing of Parts 1–3 changed. Part 4's
modules start only once Part 3 is frozen (Build 3-4 §0); if Part 3 changes before its freeze,
`p4-prep` is rebased onto it.

**Step 0, done:**
0. **Test enforcement** `python/sever_testkit_p4`: `spec_trace` (the Part 4 sections), `oracle_check`
   (the Part 4 crates and packages of Build 3-4 §2.4; a crate that does not exist yet holds no
   tests), `proofs check` (`tests/proofs/p4/`, IDs `PR4-…`; `proofs run` comes with the first Part 4
   proof), `registers`, `rfc_vectors`; 14 unit tests; five new `ci.sh fast` steps (`*-p4`). Parts 1–3's
   checks unchanged (70/70, 46/46, 102/102 traced; 213 and 162 proofs; freeze guard ok).
1. **Requirements:** 60 `SR-` entries with `part: 4` (one per normative statement, DB-58), every MUST
   line of the Part 4 sections catalogued (`spec_trace candidates --part 4`).
2. **Registers** `spec/registers_p4.yaml` (39 entries, before any result): SB-24…SB-30 (crate, the
   test that must go red, whether the scanner must find it: all but SB-27), the five §15.4 crash rows
   CT-1…5, key-file faults KF-1…6, the P4-T8 platform matrix PL-1…13 (refuse or start, the override
   flag), and the scan targets SC-1…8 of EX-2 and INV-11.
3. **Pins (§20.1, §20.3):** a throwaway spike with `aes-gcm-siv =0.11.1` beside the Part 3 crypto pins
   resolved offline to one `rand_core` 0.6.4, `digest` 0.10.7, `getrandom` 0.2.17 and
   `curve25519-dalek` 4.1.3; built on 1.98.1 and 1.85.1; `cargo deny` ok; all 26 RFC 8452 C.2/C.3
   vectors encrypt and decrypt. RFC 8452 text pinned in `spec/rfc/`, vectors extracted mechanically to
   `golden/p4_rfc8452_aes256gcmsiv.json`. `rustix` 1.1 (already pinned) covers `setrlimit`,
   `PR_SET_DUMPABLE`, `statfs` and the btrfs flags safely; `mlock` is `unsafe` (the listed exception,
   Build §1.2: `// SAFETY:` and Miri, with the syscall stubbed under `cfg(miri)`).
4. **Frozen interfaces checked** (an erratum later costs more): EP-4 `SecretMemory`, EP-6 `Sealer` and
   EP-7 `TxnParticipant` fit Part 4: recovery runs participants' `recover` before any decryption; the
   drop is a normal transaction with `after_commit`. Found G-26 and G-28 this way.

**Decided by the owner (18 Oct 2026):** "go, accept all gaps and lets do the part 4". DB-89 (Part 4
is built now, on its own branch and worktree, before Part 3's freeze; nothing merges before
`part-3-frozen`; builds and tests at the lowest priority on two cores while a gate runs) and DB-90
(G-26 … G-31 closed as proposed; spec §12.8, §12.9, §13.6, §14.1, §14.7, §14.8, §15.9, §18, Appendix A
amended; 65 Part 4 requirements). DB-53's EP-11 half (`PlatformProbe`) and DB-54 (the evaluation's
build variants) accepted on 18 Oct 2026 (the owner: "choose the option which is best"); every
build-plan proposal is now decided. Owner-side: tag `part-2-frozen-e2` set locally on a244264.

**Design notes for the modules** (not gaps): the `AeadSealer` and the `KeyRotationParticipant` share
the key state; the sealer creates a domain's next key when the core first asks for it during `plan`,
and the participant adopts it in `prepare` and drops anything unadopted on `abort` or a failed plan.
On this WSL machine swap is on and unencrypted and hibernation is listed, so development runs need
`allow_unsafe_memory` (§12.8, dev only); `RLIMIT_MEMLOCK` is 64 MiB.

**Proposed module order:** `sever-keys` → `sever-seal` → `sever-platform` (EP-11) → `sever-erasure` →
`sever-db` (composition, crash table) → `sever-scan` → final SDK → `sever_experiments` / `sever_report`.

## Part 3, The Receipt — ready to start (prepared 15 Oct 2026, branch `p3-prep`)

Claim: every deletion yields a certificate anyone can verify offline (Build 3-4 §1). Scope: spec
§3.3, §4.5, §9, §10, §11, the certificate and log steps of §15.1 and §15.3, §16.2, §16.3; INV-3,
INV-10, INV-15; Appendix B vectors 1, 2, 3, 4, 6, 8, 9. Out: encryption and erasure (Part 4).

**Step 0, design review (before any code):**
0. **Test enforcement for Part 3 first** (the rules apply, the checks do not yet): a new
   `python/sever_testkit_p3` (Part 2's testkit is frozen) with `spec_trace`, `oracle_check` and
   `proofs` scanning the Part 3 paths (reuse Part 2's functions by import, own path lists and
   `tests/proofs/p3/`), a `gates p3-mutants` runner (DB-75 needs its PASS), and the matching steps in
   `scripts/ci.sh fast` (spec-trace-p3, oracle-check-p3, proofs-check-p3). Until then a Part 3 test
   is unchecked against CLAUDE.md §6.3.
   **Done 15 Oct 2026** (uncommitted): `python/sever_testkit_p3` (`spec_trace`, `oracle_check`,
   `proofs` import Part 2's rules and add the Part 3 paths, including `verifier/` and `audit/` and
   `tests/**/test_p3_*.py`, `test_*_p3.py`; proofs may name `workspace: verifier|audit`),
   `tests/proofs/p3/MANIFEST.yaml` (empty), `gates p3-mutants` (P3-T9: ≥ 90 % `sever-crypto` and
   the verifier, ≥ 85 % `sever-cert`, `sever-log`; survivors and timeouts triaged in
   `docs/MUTANTS_P3.md`; refuses until the crates exist), 12 unit tests; `scripts/ci.sh fast`
   19/19 PASS. Still to do: `spec-trace-p3` gets `--complete` when Part 3's modules are done.
1. Decide the proposals Part 3 needs: DB-51 (pure-Python ristretto255 in the certificate model),
   DB-52 (`expand_message_xmd` in `sever-crypto` if `curve25519-dalek` 4.1.3 lacks it: check the
   pinned crate first), DB-53 (EP-10 `Witness`).
   **Done 15 Oct 2026** (owner's choices): 4.1.3 has `from_uniform_bytes` but no
   `expand_message_xmd`. DB-51, DB-52 and DB-53's EP-10 half accepted (overview §6.8); EP-11 waits
   for Part 4. Spec §9.1 (the one self-implemented primitive), §9.2 (K.3 vectors), §19.1 C-18
   amended; G-3 closed.
2. Requirements catalogue: `spec/requirements.yaml` has 4 Part 3 entries; add one `SR-` per MUST of
   the in-scope sections (Build §2.2), before tests.
   **Done 15 Oct 2026:** 96 new `SR-` entries (100 for Part 3), one per normative statement
   (DB-58) of the scope; invariants as `SR-21-<INV number>`, Appendix B vectors as
   `SR-B-<vector number>`. Open for the owner: G-4 (genesis checkpoint, SR-11.3-9); SR-4.2-3 (part 3)
   repeats SR-4.2-4 (part 2).
3. Registers: attacks AT-1…AT-17 and auditor faults AF-1…AF-5 (Build 3-4 §3), sabotage SB-16…SB-23.
   **Done 15 Oct 2026:** `spec/registers_p3.yaml` ties AT-1…AT-20, AF-1…AF-5 and SB-16…SB-23 to
   their requirements (attacks: the §11.3 step that must reject, re-signed by the operator except
   AT-4; sabotage: owning crate, the test that must go red); `registers check` in `ci.sh fast` (20/20
   steps PASS). DB-76 (owner): AT-18…AT-20 added before any result. Each SB item joins
   `tests/sabotage/run.sh` when its crate is built.
4. Pin the crypto dependencies (spec §20.2/§20.3: one `rand_core`, `digest`, `curve25519-dalek`).
   **Done 15 Oct 2026:** a throwaway spike (temporary worktree, deleted) with `curve25519-dalek
   =4.1.3`, `ed25519-dalek =2.2.0`, `merlin =3.0.0`, `sha2 =0.10.9`, `hmac =0.12.1`, `rand_core
   =0.6.4`, `zeroize =1.9.0` resolved offline to one `rand_core` 0.6.4, `digest` 0.10.7, `getrandom`
   0.2.17 and `curve25519-dalek` 4.1.3 (§20.3 checks 1–2), built on 1.98.1 and 1.85 (check 6), and
   passed `cargo deny` licences, advisories, bans and sources (check 5; the existing `syn`
   duplicate warning is unchanged); a standalone verifier-style workspace resolved the same way.
   New `ci.sh fast` step `dalek-pinned` (check 2 in every lockfile), and `crypto-deps` also covers
   `verifier/` once it exists. Each Part 3 crate pins these exactly in its own `Cargo.toml`
   (`"=x.y.z" # spec §20.1`), as Parts 1–2 do. Step 0 is complete; next: module 1, `sever-crypto`.

**RESUME HERE (16 Oct 2026, grind mode).** Branch `p3-sever-p3` (built on `p3-log-participant` ←
`p2-erratum-e2` ←
`p3-sever-cert` ← `p3-sever-log` ←
`p3-sever-commit` ← `p3-refmodel-certs` ← `p3-sever-crypto`; nothing merged to `main`, nothing pushed
since `p3-sever-crypto`@60a8bf5, by the owner's rule "commit only, no push"). Done: step 0; modules
1 (closed locally; fair run deferred until SDK/CLI exist), 2 (complete, with the §11.3 certificate
model and golden B 6), 3, 4 (4c on `p3-log-participant`, after erratum E-2 on `p2-erratum-e2`), 5
(`sever-cert`, with `LogParticipant`, DB-81), 6 (`sever-p3`, branch `p3-sever-p3`, DB-83), 7 (SDK,
branch `p3-sdk`, DB-84), 8 (`verifier/`, branch `p3-verifier`, DB-85), 9 (`audit/`, branch `p3-audit`, DB-86), 10 (`SOUNDNESS.md`, branch `p3-soundness`). Next: 11
demo + gates P3-T1…T12 (crash campaign with certificates, fuzz 10^8, p3-mutants, coverage, fair
run part 3) + measure P3-T13 + proof spike, then the freeze manifest (tag left to the owner).
Tools for proofs: write patches with a scratch script (diff -u of one replaced string), add
manifest entries, verify each with `cargo test -p <pkg> -- --exact tests::<name>` (must FAIL), then
`python -m sever_testkit_p3.proofs check`. rustfmt rewraps lines: match the formatted text.
The two helper scripts live in the session scratchpad and are lost between sessions; recreate them:
`mkproofs.py ITEMS_JSON SCRATCH` (each item: id, file, old, new, claim, reqs, tests, package,
testfile; writes `tests/proofs/p3/<id>.patch` as `diff -u` of one replaced string and appends a
manifest entry with the claim JSON-quoted) and `verify2.sh ID…` (applies each patch, runs each named
test with `cargo test -p PKG --lib -- --exact <module>::<name>` for `src/` tests or `--test <stem> --
--exact <name>` for `tests/` files, prints the result, reverts). A refactor can stop older patches
applying: `proofs check` names them; regenerate them with the same intent.
**Module 11 resume point (17 Oct 2026).** Built and committed on `p3-gates`: traceability 102/102,
the demo, the gate kit, the gate runners, fuzz crates, the proof spike (DB-87), and the faster kit
(726a2e1, DB-88: crash points from the main line's snapshots, every 50th operation also made the
old way and compared, accepted certificates remembered; 4 MiB segments in the replay). Measured:
148 ms a crash point at the first deletions (315 ms before), an insert of the replay 16 ms in the
engine (33 ms before). `--method compare` on seed 42 (inserts, deletions, user deletions): 0
mismatches; a build that snapshots after the operation is caught. Gate runs, all pinned to cores
0–3 (`taskset -c 0-3`; the laptop overheats on more): `gates p3-crash --data nq-10k --all-seeds
--jobs 4` started 17 Oct (about 4 h per seed). Then, as cores free up: `p3-replay --data nq-100k
--all-seeds --jobs 2`, `p3-attacks --data nq-10k --all-seeds --n 1000 --jobs 2`, `p3-fuzz --runs
100000000`, `p3-mutants`, `p3-coverage`, `p3-checks`, `p3-measures`, `p3-spikes` (then delete
`spikes/p3-proof`); the fair run of Part 3 (owner's go); the freeze manifest (tag left to the owner).
The ledger's earlier p3-crash and p3-attacks "started" lines without an end are the runs the owner
stopped on 16 Oct.

**Erratum E-2 (15 Oct 2026; `ERRATA.md`).** Building step 4c showed that the frozen Part 2 engine
never called EP-7's `pre_transaction`, so the on-demand log checkpoint could not be its own committed
transaction (§15.3 step 3). Red test first (8c314a5), fix a244264 (branch `p2-erratum-e2`): the engine
calls the hook after planning and commits a requested pre-transaction on its own first. Red proof
PR-ERR2 PROVEN; `scripts/ci.sh fast` PASS; `gates p2-checks` PASS on a244264 (ledger, 29/29 steps);
the sealed clean-room suite of the Part 2 fair run on the E-2 engine 255 passed / 0 failed / 1
skipped (ledger; run with the run's own `configs/fair.yaml`, FT-8). Freeze manifest updated (250
files). **Owner: tag `part-2-frozen-e2`** on a244264 when convenient.

**Decisions taken in grind mode** (owner, 15 Oct 2026: "at each decision don't ask me"; commit
only, no push). Each is recorded as a DB entry; review them when convenient:

- DB-87: Part 3 gate tooling (`sever-crashkit-p3`; INV-3 results memoised in test builds only;
  `sever-verify --explain`/`--batch`; the demo in Python).
- DB-86 (closes G-25): each leaf's placement is kept beside its hash and in `LOG_LEAF`; the
  log export; `sever-audit` replays placements to check every `C_S_pre`.
- DB-85 (closes G-24): the verifier's anchors are a JSON file the engine publishes;
  `sever-verify <cert> --anchors FILE` names the failed step; exit codes 0/1/2/3.
- DB-84: the SDK's request holds `r_t` unreadably and is reused for a retry; `prepare_insert` takes
  the dimension from the vector; any extra argument is `SeededNonceForbidden`; `Engine` = `Database`.
- DB-83 (closes G-23): operator keys in `SECRETS` (kinds 2–3, written before first use); the
  simulated witnesses' keys and memory in `WITNESSES`; one `d` per database; INV-15's second half
  checked at each deletion.
- DB-80 (closes G-21): before a deletion, an on-demand checkpoint whenever a witnessed one does not
  cover every leaf (the frozen hook does not name the records).
- DB-81: the log's durable layout (committed-only hash and checkpoint stores written after the
  COMMIT; last entry per key wins; `LOG_LEAF` starts with the leaf index); `LogParticipant` in
  `sever-cert`; operator keys through an `OperatorKeys` trait.
- DB-82 (closes G-22): every log checkpoint covers committed leaves only and is its own transaction
  (§15.1 step 6 would let witnesses cosign a tree a crash rolls back); four refusals of a deletion's
  checkpoint are an `IntegrityViolation`.
- Erratum E-2 on frozen Part 2 (the engine never called `pre_transaction`).
- DB-78: a malformed insert credential (non-canonical or identity `C_t`, non-canonical `r_t`) is
  `CommitmentMismatch`.
- DB-79 (closes G-4): the genesis log checkpoint is `(0, SHA-256(""), creation time, epoch 0)`,
  signed at creation; witnesses start from it; dropped from the verifier anchors.
- `sever-commit` reads the log through a `LeafLog` trait (next leaf index at `admit`; the insert
  leaf's `C_t` at removal), so module 3 does not depend on `sever-log` (module 4). One writer at a
  time (§12.5) makes the next leaf index the insert's own.

**Module order** (dependencies first; each module: tests first with oracles, CLAUDE.md §4 and §6.3):

| # | Module | Spec | Status |
|---|---|---|---|
| 1 | `sever-crypto` (generators + self-check, scalar map, commitments, PoK, hedged nonces, Ed25519, HMAC) | §4.5, §9 | **built and closed locally, 15 Oct 2026**: 32 tests + 3 doc tests; 33 red proofs hold on HEAD (`docs/PROOFS_P3.md`) + 2 doc-test proofs (`tests/proofs/p3/doctests.sh`); SB-16/17/18/19/23 each turn tests red; RFC 8032/9380/9496 vectors pass; engine = model byte for byte (Appendix B 1–4, commitments, a proof). Its §9 rules are traced except those of later modules (9.2-4 verifier; 9.3-3, 9.4-2 sever-commit; 9.4-1, 9.6-4 SDK; 9.8-6, 9.8-8 key store/witnesses). **Fair run deferred** (owner gave `--yes` 15 Oct): `fair.sh` tests through the SDK and CLI (`sever-py-p3`, `sever-p3`, modules 6–7) and needs a `p3-mutants` PASS (all its crates); the offline dry run stopped at `cargo build -p sever-p3`, no session started, nothing spent. Run it when modules 6–7 exist |
| 2 | `sever_refmodel_certs` (Python, from the spec only: the independent oracle) | §5.3, §9.3, §11.3 | **built**: pure-Python ristretto255 + `expand_message_xmd` (all RFC vectors pass), `scalar`, generators, gdigest, commitments, proof of knowledge, group state (§5.3–5.5, full-form `SEVERG` blob), RFC 9162 Merkle, pure-Python Ed25519 (RFC 8032 §7.1 vectors; strict: S < ℓ, no small-order keys) and the certificate model (§11.1 TLV, §11.2 inclusion, the §11.3 eight steps naming the failed step): 29 tests; every attack AT-1…AT-20 is rejected at a step the register lists. Goldens: B 1–4, 6 (an honest group-deletion and a holding-area certificate at d = 384 with every intermediate value), 8, 9, a group stream. Prototype cross-check of B-1 pending (no prototype values in the repo) |
| 3 | `sever-commit` (EP-1 `CommitmentExtension`) | §5.3, §9.3–9.4 | built (branch `p3-sever-commit`): EP-1 + `StoredExtension` (C_S 32, r_agg 32, record secret 41), admit (recompute C_t, `verify_strict` signature), removal check against the logged C_t, INV-3, full-form blob; 9 tests (frozen EP-1 contract passes; model stream and Appendix B 8 match byte for byte); 11 red proofs (PR3-M01…M11) |
| 4 | `sever-log` (RFC 9162 tree, proofs, checkpoints, EP-7 participant, EP-10 + `SimulatedWitness`) | §10 | **built**: 4a Merkle tree (PR3-L01…L05); 4b leaves, checkpoints, keys by epoch, cosignatures, 4-of-5 (SB-20), EP-10 (PR3-L06…L13); 4c (branch `p3-log-participant`, after erratum E-2): `LogStore` (stores `log/leaves`, `log/hashes`, `log/checkpoints`, `certs`; WAL records `LOG_LEAF`/`LOG_CHECKPOINT`/`CERT_REF`; committed-only hash and checkpoint stores written in phase C; replay; INV-15 first half) passing Part 2's frozen EP-7 contract, and `LogParticipant` in `sever-cert` (DB-81): checkpoints as pre-transactions over committed leaves (DB-80, DB-82), insert leaves, certificates chained across a `delete_user`, outputs; `OperatorKeys` trait. 7 store tests + 7 engine-level tests (a crash at every VFS operation of a deletion, three policies); PR3-L14…L19, PR3-P01…P12. Open: INV-15's second half (every live record's insert leaf exists) needs a per-record startup check (module 6); witness keys and memory persist only in module 6 |
| 5 | `sever-cert` (TLV, builder, epoch signing) | §11.1–11.2 | **built** (branch `p3-sever-cert`): `Certificate` (§11.1 encoding, strict parser: tags in order once each, fixed lengths, tags 11/12 in {0, 1}, tag 6 version 1 and an insert leaf, kind consistent with tags 2–4 and 11, no trailing bytes), `build` (tags 1/5/9/13 from the insert leaf; refuses an unproven inclusion, a bad checkpoint signature, fewer than 4 distinct witnesses, `database_lsn` not after the insert, a broken transition; proof under the certificate's own context; signs with the epoch of issue). 13 tests: the golden certificates encode and sign byte for byte as the pure-Python model (its own RFC 8032), every intermediate value matches, the §11.1 layout written by hand, Appendix A 14,093 bytes; 14 red proofs (PR3-T01…T14); SB-22 turns the emptiness test red |
| 6 | `sever-p3` (composition root, CLI `sever-db-p3`) | — | **built** (branch `p3-sever-p3`): `open_on`/`open` (generator self-check, INV-10; operator keys in `SECRETS` kinds 2–3, written before first use; five simulated witnesses with durable keys and memory in `WITNESSES`; log participant behind a wrapper where SB-21 lives), the §16.1 API (`insert` → `database_lsn`, `delete` → certificate, `certificate`, `latest_log_checkpoint`, inclusion and consistency proofs) and the verifier's anchors (JSON); CLI `sever-db-p3` (`user-key`, `create`, `insert`, `delete`, `delete-user`, `certificate`, `anchors`, …). 6 tests + 1 CLI test (a crash at every VFS operation of a deletion, three policies); PR3-R01…R07, PR3-P13; SB-21 turns the crash test red. DB-83, G-23 |
| 7 | `sever-py-p3` / `sever_db_p3` (SDK: `UserKey`, `prepare_insert`, no injectable randomness) | §16.2 | **built** (branch `p3-sdk`): native `sever_db_p3_native` (PyO3, abi3; E-1 mutex rule; every §17 error a Python exception, `CommitmentMismatch`, `BadUserSignature`, `SeededNonceForbidden` added), `UserKey` (OS key, 32-byte secret for the backend's store), `prepare_insert` (the engine's quantiser, `r_t` from the OS, `C_t`, signature; `r_t` unreadable, request reused for a retry), `Database` (alias `Engine`): `insert` → `Receipt(database_lsn)`, `delete`/`delete_user` → `Deletion(certificate)`, `certificate`, `latest_log_checkpoint`, proofs, `anchors`. 11 SDK tests (signatures and certificates checked with the model) + 1 root test; PR3-R08, PR3-S01…S09. Found on the way: `Db::insert` checked the signature over the collection the request named, and a mismatch tripped `IntegrityViolation` (engine stops): now bound to the collection inserted into. DB-84 |
| 8 | `verifier/` (separate workspace, `sever-verify`, shares no code) | §11.3 | **built** (branch `p3-verifier`): its own `expand_message_xmd`, generators and §9.2 self-check (RFC 9380 K.3, RFC 9496 vectors, golden B 1–2), §11.1/§11.2 strict parser, RFC 9162 inclusion check, §9.5 proof check, `verify_strict`, the eight §11.3 steps naming the failed step; anchors JSON (DB-85, G-24); CLI `sever-verify <cert> --anchors FILE`. 7 tests: the model's honest certificates (d = 384 golden B 6, d = 16) accepted; all 56 attack variants AT-1…AT-20 (`golden/p3_attacks.json`, written by the model with the step it rejects each at) rejected at the model's step; every single-byte change rejected; E2E-3.7. E2E-3.1…3.3 in `tests/e2e_p3/test_p3_e2e.py`: engine certificates made through the SDK verify in a separate process with the database moved away. Architecture test: no engine code. PR3-V01…V28, PR3-E01…E04, PR3-A02 |
| 9 | `audit/` (`sever-audit`, copies verifier code) | §11.3 | **built** (branch `p3-audit`): DB-86 (closes G-25): each leaf's placement (group joined or left, a flush's new group) beside its hash and in `LOG_LEAF`, recovered like the hashes; `export-log` / `Database.export_log()`; `audit/` (own workspace, nine verifier files copied byte for byte, checked by an architecture test) reports AF-1…AF-5 by replaying placements (each group's `C_S` = Σ members' `C_t`), RFC 9162 consistency, roots, signatures and held certificates. Oracle: the model auditor `sever_refmodel_certs.audit` and `golden/p3_audit.json` (honest log + one export per fault, the kinds the model reports). E2E-3.4 (a cohort `delete_user` audits clean) and E2E-3.6 (a removed deletion leaf is reported) through the SDK and both binaries. Found on the way: a flushed insert's placement must be the new group. PR3-L20, L21, P14, R09, U01…U06, A03, E05, E06; six older patches regenerated after the format change |
| 10 | `docs/SOUNDNESS.md` (extractor and simulator as tests) | §9 | **built** (branch `p3-soundness`): completeness, special soundness (extractor), honest-verifier zero knowledge (simulator), what the hedged nonces add, limits; each claim backed by a test against the engine's own prover and verifier (`p3_crypto_soundness_*`; the Σ-equation factored out as `posk::equation_holds`); an architecture test checks every cited test exists. PR3-C33…C35; PR3-C21 regenerated |
| 11 | demo `sever-demo-p3 receipt` (DB-69 pattern), gates P3-T1…T12, measure P3-T13, proof spike | Build 3-4 §1.9–1.11 | **in progress** (branch `p3-gates`): traceability 102/102; demo `scripts/p3-demo.sh` (SDK, `sever-verify --explain` in a separate directory, flipped byte REJECT, chained `delete_user`, `sever-audit`; nq-10k run clean); gate kit `sever-crashkit-p3` (campaign P3-T4, replay P3-T5, attacks P3-T1/T2, measure P3-T13), `gates p3-crash|p3-replay|p3-attacks|p3-measures|p3-fuzz|p3-coverage|p3-checks|p3-spikes`, `sever-verify --batch`, fuzz crates `fuzz-p3`, `verifier/fuzz`, `audit/fuzz`, proof spike `spikes/p3-proof` (AEAD sealer seals r_t and r_agg, a rotation stub beside LogParticipant). DB-87. Gate runs next |

**Testing for Part 3:** CLAUDE.md §6.3 (oracles, proofs) and §6.4 (fair testing). Fair testing per
module and per part: clean-room tester (Opus) + triage and oracle audit (Sonnet); blind bugs from
`gates p3-mutants` (DB-75). Every fair run starts only on the owner's `--yes` (DB-74).
`configs/fair.yaml` has the Part 3 scope; `scripts/freeze.sh` has the planned ownership list.


## Part 2 summary (8 Oct 2026, archived; the current resume point is in the Part 3 section)

**Part 2 is done and frozen.** Every Part 2 gate has passed (ledger): P2-T1…T3 crash (5 seeds,
343,837 points, 0 failures), P2-T5 replay, P2-T6 fuzz, P2-T7 spikes, P2-T8 sabotage, P2-T9 coverage
(94.8 % / 86.7 %) and mutants (91.4 %, all triaged); P2-T11 recorded. After the test audit, the
Full-tier checks (P2-T4, P2-T10, E2E-2.x) ran again on 1b7477c: 21/21 steps PASS, including the new
oracle and proof checks. Production code is unchanged since 7c7da66 outside `#[cfg(test)]` items, so
the crash, fuzz, coverage and mutants results still describe it.

**Test-oracle audit: done** (branch `p2-test-oracles`, merged in 0980d55; follow-up 035d70b).
CLAUDE.md §6.3 makes it binding: each SR-labelled test declares its oracle, no requirement rests on
the code alone, and every label has a red proof (a patch that breaks the rule). 126 labelled tests
(A 118, B 1, C 5, D 6: `docs/TEST_ORACLES_P2.md`); 211 of 211 proofs hold at 035d70b
(`docs/PROOFS_P2.md`). Findings fixed: G-18/G-19 (§14.9 versions and store magic, §14.6 ID widths)
closed by DB-72; byte-level spec tests for §14.6/§14.9 written by hand; weak tests strengthened
(checkpoint CRC flips, store torn tail, WAL cut, SDK forwarding against the engine alone); labels a
test could not fail removed (each with a green proof); a new test for one writer at a time (§12.5).
**For the owner to review by hand:** the crash gate's oracle `sever_refmodel_durable` was written by
the same AI as the engine (a shared misreading of the spec would pass both).

**Freeze:** `freeze/PART-2.sha256` (246 files, Part 2's proofs included); tag `part-2-frozen`.

**Next:** Part 3, The Receipt (Build 3-4 §1): certificates anyone can verify offline. Start with its
module list (Build 3-4 §1.4) and follow CLAUDE.md §6.3 from the first test.

**Crash safety (owner's request, done 8 Oct):** long runs go through a job queue
(`scripts/jobq.sh add|list|run`; jobs in `jobs/`, logs in `jobs/logs/`) run by the systemd user
service `sever-jobq` (linger on, so it runs with no login session; restarts by itself). A job
interrupted by a WSL stop runs again on restart, using its resume command (`gates p2-crash
--resume` continues a crash campaign from its last 30-second save, with results identical to an
uninterrupted run). Sleep needs nothing: the VM pauses and continues. A hidden `wsl.exe … sleep
infinity`, started from `Startup\sever-wsl-keepalive.vbs`, keeps WSL running after the last terminal
closes (delete that file to undo). Queued now: `p2-crash` (waits for the running gate; it finishes
or resumes it), then `p2-measures` (P2-T11, once).


## Part 2 modules (Build §5.5)

| Module | Status | Notes |
|---|---|---|
| `sever-vfs` | built | EP-5 `Vfs`; `PosixVfs`; `SimVfs` (current/durable views, crash at op N, tear, `DropAll`/`KeepAll`/`Random(seed)`, failed `fsync` loses the data like Linux, `fork`); EP-5 contract suite (functional + crash), 3 wrong backends fail it; 7 hand mutants all killed; MSRV-clean |
| `sever-format` | built | §14 codecs: file header, `MANIFEST`, segment header, `SECRETS`, group header, slot + payload (DB-46), WAL framing + typed records, paged checkpoint files, store records, the storage image (`DbImage::apply`, checkpoint streams); SB-11 red; gaps G-14…G-16 → DB-66…DB-68 |
| `sever-wal` | built | segments, one-append transactions, rollover, recovery that cuts the torn tail, covered-segment removal; crash at every op × 3 policies, every 512-byte tear, crash during recovery, proptest; SB-13 red. Durability helpers (`sever_vfs::durable`): SB-12, SB-14 red |
| `sever-appendstore` | built | EP-8 `AppendStore` + `FileStore` (segments, torn-tail cut at open, rollover); EP-8 contract suite, a wrong store fails it; crash at every op × 3 policies keeps every synced record |
| `sever-checkpoint` | built | §15.6 steps 1–4 (tmp dir, rename, MANIFEST via tmp+rename), strict load (paged files, WAL position, artefact names), cleanup of leftovers; crash at every op × 3 policies loads old or new; SB-12 red through it |
| `sever-txn` | built | EP-6 `Sealer` + `PlaintextSealer`, EP-7 `TxnParticipant`, EP-9 `Clock` (`SystemClock`, `SimClock`), each with a contract suite that wrong implementations fail; `StoredExtension` (codec beside the frozen EP-1); ChangeSet → after-images (put, move-last, drain/re-wrap, headers incl. holding count, counters, passage refs); decode + synthetic ChangeSet rebuild; the §5.4 protocol with step hooks; SB-15 red |
| `sever-engine` | built | `Engine<E, S>` + participants: create (MANIFEST last), recovery (checkpoint + WAL replay + participants), index rebuilt through a synthetic ChangeSet, full invariant check (INV-4, 6, 7, 8, §9.7 scrambled IDs, frozen layout, payload refs), insert/delete/delete_user/search/checkpoint/drop/stats, writer mutex + RwLock, Abort/Poison policy, platform (statfs, flock via rustix), test hooks (step hook, canonical state). Crash at every op × 3 policies + double crash vs a model index: PASS. SB-12…SB-15 red through the engine. WAL recovery now refuses a damaged committed record instead of dropping it (SB-11 red there too) |
| `sever-crashkit`, `sever_refmodel_durable` | built | Python oracle: 20,000-op stream (P1 inserts, cohort `delete_user`s, singles, re-inserts) and a canonical state digest per op; golden small oracle (`golden/p2_oracle_small.jsonl`) matched by the engine byte for byte. Crash kit: generic KV campaign (EX-1 step 1), index campaign (every VFS op of every op, 512-byte tears of sampled WAL writes, random points, double crash), retry checks; `SimVfs` made copy-on-write (fork cost per file, not per byte). nq-10k timing: ~8 ms per op, ~0.15 s per crash point → ~3.5 h per seed |
| `sever-p2` | built (demo pending) | composition root (platform check, lock, PosixVfs, abort policy, SECRETS 0600), `sever-db-p2` CLI (JSON in/out) |
| `sever_testkit_p2` | started | `gates p2-crash` (P2-T1 … P2-T3) — **running** since 7 Oct 19:26 UTC on commit 682bfac (5 seeds, 3 jobs, ~7 h) |
| `sever-demo-p2` | built | synthetic: all four crashes (sim before/after commit, SIGKILL before/after commit) all-or-nothing, survivors check passes |
| `sever-py-p2` / `sever_db_p2` | built | PyO3 0.29.2 (abi3, cdylib only), typed SDK (`Database`, retry semantics), stub for mypy |
| E2E-2.1 … 2.8, L13 Part 2 | built | `tests/e2e/test_p2_e2e.py` (2.1 nq-10k marked slow; 2.5 via fsync fault injection, aborts with SIGABRT; 2.6 via mkfs.ext4 -d + debugfs, DB-70); `tests/architecture/test_architecture_p2.py` (Vfs-only I/O, no mmap, freeze guard) |
| `sever-wal` | | §12.3; SB-11, SB-13 |
| `sever-appendstore` | | EP-8, §14.8 |
| `sever-checkpoint` | | §12.4, §15.6; SB-12 |
| `sever-txn` | | EP-6, EP-7, EP-9, §12.5; SB-14, SB-15 |
| `sever-engine` | | §12.7, §12.9, §15.7, §16.1 |
| `sever-crashkit`, `sever_refmodel_durable` | | EX-1 campaign, durable oracle |
| `sever-p2`, `sever-py-p2` / `sever_db_p2` | | composition root, CLI, SDK |
| Part 2 `spec_trace` | | the frozen tool knows only Part 1's sections; Part 2 needs a new module that reuses it |

## Part 1 gates (Build §4.8) — status from the ledger

| Target | Status | Evidence |
|---|---|---|
| P1-T1 exactness (survivors check) | PASS | nq-100k 5 seeds: 427,455 checks; nq-10k: 43,562; L4 synthetic: 275,114; 0 failures |
| P1-T2 engine = model | PASS | nq-10k 10.6 M values, nq-100k 12.4 M values (5 seeds each), 0 mismatches |
| P1-T3 order independence | PASS (tests) | proptest, ≥ 256 orders per set |
| P1-T4 kernels bit-identical | PASS | 10^7 pairs (ignored test); nq-10k 508 M and nq-100k 2.25 B pairs, 0 mismatches |
| P1-T5 no deleted record returned | PASS | 0 on nq-10k and nq-100k, five seeds each |
| P1-T6 builder oracle | PASS | 5 seeds; slow test in `scripts/ci.sh full-checks` |
| P1-T7 quantisation recall (measure) | **1.000** at nq-100k (target ≥ 0.999) | ledger 5 Oct |
| P1-T8 sabotage SB-1 … SB-10 | PASS | `gates p1-checks` (all 17 steps); a first run failed only because `run.sh` was not executable |
| P1-T9 traceability | 70/70 | `docs/TRACE_PART_1.md` |
| P1-T10 coverage | PASS | Rust 95.9 % lines, 87.0 % branches; Python 98.8 % |
| P1-T11 mutation | PASS | 325 / 347 = 93.7 %; 22 survivors, all triaged in `docs/MUTANTS_P1.md` |
| P1-T12 fuzzing 10^8 per parser | PASS | ledger 6 Oct: 10^8 runs each, `artefact_parse` 1,777 s, `blob_parse` 619 s; the first run found a real bug (fixed) |
| P1-T13 contracts + proof spikes | PASS | spikes recorded 5 Oct, then deleted |
| P1-T14 ghost (measure) | recorded by the demo | nq-10k seed 42: IVF 5.0e-3, float mean 1.9e-8, SEVER 0 |

Definition of done (Build §2.9): all gates above; the clean-clone demo check passed (6 Oct: the
report and the rebuilt artefact identical apart from timing); the freeze manifest and tag.

## Parts

| Part | Status | Tag | Notes |
|---|---|---|---|
| 1 The Idea | **frozen** 6 Oct 2026 | `part-1-frozen` | All Part 1 gaps closed (G-1, G-5 … G-12) |
| 2 The Database | next | | Build §5; follow-up from P1-T11: a test with two inserts into one group in one change set |
| 3 The Receipt | **preview** built in the demo | | Resolve G-3 (DB-51) and G-4 |
| 4 The Erasure | not started | | Apply G-2 |

## Part 1 modules (Build §4.4)

| Module | Status | Notes |
|---|---|---|
| `sever-types` | built | IDs, constants, every §17 error, `SecretBuf` + EP-4 |
| `sever-quant` | built | §4.1 steps 0–3 (DB-60), Q24 ties to even, dequantise; golden vector 5 |
| `sever-partition` (Rust) | built | §6.3 parser; length checked before any allocation (fuzz finding) |
| `sever_partition` (Python) | built | §6.2 builder, independent Ledoit–Wolf oracle; 5 artefacts in `artefacts/` |
| `sever_refmodel_core` (Python) | built | §3–§8 oracle; search made 4× faster on 5 Oct (same values, checked against the engine) |
| `sever-index` | built | §5, §7, §9.7; EP-1, EP-2, EP-3 with contract suites; `apply` fix (forged-change-set test) |
| `sever-search` | built | §8; scalar and AVX2 kernels bit-identical; MSRV-clean |
| `sever-tracekit`, `sever_testkit` | built | traces, replay with survivors and kernel checks, streams, ledger, gate runners, `spec_trace`, slices |
| `sever-spec` | built | `#[spec("SR-…")]` attribute (Build §2.2) |
| `sever-p1`, `sever-demo`, `sever_demo` | built | composition root (OS entropy), ghost baselines, CLI, HTML report; `scripts/p1-demo.sh` |
| Tests L1–L14 | built | L4 synthetic streams, L5 Hypothesis stateful, L9 E2E-1.1 … 1.7, L11 fuzz, L12 mutants + sabotage, L13 architecture |
| Proof spikes | passed, deleted | CommitmentExtension on ristretto255 (EP-1), rotation reader (EP-3) |
| CI | built | `scripts/ci.sh fast|full-checks`; `.github/workflows/ci.yml` (fast tier) |
| P0 pre-registration | written | `configs/experiments.yaml` (Overview §12 verbatim, pins filled from `PINS.json`) — yours to commit |

## Things to explain later (learning pass)

- Why a failed `fsync` is never retried: `SimVfs` models Linux's behaviour (pages marked clean,
  data silently gone, the retry "succeeds"), which is what SB-14 will exploit.
- The current/durable views of `SimVfs`, and why a new file needs `fsync_dir` of its parent.
- Why the EP-5 crash contract must fail a backend that loses nothing.

- `sever-engine` rebuilds Part 1's frozen index after a crash by applying one synthetic `ChangeSet`
  (every group, slot and locator entry as a "put"): no edit to the frozen crate.
- Why a valid WAL record *after* a bad one means corruption, not a torn tail (only the last,
  unsynced append can be torn).

## Open questions

- **Stop serving in Parts 2 and 3 (G-42).** Their builds still serve after an `IntegrityViolation`
  and checkpoint at close (§17 says the engine stops serving). Part 2's engine is frozen: fix it
  by erratum E-3 or accept it as a stated limit? Part 3's root could take the same guard as Part 4.
- **Two small findings (21 Oct 2026, low):** `sever-cert/src/participant.rs:188` turns a failed
  consistency proof of the operator's own tree into an empty proof (seen as a witness refusal);
  `sever-commit/src/lib.rs:237,251` would skip a `C_S` update if `record_commitment` failed
  (unreachable today: plan rejects that dimension first). 21 Oct: the first now reports `IntegrityViolation` (`§10.4 consistency proof`); the second is the bug hunt's BH-2, won't fix (frozen extension point).

- What overwrote `sciq_reference/passages.parquet` at 19:35 UTC on 27 Sep? Not `build`; the
  writer was pyarrow 25.0.1.
- The build plan's Part 2–4 proposals (DB-46, DB-48, DB-51 … DB-54) are not yet in the decision
  register; decide them at the start of each part.
- 88 % of nq passages are out of distribution for the SciQ partition (by design: the drift case), so
  most of them live in spawned groups.
- Two files in `demo/` were renamed outside these sessions (`1 data.py`, `2 quant.py`); left as is.
- Long runs need the laptop awake: three runs were lost on 5 Oct to a WSL restart and once to the
  out-of-memory killer (all recorded in the ledger as aborted).

## Session log

- **21 Oct 2026**: the owner asked for everything except the VM. Merged `p4-fix-delete-checkpoint`
  (DB-101) and `bughunt-2026-10` (DB-102, BH-5); Part 3's root takes Part 4's stop-serving guard
  (DB-103, PR3-F06/F07); errata E-4 … E-6 deferred to E-3 after v1.0 (L-28); P4-T3 reopens after
  every recovery (DB-104); BH-2 won't fix; `sever-cert`'s impossible consistency proof is an
  `IntegrityViolation`; TRACE_PART_3/4 and TEST_ORACLES_P3/P4 regenerated (SR-17-8, SR-12.9-5 moved
  to Part 3). Fast tier 36/36, full-checks 42/42, every demo, fuzz smoke 0 crashes, GitHub CI green.
  The worktree `~/sever-db-bh` and the branches `bughunt-2026-10`, `p4-fix-delete-checkpoint` are
  deleted (BH-5's evidence kept in `target/bh/kill-a-evidence`). Next: the owner's VM run.
- **20–21 Oct 2026**: investigated the 5,000-row tour failure: two tours on one work directory, not a
  regression (the owner's solo tour at HEAD passed 23/24; no bisect needed). Fixed by hand with
  red tests first (DB-101, G-41, G-42), branch `p4-fix-delete-checkpoint` pushed. A parallel
  session (sever-db-54) continues the wider review on branch `bughunt-2026-10` in its own worktree
  `~/sever-db-bh`.
- **15 Oct 2026 (evening, grind mode)**: Part 3 modules 2 (certificate model, golden B 6) and 5
  (`sever-cert`, SB-22), step 4c (`LogStore`, `LogParticipant`); erratum E-2 on Part 2 with every
  gate re-run; DB-80 … DB-82, G-21 and G-22 closed; 89 red proofs. Owner asked to stop here; resume
  from "RESUME HERE" (module 6, `sever-p3`).
- **7 Oct 2026 (later)**: built sever-format, -wal, -appendstore, -checkpoint, -txn, -engine,
  -crashkit, sever_refmodel_durable, sever-p2 (CLI, demo), sever-py-p2 + SDK, E2E-2.1…2.8, Part 2
  architecture tests, traceability 46/46, fuzz-p2 targets. Gaps G-14…G-17 → DB-66…DB-70. Crash gate
  launched (background). Owner asked to pause; resume from "RESUME HERE".
- **7 Oct 2026**: Part 2 started. Design review: DB-46, DB-48 accepted; G-13 found and closed by
  DB-65. `sever-vfs` built (30 tests, contract suite, posix on ext4 and tmpfs); a hand mutation
  pass found a weak reorder check in the contract, fixed.

- **6 Oct 2026 (afternoon)**: every Part 1 gate recorded on clean commits: P1-T11 mutants 93.7 %
  (tests added for the survivors that were real gaps: the change set's `k` after a flush,
  `QVec::dim`, INV-5 on a larger index), P1-T10 coverage, full checks (sabotage runner made
  executable; it now restores proptest files a sabotage build writes), P1-T12 fuzz, P1-T2/T5 on
  nq-100k (five seeds, 12.4 M values, 0 mismatches). Clean-clone demo check passed. Git history
  rewritten by you to drop co-author trailers (`docs/COMMIT_MAP.txt` maps the old hashes in the
  ledger). WSL given 10 GB. Part 1 frozen.
- **5–6 Oct 2026**: moved to `~/sever-db`. Built `sever-p1` (composition root, ghost baselines,
  `sever-demo idea`), `sever_demo` report, `spec_trace` and `#[spec]`, L4/L5/L13 suites, fuzz targets,
  proof spikes (passed, deleted), coverage tests, CI script, one-command demo, `experiments.yaml`.
  Ledger: P1-T7 = 1.000; nq-10k differential PASS (five seeds, with survivors and kernel checks); L4
  synthetic PASS. Bugs found by tests: artefact parser allocation (fuzz), `apply` on a malformed
  flush. Dependency pins for §20.3 (proptest 1.6 without fork; no Rust Parquet reader). Closed
  G-9 … G-12 (DB-61 … DB-64).
- **4 Oct 2026**: `sever-types`, `sever-quant`, partition builder and importer, reference model,
  `sever-index`, `sever-search`, tracekit and test kit built in write mode; G-8 closed (DB-60);
  P1-T6 and P1-T8 pass; demo moved to `demo/` and made self-contained (DB-56).
- **3 Oct 2026**: demo shell made guided; Part 3 preview (commitments, proofs, certificates, offline
  verifier).
- **1–2 Oct 2026**: the review demo (data checks, quantiser, index, baselines, full run on 1M).
- **27 Sep 2026**: specification, overview, build plan and CLAUDE.md written; P0 data encoded and
  verified.
