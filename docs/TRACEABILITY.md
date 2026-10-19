# Traceability matrix

Every specification requirement (`SR-<section>-<n>`, Build §2.2) is named by at least one test that
can fail when the rule breaks (CLAUDE.md §6.2–6.3). The matrices are generated from
`spec/requirements.yaml` and the test annotations, never kept by hand:

- [`TRACE_PART_1.md`](TRACE_PART_1.md) … [`TRACE_PART_4.md`](TRACE_PART_4.md), written by
  `python -m sever_testkit_p4.spec_trace report --part 4` (and the Part 1–3 tools for theirs);
- `… spec_trace check` fails CI on an untraced requirement of a built part.

The hand-kept table this file held until 7 Oct 2026 is in its git history.
