# Notes: index

> **Location (4 Oct 2026):** this demo now lives in `demo/` and runs on its own (`demo/README.md`). Paths below are relative to `demo/`; the spec, `CLAUDE.md`, `docs/PROGRESS.md` and `datasets/` are at the repository root (`../`).

One file per module. Each has the same sections: **one line**, **why**, **how it works**, **decisions**,
**measured results**, **tests**, **trap questions**, **open fixes**. Every number was produced by
running code; the command is given next to it.

| File | Covers | Who wrote the code |
|---|---|---|
| [P1-idea.md](P1-idea.md) | The five sentences (DEMO_PLAN §2.1), in your own words | **You, in progress** |
| [P1-data.md](P1-data.md) | `data.py`: loading the datasets, norm check (§4.1), manifest check | You (Day 1) |
| [P1-quant.md](P1-quant.md) | `quant.py`: Q24 quantiser (§4.2), dequantiser (§4.3) | You (Day 1) |
| [P1-ids.md](P1-ids.md) | `ids.py`, `errors.py`: record ID rules (§3.2), typed errors (§17) | Claude (Day 2) |
| [P1-group.md](P1-group.md) | `group.py`, `index.py`: exact deletion, survivors check, sabotage (§5) | Claude (Day 2) |
| [P1-partition.md](P1-partition.md) | `partition.py`: k-means on SciQ, routing (§6.2, §7.1) | Claude (Day 2) |
| [P1-ledger-baselines.md](P1-ledger-baselines.md) | `ledger.py`, `baselines.py`: run record, the ghost | Claude (Day 2) |
| [P1-demo-run.md](P1-demo-run.md) | `demo.py`: the full 1M-vector run and its results | Claude (Day 2) |
| [P1-commitments.md](P1-commitments.md) | Part 3 preview: Pedersen commitments, the proof of knowledge, certificates, the offline verifier | Claude (3 Oct) |
| [../DEMO_RUNBOOK.md](../DEMO_RUNBOOK.md) | `repl.py`: the live demo, step by step, with expected output | Claude (Day 3) |

**How to revise:** read "one line" and "how it works", then do the trap questions without opening the
answers. Rewrite any answer you can't say in your own words. **Read P1-group.md first**; it's what the
reviewer will push on.

## Commands

| Purpose | Command |
|---|---|
| All tests | `PYTHONHASHSEED=0 uv run pytest -q` |
| Sabotage tests only | `PYTHONHASHSEED=0 uv run pytest -q -m mustfail` |
| Fast environment, once | `scripts/demo.sh setup` (builds `~/.venvs/sever-demo`; imports 1 s instead of 60 s) |
| Demo shell | `scripts/demo.sh repl`, then `tour` and `next` for the guided story (`help`, `explain <word>`) |
| Tests (fast) | `scripts/demo.sh test` |
| Clean-clone check | `scripts/clean_clone_check.sh` |
| Verify certificates offline | `PYTHONPATH=python python -m sever_verify <anchors.json> <file.cert> …` |
| Rehearsal (makes `results/screens/`) | `scripts/demo.sh repl < scripts/rehearsal.txt` |
| Full demo run | `PYTHONHASHSEED=0 PYTHONPATH=python uv run python -m sever_demo.demo --seed 42` |
| Smoke run | `… -m sever_demo.demo --rows 50000 --stress 200` |
| Sabotage run (must FAIL) | `… -m sever_demo.demo --rows 50000 --sabotage SB-2` |
| Last ledger lines | `tail -3 docs/RUN_LEDGER.jsonl` |

## Status (3 Oct 2026)

- `scripts/demo.sh test`: **233 passed**, of which 38 are must-fail (a planted bug or forgery must be
  caught). Day 2 and Part 3 tests take expected values from `tests/spec_oracle.py` (written from the
  spec) and from RFC test vectors in `tests/vectors/`.
- Full run with the Part 3 preview: **PASS** (see P1-demo-run.md).
- Layout: all project Python is under `python/`: `sever_demo` (the demo engine) and `sever_verify`
  (the independent offline verifier; a test forbids either importing the other). Tests in `tests/`.
- ruff and mypy: **clean for the whole codebase** (Day 1 files tidied on 3 Oct: naming, type hints,
  formatting, seed 42, two new quantiser tests).
- **Environment:** `scripts/demo.sh` uses a second environment on the Linux side (`~/.venvs/sever-demo`):
  imports take ~1 s instead of ~60 s from `/mnt/c`. Crypto needs the system libsodium (1.0.18 here).
