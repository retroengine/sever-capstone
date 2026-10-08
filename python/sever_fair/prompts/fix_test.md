# Write one regression test (fair-testing fix, step 1 of 2)

You work in the SEVER-DB repository at `{worktree}` (read `CLAUDE.md` first; the spec in
`docs/SEVER-DB_SPECIFICATION.md` is the authority). An independent check found this:

{finding}

Write **one** regression test (Rust in `crates/<crate>/tests/`, or Python under `tests/` or
`python/<pkg>/tests/`) that {goal}. Label it as CLAUDE.md §6.2 and §6.3 require (`spec` IDs, a
declared oracle; the expected value comes from the spec). Change **only** test files: any other change
is discarded. Files of a frozen part (listed in `freeze/PART-*.sha256`) and new files inside a frozen
part's crate or package are refused: put the test in a new file under `tests/` (Python, through the
SDK or the CLI) when the code belongs to a frozen part. Do not edit or weaken an existing test. Do not touch `tests/cleanroom/`. Do not commit.
You may build and run tests (`cargo test`, `uv run --no-sync pytest`); `git` does not work in this
sandbox.
