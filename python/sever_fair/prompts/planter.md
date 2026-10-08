# You plant bugs (blind sabotage)

`/src` is a git repository with the source of SEVER-DB. Your job: plant **{count}** independent bugs
in the code of **Part {part}** that a good test suite should catch. Nobody who will be scored on them
sees them before scoring.

- `/room/spec/` — the specification. Every bug must break a rule written there (cite § and, when one
  fits, an `SR-` ID from `/room/spec/requirements.yaml`).
- Plant only in: {plant_paths}. Never in test code (`tests/` folders, `#[cfg(test)]` modules).

A good bug is small (1–10 changed lines), compiles, does not crash at start-up, and changes behaviour
the spec requires: an off-by-one, a missing or wrong check, a wrong error kind, a durability step in
the wrong order or missing (fsync before rename, directory sync), a wrong boundary, a recovery that
accepts what it must refuse, a lost update on one path only. Spread them over different modules and
sections. Not allowed: a change only to comments, logging, formatting or names; a change that cannot
alter behaviour; a compile error.

For each bug `NN` (01, 02, …):

1. Edit the files.
2. `cd /src && git diff > /room/out/bugs/NN.patch`
3. Write `/room/out/bugs/NN.json`: `{{"id": "NN", "files": [...], "section": "§…",
   "requirement": "SR-…" or null, "behaviour": <what now goes wrong>, "why": <the spec rule it
   breaks>}}`.
4. `cd /src && git checkout -- . && git apply --check /room/out/bugs/NN.patch`

There is no compiler here; read carefully so each patch compiles (types, borrows, imports).
