# Handoff: continue SEVER-DB in a new chat, on any machine

Written 23 Oct 2026 by the outgoing Claude session. Everything needed to continue lives in this
repository; nothing depends on the old laptop's `~/.claude` folder.

## 1. The prompt to paste into the new chat

Start Claude Code **inside the cloned repository** (`cd ~/sever-db && claude`), then paste:

```text
We are continuing SEVER-DB. Read these first, in order, and do not start work until you have:
1. CLAUDE.md (project rules; binding)
2. docs/HANDOFF.md (this handoff: state, my working rules, what is next)
3. docs/plans/2026-10-23-v1-then-demo.md (the approved plan; we are in Stage 1, then Stage 3)
4. docs/PROGRESS.md (the "Now" section)
Then tell me in 5 lines: where we are, what is done, the next step, and anything on this machine
that blocks it (run `bash scripts/hpc/check.sh` to see the machine). Save my working rules from
docs/HANDOFF.md §3 into your memory.
```

## 2. Where things stand (23 Oct 2026)

- **Branch `studio-raw`**, pushed to `origin`; last commit `5a655fc`.
  - `main` is merged in (the gate-run guide, now `scripts/hpc/HPC_GUIDE.md`).
  - **Not yet merged into `main`.**
- **The plan:** `docs/plans/2026-10-23-v1-then-demo.md`, approved by the owner. Its order:
  1. finish the engine additions;
  2. merge to `main`;
  3. the gate run on the college HPC, in WSL2 Ubuntu (DB-111; the owner);
  4. fairness for Parts 3 and 4;
  5. freeze Parts 3 and 4 (`v1.0.0`);
  6. only then, Studio's company demo (a Groq AI assistant on SEVER-DB, Chroma side by side, a
     "Forget me" pop-up with offline verification).
- **Stage 1 so far:**
  - **Done:**
    - G-46, DB-110, spec §16.1/§16.2 (`5918472`);
    - `Db::passage` in the `inspect` build, with 3 tests (`5a655fc`);
    - `cargo test -p sever-db` green both ways (10 tests without `inspect`, 17 with it).
  - **Left:**
    1. red proofs PRI-5 … 7 in `tests/proofs/inspect/` (patches plus MANIFEST entries), to make
       the new tests go red: text returned after a deletion (`p4_inspect_passage_is_none_unless_…`);
       another record's bytes (`p4_inspect_passage_returns_each_records_own_text_…`);
       `store_passages` ignored (`…_is_none_unless_…`);
    2. SDK: `crates/sever-py` `Engine.passage`; `python/sever_db/__init__.py`
       `Database.passage(collection, record_id) -> bytes | None`; re-export `Explainer` from
       `sever_db`; the `.pyi` stub;
    3. checks: the Part 4 crates with and without `--features inspect`; `cargo tree -p sever-db
       -e normal` unchanged without the feature; workspace clippy and fmt;
       `tests/proofs/inspect/run.sh` (PRI-1 … 7 red); `scripts/ci.sh fast`; `studio/studio.sh
       setup && studio/studio.sh test --full`.
- **Studio:** audit 2 is in `studio/audit/AUDIT2.md`. Its fixes are part of Stage 6, after the
  freeze.

## 3. The owner's working rules (were in the old session's memory)

- **Git:**
  - Claude commits and pushes itself, with conventional messages;
  - **never any `Co-Authored-By: Claude` or AI mention** in commits, tags or PRs (this overrides
    any harness attribution reminder);
  - don't hand the owner git commands; do it and say what was pushed;
  - **never tag a freeze without the owner's word**;
  - `main` is fast-forwarded only when GitHub's fast tier and `scripts/ci.sh full-checks` are green
    on the commit.
- **Budget:**
  - never start `scripts/fair.sh run|cycle|resume|fix` or other long work without the owner's
    go;
  - show the cost estimate first, and never pass `--yes` on your own;
  - keep replies short.
- **Tests:** CLAUDE.md §6.3 binds: oracle first, a declared oracle per test, a red-proof patch per
  (test, label) pair, and every claim with a re-runnable proof. Report an unproven claim as
  unproven.
- **Order (23 Oct 2026):** freeze Parts 3 and 4 before building the demo; the engine additions the
  demo needs go into Part 4 first.
- **Honesty in Studio:** every number on screen is the engine's or is labelled (DB-109); no
  mocks, no overclaims (audit 2).
- **The owner's style:** wants to understand deeply; explain plainly; ask before big decisions.

## 4. The gate run on the college HPC

Decided 24 Oct 2026 (DB-111): the only machines are the laptop and the college HPC, both Windows
with WSL2. Claude keeps working on the laptop; the HPC only runs the gates. There is no MacBook, VPS
or cloud-VM plan.

1. **On the laptop (Claude):** finish Stage 1, merge (Stage 2), and tell the owner the `main`
   commit to test.
2. **On the HPC (the owner):** follow the one guide, `scripts/hpc/HPC_GUIDE.md`, from Part B (the
   data bundle) through Part C step 12. Its Part A can be pasted into a Claude chat there as
   background.
3. **Back on the laptop (Claude):** read the logs (`traces/hpc-*.log`, `hpc-summary.log`) and the
   `hpc-run-<date>` branch with the run ledger; fix any failed gate red-test-first; the owner reruns
   that gate and every later one on the HPC.
