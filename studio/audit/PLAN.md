# Plan: Studio wired raw to the engine, and every audit finding fixed

23 Oct 2026. Builds on `REPORT.md` (findings C1–C4, H1–H8, M1–M9, Low). Baseline: `demo-studio` at
`60c0a9b` (the audited tree, now committed).

## Rules for every step

- **Nothing frozen is edited.** `sever-index`, `sever-search` and `sever-engine` are used only
  through their public functions and extension points (F-3). Engine-side work goes into Part 4's
  `sever-db` and `sever-py` behind a cargo feature `inspect`, so the default build, and the VM gate
  run that tests it, stays byte for byte the same.
- **Tests first, with an oracle** (CLAUDE.md §6.3). Each fix starts with a test that is red on
  today's code, then the smallest change turns it green. The audit scripts in this folder become
  those tests.
- **The provenance rule** (new, DB-109 below), for every number, dot and verdict on screen:
  - it is E (engine) or P (part program), or it carries a visible label saying what it is;
  - a checklist row ticks only from E or P.
- **Every phase ends green:**
  - `studio/studio.sh test --full` passes;
  - `studio/studio.sh smoke` PASSes on synthetic and on NQ, at 1280 × 800 and 1920 × 1080;
  - the phase's audit scripts pass;
  - one commit per step on a branch `studio-raw`.

## Paperwork (with the first commit that needs it)

| ID | What | When |
|---|---|---|
| G-45 | The spec has no read-only way to observe the engine: §16.1–16.2 list only operations. A demo or monitor must recompute or guess. Fix: add `events()` and `explain_route`/`explain_search` as optional, feature-gated APIs | Phase 2 |
| DB-107 | `InspectParticipant` (EP-7): copies only §13.2's public fields of each committed `ChangeSet`, in memory, after commit; never `S`, `r_agg`, `x̃`, record IDs, `r_t` or text; built only with `--features inspect`, never in the default build | Phase 2 |
| DB-108 | `sever-explain`: routing and search explanations computed by the frozen crates' own public functions (`sever_index::route`, `sever_search::rank_groups`, `probe_count`), never re-implemented | Phase 3 |
| DB-109 | Studio's provenance rule (above), amending DB-106 | Phase 1 |

---

## Phase 1: Studio only, from the SDK as it is (no engine change)

Goal: remove the charade with what the engine already returns.

| Step | Fixes | What changes | Test first (oracle) |
|---|---|---|---|
| 1.1 | M2, and the basis for everything | Each record keeps its insert's `database_lsn` (the receipt has it). At open and after every operation, Studio replays `export_log()` and **the replay is the truth**; `index.json` becomes a cache checked against it | `check_log.py` as a test (B: engine log). Red: swap two records between two groups of equal size in `index.json`; the old count check stays green, the new check goes red |
| 1.2 | C1, M9 | Checklist gets three states: ✓ live (E/P), ◐ seen in a recording, ○ not shown. Recorded runs give ◐ and their card shows the file, its date and "commit unknown". Tour "Do it" runs Part 1–3 programs live on synthetic. `limits`, `evidence`, `hover` move to a "shown" list, not checks. The drawer says what ✓ means | (A Build §2.5) loading a recorded run leaves `exact`, `ghost`, `durable`, `chain` not ✓; opening Receipts ticks nothing |
| 1.3 | C2 | Disk needles add 32-byte windows of `x̃` (i32, big- and little-endian); the naive store writes `x̃` too | `experiments.py disk-needle` as a test (A §13.2): planted plaintext `x̃` is found 40/40 |
| 1.4 | C3 | "Float vs exact": on-screen label "Studio's model of §4–5"; legend "integer sum (model)"; a "Run the engine's proof" button runs Part 1's `sever-demo idea` on synthetic | the label is present; the row ticks only from the live Part 1 run |
| 1.5 | M3, part of H1 | Group card from the engine: `n` from `group_sizes()`; `C_S` from the group's latest certificate (`C_S_post`), shown as the engine's commitment; frozen μ from the artefact. `S` and the mean move under a label "computed by Studio from its copy of the vectors" | `n` equals `group_sizes()` (E); `C_S` bytes equal the certificate's tag (A §11.1) |
| 1.6 | H2 | Spare passages: count on screen; NQ loads the next 3,000 rows when spares run low (the corpus has a million); synthetic makes more on demand; "Reset demo database" re-runs prepare | (E) after using every spare, the crash demo, fill and kill-a-delete still work; `smoke` PASS on the current, exhausted copies |
| 1.7 | H3, M5 | Kill-a-delete: verdict counts only killed runs, says "only before-commit kills landed" when no "all", checks each ID with `delete` → `absent`, draws a timeline with the commit point. Crash: a marker before each insert call, so the kill can land inside an insert | (E) a run that finished first never gives a green verdict; per-record check |
| 1.8 | H6, H7, M6, M7 | Encoder check encodes 5 stored passages (cosine ≥ 0.9999). "Machine checked" amber when refused. Receipt names saved in the index. Attack lab: "caught" = rejected at any step, the step shown | (B ONNX vs stored embeddings); (E) startup; names survive a restart; a flip in a length field shows "caught, step 1" |
| 1.9 | Low | Group counts: home and map both say "184 groups (3 empty, still searched)"; tour bar never covers "Add yourself"; drawer docstring 37 | layout probe |

