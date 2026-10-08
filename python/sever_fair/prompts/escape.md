# You are a judge (escaped bugs)

Bugs were planted in the code of **Part {part}** of SEVER-DB. The ones in `/room/out/escapes.json`
were caught by **no** test. For each, decide whether that is a hole in the tests.

- `/room/spec/` — the specification, the only authority. Cite it as §N.
- `/room/out/escapes.json` — each escaped bug: its patch and the planter's claim.

Verdicts:

- `TEST_GAP` — with the patch applied, the engine violates a rule of the spec in a way a test could
  observe (through the API, the CLI, the files on disk, or a crash and recovery).
- `EQUIVALENT` — the patch cannot change any behaviour the spec constrains (the planter's claim is
  wrong), or the change is unobservable by any test.

Judge the patch itself, not the planter's description. Write `/room/out/escape_verdicts.json`: a JSON
list, one object per bug, `{{"id": <id>, "verdict": <verdict>, "section": "§…", "reason": <two to
five sentences, and for TEST_GAP the observable symptom>}}`.
