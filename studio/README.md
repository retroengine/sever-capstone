# SEVER-DB Studio

**A company app on SEVER-DB, and the evidence behind it.** Acme Notes is a notes app with an AI
assistant, built the way a company would build one: its own code, the SEVER-DB SDK, and nothing
else. You store a few notes, ask the assistant about them, then ask to be forgotten. Then you check
what is left of you: in SEVER-DB, and in an ordinary vector store (Chroma) running the same app
beside it. You keep one receipt per note, which anyone can check offline.

Every number on screen is the result of a real call, listed live under **SEVER-DB calls**. Studio
runs on the frozen v1.0.0 engine (Part 4's build) and changes nothing in it (DB-106, DB-119).

## Run it

WSL2 (Ubuntu, with WSLg for the window) or Linux, from the repository root. It needs `uv` and the
Rust toolchain (for `setup` only).

```bash
studio/studio.sh setup      # once: the environment, the SDK wheel, the programs, config.toml, the encoder
studio/studio.sh prepare    # once: stores 10,000 NQ passages through the SDK (~10 min), lays out the map
studio/studio.sh run        # opens the window, sized to your screen
```

- **The AI answers** need a Groq key: `export GROQ_API_KEY=…` before `run`. Without it the
  assistant shows the passages it found, labelled "AI off"; everything else works the same.
- **No NQ data?** Without `datasets/` (not in git), add `--data synthetic` to `prepare` and `run`.
  The offline fixture runs everything: d = 16, 240 vectors plus 2,000 made-up ones, spawn size 8.
  It has no real encoder, so the two encoder rows of the checklist stay unticked.
- **Boxes instead of letters** in a few NQ passages (Hindi, Bengali): `sudo apt install
  fonts-noto-core`.
- **Dark theme:** `SEVER_STUDIO_THEME=dark`. **X11 instead of Wayland:** `--x11`.
- **Your machine will be refused, and that is a feature.** The database will not start where
  secrets could leak (§12.8–12.9). `studio.sh` passes `--dev`, so the window shows the refusal,
  then opens with the development override and says so. `SEVER_STRICT=1` leaves the override out.

## The boundary (DB-119)

Studio uses SEVER-DB only as a company's application would:

- it imports only `sever_db`, the SDK;
- it runs `sever-verify`, `sever-audit` and Part 3's attack generator from the paths in
  `studio/config.toml`;
- it reads its data and the project's evidence from the folders named there.

`studio.sh setup` is the only code that knows the repository. It builds the SDK wheel (with the
`inspect` feature, so the app can read a stored passage, DB-110) and the programs into the
git-ignored `studio/vendor/`. It links the data, copies the evidence and writes `config.toml`.
`tests/test_boundary.py` fails if Studio's code imports anything else, runs `cargo`, or names a
repository folder.

## The story: the Assistant

| Step | What you do | What it shows |
|---|---|---|
| **1 You** | Type a name and notes, or **Fill example**; **Store my notes** | Each note is encoded, signed with your key and stored encrypted with its text (§3.4, §13.2). Studio shows where the engine put it, its log position, and whether the engine's own routing code predicted that place (§7.3). A note far from every group waits in the holding area: stored, not searchable (§7.4). **Let other users write** fills it until it flushes into a new group. |
| **2 Ask** | Ask a question | Search (§8), the groups the engine opened (§8.1), and `passage()` for each hit (§16.1), so the text comes only from the database. With a key, Groq writes the answer and cites [1]…[5]; ★ marks your notes. |
| **3 Forget me** | **Forget me** | All your notes go in one transaction (§12.5), with one receipt each (§11). The report opens. |

**The Forget-me report**, row by row, SEVER-DB beside Chroma:

| | SEVER-DB | Chroma, the same app |
|---|---|---|
| Deleted | your notes; each group's `n` before → after | your notes, with `delete()` |
| Search with her own words | what search returns | what `query` returns |
| The app can still read her text | `passage()` | `get()` |
| Her text in the files, before → after | byte search of the database's files | byte search of Chroma's folder |
| Her vectors in the files, before → after | the same, for her vectors | the same |
| Proof she can keep | one receipt per note | none |

Its buttons:
- **Verify receipts (offline):** `sever-verify` checks each receipt with only the receipt and the
  public anchors (§11.3), and its step list is shown.
- **Flip a byte:** the receipt is rejected at the step that fails.
- **Save receipts…:** writes the receipts, `anchors.json` and the exact command that checks them,
  to run in a terminal.

Chroma's column is measured, never assumed. On 6 Nov 2026, with Chroma 1.5.9, `get` and `query`
returned nothing after `delete()`, but the scan still found every ID, text window and vector in its
files (DB-119).

On the right of the screen are the map (your notes ★, lines to the hits; 2-D or 3-D), the
**SEVER-DB calls** log, and the **Engine state** after each action: records, groups, the holding
area, the log's size and its latest checkpoint.

## The rest of the window

| Section | What it shows |
|---|---|
| **Home** | The four claims, each with its status from the evidence: its freeze tag and its gate's latest run (for example "frozen: part-4-frozen · P4-T1 PASS on 2026-10-30, nq-10k"); the data re-hashed; the machine check; the encoder check |
| **Explore** | The map of every passage. Hover a dot; click a ✕ to light its group; add yourself, delete, forget; search; fill the holding area. Routing is predicted by the engine's own code and checked against where the engine put it (§7.1–7.3). After a deletion, one observed line: each group's `n` before → after, and the receipt numbers |
| **Receipts** | Verify any receipt offline; flip a byte |
| **Live** | **Groups made:** the same algorithm as the partition builder (C-15), with one start, small enough to watch; then the real 128 centres, and **Are they clusters? (384-D)**. **Attack lab:** forgery attempts judged by `sever-verify`, including Part 3's 20 forgeries made with the operator's own keys (P3-T2) |
| **Under the hood** | The public log and the auditor (§10, §11.3); the database's files searched for plaintext (§13.2); typed refusals (§4, §17); a retry stored once (§15.1) |
| **Evidence** | Traceability, proofs, oracles, the run ledger, the fairness runs, read from the generated files |

**The tour** has 10 chapters, one action each: the company, store notes, the holding area, ask,
forget me, verify, flip a byte, Chroma beside it, how the groups were made, the log and the
auditor. **The checklist** has 27 rows: 24 checks, each ticked only by a live engine check, and 3
that only show something. **Save the session report** writes every verdict, with numbers only: no
key, `r_t` or passage text.

## What it does not claim

- **The witnesses are simulated.** In v1 the database holds the five witnesses' keys and cosigns
  itself (§10.4). Real independent witnesses are future work (overview L-7).
- **The file scan is not the raw-disk test.** Studio searches the database's own files. Carving
  deleted blocks from a whole raw device with every key a scanner can find is gate P4-T1, run on a
  16 GiB image (see Evidence).
- **What Groq receives is outside the database.** SEVER-DB can neither delete it nor prove
  anything about it.
- **No receipt proves the operator kept no copy** (L-2), or that the person asked for the deletion
  (L-27).
- **`passage()` exists only in the `inspect` build** (DB-110), which Studio uses. The release build
  stores the text encrypted and never returns it.
- **The map is a picture.** t-SNE flattens 384 dimensions to two (or three); distances are measured
  in 384. The frozen groups were fitted on SciQ, not NQ, so most NQ passages end up in spawned
  groups: batches, not clusters.

## Tests

```bash
studio/studio.sh test          # fast, offline: lint, mypy --strict, the boundary, the tests
studio/studio.sh test --full   # adds the real display, more screen sizes, a soak, the NQ data,
                               # and one live Groq call (with GROQ_API_KEY)
```

Every Qt test runs on an emulated 1280 × 800 screen at scale 2. Results go to
`studio/work/test-report.json`. The tests cover:

- **The boundary:** `test_boundary.py`, which also proves it catches each kind of offence.
- **The company app** (`test_company.py`):
  - notes read back byte for byte (§3.4);
  - every hit's text is the engine's passage;
  - after Forget me, every receipt ACCEPTs, `passage()` is absent, search finds none of her IDs,
    and the files hold nothing of her, before or after (§13.2);
  - the call log holds only calls that ran.
- **The assistant** (`test_assistant.py`):
  - no key gives the passages and "AI off";
  - the prompt holds only the question and the passages;
  - the key is never in an answer, a note or an error.
- **The window:** the story walked by clicks, with the report's two columns, Verify ACCEPT, Flip
  REJECT, and the saved command run in a shell. Also the layout on every screen size, in every
  state (`layout_probe.py`).
- **The engine's own truth:** each record's group replayed from `export_log`; routes predicted by
  the engine's routing code; §7.1–7.2 worked again with sequential float64 sums.

## Files

| Path | What |
|---|---|
| `studio.sh` | the entry point and the one bridge to the repository (`setup`) |
| `config.toml`, `vendor/` | written by `setup` (not in git): the SDK, the programs, the data links, the evidence |
| `sever_studio/company.py` | Acme Notes on SEVER-DB: store, retrieve, forget, the checks after, the call log |
| `sever_studio/ordinary.py` | the same app on Chroma |
| `sever_studio/assistant.py` | the Groq call, and "AI off" |
| `sever_studio/config.py` | reads `config.toml` |
| `sever_studio/backend.py`, `actions.py` | the application backend and every demonstration with its live check |
| `sever_studio/wow.py` | the attack lab: the certificate parser, the forgeries, the operator's forgeries |
| `sever_studio/checklist.py`, `explain.py`, `evidence.py` | the 27 rows; the certificate fields and the observed deletion line; the generated evidence and the claims' status |
| `sever_studio/kmeans.py`, `q24.py` | k-means step by step; Studio's own §4.2, labelled |
| `sever_studio/ui/` | the window: `assistant.py` the main screen; `copy.py` every word on screen |
| `tests/` | the fast tier and the `full` tier |
| `work/` | databases, keys, receipts, Chroma's folder, the model, the test report (not in git) |
