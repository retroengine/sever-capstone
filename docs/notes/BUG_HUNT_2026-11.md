# Bug hunt, November 2026 (before the Part 3 and Part 4 freezes)

Started 1 Nov 2026 after fair run `20261031T225306Z-p3-1479019b` (FAIL, two findings). Owner's rules:
search extensively first, fix every finding red-test-first, then rerun the gates the fixes touch,
then fair testing, then freeze. No time limit; the hunt ends after two full rounds of every search
with no new real finding. IDs continue from October (BH-1 … BH-5, `BUG_HUNT_2026-10.md`).

| ID | Where | Rule | Finding | Class | Status |
|---|---|---|---|---|---|
| BH-6 | `sever-log` `store::scan`, `sever-erasure` `store` scan | §14.9, §17 | A record whose length runs past the end of an **older** (sealed) segment ends that segment's scan silently; only the newest segment may have a torn tail | engine bug | fixed in both scanners: a partial record or leftover bytes in an older segment is `IntegrityViolation` (`p3_log_store_an_older_segment_cut_short_is_refused`, `p4_erasure_store_refuses_an_older_segment_cut_short`, each red before the fix) |
| BH-7 | `sever-cert` participant recovery | §17, §14.9; E-2 | Fair F-1. A byte flipped in the log's checkpoint store: Part 2's `FileStore::open` cuts the store at the first bad record (its torn-tail rule), and after a storage checkpoint the log opened at the genesis checkpoint. Part 2 is not wrong (its own stores are checked through committed references); Part 3's stores had no such check | engine bug | fixed: every stored certificate's tag-6 checkpoint must be in the log, else `IntegrityViolation` (`p3_log_txn_a_damaged_checkpoint_store_refuses_to_open`, red before the fix) |
| BH-8 | fair F-2, `test_consistency_proofs_equal_rfc9162_proofs` | §10.1, RFC 9162 §2.1.4.1 | The clean-room test asks for `PROOF(m, D[n])` with m = n; RFC 9162 defines it for 0 < m < n only, and §2.1.4.2 step 1 fails an empty path. The engine's `None` is right | test error (judge misread) | spec §10.1 states the range (G-50, DB-116) |

| BH-9 | `sever-log` `LogStore::open` | §17, §10.5 (append-only) | Found by the corruption sweep. A checkpoint store that is missing or reads as empty was taken for a half-created log, and `create` **erased every leaf and certificate** before starting a new log | engine bug (severe) | fixed: re-creation only when every log store is empty, else `IntegrityViolation` (`p3_log_store_a_lost_checkpoint_store_is_refused_not_recreated`, red before the fix: the log came back with 0 leaves) |

**Residual limit after BH-7.** Log checkpoints are either due (every multiple of 10,000 leaves, issued lazily before the next operation, §10.3) or a deletion's (always named in its certificate's tag 6). A damaged tail of the checkpoint store that loses only checkpoints no stored certificate names is still not seen; checking due checkpoints at startup would refuse healthy databases after a crash, because a due checkpoint is legitimately missing until the next operation. Recorded with G-39's limit. Stated in §12.3 (G-51).

## Search log

| Search | Round 1 (1 Nov) | Real findings |
|---|---|---|
| 1.1 silent fallbacks: every `.ok()`, `unwrap_or*`, `filter_map`, `let _`, `break`, `continue` in Parts 3–4, the verifier and the auditor (137 sites) | done | BH-6, BH-7 |
| 1.2 corruption sweep, Part 3 SDK: every stored file, 42 positions, flips, zeroed run, cuts, deletion (752 damaged copies after the fixes) | done | BH-9; the 6 left are all in the hash store's last record (G-51) |
| 1.2 corruption sweep, Part 4 SDK: the final build with key file, wrapped store and seal blocks (801 damaged copies over 18 files) | done | none new; the 4 left are the hash store's last record (G-51) |
| 1.3 API edge sweep, final build: record-ID rules (§3.2), bad vectors (§2.2), search edges, repeated and unknown deletes (§5.4), every inclusion and consistency pair checked by an independent RFC 9162 implementation, certificates by LSN, use after drop; oracles: typed errors and no ID or text in them (§17), state unchanged after a refusal | done (the harness shown to report a planted wrong expectation) | none |
| 1.4 adversarial inputs: every single-byte flip, every truncation and a trailing byte of 3 real certificates (10,644 inputs to `sever-verify`); 41 changed log exports to `sever-audit`, with and without the certificates | done | none. A dropped intermediate checkpoint audits clean, which is right: a certificate's own checkpoint is witnessed (4 of 5 checked consistency before signing, §10.4), so no fork can hide behind it |
| 1.5 random sequences on the final build: 5 seeds × 300 operations (inserts in and out of distribution, deletes, repeated deletes, mixed `delete_user`, reopens) against a model; every certificate verified by the independent verifier, every `database_lsn` at its own leaf, deleted records never found, `sever-audit` clean | done | none (the first run's mismatches were the harness: the holding area is counted in `stats`, not `group_sizes`) |
| 1.6 spec MUST audit of §9–§11, §12.8–12.9, §13, §14.5, §14.7, §15, §16 against `spec/requirements.yaml` | done | none: every section has at least as many IDs as MUSTs (§9.9's two MUSTs of one sentence share SR-9.9-1); spec-trace, oracle and proof checks already require a strong test with a red proof per ID |
| 1.7 frozen Part 2 behaviour that Parts 3–4 rely on | done | the store's torn-tail cut (BH-7, BH-9, handled in Parts 3–4); every Part 2 file was damaged in 1.2 with no wrong answer, so no Part 2 erratum is needed |

**Rounds 2 and 3** (1 Nov) repeated 1.2–1.5 with other damage positions, other flip values and ten new sequence seeds (each round: 1,553 damaged copies, the API sweep, 10,644 certificate inputs, 41 exports, 1,500 operations). No new real finding: every corruption hit is the hash store's last record (G-51), and the audit results are the two dropped-checkpoint cases above. **The hunt ends here** by the stopping rule (two full rounds with no new real finding).
