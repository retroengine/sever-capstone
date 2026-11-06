# 14 · Honest status, gaps, pending work and known limitations

## In simple words

This file says exactly what is finished, what exists but is not frozen, what was never completed, what
v1 simplifies, where the documents disagree with the code, and what SEVER-DB does **not** guarantee. If
any other file in this report seems stronger than this one, this one wins.

> **Prerequisites.** Gates vs measures ([11](11_results.md)); freeze ([09](09_coding_style_and_engineering_rules.md)).
> Glossary: [L-N limit](16_glossary.md#l-n-limit), [G-N gap](16_glossary.md#g-n-spec-gap).

## The problem this solves

Final-year reports often overstate. Examiners look for the boundary of the claim. This is it.

## 1. Status of each part

| Part | Status (exact) | Evidence |
|---|---|---|
| 1 The Idea | **done and frozen** | tag `part-1-frozen` → b1d4576; freeze/PART-1.sha256 (81 files) [RUN] |
| 2 The Database | **done and frozen**, with errata E-1 and E-2 | `part-2-frozen-e2` → a244264; PART-2 (250 files) [RUN]; no fair-testing PASS in the ledger for Part 2 (line 72 FAIL; clean-room re-runs after E-1/E-2 PASS, lines 79, 83) [DATA] |
| 3 The Receipt | **done and frozen** | `part-3-frozen` → a304014; PART-3 (342 files); fair PASS line 215 [DATA] |
| 4 The Erasure | **done and frozen** = `v1.0.0` | `part-4-frozen` → 7942c1d; PART-4 (191 files); fair PASS line 224 [DATA] |

Gate summary of the v1.0 run: 16 of 17 gates pass as recorded; **P4-T10 recorded FAIL** on one
untriaged timeout and **accepted as a pass by the owner** (a later run, line 220, records PASS); 5 of 6
measures recorded; **EX-8 not completed** [DOC: Overview DB-114; DATA: lines 189, 220].

## 2. Built, not frozen

- **SEVER-DB Studio** (`studio/`, its own environment; DB-106 … DB-109): in no freeze list
  [RUN: `grep -c studio/ freeze/*.sha256` → 0 in all]. Last recorded test run on `3417b7f`: 129 passed,
  2 failed (a timing test, 677 ms vs 250 ms; a UI smoke timeout) [DOC: docs/PROGRESS.md "Studio"].
- **`crates/sever-explain`** (DB-108, used only by the `inspect` build): in no freeze list
  [RUN: `grep -c sever-explain freeze/*.sha256` → 0 in all].
- `spikes/p3-proof` still exists although its header says it is deleted after its gate [RUN: `ls spikes/p3-proof`].

## 3. Not completed / pending

| Item | State | Source |
|---|---|---|
| EX-8 (P4-T15, nq-1m scale measure) | **not completed**: OOM-killed at 10.39 GB after 6 h 11 min; no ledger entry; owner chose no rerun | [DOC: DB-114] [RUN: no `ex8` in the ledger] |
| T-5 search stability (P4-T12) | **recorded, target not met** (drift 0.008–0.013 per seed vs ≤ 0.005) | [DATA: line 161, `t5_met: false`] |
| HPC full-size gate run (DB-111) | **cancelled**; replaced by a scoped laptop run (DB-113): P4-T3 in windows of 300 ops, forensics/replay/EX-6 at nq-10k, EX-7 at nq-10k (5 seeds) + nq-100k (1 seed) | [DOC: DB-113] |
| Final-commit reruns | after the November fixes, p4-crash-a ran ~⅓ and was stopped; p4-crash-b, p3/p4-mutants, p3-replay, p3-crash were **not rerun on the final commit** (last results on 7c3c313) | [DOC: Overview line 1061, DB-116] |
| Studio "company demo" (Stage 6) | not done; `studio/audit/AUDIT2.md` findings unfixed (critical: "nowhere does Studio say 'simulated'") | [DOC: PROGRESS.md; _notes/history.md C3] |
| Branch | `bughunt-2026-11` is 53 commits ahead of the local `origin/main` ref; not merged | [RUN: `git rev-list --count origin/main..HEAD`] |
| BH-7 follow-up | the certificate check at recovery makes crash campaigns ~3× slower | [DOC: DB-116] |

## 4. v1 simplifications (stated in the spec)

- **Simulated witnesses** — all five in-process, keys in one `WITNESSES` file in the operator's key
  directory [CODE: crates/sever-log/src/witness.rs:L3; crates/sever-p3/src/witnesses.rs:L1-L9; DOC: L-7].
- **Service-held keys** — the application backend holds every account key and every `r_t`, so neither
  the insert signature nor deletion authorisation constrains a dishonest operator [DOC: §3.3, L-27, DB-55].
- **Memory-resident** — data must fit in RAM (about 3.8 GB predicted at 10⁶) [DOC: L-9].
- **Platform** — Linux x86-64, ext4/XFS; WSL/VM hosts may keep old pages (L-8).

## 5. Limits L-1 … L-28 (Overview §14, one line each) [DOC]

L-1 key erasure depends on the device honouring a 512-byte overwrite + fsync · L-2 no erasure guarantee
against the operator (who can copy keys) · L-3 the index shape persists · L-4 a deleted ID's existence is
testable with `k_scramble` · L-5 visible metadata (counts, commitments, key versions) · L-6 the search
mirror is not locked in memory · L-7 witnesses simulated · L-8 platform limits · L-9 data fits in RAM ·
L-10 group balance unmanaged · L-11 search approximate · L-12 new OOD data unsearchable until its group
forms · L-13 a certificate does not prove its own deletion leaf was appended · L-14 verifier anchors fixed
at release · L-15 certificates are large (~14 KB) · L-16 a flushed record's `r_t` survives in old
ciphertext until deletion · L-17 no replication/backups · L-18 the forensic scan is evidence, not proof ·
L-19 SciQ reference set is non-commercial (CC BY-NC 3.0) · L-20 statistics on five seeds · L-21 no
independent cryptographic review · L-22 user data simulated (Wikipedia passages grouped by article) ·
L-23 tested to 10⁶ vectors, 384 dims · L-24 determinism over input order only · L-25 two properties argued,
not machine-proven · L-26 side channels out of scope · L-27 service-held keys · L-28 frozen Part 2 keeps
three known defects.

## 6. Spec gaps

`docs/SPEC_GAPS.md` has 52 entries, G-1 … G-52, **all closed** (each by a DB-N decision); none open
[DOC: _notes/history.md C6]. Several were found by tests: G-8, G-20, G-34, G-35, G-37 … G-43, G-50 … G-52.

## 7. TODO / FIXME markers

None found in `crates/`, `verifier/`, `audit/`, `python/`, `studio/`, `scripts/`; only "XXXX" test
bytes (crates/sever-format/src/paged.rs:L154; crates/sever-vfs/src/contract.rs:L340, L344)
[RUN: grep, recorded in _notes/history.md C7]. Pending work is tracked in docs, not code comments.

## 8. Doc-vs-code and doc-vs-doc mismatches

| # | Document says | Code / data shows |
|---|---|---|
| 1 | README: Parts 3 and 4 "Built … freezes after a fair-testing pass"; gates "on the college HPC" | frozen and tagged 1 Nov; gates ran on the laptop (DB-113) |
| 2 | README P4 traceability 68/68 | TRACE_PART_4: 69/69 |
| 3 | README P3-T13 prove 12.2 ms, verify 2.2 ms | that was the 19 Oct interim (line 109); final line 182: 15.78 / 2.74 ms |
| 4 | README P1-T6 differences, P1-T14 ghost values, P2 "28,707 generic-record points" | not in ledger or result fields |
| 5 | README does not mention T-5 not met | `t5_met: false` (line 161) |
| 6 | CLAUDE.md §1/§6.1: "current part is Part 3", Part 2 at `-e1` | all four frozen; Part 2 at `-e2` |
| 7 | PROGRESS.md "Next"/"Branch" sections: Stage 4 next, main = 3417b7f | stale against its own top table |
| 8 | Build 3-4 §1.6: verifier has "no path dependencies" | one dev-dependency on `crates/sever-spec` (a no-op test-label macro) [CODE: verifier/Cargo.toml:L29-L31] |
| 9 | Build 3-4 §1.4: HMAC helpers in sever-crypto | HMAC is in sever-index (Part 1) [CODE: crates/sever-index/src/scramble.rs] |
| 10 | registers_p3: SB-19 "non-canonical point or scalar" | only scalar decoding is sabotaged [CODE: crates/sever-crypto/src/group.rs:L43-L47] |
| 11 | spec §18: `configs/engine.yaml`, `configs/partition.yaml` | do not exist; values hard-coded [RUN: `ls configs`] |
| 12 | Build §2.1/CLAUDE.md §6.2: `tests/spec/`, `tests/differential/`, … `benches/` | do not exist; tests live in crates and packages |
| 13 | Build §2.8: Fast / Extended / Full tiers | `ci.sh` has `fast` and `full-checks`; gates run via the gate runners |
| 14 | Build §4.4: mirror owned by sever-search | kept in sever-index |
| 15 | Root Cargo.toml comment: `unsafe` exceptions "(SIMD kernels, mlock)" | only the SIMD kernel allows `unsafe`; mlock goes through safe `rustix` |
| 16 | docs/PROOFS_P3.md "31 of 31", PROOFS_P4.md "79 of 79" | manifests have 173 and 92 red entries (older generated runs) |
| 17 | sever-py-p2 doc: threads can search while another writes | one mutex serialises all calls (GIL released, but not parallel) |
| 18 | ERRATA.md E-2: tag "left to the owner" | tag `part-2-frozen-e2` exists (18 Oct) |
| 19 | BUG_HUNT_2026-11: "IDs continue from BH-5" | October already used BH-6, BH-7 |
| 20 | DB-113 title "36 hours" | body/commits ~29–33 h |
| 21 | tests/README.md "550 Rust and 384 Python tests" | plain greps: 559 Rust `#[test]`, 398 Python `def test_` outside studio |
| 22 | memory/docs mention a `part-2-frozen` tag | no such tag exists |

## 9. What SEVER-DB does NOT guarantee

- No protection against a **dishonest operator** who copies keys or data before deletion (L-2, L-27).
- No **independent witnesses** in v1 (L-7).
- Erasure depends on the **storage device** honouring in-place overwrite (L-1); SSD firmware remapping
  is outside the claim.
- The forensic scan is **evidence on tested images**, not a proof (L-18); no independent crypto review (L-21).
- Search is **approximate** and its stability target T-5 was **not met**.
- Side channels (timing, cache) are out of scope (L-26).

## Key points to remember

- All four parts are frozen; v1.0.0 = 7942c1d.
- EX-8 did not complete; T-5 was not met; P4-T10 passed by the owner's acceptance first.
- Witnesses are simulated; the operator holds all keys.
- The README is stale in several places; the ledger is the authority.

## Check your understanding

1. *Is Studio part of the frozen product?* — No; it is built but in no freeze list.
2. *Which measure has no result at all?* — EX-8 (P4-T15).
3. *Which pre-registered target was missed?* — T-5 (search stability).
4. *Why can't SEVER-DB stop a dishonest operator?* — The operator holds every key and `r_t` (L-2, L-27).
