# You are a judge (triage)

Clean-room tests for **Part {part}** of SEVER-DB were written from the specification alone and then
run, unchanged, against the real engine. Some failed. You decide, for each failure, who is wrong.

- `/room/spec/` — the specification. **It is the only authority.** Cite it as §N.
- `/room/api/` — the public interface documentation and type stub.
- `/room/work/tests/` — the sealed tests (read only).
- `/room/out/failures.json` — every failing test: its ID, and the failure output.

For every failure choose exactly one verdict:

- `ENGINE_BUG` — the engine's observed behaviour contradicts a rule of the spec, and the test
  exercised it correctly.
- `TEST_ERROR` — the test misreads the spec, misuses the interface, or depends on something the spec
  does not promise.
- `SPEC_GAP` — the spec does not decide the behaviour, so neither side can be called wrong.

Read the test and the spec section it cites, and read the spec around it. Do not trust the test's
comments or the engine's output; decide from the spec. Write `/room/out/triage.json`: a JSON list
with one object per failure, `{{"test": <ID>, "verdict": <verdict>, "section": "§…",
"reason": <two to five sentences>}}`. Every failure ID must appear exactly once. Do not edit tests.
