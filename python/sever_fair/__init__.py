"""sever_fair: the automated fair-testing system (docs/FAIR_TESTING.md, FT-1 … FT-10).

    scripts/fair.sh doctor            # sandbox, canary and credential check, no session started
    scripts/fair.sh run 2             # one run for Part 2 (stages 0-9)
    scripts/fair.sh run 2 --module sever-wal
    scripts/fair.sh cycle 2           # run, fix the findings (FT-9), run again, up to fix_rounds
    scripts/fair.sh dry-run 2         # every stage with offline stub agents (plumbing check)

A run lives in ``~/.sever-fair/runs/<run_id>/``, outside the repository, so no sandbox ever sees a
path that leads back to it. The report goes to ``docs/audit/FAIRNESS_P<N>.md`` and the run ledger.
"""
