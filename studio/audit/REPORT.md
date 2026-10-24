# SEVER-DB Studio: audit report

> **Status:** every finding below is fixed on branch `studio-raw`; see **§8, After the fixes**. The
> audit scripts named below were turned into Studio tests and deleted; §8 maps each one to its test.
> The screenshots were working files and are not kept (they show passage text).

23 Oct 2026. Audit of `studio/` as it stands on branch `demo-studio`, including the uncommitted edits
to `actions.py`, `layout.py`, `ui/copy.py`, `ui/explore.py`, `ui/map_view.py` and `tests/test_map.py`.
Report only: no Studio code was changed and nothing was committed. All work was done on copies. The
owner's open window on `studio-nq` (pid 136004) was never touched. The copy of it opened cleanly
(recovery passed), so no second copy was needed.

Every claim below names its evidence. The scripts are in `studio/work/audit/` (git-ignored):

| Script | What it proves | Oracle |
|---|---|---|
| `check_routing.py COPY` | each record's group against §7.1–7.3; spawned μ against §7.5; the distance shown against §7.1 | A: own §6.3 parser, §4.2, sequential sums |
| `check_log.py COPY` | each record's group against the engine's own log (DB-86) | B: the engine's public log |
| `spawn_mu.py DIR spill-first\|draw-first` | red proof for the spawned centre | A: §7.5 |
| `experiments.py COPY disk-needle\|kill` | the disk scan cannot see `x̃`; kill-a-delete outcomes | A: §13.2; E |
| `crash.py DIR` | the crash demo on a fresh database | E |
| `shots.py COPY OUT` | screenshots and main-thread timings | — |

Screenshots: `screens-1280/` (15 states, 1280 × 800) and `screens-1920/` (6 states). Copies of a work
directory must sit on ext4 (`~/.cache/...`), because the engine refuses tmpfs (§12.9). Make them with
`rsync -a --exclude accounts.keys`.

---

## 1. Verdict

**Real, with a misleading frame.** Every record's group on the map is the engine's. Studio's index
agrees with the engine's own log export for 10,000 of 10,000 placements and 9,999 of 9,999 live records,
with 0 of 184 group sizes different (`check_log.py`). An independent recomputation of §7.1–7.3 on all
12,799 dataset records finds 0 records in the wrong group (`check_routing.py`). Search hits, receipts,
verifier and auditor verdicts, the log, refusals, restarts and crashes are live engine output.

Around that core, much of what a reviewer would read as the engine is not:

- the group card's `S`, mean and spawned μ are recomputed by Studio;
- the "By group" picture is Studio's arrangement, not the data's;
- "Float vs exact" is a numpy model;
- the disk scan's vector test cannot fail;
- 4 checklist rows tick from untracked local files, 3 tick by just opening a screen;
- both demo databases have run out of spare passages, so three live demos no longer work.

Provenance of the 88 on-screen items in §7: **E 27, P 3, R 16, S 25, I 14**, 2 static texts, and the
checklist drawer, which is mixed.
For the 37 checklist rows, by what ticks them:

| Class | Rows | Count |
|---|---|---|
| E | startup, clusters, insert, routing, flush, unsearchable, search, delete, absent, retry, refusals, forget, verify, tamper, log, audit, restart, crash, attacks, crashdelete | 20 |
| P | shred, leak, phasec, sabotage | 4 |
| R | encoder, evidence; exact, ghost, durable and chain when "Recorded run" or the tour's "Do it" is used | 6 |
| S | data, freetext, disk, climb, race | 5 |
| I | hover | 1 |
| nothing | limits (ticked by opening Receipts) | 1 |

---

## 2. Defects, by severity

### Critical: misleads a reviewer about the engine

**C1. The checklist says "Ticked only by a live check". Seven rows tick without one.**

- `exact`, `ghost`, `durable` and `chain` tick from `artefacts/demo/*-nq-10k-seed42.json`.
  - Those files are git-ignored (`.gitignore:35 /artefacts/`), dated 21 Oct, carry no commit, and
    anyone can edit them.
  - The tour's "Do it" always uses them (`ui/main_window.py:246-249` passes `live=None`).
- `limits` ticks `True` unconditionally on opening Receipts (`actions.py:623-625`,
  `ui/receipts.py:390`).
- `evidence` ticks on opening its tab (it reads files).
- `hover` ticks on any hover.

Evidence: `shots.py` opened screens without one insert or deletion and ticked 16 rows.
`14-drawer-after-no-insert-or-delete.png`. Report row details read "(recorded nq-10k
(idea-nq-10k-seed42.json))".

