# SEVER-DB Studio

**The whole project in one desktop app.** Ten thousand real Wikipedia passages appear as dots on a
map, coloured by group. You add yourself and watch where the database puts you. You delete yourself
and the dot disappears, and you get a receipt anyone can check offline. You climb that receipt up
the public log, try to forge it, kill the database in the middle of a deletion, and watch a float
average drift while SEVER's integer sum stays exact. Every claim of the project is one click away.

Studio drives the real engine (Part 4's build) only through its public surfaces: the SDK
`sever_db`, the separate checkers `sever-verify` and `sever-audit`, and each part's own proof
program. It reaches inside nothing, is owned by no part, and nothing depends on it (DB-106).

## Run it

WSL2 (Ubuntu, with WSLg for the window) or Linux, from the repository root. It needs `uv` and the
Rust toolchain.

```bash
studio/studio.sh setup      # once: Studio's environment, the SDK, the encoder (90 MB, hash-checked), the checkers
studio/studio.sh prepare    # once: stores 10,000 NQ passages through the SDK (~13 min) and lays out the map
studio/studio.sh run        # opens the window, sized to your screen
```

- **No NQ data?** Without `datasets/` (not in git), add `--data synthetic` to `prepare` and `run`.
  The offline fixture then runs everything: d = 16, 240 vectors plus 2,000 made-up ones, spawn
  size 8.
- **Dark theme:** `SEVER_STUDIO_THEME=dark`.
- **X11 instead of Wayland:** `--x11` (needs `libxcb-cursor0`).
- **A busy work directory** is not an error. While a `prepare` runs, `run` says so and names the
  process.
- **Your machine will be refused, and that is a feature.** The database will not start where
  secrets could leak (§12.8–12.9). `studio.sh` passes `--dev`, so the window shows the refusal,
  then opens with the development override, which the database reports. `SEVER_STRICT=1` leaves
  the override out.

## The window

**Layout:**
- A rail of six sections on the left.
- A slim bar at the top, with the checklist pill (✓ 12/37) and **Tour**.
- Short labels everywhere. Every ⓘ opens the full explanation, with its section of the spec.

**Controls:**
- **Tour:** 20 chapters, each with one line on screen, presenter notes behind **Notes**, and
  **Do it**, which runs the chapter's step for you.
- **The checklist:** every row is ticked only by a live check. **Save the session report** writes
  every verdict, with numbers only: no key, `r_t` or passage text.
- **Shortcuts:** `/` search, `N` next chapter, `Esc` close, `F11` full screen.
- **Rail buttons:** A− / A+ change the text size; the eye switches to colour-blind-safe colours.

| Section | What you do | What it proves |
|---|---|---|
| **Home** | Read the four claims; re-hash the data; check the encoder | The data is pinned (P0), the machine is checked before opening (§12.8), and one encoder serves everything (§3.3) |
| **Explore** | Hover a dot; **+ Add yourself**; click a dot, then Delete / Forget; search; fill the bucket | Groups (§6–7); routing of your own text (§7.3); the bucket is stored but unsearchable and flushes at 200 into a group named by a hash of its members (§7.4–7.5); deletion keeps the counts exact (§5) and is idempotent (§5.4); forgetting a person is all or nothing (§12.5) |
| **Receipts** | Verify; flip one byte | `sever-verify` checks a receipt offline (§11.3), and the flipped copy is rejected at the step that fails |
| **Live** | **Log tree**, **Attack lab**, **Kill a delete**, **Float vs exact** | See below |
| **Under the hood** | The log, the disk, crashes, bad input | Signed and witnessed log, with an audit (§10, §11.3); nothing in the clear on disk (§13.2); restart and SIGKILL lose nothing (§12, §15.1); typed refusals (§4, §17); a retry stored once |
| **Proof** | The four parts' own programs; the sabotage lab; the evidence | Survivors-only state, all or nothing at the commit point, chained receipts, forensic erasure (and the SB-24 leak); a planted bug turns a test red; traceability, proofs, gate runs, fairness runs |

### Live

- **Log tree.** Your receipt carries your insert leaf and the hashes beside it on the way up the
  public log. Studio hashes them itself (RFC 9162, with its own code), draws the climb level by
  level, and checks that the top equals the root the operator signed and 4 or more independent
  witnesses cosigned.
- **Attack lab.** Five real forgery attempts on a receipt. Each is caught, and the screen says
  what caught it:
  - change one byte → step 2;
  - cut it short → step 1;
  - trust only 2 witnesses → step 4;
  - another operator's key → step 2;
  - someone else's valid receipt → your own key check.
- **Kill a delete.** One person's records are deleted by a second process, killed with SIGKILL at
  a random moment, five times. After each recovery the person has all of their records or none,
  never some. The tiles count none, all, finished first, and half (always 0).
- **Float vs exact.** 200 real vectors; one is removed and put back 20,000 times, so the members
  never change. The float32 running mean, as most indexes keep it, changes in almost every
  number. SEVER's Q24 integer sum stays bit-identical. This is a model of the §4–5 arithmetic in
  Studio; the engine's own proof is Part 1's (Proof).

## What it does not claim

- **The map is a picture.** t-SNE flattens 384 dimensions to two.
- **Hover text is not read back from the database.** It comes from the dataset or from what you
  typed; the database stores it encrypted and never hands it back.
- **Every byte of a receipt is signed.** So the Attack lab reaches steps 1, 2 and 4. Steps 3, 5 and
  6 guard against the operator itself and are tested by Part 3's attack gate (P3-T2).
- **Part 4's erase program counts what the SB-24 scan decrypts.** It does not print the rebuilt
  vector (Build 3-4 §2.11 step 4).
- **No receipt proves the operator kept no copy** (L-2).

## Tests

```bash
studio/studio.sh test          # fast, offline, ~2 min: lint, mypy --strict, 60 tests
studio/studio.sh test --full   # adds the real display, more screen sizes, a 500-step soak,
                               # the NQ data, a freeze watchdog and live sabotage (~30 min)
```

Every Qt test runs on an emulated 1280 × 800 screen at scale 2 (the owner's laptop). Results go to
`studio/work/test-report.json`. The tests cover:

- **Layout,** on every screen size, in every state: the window fits the screen, nothing is clipped
  or sticks out of its parent, and nothing scrolls sideways (`tests/layout_probe.py`, with a
  screenshot of each state).
- **Click-through:** real clicks, keys and mouse moves, and the whole tour by its buttons.
- **Edge cases:**
  - an empty bucket;
  - deleting from the bucket (§11.3 step 7);
  - emptying a whole group (tag 11);
  - Unicode, emoji, 10 kB texts, empty and very long names;
  - lost answers and crashes;
  - a busy work directory;
  - missing data or model;
  - a report with no secrets.
- **Independent oracles:** RFC 9162 trees and paths are built by the tests from the definitions,
  and §7.5 IDs and §4.2 rounding are written out again.
- **The real display:** `studio.sh smoke` opens on this screen, walks everything and quits (the
  `--full` tier runs it).

## Files

| Path | What |
|---|---|
| `studio.sh` | the entry point |
| `sever_studio/backend.py` | the application backend: account keys (0600, never shown), inserts, deletions, receipts, the index of where each record landed, and the work-directory lock |
| `sever_studio/actions.py` | every demonstration as a function that runs its live check and ticks its row |
| `sever_studio/wow.py` | the Live demonstrations: certificate parser, RFC 9162 climb, attacks, killed deletion, the race |
| `sever_studio/checklist.py` | the 37 rows and the session report |
| `sever_studio/encoder.py`, `layout.py`, `corpus.py` | the pinned encoder (ONNX), the map layout, the data |
| `sever_studio/proofs.py`, `sabotage.py`, `evidence.py` | each part's proof program, the sabotage runner, the generated evidence |
| `sever_studio/ui/` | the window: `copy.py` holds every word on screen; `theme.py` the light and dark palettes |
| `tests/` | the fast tier and the `full` tier |
| `work/` | databases, keys, receipts, the model, screenshots, the test report (not in git; `studio.sh clean`) |
