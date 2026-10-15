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
