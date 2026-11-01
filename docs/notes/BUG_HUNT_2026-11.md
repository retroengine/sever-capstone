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

**Residual limit after BH-7.** Log checkpoints are either due (every multiple of 10,000 leaves, issued lazily before the next operation, §10.3) or a deletion's (always named in its certificate's tag 6). A damaged tail of the checkpoint store that loses only checkpoints no stored certificate names is still not seen; checking due checkpoints at startup would refuse healthy databases after a crash, because a due checkpoint is legitimately missing until the next operation. Recorded with G-39's limit.
