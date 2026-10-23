You are auditing SEVER-DB Studio (`studio/` in this repository), a desktop demo of the SEVER-DB
vector database. Another session wrote it. Your job is to find out whether it really shows the
database, or only looks like it does, and how to make it clear to a beginner. Assume nothing that
you have not checked yourself. Report; do not change code.

## Ground rules

- Read `CLAUDE.md` first and obey it. In particular:
  - never print, log or copy `r_t`, private keys, group keys or passage text from any database
    directory;
  - never modify `datasets/` or any file of a frozen part (Parts 1 and 2);
  - do not commit.
- The specification `docs/SEVER-DB_SPECIFICATION.md` is the truth. Cite it as §N for every claim
  about what the database does.
- Work on copies. Never open `studio/work/studio-nq` while a Studio window may be using it: copy it
  first, and if the copy fails its integrity check, copy again when the window is closed.
- Every finding needs evidence anyone can re-run: a file and line, a command and its output, or a
  screenshot. A claim without evidence is reported as unproven.
- **Coverage must be complete, not sampled.** List every screen, tab, button, card, number and
  checklist row (`studio/sever_studio/checklist.py` has 37 rows), and say for each one that you
  checked it. At the end, report how many items you checked out of how many exist. If you could
  not check something, say so and why.

## Part 1: Is it real, or a wrapper around mock files?

For **every number, dot, verdict and text on screen**, trace where it comes from. Put each in
exactly one class:

| Class | Meaning |
|---|---|
| **E: engine** | Returned at that moment by the real engine, through the SDK `sever_db` (`crates/sever-py`) or a separate checker (`sever-verify`, `sever-audit`) |
| **P: part program** | Printed by a part's own proof program, run live |
| **R: recorded** | Read from a file written earlier (`artefacts/`, `golden/`, generated docs, `studio/tests/data/`) |
| **S: Studio computes** | Calculated by Studio itself in Python (numpy), even if it imitates the engine |
| **I: Studio's index** | Studio's own bookkeeping (`index.json`, `group-map.json`, its account keys) |

Produce one table: item, screen, class, source (file:line), and whether the screen says so.

**Flag as a defect** anything a reviewer would take for engine output that is not E or P, and is
not labelled as such. Check at least these, and verify each yourself; they are leads, not
conclusions:

- **Hover text:** where it comes from. The engine never returns plaintext (§13.2).
- **The group card's numbers:** count `n`, sum `S`, mean, centre μ. Are they read from the engine,
  or recomputed by Studio from its own copy of the vectors? Does `n` match the engine's
  `group_sizes`?
- **A spawned group's centre μ:** does Studio compute it from the founding 200 (§7.5)? Or from the
  members it sees later, which is wrong once spillover (§7.3) or deletions have happened?
- **The map's positions:** t-SNE plus Studio's group layout. Is any of that the engine's? Does the
  screen claim otherwise?
- **Studio's index:** `Backend.mismatches()` compares it with the engine. Which fields, exactly?
  What could disagree without being caught?
- **"Float vs exact":** a numpy model or the engine?
- **"Kill a delete":** is the outcome read back from the engine after recovery? Why does it almost
  always end "none deleted"? Is that shown honestly?
- **The Attack lab:** which verifier steps (§11.3) it really reaches, and which it cannot.
- **The Proof tab:** "Recorded run" against "Run now". Can a reviewer tell them apart?
- **Every checklist row:** does a live check tick it, or can it be ticked without the engine?

## Part 2: The k-means picture

The owner wants the map to show the k-means algorithm live: the dots are the data points, and
everything must be real to the engine and accurate. Establish from the spec and the code:

1. **What the engine actually does:**
   - The frozen partition is fitted **offline** by the partition builder C-15 (`sever_partition`),
     with k-means on `nq-1m` (§6). The engine never runs k-means.
   - Routing (§7.1–7.3) sends a new vector to the nearest frozen centroid, after a Mahalanobis
     drift test.
   - Spawned groups are **not** clustered: whichever 200 records waited together are flushed as
     one group (§7.4).

   Say plainly which parts of "live k-means" can be real, and which cannot.
2. **An honest design** that shows:
   - (a) k-means itself, run live and visibly: assignment and update steps, centroids moving,
     using C-15's own code and parameters on a sample, clearly labelled as the offline build step;
   - (b) the engine routing a new record against the real frozen centroids, with the distances
     and the drift test τ shown;
   - (c) spawned groups as what they really are.

   Every number must be E, P or labelled S, and must match the engine bit for bit where the spec
   pins it (§4.2 rounding, §7.1 order of summation).
3. **Checks for the current map:**
   - Are the drawn centres the real μ: frozen from `artefacts/partition-seed42.svp`, spawned per
     §7.5?
   - Is each dot's group the engine's?
   - Does "distance to its centre" equal §7.1's formula?

   Write tests that would prove each one, with expected values taken from the spec or the
   artefact, never from Studio's code (CLAUDE.md §6.3).

## Part 3: Can a first-year CS student follow it?

Walk the tour (**Tour** button, 20 chapters) and every screen as that student would. For each
screen, record:

- **The one idea it should teach,** and whether a beginner gets it in 30 seconds.
- **Jargon left unexplained:** for example Q24, `r_t`, Pedersen, Merkle, WAL, Mahalanobis, τ,
  spawn, flush.
- **Missing logic:** where the screen shows a result (✓, ACCEPT, "caught") but not **why**. Say
  which diagram or formula would make it clear:
  - a flowchart of insert → quantise → route → group or bucket;
  - delete → S − x̃ → commitment check → receipt → log;
  - the Merkle path;
  - the verifier's 8 steps;
  - search ranking groups and opening 25 %;
  - the commit point on a timeline;
  - the key hierarchy and the key destroyed.

  Give each its formula from the spec, worked on one real record.
- **Too much or too little text,** labels that mislead, and states with no feedback.

## Part 4: UI, UX and presentation

- Run `studio/studio.sh smoke --data synthetic` and `studio/studio.sh run`. Take screenshots at
  1280 × 800 (the owner's laptop) and 1920 × 1080.
- Judge each screen on layout, hierarchy, colour (light theme, colour-blind safety), clipping,
  overlap, speed (any freeze over 100 ms), empty states and error messages.
- Judge the presentation as a 10-minute demo to reviewers:
  - the order of screens;
  - what is missing to prove each part's one claim (CLAUDE.md §6.1);
  - what to cut;
  - what would "wow" without overclaiming.

## What to hand back

1. **Verdict:** real or wrapper, in one paragraph, with the counts per class (E/P/R/S/I).
2. **Every defect,** ranked by severity:
   - **Critical:** misleads a reviewer about the engine.
   - **High:** wrong number or claim.
   - **Medium:** unclear to a beginner.
   - **Low:** polish.

   Give each one evidence, the § it concerns, and the smallest fix.
3. **The k-means design** of Part 2, with its tests.
4. **The beginner gaps** of Part 3, as a list of diagrams and formulas to add, screen by screen.
5. **A presentation script** for 10 minutes, and a list of UI changes in priority order.
6. **Coverage:** items checked out of items that exist, and every item not checked, with why.
