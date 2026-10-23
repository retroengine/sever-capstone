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
that blocks it (run `bash scripts/vm/check.sh` to see the machine). Save my working rules from
docs/HANDOFF.md §3 into your memory.
```

## 2. Where things stand (23 Oct 2026)

- **Branch `studio-raw`**, pushed to `origin`; last commit `5a655fc`.
  - `main` is merged in (the VM guide).
  - **Not yet merged into `main`.**
- **The plan:** `docs/plans/2026-10-23-v1-then-demo.md`, approved by the owner. Its order:
  1. finish the engine additions;
  2. merge to `main`;
  3. the VM gate run;
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

## 4. Moving to a VPS / HPC: the method

1. **On the old laptop (already done by this handoff):** everything is committed and pushed. The
   only things not in git are the data (`datasets/`, by design) and Studio's demo databases
   (rebuilt by `studio/studio.sh prepare`).
2. **On the new machine:** follow `scripts/vm/HPC_GUIDE.md`, Part C:
   1. check the machine;
   2. add an SSH key to GitHub;
   3. `git clone git@github.com:retroengine/sever-capstone.git ~/sever-db`, then
      `git checkout studio-raw`;
   4. put the data bundle (`sever-hpc`, from the Windows Desktop) in `datasets/`, then
      `(cd datasets && sha256sum -c MANIFEST.sha256)`;
   5. `bash scripts/vm/check.sh`;
   6. `bash scripts/vm/setup.sh` (`NO_SUDO=1` without admin).
   - Clone onto a **local ext4/XFS disk**, not a network home (the engine refuses others, §12.9).
3. **Install Claude Code on it:** `curl -fsSL https://claude.ai/install.sh | bash` (or `npm install
   -g @anthropic-ai/claude-code`), run `claude` in `~/sever-db`, log in, and paste §1's prompt.
4. **Long runs survive a closed terminal:** use `tmux new -s sever` (detach with Ctrl-b d, come
   back with `tmux attach -t sever`) for both Claude Code and the run, or the guide's `setsid nohup
   …` line.
5. **Then, in that new chat:** finish Stage 1, merge (Stage 2), and start the VM run (Stage 3) on
   that same machine.