§ concerned: Build §2.5 (gates versus records), CLAUDE.md §6.3 ("a claim without a proof is reported
as unproven").

Smallest fix:
- A recorded run sets a third state, "seen in a recording" (◐, grey), never ✓.
- The tour's "Do it" runs live on synthetic (seconds).
- `limits` and `evidence` become "shown", not "checked".
- Each recorded-run card prints its file's date and the commit it was made on (or "unknown commit").

**C2. The disk scan's "vectors 0/40" cannot fail.**

- The needle is the first 32 bytes of the float32 vector (`tools.py:332-343`).
- The engine stores `x̃` as integers (§13.2 slot payload; §4.2 `i32`).
- Planting the plaintext `x̃` of the 40 sampled records in a file gives 0 of 40 vectors found, for
  both little- and big-endian. The float32 control finds 40 of 40.
  (`experiments.py COPY disk-needle`: `xqTrue.bin (0, 40)`, `xqFalse.bin (0, 40)`,
  `f32.bin (40, 40)`.)
- The "SEVER-DB: 0/40 vectors" tile is therefore no evidence of encryption.

§13.2, §0.2. Smallest fix: add 32-byte windows of `x̃` (i32 big- and little-endian) as needles, and
write the naive store with `x̃` too, so its column shows the needle can see that form.

**C3. "Float vs exact" is labelled as SEVER but is a numpy model.**

- The legend says "SEVER's integer sum"; the tile says "numbers of the integer sum that changed".
- The arithmetic is `wow.race` (`wow.py:354-385`), 200 vectors in numpy. No engine call.
- Only the ⓘ text says "a model of the arithmetic in Studio".
- The integer side is also trivially exact: `s − q + q = s` in int64. It shows that integer addition
  undoes itself, not that the engine does.

§4.2, §5. Smallest fix: on-screen subtitle "Studio's model of §4–5, not the engine", and the legend
"integer sum (model)". Put a button beside it that runs Part 1's `sever-demo idea --data synthetic`,
which is the engine's own proof of the same claim (§5, P1-T14).

**C4. The default "By group" map draws clusters the data does not have, and the tour describes it
backwards.**

- 11,200 of 12,802 records are in 56 spawned groups.
- A spawned group is 200 records that waited together, with no clustering step (§7.4).
- `layout.GroupMap.point` (`layout.py:176-185`) still packs each group's members into a compact disc
  at its μ's meaning position. "By meaning" (`07-by-meaning.png`) shows the same members scattered
  across the whole map.
- The big discs in the middle are the spawned groups, and the small right-hand cluster is the 128
  frozen groups (1,511 records, about 12 each).
- Tour chapter 3 says "The frozen groups (◆) sit in the middle; the spawned groups (■) ring them"
  (`ui/tour.py:53-55`). The symbols ◆ and ■ appear nowhere on the map (the legend has ✕).
- Evidence: `02-explore.png`, `07-by-meaning.png`, `15-tour-chapter-3.png`.

§7.4, §8 (search ranks by μ, not by these pictures). Smallest fix:
- Default to "By meaning", with the ✕ centres placed at their μ.
- Label "By group" on screen as "arranged by Studio: positions mean nothing".
- Draw spawned groups as a cohort (members at their meaning positions, joined by thin lines), not
  as a disc.
- Correct tour chapter 3.

### High: a wrong number or claim

**H1. A spawned group's centre μ is wrong if a deletion or spillover reaches it before Studio first
draws it.**

- `Studio.place_groups` (`actions.py:157-159`) computes μ = S/n of the current members the first time
  it sees the group, then keeps it.
- §7.5 says μ is the founding cohort's, computed once at the flush.
- Red proof, `spawn_mu.py`, on a fresh synthetic database:
  - 3 spillovers, then the first draw: Studio μ ≠ founding S/n, max |diff| 0.0314;
  - drawn first: bit for bit equal.
- On the NQ copy, 43 of 43 prepare-time groups are correct (no spillover at this size: room needs
  n < 1.5·N/k ≈ 104 < 200).
- The other 13 groups cannot be checked from Studio's files, because their founding cohorts are not
  recorded.
- The same μ feeds the ✕ position, the group card and the distance shown.

Fix: compute μ in `Backend.track` from `Flush.members` at the flush, whose membership the §7.5 ID
hash has already verified, and store it with the flush.

**H2. Both demo databases have no spare passages left, so three demos silently stop working.**

- NQ copy: `loaded = 13,000 = rows + SPARE` (`actions.py:37`). Synthetic: `loaded = 2,240` of 2,240.
- With no spares:
  - the crash demo writes nothing and fails ("killed after 0 acknowledged inserts");
  - "Fill it until it flushes" only toasts "No passages left";
  - Kill a delete builds a person with 0 records.
- `studio.sh smoke --data synthetic --work COPY` gives **FAIL**: checklist 32/37; never shown: flush,
  unsearchable, sabotage, crashdelete; failed: crash.
- On synthetic the bucket also never flushes any more: 5 spawned groups have room
  (`2·k·n < 3·N`, §5.6), so every out-of-distribution record spills over (§7.3).

Fix:
- Show "spare passages left" on screen.
- Load more corpus rows on demand (NQ has a million), or let the demos reuse deleted passages under
  new IDs.
- A "Reset demo database" button that re-runs prepare.

**H3. "Kill a delete" says "Never half: all or nothing, every time" when it showed neither.**

- Outcomes measured:
  - synthetic, 12 runs: none 7, finished first 3, all 2;
  - another 10 runs: none 10.
- The verdict is green whenever no run was partial (`ui/live.py:298`), including when every run
  finished before the kill.
- "All" (a kill after the commit point) is rare. The kill time is a fraction of the whole
  `delete_user` time, and the commit point sits near its end, after the proofs are computed.
- The outcome also comes from the total count (`wow.py:302`), not from each record.

§12.5, §15.4. Fix:
- Count only runs that were killed.
- Say "this run only hit before-commit" when there is no "all".
- Check each ID with `delete` → `absent`.
- Show the commit point on a timeline.

**H4. The "routing" row never checks routing.**

It ticks when the index's counts agree (`actions.py:339-344`). A wrong destination (SB-7, SB-8) with
the same counts would pass.

§7.3. Fix: before each insert, predict the destination per §7.1–7.3:
- j\* and D to it;
- d_M against τ from the artefact;
- whether a spawned group has room, from the engine's `stats` and `group_sizes`.

Then compare with the receipt's placement. `check_routing.py` shows the computation.

**H5. The distance shown is neither §7.1's number nor what decides routing.**

- `Studio.distances` (`actions.py:178-193`) uses `x`, not `x̂`, and a pairwise sum. Result: 0 of
  1,511 bit-identical to §7.1, max diff 6.7e-8.
- It shows Euclidean ‖x − μ‖, while the route is decided by d_M ≤ τ (§7.2). τ appears nowhere in
  Studio.
- "To the next" includes spawned centres, which routing ignores for in-distribution records.
- `05-selected.png` shows a spawned record "0.968 to its centre · 0.968 to the next" with no
  explanation.

Fix: show `D_{j*} = Σ(x̂ᵢ − μᵢ)²` (sequential, §7.1), d_M and τ, and the decision.

**H6. "One encoder" compares three strings.**

`actions.py:285-295` checks that the artefact's, the dataset's and Studio's names are equal. It never
checks that Studio's ONNX encoder reproduces the stored vectors.

§3.3. Fix: encode 5 stored passages and require cosine ≥ 0.9999 with their embeddings.

**H7. "Machine checked" shows a green ✓ on a refused machine.**

`actions.py:249` sets ok when the database was refused and opened with the override. The home screen
says "refused here, opened with the development override" in green (`01-home.png`).

§12.8–12.9. Fix: amber state, "refused (swap not encrypted; mlock), opened with the development
override".

**H8. Groups placed after the first draw overlap other groups (found after the first version of this
report, from the owner's screenshot).**

- Real map: 20 pairs of discs truly overlap, by up to 12.4 map units (a radius is 14.1).
- **All 20 involve the five groups placed last (#176–#180)**, flushes that happened after the map was
  first drawn.
- `GroupMap.ensure` (`layout.py:220-230`) moves only the new discs, starting from where their meaning
  falls, which is inside the packed map. Pushes from neighbours on opposite sides cancel. After 600
  steps the loop stops and **keeps the overlapping position**: nothing checks the result after the
  loop.
- Separately, 326 pairs of dotted edges cross even where the discs don't. The edge is drawn
  `0.12·r + 0.8` outside the members (`map_view.py:324`), but discs are kept only `GAP = 2` apart,
  so two neighbours' edges always cross. On top of that, dots are drawn in pixels (4.6 px ≈ 1.2 map
  units).
- Red proof: `overlap.py`. The first batch of 178 groups places with 0 overlaps; 5 later flushes
  give 13 overlapping pairs, every one involving a late group.
- `test_map.py` cannot catch it: it calls `ensure` once, never adds a second batch to a full map.
- Fix:
  - After the loop, if any overlap remains, search outward in a spiral from the start for the
    nearest free spot of radius `r + GAP`.
  - Keep discs `GAP ≥ pad_a + pad_b + one dot` apart.
  - Add a test that adds batches to a full map.
- Even fixed, this stays Studio's arrangement (C4).

### Medium: unclear to a beginner, or a weak check

- **M1. The frozen partition is fitted on SciQ (13,679 science passages), not on NQ.**
  - Evidence: `datasets/processed/meta.json`; the artefact has m = 13,679; `python/sever_partition/build.py:172`.
  - So 88.2 % of NQ passages fail the drift test and become spawned groups.
  - Studio never says this, and it is why the map is 87 % spawned. (The audit prompt's "k-means on
    nq-1m" is also wrong.)
  - Fix: one line on the map's legend and in tour chapter 3.
- **M2. `Backend.mismatches()` compares counts only** (`backend.py:352-366`): each group's size, the
  holding count and N.
  - Two records swapped between groups pass.
  - `check_log.py` shows the stronger check is available through the public SDK: replay
    `export_log()`.
  - Fix: store each record's `database_lsn` (the receipt already carries it, §16.2) and compare
    leaf by leaf.
- **M3. The group card's `S`, mean and μ are Studio's numbers.** They are labelled only in the last
  line of small grey text ("Recomputed by Studio").
  - The frozen card shows mean ≠ μ with no word on why (μ was fitted on SciQ and never moves, §6.1).
  - `04-group-card-frozen.png`.
  - Fix: a header chip "computed by Studio" and one line "μ is fixed; the mean of today's members
    drifts away from it".
- **M4. The map's ⓘ omits spillover** ("joins the nearest frozen centre if close enough, else the
  bucket", `ui/copy.py:58-68`), while §7.3 checks spawned groups with room first.
- **M5. The crash demo never shows the hard case.** 3 of 3 runs: the insert in flight had not
  committed (`crash.py`: `committed=False`). The child writes its ack after the insert returns, so
  the kill falls between inserts. "The write in flight landed: no" is always the answer.
  - Fix: kill at a random moment after the insert call starts (a marker before the call), so a
    "committed but never acknowledged" outcome can occur.
- **M6. Receipts lose their record names after a restart.** `receipts_of` lives only in memory
  (`ui/main_window.py:89`), so every receipt reads "a deletion from an earlier session"
  (`08-receipt-verified.png`).
- **M7. The attack lab counts "Change one byte" as caught only if it fails at step 2**
  (`wow.py:186`). A flip landing in a length field fails at step 1 and is reported "✗ not caught"
  although it was rejected.
- **M8. The attack lab reaches only steps 1, 2 and 4 of §11.3.** Verified live: step 2, 1, 4, 2, plus
  Studio's own key comparison. Steps 3, 5 and 6 cannot be reached without the operator key. The
  small note says so, which is honest.
  - Fix: a sixth row that runs Part 3's attack gate (P3-T2) on synthetic and shows its step-3/5/6
    rejections (P).
- **M9. The proof cards show no source details.** They give "8 of 8 checks · recorded nq-10k" with
  no date, no commit and no file path (`13-proof-recorded.png`). Covered by C1's fix.

### Low: polish

- **Main-thread pauses over 100 ms:**

  | Action | ms |
  |---|---|
  | `map.refresh` | 253–293 |
  | first map draw | 158–276 |
  | switch to "By meaning" | 89–120 |
  | switch back to "By group" | 206–242 |

  These were measured offscreen; a real display adds painting time. Fix: cache the per-dot brushes
  as arrays, and refresh only the changed dots.
- **Group counts disagree.** Home says "128 frozen + 56 spawned"; the map's status says "181 groups"
  (3 empty groups are not drawn, though they still use a search probe slot, §5.4, §8.1).
- At 1280 × 800 the tour bar covers the "Add yourself" button (`15-tour-chapter-3.png`).
- The colour-blind palette has 8 colours for 184 groups, so groups repeat colours.
- *(Moved up: see H8.)*
- At 1920 the gate-run table uses half the width.
- `ui/drawer.py` docstring says 33 features (there are 37).
- The hover card can sit on top of the selected-record panel (`05-selected.png` state from the probe).

---

## 3. The k-means picture (Part 2 of the prompt)

### What is real

| The owner wants | What the system does | Can it be live and real? |
|---|---|---|
| k-means running, centroids moving | Done **once, offline**, by C-15 on **SciQ** (§6.1–6.2: quantise, dequantise, `KMeans(128, k-means++, n_init=10, max_iter=300, tol=1e-4, lloyd, random_state=seed_kmeans mod 2^32)`). The engine never fits anything. | Yes, as **C-15's own code on the reference data**, labelled "the offline build step". Not as something the database does. |
| dots are the data points | Records are routed to frozen centroids that never move (§7.1–7.3). | Yes: each NQ dot's group is the engine's (proven, §1). |
| spawned groups as clusters | A flush takes exactly the 200 waiting records, with no clustering (§7.4). μ = their S/n, then frozen (§7.5). | No. They must be drawn as what they are. |

### Design

**(a) "How the groups were made" (offline, labelled P/S).** A panel that runs C-15's functions
(`sever_partition.build`) on the SciQ reference rows.

- **Quick mode:** k = 8 on a 2,000-row sample, Lloyd stepped one iteration at a time
  (`KMeans(init=previous centroids, n_init=1, max_iter=1)` repeated). Each step shows the assignment
  (points coloured by nearest centroid) and the update (each ✕ glides to its members' mean), plus
  the iteration number and the objective Σ‖x̂ − μ‖².
- **Real mode:** load the 128 centroids from `artefacts/partition-seed42.svp` and say "C-15 produced
  these with seed 42 on all 13,679 SciQ rows; τ = 25.743 is the 99th percentile of their d_M".
- Projection: one PCA fitted on X̂_ref and then fixed, so centroids visibly move. The caption says
  "2-D picture; every distance is measured in 384-D".

**(b) "Where does a new record go?" (live).** Before calling `insert`, show for the typed text:

1. x̃ = round(x · 2²⁴) (§4.2), first three numbers.
2. The five nearest frozen centroids with D_j (§7.1, sequential on x̂).
3. j\*, then d_M on a gauge with τ marked (§7.2).
4. If d_M > τ: the spawned groups with room (`2·k·n < 3·N`, with k, N and n from the engine's
   `stats` and `group_sizes`) and the nearest of them, else the bucket (§7.3).
5. Call the engine and show its placement next to the prediction: "engine agrees ✓". Studio's
   numbers are labelled S; the placement is E.

**(c) Spawned groups as batches.** Each flush draws its 200 members at their meaning positions,
joined by thin lines to a ✕ at μ, which is computed at the flush from the ID-verified cohort (H1 fix).
Spillover members are drawn hollow. The caption reads "200 records that waited together; not
similar to each other".

Numbers that must match the engine bit for bit: x̃ (§4.2, ties to even), D_j and d_M (sequential
float64, §7.1–7.2), spawned μ (§7.5, `((f64)S/2^24)/n`).

### Tests

Each test names its oracle. None takes an expected value from Studio's code.

| # | Test | Oracle | Status today |
|---|---|---|---|
| K1 | The drawn frozen ✕ values equal rows of the artefact, read by an independent §6.3 parser (`check_routing.parse_svp`, sha256 checked), bit for bit: `Studio.centre("frozen-NNNN") == mu[NNNN]` for all 128 | A §6.3 | not yet a test; parser exists |
| K2 | Every record Studio shows in `frozen-j`: j = argmin over sequential D (ties to smaller label) and d_M ≤ τ | A §7.1–7.3 | holds: 0 / 1,511 violations |
| K3 | Every spawned or holding record: d_M > τ | A §7.3 | holds: 0 / 11,288 |
| K4 | Each record's group equals the group replayed from `export_log()` | B (engine log, DB-86) | holds: 9,999 / 9,999 |
| K5 | Spawned ✕ equals `((f64)Σx̃/2^24)/200` over the founding cohort (from `Flush.members` or the log replay), bit for bit. **Must-fail:** spillover before the first draw (`spawn_mu.py spill-first`) | A §7.5 | **fails** after spillover (0.031) |
| K6 | The distance shown equals `sqrt(cumsum((x̂ − μ)²)[-1])`, bit for bit | A §7.1 | **fails**: 0 / 1,511 |
| K7 | Prediction (b) equals the engine's placement for 50 inserts on synthetic, including at least one frozen, one spillover and one holding case | E (receipt) | new |
| K8 | Stepped Lloyd from k-means++ init gives the same final centroids as one-shot `KMeans(init=same, n_init=1, max_iter=300)` within 1e-12 | B (scikit-learn) | new |
| K9 | §4.2 by hand: x = ±0.5·2⁻²⁴ → 0; 1.5·2⁻²⁴ → 2; −1.5·2⁻²⁴ → −2; 2.5·2⁻²⁴ → 2 | A §4.2 | new |

Test sketch for K2/K3, written from the spec only:

```python
@pytest.mark.spec("SR-7.1-1", "SR-7.3-1")
@pytest.mark.oracle("A", "§7.1 sequential f64 sum, ties to smaller label; §7.2; §7.3")
def test_studio_map_groups_follow_routing_rule(nq_copy):
    art = parse_svp(ARTEFACT.read_bytes())            # own §6.3 parser, sha256 verified
    xhat = q24(X).astype(np.float64) / 2**24         # §4.2 then §4.3
    j, dm = nearest_and_dm(xhat, art["mu"], art["P"])  # cumsum(...)[..., -1] throughout
    for label, jj, d in zip(studio_groups, j, dm):
        if label.startswith("frozen-"):
            assert int(label[7:]) == jj and d <= art["tau"]
        else:
            assert d > art["tau"]
```

---

## 4. Beginner gaps (Part 3 of the prompt)

The worked numbers use two real records from the NQ copy (`check_routing.py` functions):

| | doc565 (in `frozen-0009`) | doc645427 (in `spawn-d007719da6526063`) |
|---|---|---|
| x, first three | 0.004765, 0.032345, −0.042706 | −0.102608, 0.093814, −0.069832 |
| x̃ = round(x · 16,777,216) | 79,948, 542,665, −716,483 | −1,721,480, 1,573,932, −1,171,585 |
| Nearest frozen D, then next | frozen-0009: 0.5447; frozen-0048: 0.6897 | frozen-0063: 1.2545; frozen-0100: 1.2794 |
| d_M vs τ = 25.743 | 17.142 ≤ τ: **in-distribution → frozen-0009** | 37.123 > τ: **OOD → bucket**, then flushed into the spawned group |

**Home** (idea: four claims, checked inputs). It is a list of words with no picture. Add one diagram
of the pipeline: text → encoder → x (384 floats) → x̃ (integers) → group or bucket → log → receipt.
Jargon to explain: "development override", "encoder", "spawned".

**Explore map** (idea: every passage lives in exactly one group; groups are what get counted).
Unexplained: μ, spawn, flush, spawn size, holding area/bucket (two names for one thing), Q24.

Diagrams and formulas to add:

- **Insert flow** (on Add):

  ```
  x̃ = round(x·2²⁴) → D_j = Σ(x̂ᵢ − μ_{j,i})² → j*
    → d_M(x̂, μ_{j*}) ≤ τ ?  frozen j*
    : spawned group with room ?  that group
    : bucket
  ```

  Worked: doc565 → frozen-0009 (17.142 ≤ 25.743).
- **Delete flow** (on Delete):

  ```
  S ← S − x̃,  n ← n − 1,  C_S ← C_S − C_t   (§5.3)
  ```

  Worked: frozen-0009's first number −6,076,813 − 79,948 = −6,156,761, and n 11 → 10. Then the
  commitment check, the receipt and the log leaf, as four boxes lighting up in turn.
- **Why most groups are spawned** (M1): "the frozen groups were fitted on science questions; most
  Wikipedia passages are too far from them (d_M > τ)".

**Search** (idea: the engine opens only the nearest quarter of the groups). Today the screen shows a
beam and ranks but not the method. Add:

1. Rank all 184 groups by D_g.
2. Open p = ⌈0.25 · 184⌉ = 46 of them (empty ones count, §8.1).
3. Score members in float32 and keep the top 10.

Show the score of each hit (the SDK returns it; Studio drops it, `ui/explore.py:650`). Add the note
"records in the bucket are never searched".

**Receipts** (idea: a stranger can check the deletion with two files). The step dots have no labels.
Add the 8 steps of §11.3 as a vertical list with one line each, "n/a" explained (step 6 applies to
group deletions, 7 to bucket deletions). For "Flip one byte", name the field the byte belongs to
(§11.1 tag) and why step 2 catches it: the operator signed every byte. Jargon: certificate vs
receipt (both used), anchors, epoch, LSN.

**Live: Log tree** (idea: your insert is provably in the one public log). Add the formula of each
level, `H = SHA-256(0x01 ‖ left ‖ right)`, with the leaf `SHA-256(0x00 ‖ leaf)`, and say why about 14
hashes prove membership among 13,204 leaves: ⌈log₂ 13,204⌉ = 14. Jargon: Merkle, RFC 9162, witness,
cosignature.

**Live: Attack lab** (idea: forgeries fail at a named step). Map each row to its step in a small
picture of the 8 steps. Explain why the operator could still lie and who catches it (the auditor),
which is today a grey note.

**Live: Kill a delete** (idea: all or nothing). A timeline of one `delete_user`, with the plan, the
proofs, **COMMIT**, key erasure and the certificates, and the kill moment marked on it. Today the
result appears without the commit point (H3).

**Live: Float vs exact** (idea: a float average cannot be undone, an integer sum can). Add the two
formulas side by side:

```
mean ← (mean·n − x)/(n − 1)    (float32, rounds every time)
S ← S − x̃                       (integer, exact)
```

Label it a model (C3).

**Under the hood: Log**. Leaves, witnesses, "hashes in a proof" are numbers without meaning: say what
an auditor does with each. **Disk**: explain plaintext versus ciphertext, and say what may legally be
plaintext (§13.2 list). **Crash**: draw the WAL and the commit point; explain "acknowledged". **Bad
input**: show each error message in full (it is only a tooltip) and say why it holds no ID (§17).

**Proof** (idea: some claims can only be shown from inside). Say in one line what "recorded" means
(C1). **Sabotage**: say what "a test went red" proves, and show the failing test's name, not just
"N failing test line(s)". **Evidence**: explain "requirements with a test", "proofs that tests can
fail" and oracles A–D.

**Key hierarchy and key destroyed** (Part 4's claim). Nothing in the window draws it. Add the tree
RK_t → wrapped by BK_{g,b} → wrapped by GK_g (§13.1–13.2). On a deletion, the group key and bucket
key are rotated and the old ones overwritten in the two-slot key file (§13.3–13.4), so the old
ciphertext stays on disk but nothing can open it.

**States with no feedback.** Fill or crash with no spares left (H2) shows only a toast or a failed
row. Receipts after a restart are unnamed (M6). "Check every question" shows no progress. A sabotage
run gives minutes of compile with only a console behind "Show output".

---

## 5. Presentation

### A 10-minute script for reviewers

| Min | Screen | Say and do | The claim it proves |
|---|---|---|---|
| 0–1 | Home | "Deleting from a vector index usually leaves traces in averages. We keep integer sums, so deletion is exact, and we prove it to strangers." | — |
| 1–3 | Map, **By meaning** | Hover a dot. Add yourself and show the prediction panel (3b) next to the engine's placement. Say why most records are spawned (SciQ). | routing is real |
| 3–4 | Map | Delete your star. Show `S − x̃` on the card and the toast "receipt #…". Delete again: "absent". | Part 1 |
| 4–5 | Proof → Part 1, **Run now** (synthetic, seconds) | "Every touched group equals the state rebuilt from survivors, bit for bit; floats don't." | Part 1, from inside |
| 5–7 | Receipts → Live tree → Attack lab | Verify ACCEPT; flip a byte, REJECT at step 2; climb the tree; five forgeries caught. | Part 3 |
| 7–8 | Kill a delete (with the timeline) + Part 2 card, **Run now** | "Killed before the commit: none; after: all; never half." | Part 2 |
| 8–9 | Proof → Part 4, **Run now** | "A scanner with the whole disk recovers a live record, nothing deleted; skip key rotation (SB-24) and it does." | Part 4 |
| 9–10 | Sabotage (one item run beforehand) + Evidence, failures included | "Every guarantee has a test that was shown to fail." Say what is still open: fairness runs FAIL, VM gates pending. | honesty |

**Cut:** Float vs exact (a model, C3) or turn it into Part 1's live run. Drop the disk tab until C2
is fixed. Drop the "By group" view from the demo. Drop "Retry stored once" and "Bad input" from the
talk (keep them in the checklist).

**Wow without overclaiming:** the prediction panel agreeing with the engine live; a receipt verified
in an empty folder by a separate program; the Part 4 scan finding the deleted data only in the SB-24
build.

### UI changes, in priority order

1. Checklist honesty (C1): a third state for recorded runs; live tour; remove the navigation ticks.
2. Fix the disk needle (C2) and label the race as a model (C3).
3. Map: default "By meaning", draw spawned groups as cohorts, fix tour chapter 3, explain SciQ (C4,
   M1).
4. Spawned μ at the flush (H1); distances per §7.1 with d_M and τ (H5); the routing prediction panel
   (H4).
5. Spare passages: count on screen, more on demand, a reset button (H2).
6. Kill a delete: honest verdict and a commit-point timeline (H3); crash kill inside an insert (M5).
7. The §11.3 steps as a labelled list; receipts keep their names (M6).
8. A key-hierarchy diagram for Part 4.
9. Performance: no main-thread pause over 100 ms on map redraw.
10. Polish (Low list).

---

## 6. Coverage

| Kind | Checked | Exist | How |
|---|---|---|---|
| Sections | 6 / 6 | 6 | screenshots and code |
| Tabs | 11 / 11 | 11 (Live 4, Hood 4, Proof 3) | screenshots and code |
| Checklist rows | 37 / 37 traced in code; 35 / 37 exercised live (smoke walk, probes, `crash.py`, `spawn_mu.py`, `experiments.py`); not: unsearchable, sabotage | 37 | `actions.py`, smoke |
| Tour chapters | 20 / 20 | 20 | text read; each viewed in the earlier probe (those screenshots were lost; chapter 3 kept) |
| On-screen items in §7's table | 88 / 88 | 88 | traced to file:line |
| Buttons | 50 / 50 traced to their handler | 50 (`button(` calls) | code |
| Texts (`copy.TEXT`) | 41 / 41 read | 41 | code |
| Tiles | 15 / 15 | 15 | code and screenshots |

Not checked, and why:

- **Sabotage "Plant it and test"** was not run live (minutes of compile per item; the smoke walk
  leaves it out). The code path was read (`sabotage.py`); `test-full.log` shows the owner's earlier
  live run.
- **Proof "Run now"** for Parts 1–3 was not run by me. Part 4's ran live inside the smoke walk
  (shred, leak, phasec ticked).
- **`studio/studio.sh run` on the real display** was not run, because the owner's window held
  `studio-nq`. I used offscreen emulated screens instead, so WSLg painting time is not included in
  the timings.
- **Dark theme, the colour-blind palette and A−/A+** were not inspected visually (the smoke walk
  exercises A−/A+).
- **"Replay" and typed-text search with the ONNX encoder on NQ** were not exercised.
- **The 13 spawned groups created after prepare** can't have their μ checked from Studio's files
  (H1).

The earlier full-state screenshots (49 states at 1280 × 800) were lost with the session's temporary
folder. The 15 in `screens-1280/` cover every state this report cites.

---

## 7. Provenance of every on-screen item

E engine or separate checker live; P part program live; R file written earlier; S computed by Studio;
I Studio's own index.

| # | Screen | Item | Class | Source | Says so on screen? |
|---|---|---|---|---|---|
| 1 | Top bar | "Natural Questions · N records" | I | `main_window.py:134-139` (index count) | no |
| 2 | Top bar | "development override" | E | `backend.py:163-167` (PlatformUnsafe) | yes |
| 3 | Top bar | checklist n/37 | S | `checklist.py:133` | — |
| 4 | Home | Data pinned | S | `actions.py:259-283` (re-hash vs manifest) | yes |
| 5 | Home | Machine checked | E | `actions.py:245-257` (`db.startup`) | yes, but ✓ green (H7) |
| 6 | Home | One encoder | R | `actions.py:285-295` (three strings) | no (H6) |
| 7 | Home | records · frozen + spawned · waiting | E | `actions.py:297-307` (`stats`) | no |
| 8 | Map | dot position, By group | S | `layout.py:176-185` | ⓘ only (C4) |
| 9 | Map | dot position, By meaning | S | `layout.py:36-55` (t-SNE) | ⓘ only |
| 10 | Map | dot colour = group | I (from E receipts, matches the log) | `backend.py:263, 277-291` | no |
| 11 | Map | ✕ position | S | `actions.py:144-163` | no |
| 12 | Map | frozen μ | R | `actions.py:168-174` (artefact) | no |
| 13 | Map | spawned μ | S | `actions.py:157-159` | no (H1) |
| 14 | Map | dotted outline | S | `layout.py:128-137` | no |
| 15 | Map | ★ yours | I | `backend.py:290` | yes (legend) |
| 16 | Hover | record ID | I | `actions.py:454-475` | — |
| 17 | Hover | group chip | I | same | no |
| 18 | Hover | account | R (parquet cohort column) | `corpus.py:330-334` | no |
| 19 | Hover | text | R, or I if typed | `backend.py:320-324` | yes |
| 20 | Hover | number strip | R, or I if typed | `backend.py:326-331` | no |
| 21 | Group card | n | I | `actions.py:206-217` | no |
| 22 | Group card | S = Σ x̃ | S | same | small text (M3) |
| 23 | Group card | mean | S | same | small text |
| 24 | Group card | μ | R (frozen) / S (spawned) | `actions.py:165-176` | no |
| 25 | Group card | strip of the mean | S | `map_view.py:164` | no |
| 26 | Selected | text | R | `explore.py:348` | no |
| 27 | Selected | x | R | `explore.py:349-353` | no |
| 28 | Selected | x̃ | S | `explore.py:351, 354` | no |
| 29 | Selected | ‖x − μ‖, to the next | S | `actions.py:178-193` | no (H5) |
| 30 | Selected | Forget (n) | I | `explore.py:341` | no |
| 31 | Map | gauge n/200 | I (equals E holding while counts agree) | `explore.py:276` | no |
| 32 | Map | gauge dots and tooltips | I | `map_view.py:520-592` | — |
| 33 | Map | status "records · groups" | I | `explore.py:278` | no |
| 34 | Search | hit order | E | `actions.py:477-489` (`search`) | — |
| 35 | Search | ✓ judged answer | R (qrels) | `corpus.py:342-344` | no |
| 36 | Search | result text | R | `explore.py:651` | no |
| 37 | Search | beam and labels | S | `explore.py:619-627` | no |
| 38 | Search | "first k, top 10 m" | E (with R qrels) | `actions.py:491-507` | no |
| 39 | Search | account lookup | I | `explore.py:633-649` | yes |
| 40 | Search | "waiting in the bucket" note | I | `explore.py:662-670` | — |
| 41 | Add | placement toast | E | `explore.py:416-433` | — |
| 42 | Add | flush toast "ID checked" | E + S | `backend.py:281-287` | — |
| 43 | Delete | "n deleted · receipts" | E | `actions.py:537-571` | — |
| 44 | Delete | total after | E | same | — |
| 45 | Delete again | "absent" | E | `backend.py:391-393` | — |
| 46 | Bucket | fill progress toast | I | `explore.py:457-483` | — |
| 47 | Bucket | "stored, but search can't find it" | E | `actions.py:509-527` | — |
| 48 | Map | Replay | R (`prepare-events.jsonl`) | `explore.py:699-747` | yes |
| 49 | Receipts | receipt numbers | E (LSNs from deletions) | `backend.py:381-383` | — |
| 50 | Receipts | "the deletion of X · account" | I (memory only) | `main_window.py:89` | no (M6) |
| 51 | Receipts | step dots | E (sever-verify) | `actions.py:595-605` | yes |
| 52 | Receipts | ACCEPT / REJECT, reason | E | same | yes |
| 53 | Receipts | hex view, byte flipped | S (flip) on E bytes | `actions.py:607-621` | yes |
| 54 | Receipts | "What it can't prove" | static text | `copy.py:126-132` | — |
| 55 | Log tree | leaf #, tree size, key, witnesses | E (parsed by Studio) | `wow.py:67-96` | yes |
| 56 | Log tree | the hashes | S (recomputed) | `wow.py:117-139` | yes |
| 57 | Log tree | "= the signed root" | S compare on E root | `ui/live.py:118-126` | yes |
| 58 | Attack lab | rows 1–4 verdicts | E (sever-verify) | `wow.py:183-237` | yes |
| 59 | Attack lab | "someone else's receipt" | S (key compare) | `wow.py:238-251` | yes |
| 60 | Attack lab | "5 of 5 caught" | S | `ui/live.py:227-228` | — |
| 61 | Kill a delete | per-run outcome | E (total count) | `wow.py:302-316` | — |
| 62 | Kill a delete | four tiles | E | `ui/live.py:294-297` | — |
| 63 | Kill a delete | "Never half … every time" | S | `ui/live.py:298` | no (H3) |
| 64 | Float vs exact | tiles | S | `wow.py:354-385` | ⓘ only (C3) |
| 65 | Float vs exact | chart | S | same | ⓘ only |
| 66 | Float vs exact | verdict | S | `ui/live.py:360-366` | ⓘ only |
| 67 | Log | leaves, witnesses, hashes in a proof | E | `actions.py:629-646` | — |
| 68 | Log | witness chips | E | same | — |
| 69 | Log | audit result | E (sever-audit) | `actions.py:648-663` | yes |
| 70 | Disk | ordinary store tiles | S | `tools.py:322-355` | yes |
| 71 | Disk | SEVER-DB tiles | S over the engine's files | `actions.py:667-693` | yes (vectors vacuous, C2) |
| 72 | Disk | files · MB | S | same | — |
| 73 | Crash | confirmed before the kill | E (child's receipts) | `actions.py:711-759` | — |
| 74 | Crash | missing after recovery | E (duplicate probe) | `backend.py:333-340` | — |
| 75 | Crash | write in flight landed | E | `backend.py:397-422` | — |
| 76 | Crash | restart before/after | E | `actions.py:697-709` | — |
| 77 | Bad input | five refusals | E (SDK typed errors) | `actions.py:407-450` | yes |
| 78 | Bad input | retry stored once | E | `actions.py:388-405` | yes |
| 79 | Proof | Recorded run checks | R (untracked JSON) | `proofs.py:85-89` | the word "recorded" only (C1) |
| 80 | Proof | Run now checks | P | `proofs.py:48-82` | yes |
| 81 | Sabotage | caught / green verdict | P (cargo test) | `sabotage.py:318-368` | yes |
| 82 | Sabotage | console | P | same | yes |
| 83 | Evidence | 10 tiles | R (`docs/*.md`) | `evidence.py:181-194` | yes |
| 84 | Evidence | gate runs | R (run ledger) | `evidence.py:197-214` | yes |
| 85 | Evidence | fairness runs | R (`results/fair-*.json`) | `evidence.py:217-233` | yes |
| 86 | Drawer | 37 rows | see §1 | `checklist.py:23-113` | claims "live" (C1) |
| 87 | Tour | 20 chapters | static text | `ui/tour.py:28-205` | chapter 3 wrong (C4) |
| 88 | Home | four claim cards | R (text in `copy.py`) | `ui/home.py:410-441` | — |

Counts over rows 1–88: E 27, P 3, R 16, S 25, I 14, static 2, mixed 1 (row 86). Mixed rows count
under their first class: 10 as I, 24 as R, 42 as E, 53 as S, 71 as S.

---

## 8. After the fixes (23 Oct 2026, branch `studio-raw`)

The plan (`PLAN.md`, done and removed on 24 Oct 2026; in git history) was carried out; the decisions are G-45, DB-107 (the engine's `inspect` participant),
DB-108 (`sever-explain`: routing and search explained by the frozen crates' own functions) and
DB-109 (Studio's provenance rule). Each finding has a test that fails without its fix; the tests are
in `studio/tests/` and run with `studio/studio.sh test` (`--full` for the NQ ones).

### Every finding, its fix and its test

| Finding | Fix | Test (oracle) |
|---|---|---|
| C1, M9 | `dd7bd59` | `test_checklist.py`: a recorded run is shown ◐, never ticked, and names its file, date and "commit unknown"; opening Receipts or Evidence ticks nothing; the race model ticks nothing (A Build §2.5) |
| C2 | `9fefcc8` | `test_disk.py`: a planted plaintext `x̃` (i32 big- and little-endian) is found; the naive store holds every form (A §13.2) |
| C3 | `9d2f26c` | `test_checklist.py::…race_model_ticks_nothing`, `…part_1_run_live_ticks_the_race_row` (P) |
| C4, H8, M1, M4 | `9986a93` | "By group" and its discs are deleted; `test_map.py`: every dot is where its meaning puts it, a frozen ✕ is the partition's centroid, one ✕ per engine group, colour by kind (A §6.3, E) |
| H1 | `bb3c122`, `63633e5` | `test_events.py`: a spawned centre is the engine's (DB-107 event) and stays after spillover; `crates/sever-db` `p4_inspect_*` (A §7.5), with 4 red proofs in `tests/proofs/inspect/` |
| H2 | `f9e953c` | `test_spares.py`: the crash demo works after the spares ran out; reset gives a fresh database that agrees with its log (E) |
| H3, M5 | `162a7ed` | `test_kill.py`: the verdict needs a kill; only before-commit kills say so; a half deletion is red; a kill at once deletes none, record by record (A §12.5, E) |
| H4, H5 | `3bf52a2`, `5feeacc` | `test_routing.py`: 1,000 inserts' predictions equal the engine's placements; `why` is §7.1–7.2 worked again with sequential sums, bit for bit (A, E) |
| H6 | `b114522` | `test_full.py::…encoder_check_reencodes_stored_passages` (B: the ONNX model against the stored embeddings) |
| H7 | `b114522` | `test_ui.py::test_ui_a_refused_machine_is_amber_never_green` (A §12.8–12.9) |
| M2 | `f42aa6f` | `test_engine_truth.py`: each record is in the group the engine's log says; a swap that keeps every count is caught (B: `export_log`) |
| M3 | `74997db` | `test_engine_truth.py::…group_card_shows_the_engines_n_and_published_commitment` (E, A §11.1 tag 3) |
| M6, M7 | `b114522` | `test_engine_truth.py`: a receipt keeps its record name after a restart; a rejection at any named step counts as caught (E) |
| M8 | `597e36f` | `test_live.py::…operator_forgeries_are_each_rejected_at_their_register_step` (P: Part 3's kit, E: `sever-verify`) |
| Low: counts | `e0a48a2` | `test_ui.py::test_ui_home_and_map_give_the_engines_one_group_count` (E) |
| Low: tour bar | `e0a48a2` | no automated test: checked by eye on the 1280 × 800 screenshots |
| Low: palette | `9986a93`, then each group its own colour (owner, 23 Oct) | `test_map.py::test_map_each_group_has_its_own_colour`, `test_ui.py::…every_dot_has_its_groups_colour_and_its_kinds_shape` |
| Low: speed | Phase 3 removed the slow path | timings below |

The audit scripts became these tests: `check_log.py` → `test_engine_truth.py`; `check_routing.py`
→ `test_routing.py`; `spawn_mu.py` → `test_events.py` and the Rust `p4_inspect_*` tests;
`experiments.py disk-needle` → `test_disk.py`; `experiments.py kill` and `crash.py` →
`test_kill.py` and `test_spares.py`; `overlap.py` tested the removed "By group" view and went with it.

### The checklist, by what ticks it

| Class | Rows | Before | After |
|---|---|---|---|
| E engine or separate checker, live | startup, clusters, insert, routing, flush, unsearchable, search, delete, absent, retry, refusals, forget, verify, tamper, log, audit, restart, crash, attacks, crashdelete | 20 | 20 |
| P part program, run live | exact, ghost, durable, chain, race, shred, leak, phasec, sabotage | 4 | 9 |
| Studio's own check against a fixed oracle, able to fail | data (manifest), encoder (re-encoded passages), freetext (unit length), disk (every stored form), climb (RFC 9162 against the signed root) | 5 (S) | 5 |
| R recorded file | — (a recording is shown ◐ and ticks nothing) | 6 | 0 |
| shown, not a check | hover, limits, evidence | 2 | 3 |

34 checks and 3 shown rows; nothing ticks from a recording or by opening a screen.

### On-screen items that changed class (rows of §7)

| # | Item | Before | After |
|---|---|---|---|
| 5 | Machine checked | E, green on a refused machine | E, amber ⚠ when refused |
| 6 | One encoder | R (three strings) | B: 5 passages re-encoded, cosine ≥ 0.9999 |
| 8, 14 | By group positions, outlines | S | removed |
| 10 | dot colour | I, a colour per group | E (the log's group): its own colour, the kind as the shape |
| 13 | spawned μ | S | E (the engine's event at the flush) |
| 21 | group card n | I | E (`group_sizes`) |
| 22, 23, 25 | group card S, mean, its strip | S | removed; the card shows the engine's `C_S` (receipt tag 3) and μ with its source |
| 28 | selected x̃ | S | E (the engine's quantiser, DB-108) |
| 29 | ‖x − μ‖ | S, not §7.1's number | E: `D_{j*}`, `d_M`, `τ` from the engine's routing code |
| 33 | map status | I | E (`group_sizes`, empty groups counted) |
| 41 | placement toast | E | E beside the engine's prediction, red if they differ |
| 50 | receipt names | I, lost on restart | I, saved in the index |
| 63 | "Never half … every time" | S, overclaimed | S over E record-by-record outcomes; says what the kills showed |
| 64–66 | Float vs exact | S, ⓘ only | S, labelled a model on screen; the row ticks only from Part 1's program (P) |
| 71 | SEVER-DB disk tiles | S, could not fail | S over every stored form of `x̃`, can fail |
| 79 | recorded run | R, ticked | R, shown ◐ with file, date and "commit unknown" |
| 86 | drawer | claimed "live" | as the table above |
| 87 | tour | 20 chapters, chapter 3 wrong | 21 chapters; chapter 3 rewritten; "How the groups were made" added |

New items: search hit scores and "p of k groups opened" (E, `search` and `explain_search`); the
insert and delete flows (E numbers for the record shown); Groups made (C-15's code on the reference
rows, labelled the offline build step); the operator's forgeries (P and E).

Still Studio's, by design, and said so on screen: the map's 2-D positions and the search beam
(t-SNE, "a 2-D picture; distances are measured in 384-D"), the hover text and numbers (the dataset,
or what you typed), the RFC 9162 climb (an independent re-computation), and the race model.

### Main-thread timings (NQ, 10,000 records, 1280 × 800, offscreen)

| Action | Before | After |
|---|---|---|
| map refresh | 250–290 ms | 34–49 ms |
| first Explore draw | — | 33 ms |
| click a dot (insert flow included) | — | 25 ms |
| select a group | — | 36 ms |
| back to Explore | — | 59 ms |

Inserts, deletions, searches, verification and the part programs run on the worker thread; the
main thread asks the engine only for `group_sizes` and `stats`, and reads the log replay (about
120 ms on NQ), which the worker rebuilds after every write. Nothing on it took over 100 ms.
