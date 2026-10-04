# Demo runbook (review, 5 Oct 2026)

> **Location (4 Oct 2026):** this demo now lives in `demo/` and runs on its own (`demo/README.md`). Paths below are relative to `demo/`; the spec, `CLAUDE.md`, `docs/PROGRESS.md` and `datasets/` are at the repository root (`../`).

Everything to type, what will appear, and what to say. Every "you'll see" value comes from the full
rehearsal on 2 Oct 2026 (1,000,000 vectors, seed 42). If you type the commands **in exactly this
order**, the numbers will be the same: the shell's random choices are seeded.

Slides: <https://claude.ai/artifact/5h7RoaX9KGdUkzSZ3zqWn1> (private until you share it; download as
PDF or PPTX from its menu). Backup screenshots of every step: `results/screens/01…14.svg` (open in a browser). They are
the saved output of `scripts/demo.sh repl < scripts/rehearsal.txt`, not hand-made.

---

## A. Before the review (once, with the computer)

| # | Do | Why |
|---|---|---|
| 1 | Commit everything (you said you would) | The ledger then points at committed code |
| 2 | `scripts/demo.sh setup` | Builds the fast environment in `~/.venvs/sever-demo` (imports 1 s instead of 60 s) |
| 3 | `scripts/demo.sh test` | Expect **218 passed** (about 30-70 s) |
| 4 | `scripts/demo.sh run` | The full acceptance run, about 13 min. Expect **PASS**, `certs_verified 912 / 912`, `tamper_caught 10`, `git_dirty: false`. Then commit `docs/RUN_LEDGER.jsonl` and the new `results/p1-demo-*.json` |
| 5 | `scripts/clean_clone_check.sh` | Fresh clone + environment from `uv.lock` + tests + smoke run. Expect **CLEAN CLONE OK** |
| 6 | `scripts/demo.sh repl`, then `load`, then `quit` | Warms the caches in `~/.cache/sever/` so `load` takes about 30-40 s live |
| 7 | Optional: `scripts/demo.sh repl < scripts/rehearsal.txt` | Re-makes every screenshot in `results/screens/` yourself (about 5 min) |
| 8 | Tag: `git tag demo-v0` | The version you demo |

The machine needs **libsodium** (it has 1.0.18; on another Ubuntu: `sudo apt install libsodium23`).

On the day: terminal font large, other apps closed, slides open in one window, the screenshots in
another.

---

## B. The live script (about 8 minutes)

Start: `scripts/demo.sh repl` (prompt `sever>`). Computer time for the whole script: about 2-5 min
(`verify_data` alone is 12-90 s, depending on whether Windows has the files cached).

**Two ways to run it, same numbers either way** (the shell's random choices are seeded, and the tour
runs exactly the commands below, in this order):

- **Guided (recommended):** type `tour`, then `next` for each step. Each step prints **Say:** (what
  to tell the audience), runs its commands for you, then **Look for:** (what to point at). `tour 2`
  skips the slow data check. Lost? `tour` shows where you are (▶).
- **By hand:** type the commands in the table below.

Every result ends with a cyan `┊` note in plain words and a dim `→ next:` hint, so the audience can
read along. `notes off` hides them if the screen gets crowded; `explain <word>` (for example
`explain C_S`) answers "what is that?" on screen.

