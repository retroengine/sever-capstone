# Close a spec gap (fair-testing fix)

You work in the SEVER-DB repository at `{worktree}` (read `CLAUDE.md` first, especially §2: a spec
change needs a G-N gap entry and a DB-N decision in the same commit). An independent judge found that
the spec does not decide this:

{finding}

Decide it the most spec-faithful way. Change only `docs/SEVER-DB_SPECIFICATION.md`,
`docs/SPEC_GAPS.md` (a new G-N entry) and `docs/SEVER-DB_PROJECT_OVERVIEW.md` (a new DB-N entry in
the decision register), all three. If the decision requires a code change, say so in the G-N entry;
the next fair-testing run will test it. Do not commit (`git` does not work in this sandbox).
