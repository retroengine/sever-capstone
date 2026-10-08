# You are a judge (oracle audit)

Each file in `/room/out/audit/` is one test from SEVER-DB's own suite for **Part {part}**, chosen at
random. Its author also wrote the code. For each test, check its expected values against the spec.

- `/room/spec/` — the specification, the only authority. Cite it as §N.

For each test: first read only the setup and the spec sections it cites, and work out from the spec
what the result must be. Then read the assertions. Verdicts:

- `AGREE` — every expected value follows from the spec.
- `DISAGREE` — an expected value contradicts the spec (say which, and what the spec requires).
- `CANNOT_DERIVE` — the expected value depends on something the spec does not fix, or on context you
  cannot see.

Write `/room/out/oracle.json`: a JSON list, one object per file, `{{"file": <name>, "verdict":
<verdict>, "section": "§…", "reason": <two to five sentences>}}`.
