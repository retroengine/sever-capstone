# Make the regression test pass (fair-testing fix, step 2 of 2)

You work in the SEVER-DB repository at `{worktree}` (read `CLAUDE.md` first; the spec in
`docs/SEVER-DB_SPECIFICATION.md` is the authority). This finding:

{finding}

has a failing regression test, already committed:

```diff
{test_diff}
```

Write the **smallest** fix in the code so that it passes, with `§` comments as CLAUDE.md requires.
`git` does not work in this sandbox; build and run tests with `cargo` and `uv run --no-sync`. Rules, checked by a script from your
diff; a breach discards your work:

- Do not change any test, `golden/`, `freeze/`, `configs/`, `tests/cleanroom/`, `docs/audit/`, or a
  file of a frozen part (listed in `freeze/PART-*.sha256`).
- A change to `docs/SEVER-DB_SPECIFICATION.md` needs a G-N entry in `docs/SPEC_GAPS.md` and a DB-N
  entry in `docs/SEVER-DB_PROJECT_OVERVIEW.md` in the same change.
- `scripts/ci.sh fast` must pass afterwards. Do not commit.
{retry}