## Phase 2: the engine reports itself (layer 2)

Goal: Studio receives the engine's own events instead of inferring them.

| Step | What | Test first (oracle) |
|---|---|---|
| 2.1 | G-45, DB-107, spec §16.1–16.2 amendment, in one commit | — |
| 2.2 | `InspectParticipant` in `sever-db` behind `inspect`. In `prepare` it copies from the `ChangeSet`: `created` (spawned ID and **the engine's centroid μ**), per touched group `n` and `C_S` before and after, `counters_before`/`after` (`N`, `k`), per request the destination and the outcome. It publishes them in `after_commit`, so a rolled-back transaction emits nothing. In memory only | (A §7.5) a flush's event centroid equals `((f64)Σx̃/2^24)/200` over the founding cohort (`spawn_mu.py`); (A §5.3) `n_after − n_before = ±1` per record; (A §7.6) counters |
| 2.3 | Secrecy | (A §13.2, §17) byte search of every event over a whole session for each record's ID, `x̃`, text, `r_t`, `S`, `r_agg`: zero hits. Red proof: a patch that copies `S` into the event must turn the test red |
| 2.4 | Default build untouched | the full Part 4 suite passes with `inspect` on and off; `cargo tree` of the default build unchanged |
| 2.5 | `sever-py`: `db.events(since)`, built by `studio.sh setup` with the feature | round trip (D) plus 2.2's tests through Python (A) |
| 2.6 | Studio uses events: the spawned μ is the engine's (**fixes H1 for good**); `N`, `k`, sizes and placements live; the bucket gauge from the engine | (B) events replayed equal the `export_log()` replay at every step |

Limit, stated on screen: the engine keeps spawned centroids in plaintext (§13.2) but the frozen engine
has no reader for them. After a restart Studio shows the centroid the engine **reported at the flush**,
saved then. It is never recomputed.

## Phase 3: why it went there (layer 3), and the map redone

Goal: every routing and search decision is explained by the engine's own functions, and the map
stops inventing clusters.

| Step | Fixes | What | Test first (oracle) |
|---|---|---|---|
| 3.1 | — | DB-108. Crate `sever-explain` (new, outside every frozen part): `explain_route(x, artefact, spawned μ and n, N, k)` returns x̃, the five nearest frozen D_j, j\*, d_M, τ, groups with room, destination; `explain_search(q, groups)` returns the ranked groups and the p probed. Calls `sever_index::route::{sq_dist_f64, mahalanobis}` and `sever_search::{rank_groups, probe_count}`. Exposed through `sever-py` with `inspect` | (E) prediction equals the engine's placement for 1,000 inserts on synthetic (frozen, spillover and holding cases) and 2,000 on NQ; (A §7.1–7.3) `check_routing.py` |
| 3.2 | H4, H5 | Add panel shows the prediction beside the engine's placement; the `routing` row ticks only when they agree. The selected record shows D_{j\*}, d_M and τ (explain values, not Studio's) | K6 (A §7.1 bit for bit) |
| 3.3 | C4, H8, M1, M4 | Map: default "By meaning" (labelled "2-D picture; distances are measured in 384-D"). Frozen groups as their records with ✕ at the artefact's μ; spawned groups as scattered cohorts joined to their ✕, spillover hollow; the 11 % own-centre figure as the reason. "By group" either removed or fixed (spiral search after the push loop, gap ≥ both edge pads + a dot) and labelled "arranged by Studio". Tour chapter 3 rewritten; SciQ explained; spillover in the ⓘ | (geometric rule) `overlap.py` as a test: no overlap after adding batches to a full map; K1–K5 |
| 3.4 | — | Search shows each hit's score and "46 of 184 groups opened", from `explain_search` | (E) the hits equal `search()`; (A §8.1) p = ⌈0.25·k⌉ |
| 3.5 | — | "How the groups were made": C-15's own code on SciQ, Lloyd stepped (k = 8 on 2,000 rows), then the real 128 from the artefact; labelled "offline build step (§6), not the database" | K8 (B scikit-learn one-shot), K9 (A §4.2 by hand) |

