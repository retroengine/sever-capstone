# SEVER-DB Studio

**The whole project in one desktop app.** Ten thousand real Wikipedia passages appear as coloured
clusters on a map. You type your own details and watch where the database puts them. You delete
them and watch them disappear, and you get a receipt anyone can check offline. Every other claim
of the project is one click away: the holding area, search, encryption at rest, crash safety, the
public log, the forensic scan, the planted bugs, and the evidence files.

Studio drives the real engine (Part 4's build) only through its public surfaces: the SDK
`sever_db`, the separate checkers `sever-verify` and `sever-audit`, and each part's own proof
program. It reaches inside nothing. It is owned by no part, is in no freeze manifest, and nothing
depends on it (DB-106).

## Run it

WSL2 (Ubuntu, with WSLg for the window) or Linux, from the repository root. It needs `uv` and the
Rust toolchain.

```bash
studio/studio.sh setup      # once: Studio's environment, the SDK, the encoder (90 MB, hash-checked), the checkers
studio/studio.sh prepare    # once: stores 10,000 NQ passages through the SDK (~10 min) and lays out the map
studio/studio.sh run        # opens the window
studio/studio.sh test       # Studio's own tests, offline (lint, types, 21 tests)
```

Without the NQ data (`datasets/`, not in git), add `--data synthetic` to `prepare` and `run`. The
golden fixture (d = 16, 240 vectors, spawn size 8) then runs everything offline.

**Your machine will be refused, and that is a feature.** The database will not start where secrets
could leak (§12.8–12.9). WSL and most laptops have plain swap, so `studio.sh` passes `--dev`: the
window shows the refusal, then opens with the development override, which the database reports.
`SEVER_STRICT=1` leaves the override out.

## The window

- **Left:** the screens.
- **Right:** the checklist of 33 features. A row is ticked only when its live check has passed in
  this session.
- **Top:** Story mode, which tells the whole project in 17 chapters with presenter notes. "Do it"
  runs each chapter's step.

Each checklist row has a **show** button that goes to its screen and runs it. **Save the session
report** writes `studio/work/studio-nq/report-<utc>.json`: every row with its verdict. It holds
numbers and verdicts only, never a key, `r_t` or passage text. F11 toggles full screen.

| Screen | What you do | What it proves |
|---|---|---|
| **Start** | Re-hash the data, see the startup check, compare the three encoder names, count the groups | The data is pinned (P0). The platform check happens before opening (§12.8). One encoder serves everything (§3.3). The application's index agrees with the database's counts |
| **Map** | Hover any point: its account, group, passage and its 384 numbers as a heat strip. Click a point to select it and show its group | Records live in frozen groups (filled dots) and spawned groups (rings) (§6–7) |
| **Map · Add your details** | Type a name and a sentence | It is encoded by the pinned model, signed with your account's key and stored encrypted. It appears as a white star, with a sentence saying why it went where it went (§7.3) |
| **Map · the bucket** | One record in, then search for it; fill until it flushes | A waiting record is stored but no search finds it (§7.4). At the spawn size all of them leave as one new group, whose ID is recomputed from its members (§7.5) |
| **Map · Search** | Type a question, or `#12` for a dataset question | A beam to the 10 nearest records, with ✓ on the judged answer. Search quality over every question |
| **Map · Delete / Forget** | Delete a record, delete it again, forget a whole account | The dot vanishes and the counts stay exact (§5, §15.3). A second delete returns `"absent"` (§5.4). An account goes all or nothing (§12.5), with one certificate per record |
| **Refusals** | Five invalid inputs, and a retried insert | Errors are typed and hold no secret (§4, §17). A retry is stored once (§15.1) |
| **Receipt** | Verify a receipt, then flip one byte | `sever-verify` runs in a folder holding only the certificate and the anchors and says ACCEPT. The flipped copy is REJECTed with the failing step named, and the flipped byte is shown. The limits are stated (L-2, L-27) |
| **Log** | Read the checkpoint; export and audit | The signed log with at least 4 witness cosignatures (§10). `sever-audit` finds 0 findings (§11.3) |
| **Disk** | Search both disks | A raw byte search finds every ID, text and vector in an ordinary store, and none in SEVER-DB's (§13.2) |
| **Crash** | Restart; pull the plug | A restart loses nothing. A writer killed with SIGKILL mid-stream loses no acknowledged insert (§12, §15.1) |
| **Proofs** | Recorded nq-10k run, or run it now | Part 1: each group equals its survivors-only rebuild, and float and soft-delete baselines do not (§5). Part 2: all or nothing at the commit point (§12). Part 3: chained receipts and audit (§11). Part 4: the forensic scanner recovers a live record but nothing deleted, and the SB-24 build leaks (§13) |
| **Sabotage lab** | Pick one of SB-1 … SB-30 and run it | The real code with one planted bug: a test goes red (Build §2.6) |
| **Evidence** | Open it | Traceability, proofs, oracles, the run ledger and the fairness runs, read from the generated files (failures included) |

## What it does not claim

- **The map is a picture.** It flattens 384-dimensional vectors to two (t-SNE), so neighbours on
  the map are only roughly neighbours in the search. New points are placed beside their nearest
  passages.
- **Hover text comes from outside the database.** It is read from the dataset, or from what you
  typed. The database stores passages encrypted and never hands them back.
- **Part 4's erase program counts what the SB-24 scan decrypts.** That is old accumulator versions
  and deleted records' keys and payloads. It does not yet print the reconstructed vector next to
  the original, as Build 3-4 §2.11 step 4 describes.
- **No certificate proves the operator kept no copy** (overview L-2).

## Files

| Path | What |
|---|---|
| `studio.sh` | the entry point |
| `sever_studio/backend.py` | the application backend: account key store (0600, never shown), inserts, deletions, receipts, and the application's own index of where each record landed |
| `sever_studio/actions.py` | every demonstration as a function that runs its live check and ticks its row; the window only draws these |
| `sever_studio/checklist.py` | the 33 rows and the session report |
| `sever_studio/encoder.py` | the pinned MiniLM encoder as ONNX (revision and SHA-256 checked; cosine > 0.9999 with the dataset's vectors) |
| `sever_studio/layout.py` | the map's 2D layout and the placement of new points |
| `sever_studio/proofs.py`, `sabotage.py`, `evidence.py` | each part's proof program, the sabotage runner, the generated evidence |
| `sever_studio/ui/` | the window |
| `tests/` | Studio's tests, offline on the fixture, with the window drawn offscreen |
| `work/` | the databases, keys, receipts and the model (not in git; `studio.sh clean`) |
