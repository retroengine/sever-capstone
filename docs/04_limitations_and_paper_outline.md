# 04 · Limitations, integrity issues, future work and paper outline

Sources as in [03](03_experiments_and_results.md): **L*n*** is line *n* of `docs/RUN_LEDGER.jsonl`;
"L-*n*" (with a hyphen) is a stated limit in Overview §14 — the two are different.

---

## 1. Limitations the project itself declares

The overview lists its own known limits (Overview §14, "Each limit gets one honest sentence in the
paper"). The ones that most affect a paper's claims:

| Limit | What it means for the claims |
|---|---|
| **L-7 Witnesses are simulated** | The log's anti-equivocation guarantee needs independent witnesses; here they run inside the same system. The mechanism is built and tested, the guarantee is not delivered. |
| **L-21 No independent cryptographic review** | The soundness argument (`docs/SOUNDNESS.md`) and the verifier share one author. Mitigations: standard constructions, RFC test vectors, a verifier that shares no code. |
| **L-2, L-27 The operator is trusted** | No erasure guarantee against the operator, who can copy keys; the operator also holds every account's signing key and every `r_t`, so insert signatures do not constrain a dishonest operator. |
| **L-1 Key-file erasure depends on the device** | Overwriting a 512-byte slot is *assumed* to destroy the old key; flash translation layers and copy-on-write file systems may keep copies. |
| **L-8 Platform** | All runs are in WSL2 on one laptop. The forensic scan covers the Linux guest's ext4 device; the Windows host's pagefile and the virtual disk file's old blocks are outside the claim. |
| **L-18 The forensic scan is evidence, not proof** | It finds known encodings and formats only. |
| **L-13 A certificate cannot prove its own deletion leaf was appended** | That needs the auditor with log access. |
| **L-15 Certificates are large** | About 14 KB each (measured mean 13,986 B at nq-100k, [03](03_experiments_and_results.md) §5.4). |
| **L-9, L-23 Scale** | Memory-resident; tested up to 10⁶ vectors and 384 dimensions only, and the database-level scale test (EX-8) did not complete. |
| **L-12 Holding area not searchable** | Out-of-distribution records wait unsearchable until 200 form a group. |
| **L-17 No replication or backups** | A backup that includes the key file would defeat erasure. |
| **L-20 Statistics** | Five seeds; equivalence test underpowered; `ddof 0` is the more permissive convention. |
| **L-22 Simulated users** | "People" are Wikipedia article titles. |
| **L-19 Non-commercial reference set** | SciQ is CC BY-NC 3.0. |
| **L-28 Frozen Part 2 keeps three known defects** | Fixed in the v1 build, not in the frozen Part 2 builds (DB-103). |

---

## 2. Integrity issues found while preparing these documents

These are not in Overview §14. Each was found by reading the files named.

1. **Several recorded runs used a working tree with uncommitted changes.** The gate runners build from
   the working directory ([python/sever_testkit/gates.py](../python/sever_testkit/gates.py) runs
   `cargo build` in the repository root) and record `git_dirty` and `dirty_paths`
   ([python/sever_testkit/ledger.py](../python/sever_testkit/ledger.py)). Dirty PASS results include:
   - **L51, P2-T5 PASS** with `crates/sever-format/src/image.rs` modified — engine code, and not
     superseded by a later clean P2-T5 run.
   - **L53, P2-T8 PASS** with the crash-kit sources modified (test tooling).
   - **L28, P1-T12 fuzz PASS** with test files, `python/sever_testkit/gates.py`, `configs/` and
     scripts modified.
   - **L40, P2-T1…T3 (one seed) PASS** with `crates/sever-txn` engine files modified — superseded by the
     clean five-seed run L56.
   - **L13, L16, L19** (Part 1 differential, spikes, synthetic) with only `demo/` and `spikes/` files
     modified — outside the engine.
   - **L141, P3-T1/T2 PASS** with `scripts/hpc/steps.sh` modified; superseded by L206.
   The binary under test in L51 may therefore not equal any commit. [NEEDS INPUT: what the uncommitted
   change to `sever-format/src/image.rs` was at L51, or whether P2-T5 should be rerun on a clean tree.]
2. **Several gates were not rerun on the frozen code.** DB-116 records that after the November bug
   hunt, the P3-T4 crash campaign, P3-T5 replay, P3-T9 mutants and both P4-T3 windows were *not*
   rerun on the final commit `94d0b24` (P4-T10 mutants were, at L220). Their results are on
   `7c445b5` / `9e11156` / `11f00f2`. Between `7c445b5` and `94d0b24` the non-test library code of
   `sever-cert`, `sever-log` and `sever-erasure` changed by about 70 added lines
   (`git diff --stat 7c445b5 94d0b24 -- crates`), besides tests. DB-116 states that the changed code is
   covered by the full suites and red-first regression tests that did run (L196–L210).
3. **One gate passed by the owner's decision, not by the gate.** P4-T10 mutation was recorded FAIL at
   L189 (one untriaged timeout) and accepted as passed by the owner (DB-114); a later run, L220, passes
   on its own. A paper should say both.
4. **The attack set changed after failures** (G-34; [03](03_experiments_and_results.md) §4.3). The
   final T-4 result does not test the replay of proofs between group-emptying certificates, because
   that attack succeeds by design and was removed from the generator after the spec was amended.
5. **Scope was reduced after interim results had been seen.** DB-113 moved several pre-registered
   sizes down (P4-T3 to two 300-op windows; EX-2, EX-6 and P4-T9 replay to nq-10k; EX-7 to nq-10k and
   one nq-100k seed). DB-113 states the sizes were chosen "by measured cost only … never by which sizes
   passed before", and thresholds did not change. The reduction itself is a deviation from
   pre-registration.
6. **The same AI wrote the engine, the tests, the reference models and the harness.** CLAUDE.md §6.3
   names the durable reference model (`sever_refmodel_durable`) as an example of a **B-shared** oracle
   (an independent implementation written by the same AI). The project's
   counter-measures — declared oracles, red proofs, and clean-room fair testing by fresh sessions —
   are themselves AI-run. Five of the harness faults in DB-114 and the AT-14 generator bug were in this
   tooling. Fair testing passed for Parts 3 and 4 only after four failed runs each (P3: L131, L135, L194,
   L213; P4: L133, L137, L217, L222), each followed by fixes, and its pass rule's
   planted-bug criterion was replaced by "cargo-mutants gate PASS in the ledger" (DB-75; visible in
   `results/fair-*.json` rows).
7. **Part 2 was frozen without a fair-testing PASS.** The only non-dry Part 2 fair run (L72) failed on
   incomplete judge output; Part 2's tags are `part-2-frozen-e1` / `-e2`. CLAUDE.md §6.4 FT-10 says
   freeze needs a PASS (for N ≥ 2). [NEEDS INPUT: how to state Part 2's freeze status in the paper.]
8. **Some quoted numbers live only in untracked files.** P1-T6 (builder–oracle differences) and P1-T14
   (the ghost) are backed by `artefacts/partition-seed*.json` and `artefacts/demo/idea-nq-10k-seed42.json`,
   which are not in git and have no ledger line; the ghost is one seed. The 10⁷ random kernel pairs
   (README L123) have code but no recorded output.
9. **The README is partly stale** (Part 3 freeze status, "college HPC", 68 vs 69 requirements, no
   mention that T-5 was missed; [03](03_experiments_and_results.md) §9).
10. **A decision entry cites a commit inconsistently.** DB-116 says the remaining results are "on
    7c3c313 (DB-114)"; the ledger lines name `7c445b5`, and `7c3c313` is the `pre-tidy` tag. Likely a
    typo; it does not change a result.

---

## 3. Threats to validity

**Internal validity (is the measured effect real?)**
- *Oracle independence.* T-3's reference model is in Python and written from the spec, but by the same
  AI as the engine; a shared misreading of the spec would pass. Mitigated, not removed, by clean-room
  tests (issue 6).
- *Ground truth excludes holding-area records* in EX-6 for every arm (165–193 records at rung 0). This
  is the documented rule (they are not searchable), but it hides the cost that ~2 % of stored records
  cannot be found at all.
- *Live-record control at 0/20 after rungs 1–3* in EX-2 ([03](03_experiments_and_results.md) §5.2)
  weakens "0 findings" for those scans; the sabotage builds were tested on seed 42, ingest and rung 1
  only.
- *Timing measurements shared a machine.* DB-113/DB-114 record that EX-7's two sizes and EX-8 ran side
  by side on one core each, with turbo off, and that EX-6's timings are "descriptive only". The laptop
  also overheats and sleeps (`scripts/hpc` supervisor; DB-113). Latencies are indicative.

**Construct validity (does the metric measure the claim?)**
- *Recall@10 is against brute force,* not human relevance; it measures the approximation, not answer
  quality.
- *nDCG@10 rises with deletion* because the judged set shrinks with the live set; it is not a
  stability measure here.
- *nq-10k is 42 % judged passages* (4,201 of 10,000, by construction), which is far denser in relevant
  answers than a real corpus (nq-100k: 4.2 %). Results at nq-10k may not transfer.
- *"Exactness" is about the group's stored fields,* not about what the search returns, which stays
  approximate (§1).

**External validity (does it generalise?)**
- One machine, one OS (WSL2), one encoder (MiniLM-L6-v2, 384-D), one live dataset (NQ), one
  reference set (SciQ). About 87 % of NQ inserts were out-of-distribution for SciQ, so most data was
  in spawned groups; a deployment whose reference set matched its data would behave differently.
- The largest database-level tests are at nq-100k; the 10⁶ scale test failed with out-of-memory.

**Statistical conclusion validity**
- Five seeds; one confirmatory test (Welch, p = 0.00015) — significant, but with n = 5 per arm.
- P2-T11, EX-7 at nq-100k, the ghost, and P3-T13 (20 deletions, 200 proofs) are single-seed or
  small-sample measures with no interval.

**Comparison validity**
- No baseline is a production vector database. FAISS IVF arms were configured by the project
  (`nlist` = SEVER-DB's group count, `nprobe` = 25 %), which is a fair like-for-like IVF setting but
  not a tuned FAISS. The `softdelete` and `noerase` arms are builds of the same codebase (DB-54).

---

## 4. Future work (realistic next steps)

1. **Rerun the gates on the frozen commit** that DB-116 left on earlier commits (P3-T4, P3-T5,
   P3-T9 mutants, P4-T3), and rerun P2-T5 on a clean tree — so every gate result names the exact
   frozen code.
2. **Run EX-8 on a machine with more memory**, and the pre-registered full sizes (P4-T3 over all
   20,000 ops; EX-2, EX-6 at nq-100k; EX-7 at nq-1m), on native Linux.
3. **Real independent witnesses** (for example via the C2SP tlog-witness protocol the earlier report
   cites) to deliver L-7's missing guarantee.
4. **An independent cryptographic review** of §9.5 and of the G-34 exception.
5. **Explain or fix the live-record control** in EX-2 after rungs 1–3.
6. **Address search drift (T-5).** The rebuild-IVF arm drifts less; investigate whether drift comes
   from emptied groups, spawned-group imbalance, or the holding area.
7. **Comparisons with production systems** (Chroma, pgvector, Milvus …) on the same deletion
   workload, measured the same way (ghost, forensic scan), as a fair external baseline.
8. **Hardware key storage** (TPM/HSM) for group keys (L-1).
9. Bring the README in line with the ledger.

---

## 5. Suggested paper outline

| Section | Content | Draws on |
|---|---|---|
| 1 Introduction | The "ghost" problem; three claims; what is and is not proved | 02 §1–§2; Overview §1.2 |
| 2 Background | IVF search, fixed point, WAL, Pedersen commitments, Σ-proofs, transparency logs, crypto-shredding | 01 |
| 3 Threat model and goals | Parties (user app, backend, engine), trusted operator, attacker who later obtains the disks; T-1…T-6 pre-registered | 02 §2.2, §4.3; §3.3, §11.3 |
| 4 Design | Frozen partition, routing, exact accumulators, certificate, key hierarchy | 02 §4; spec §5–§13 |
| 5 Implementation | Rust + Python, four frozen parts, independent verifier, testing discipline | 02 §5 |
| 6 Evaluation methodology | Data, seeds, gates vs measures, ledger, baselines | 02 §3; 03 §1 |
| 7 Results | Exactness, crash safety, certificates, forensic scan, quantisation, stability (not met), cost | 03 §2–§6 |
| 8 Discussion | What it shows, surprises (OOD rate, G-34, nDCG), failed-then-fixed gates, bugs found | 03 §7–§8 |
| 9 Limitations and threats | 04 §1–§3 | 04 |
| 10 Related work | [NEEDS INPUT: verified related-work citations] | `project_report/research/R02_related_work.md` as leads only |
| 11 Conclusion and future work | 04 §4 | 04 |
| Appendix | Ledger-line table; attack register; AI-assisted method | 03; CLAUDE.md §6.3–§6.4 |

---

## 6. Draft abstract (verified facts only)

> Vector databases used for AI search usually delete a record by hiding it, while index summaries,
> logs and freed disk blocks can still carry it. We describe SEVER-DB, an embedded vector database
> built to make deletion exact, externally checkable and physically effective. Each fixed group of
> vectors stores an integer sum of 24-bit fixed-point vectors, so deleting a vector restores the group
> bit for bit; a Pedersen commitment to each group, a proof of knowledge and an RFC 9162 transparency
> log yield a deletion certificate that a separate verifier checks offline; and all secret data is
> encrypted under a three-level key hierarchy whose group key is destroyed on every deletion. Targets
> were pre-registered before any result. On a single laptop (WSL2), with Natural Questions passages
> embedded by MiniLM-L6-v2 and five seeds, the engine agreed exactly with an independent reference
> model on 23.0 million compared values; no crash violation occurred in 1.34 million injected crash
> points; the verifier accepted all 5,000 honest certificates and rejected all 226,410 generated
> forgeries; a scan of raw 16 GiB disk images after deletion found no deleted data in 30 scans at
> 10,000 passages, while sabotaged builds were detected; and fixed-point vectors kept Recall@10 at 1.0
> against float brute force at one million vectors. Provable erasure cost about 75–109 ms and 39 KB per
> deleted record, against about 0.9–1.4 ms and 10–11 bytes for a tombstone. The pre-registered
> search-stability target was not met (drift 0.008–0.013 against 0.005), the one-million-vector scale
> test ran out of memory, witnesses were simulated, and proofs for deletions that empty a group are not
> bound to their certificate. We report every failed run alongside the passes.

Each number in this abstract is in [03](03_experiments_and_results.md): 23.0 M = 10,648,947 +
12,389,642 (§2); 1.34 M = 1,344,566 (§8); 5,000 / 226,410 (§4.1); 30 scans (§5.1); Recall@10 1.0 (§2);
75–109 ms, 39 KB, 0.9–1.4 ms, 10–11 B (§5.4); drift 0.0079–0.0130 (§5.3). [NEEDS INPUT: author names,
affiliation, target venue and word limit.]