## Phase 4: a beginner can follow it

Goal: each screen teaches its one idea in 30 seconds. Content from `REPORT.md` §4, worked on real
records (doc565, doc645427).

| Step | What |
|---|---|
| 4.1 | Insert flow and delete flow diagrams on the map, lighting up on Add and Delete, filled from Phase 2–3 events and explanations |
| 4.2 | Receipts: the 8 steps of §11.3 as a labelled list; the flipped byte's field named |
| 4.3 | Log tree: the hash formula per level and why about 14 hashes suffice |
| 4.4 | Kill-a-delete timeline (from 1.7); crash: the WAL and the commit point |
| 4.5 | Part 4: the key hierarchy and the key destroyed on a deletion (§13.1–13.4) |
| 4.6 | One jargon glossary behind ⓘ (Q24, r_t, Pedersen, Merkle, WAL, Mahalanobis, τ, spawn, flush); "bucket" and "holding area" become one name |

## Phase 5: speed and proof of the whole

| Step | What |
|---|---|
| 5.1 | Main thread never pauses over 100 ms: brushes as arrays, refresh only changed dots, layout off the main thread (Low). Test: timings from `shots.py` under 100 ms |
| 5.2 | Re-run this audit's table: every on-screen item E or P, or visibly labelled; the count goes in `REPORT.md` as "after" |
| 5.3 | The 10-minute script of `REPORT.md` §5 run end to end on NQ, timed |
| 5.4 | Optional, the owner's go and budget: a clean-room fairness run on Studio (`scripts/fair.sh`) |

## Every finding, and where it is fixed

| Finding | Step | Finding | Step | Finding | Step |
|---|---|---|---|---|---|
| C1 | 1.2 | H3 | 1.7 | M3 | 1.5 |
| C2 | 1.3 | H4 | 3.2 | M4 | 3.3 |
| C3 | 1.4 | H5 | 3.2 | M5 | 1.7 |
| C4 | 3.3 | H6 | 1.8 | M6 | 1.8 |
| H1 | 1.5 (label), 2.6 (fixed) | H7 | 1.8 | M7 | 1.8 |
| H2 | 1.6 | H8 | 3.3 | M8 | 3.1 adds P3-T2's operator forgeries as a sixth attack (P) |
| M1 | 3.3 | M2 | 1.1 | M9 | 1.2 |
| Low: speed | 5.1 | Low: counts, tour bar, docstring | 1.9 | Low: colour-blind palette | 3.3 (colour by kind, shape by group) |

## Order and size

Phase 1 → 2 → 3 → 4 → 5. Phase 1 alone removes all four critical findings except C4, and needs no
engine work.

Rough size, in working sessions: Phase 1 two to three, Phase 2 two, Phase 3 three, Phase 4 two,
Phase 5 one.

Open question for the owner: should Phase 2 wait until the VM gate run has finished? The `inspect`
feature keeps the default build unchanged, so it need not.
