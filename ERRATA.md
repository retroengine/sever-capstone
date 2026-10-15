# Errata (CLAUDE.md §4.1 F-6; template Build §6.3)

The only way to change a frozen part. Each entry: a failing regression test committed first, the
smallest fix, the gates re-run, a new freeze tag.

## E-1

```
E-1  Part: 2   Found by: clean-room tester, fair-testing run 20261008T164154Z-p2-42fc06df
               (docs/FAIR_TESTING.md), test test_concurrent_reader_sees_all_or_nothing (§12.5)
Symptom:        the Python SDK deadlocks when one Database is used from several threads: searches
                from reader threads during delete_user never return (the run hung for hours)
Root cause:     crates/sever-py-p2 took the engine mutex while holding the GIL, then released the
                GIL for the engine call; a thread holding the mutex then waited for the GIL to
                return its result while the GIL holder waited for the mutex
Regression test: tests/errata/test_p2_e1_sdk_threads.py::
                test_p2_errata_e1_sdk_searches_from_threads_during_delete_user, committed at
                a494354 before the fix (red: timed out after 60 s)
Fix:            the mutex is taken inside py.detach, with the GIL released (PyEngine::with and
                close); files changed: crates/sever-py-p2/src/lib.rs; the test's oracle (live
                count, not search results: a search probes 25 % of the groups, §8); red proof
                PR-ERR1; the Part 2 oracle and proof checks scan the new test
Gates re-run:   Part 2 (no later part exists): scripts/ci.sh fast, proofs run --only PR-ERR1,
                gates p2-checks (ledger), the sealed clean-room suite of the run above
New freeze tag: part-2-frozen-e1
```

## E-2

```
E-2  Part: 2   Found by: building Part 3's LogParticipant (Build 3-4 §1.5), 15 Oct 2026
Symptom:        a participant's pre_transaction (EP-7, Build §3.3: "may request a separate committed
                transaction first") is never called, so Part 3 cannot commit its on-demand log
                checkpoint as its own transaction before a deletion (spec §15.3 step 3, SR-15.3-3)
Root cause:     crates/sever-engine declared the hook through sever-txn but no engine path invoked it;
                Part 2 registers no participant, so no Part 2 test could notice
Regression test: crates/sever-engine/tests/errata_e2.rs::
                p2_errata_e2_a_pre_transaction_commits_on_its_own_before_the_deletion, committed at
                8c314a5 before the fix (red: the deletion is prepared with no pre-transaction)
Fix:            Engine::run calls every participant's pre_transaction after planning (an absent record
                or a failed integrity check returns before it: §15.3 steps 1-2) and commits a
                requested PreTxn as its own WAL transaction, confirmed by after_commit (abort if the
                WAL write fails), before the operation's transaction; the hook's documentation and the
                Build §3.3 table say "after planning"; files changed: crates/sever-engine/src/engine.rs,
                crates/sever-txn/src/participant.rs (doc comments only); the regression test's restart
                drops the engine instead of closing it (a storage checkpoint truncates the WAL, §12.4,
                so replay would not show the earlier transactions); red proof PR-ERR2
Gates re-run:   Part 2 (the Part 2 build registers no participant, so the new loop is empty there):
                scripts/ci.sh fast, proofs run --only PR-ERR2, gates p2-checks (ledger), the sealed
                clean-room suite of fair run 20261008T164154Z-p2-42fc06df (ledger)
New freeze tag: part-2-frozen-e2 (left to the owner)
```