| # | Slide / type | You'll see | Say (one or two sentences) |
|---|---|---|---|
| 1 | Slides 1-3 | — | "Deleting a vector should leave the database exactly as if it never arrived. Averages can't be undone exactly; integer sums can." |
| 2 | `verify_data` | `PASS: 9 files re-hashed, 0 mismatches` | "The data is pinned and hashed. This re-checks every byte against the committed manifest." |
| 3 | `load` | norm check 0 failures; ID check 1,000,000, 0 rejected; groups min 74, median 2,252, max 161,376; `commitments: r_t for 1,000,000 records … C_S for 128 groups` | "One million real passages, turned into integers, sent to 128 fixed groups; each group gets a sealed fingerprint." |
| 4 | `group 3` then `ids 3` | n = 4,606, the S hash, the blob hash and C_S; first IDs `doc2015226`, `doc273331` | "Group 3 holds 4,606 records. This is its state before." |
| 5 | `delete doc2015226` | `Deleted doc2015226 from group 3   n 4,606 → 4,605`; blob hash and C_S before → after, and the C_t it moved by; `public check C_S_post + C_t = C_S_pre: holds`; `certificate 000000.cert written (12,676 bytes …)` | "One record out. The fingerprint moved by exactly the record's fingerprint, and a signed receipt was written." |
| 6 | `verify 3` | a table: each field's live value next to the value rebuilt from the 4,605 survivors; five ✓, **EXACT** | "The proof of exactness: the live group equals one built only from the survivors, on all five fields." |
| 7 | `cert last` | steps 1, 2, 6a, 6b, 6c ✓; 3-5 NOT CHECKED; **ACCEPTED** | "A separate program, no database, checks the receipt. It says honestly what it can't check yet: the public log." |
| 8 | `tamper last` | forged copy (lsn changed); ✗ operator signature, ✗ proof of knowledge; **REJECTED** | "Reuse a receipt for another deletion: the signature and the proof both fail." |
| 9 | `delete_user 5` then `cert all` | the 5 cohort titles; 15 groups, all ✓; `57 deleted (0 already absent) from 15 groups: all 15 exact`; `untouched groups changed: 0 of 113`; `58 accepted, 0 rejected` | "A whole person's data across many groups: every touched group exact, no other group changed by one byte, every receipt valid." |
| 10 | `delete doc2015226` | `AlreadyAbsent: doc2015226 is not live, so nothing was subtracted and nothing changed` | "A retry after a timeout must not subtract twice." |
| 11 | `ghost` | group of 60,683, 10 deleted: SEVER **0, yes**; float32 **2.1e-07, no**; soft delete **yes (10)** | "Floats are close but not identical. Soft delete still has the records. We're exact." |
| 12 | `sabotage SB-4`, `delete doc273331`, `verify 3`, `cert last` | prompt becomes `sever [SB-4 ON]>`; C_S ✓ but blob ✗, and "blob only: … the secret blinding total r_agg"; certificate: 6a ✓ but **6b proof ✗, REJECTED** | "A planted bug in the hidden bookkeeping: the public check can't see it, the proof can." |
| 13 | `sabotage off`, `verify 3` | `1 group(s) rolled back`, **EXACT** | "Bug off, state rolled back, exact again." |
| 14 | `ledger 14` (the tour uses `ledger session`: only this sitting) | the append-only table, with a plain "what happened" sentence per line and `*` after a dirty commit | "Every command is logged with the commit and the data hash, and says what it did." |
| 15 | `quit`, slides 5-9 | — | The receipt, results, limits, roadmap |

Spare time:

- `sabotage SB-2` / `delete doc273331` (`n 4,605 → 4,605`: it didn't move) / `verify 3` (n ✗, "the
  count says 4,605, but 4,604 records are members") / `sabotage off`.
- `insert doc2015226`: "the same blob hash as at `group 3`": putting the record back returns the group
  to its exact earlier state. `delete doc2015226` again returns to the exact "after" hash.
- `stress 200` (0 mismatches, about a minute with certificates).
- `sabotage` alone: the table of planted bugs, including why SB-1 and SB-3 can't show in the shell.

---

## C. If something goes wrong

| Problem | Do |
|---|---|
| `verify_data` or `load` is slow (first run after a reboot reads 1.5 GB from the Windows drive) | Keep talking through slide 3; or switch to the screenshots |
| A typo | The shell prints the error type and what to type (`verify needs a group number, e.g. verify 3`; an unknown word gets "did you mean …?") and keeps going. Retype |
| Lost your place | `tour` shows the steps with ▶ at the next one; `status` shows what is loaded, deleted and switched on |
| An unexpected error | The shell prints `unexpected <type>` and keeps going (started from `scripts/demo.sh repl`). Carry on with the next step |
| Different numbers from the table above | You changed the command order (seeded choices). Fine: the ticks, "0 of N changed" and ACCEPTED/REJECTED are what matter |
| The shell crashes or hangs | Say "switching to the recorded run" and open `results/screens/` in order, 01 to 14 |
| Asked to show the full run | `tail -1 docs/RUN_LEDGER.jsonl` and the results JSON it names; don't re-run live (13 min) |
| Asked "who made the screenshots?" | "A scripted run of the same shell (`scripts/rehearsal.txt`), output saved as images by the shell's `save` command; I can re-make them." |

---

## D. The words to avoid

- "Proved secure", "the system is built", "the error grows" (it measured flat), "Part 3 is done",
  "the certificate proves the data is gone", any number not in the ledger.
- Say instead: "Part 1 core, in a Python prototype, with a Part 3 preview", "all 5 exactness fields",
  "the certificate proves the group's accounting moved by exactly that record and the operator knows the
  new state; no certificate can prove the operator kept no copy", "AI drafted the spec and wrote the
  Day 2 and Part 3 preview code under my direction; I reviewed, ran and broke it".
