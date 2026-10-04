# SEVER-DB review demo

The **Part 1 core as a Python prototype**, plus a **preview of Part 3** (commitments, proof of
knowledge, signed deletion certificates, offline verifier), built for the review on 5 Oct 2026. It is
not the engine: the engine is the Rust workspace at the repository root (`../README.md`). This folder
is self-contained (own environment, tests, scripts, container) and nothing outside it depends on it
(Overview DB-56).

**The one outside input is the data**: `../datasets/` (built by `../scripts/data-preparation/`,
verified against `../datasets/MANIFEST.sha256`). Set `SEVER_DATASETS=/some/path` to read it from
elsewhere. It is only ever read.

## Layout (paths relative to `demo/`)

| Path | What |
|---|---|
| `python/sever_demo/` | The demo engine: data checks, Q24 quantiser, record IDs, groups, index, routing, baselines, run ledger, commitments, proofs, certificates, the full run (`demo.py`) and the demo shell (`repl.py`) |
| `python/sever_verify/` | The independent offline certificate verifier (shares no code with the engine; a test enforces it) |
| `tests/` | 233 tests, spec-driven (`spec_oracle.py`), RFC test vectors in `tests/vectors/` |
| `scripts/` | `demo.sh` (setup, shell, run, tests, Docker), `clean_clone_check.sh`, `rehearsal.txt`, `entrypoint.sh` (container) |
| `docs/` | `DEMO_PLAN.md`, `DEMO_RUNBOOK.md`, `CODEBASE_WALKTHROUGH.md`, `RUN_LEDGER.jsonl`, `notes/` |
| `results/` | Result files of runs (named in the ledger) and the rehearsal screenshots |
| `pyproject.toml`, `uv.lock` | The demo's own environment (Python 3.13, numpy, scikit-learn, pyarrow, pandas, rich) |
| `Dockerfile`, `compose.yaml` | The container: everything but the data |

## Run it locally (WSL; needs `uv` and the system libsodium 1.0.18: `apt install libsodium23`)

`scripts/demo.sh` works from any directory.

```bash
demo/scripts/demo.sh setup        # once: ~/.venvs/sever-demo from demo/uv.lock
demo/scripts/demo.sh test         # all tests (233; 38 must-fail: add -m mustfail)
demo/scripts/demo.sh run          # the full 1,000,000-vector acceptance run (~13 min); appends to the ledger
demo/scripts/demo.sh run --rows 50000 --stress 100   # smoke run (~45 s)
demo/scripts/demo.sh repl         # the demo shell; type tour, then next (or help)
cd demo && PYTHONPATH=python python -m sever_verify <anchors.json> <file.cert>   # check a certificate offline
```

## Run it in a container

Needs Docker; under WSL, turn on Docker Desktop → Settings → Resources → WSL integration for this
distro. `compose.yaml` mounts `../datasets` read-only at `/data`, and `results/` and `docs/` (the
ledger) from this folder, so outputs land here as with a local run.

```bash
demo/scripts/demo.sh docker-build                   # image sever-demo:local, stamped with the git commit
demo/scripts/demo.sh docker test                    # all tests inside the container
demo/scripts/demo.sh docker run --rows 50000 --stress 100
demo/scripts/demo.sh docker repl                    # the demo shell
demo/scripts/demo.sh docker verify <anchors.json> <file.cert>
```

There is no git inside the image: `docker-build` stamps the commit and the dirty flag into the image
(`SEVER_GIT_COMMIT`, `SEVER_GIT_DIRTY`), and the ledger records those. Build through `demo.sh` so the
stamp is present; the ledger tests check it.

## Latest full run

2 Oct 2026, seed 42, 1,000,000 vectors, 128 groups: **PASS**. All 5 exactness fields on every touched
group, 0 of 105 untouched groups changed, 912 of 912 certificates accepted by the offline verifier,
10 of 10 forged copies rejected. Ledger: `docs/RUN_LEDGER.jsonl`.
