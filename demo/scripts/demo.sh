#!/usr/bin/env bash
# The demo, self-contained in demo/: its own environment, tests and Docker image. The only outside
# input is the data: ../datasets next to demo/, or $SEVER_DATASETS. Works from any directory.
#
# Why a second venv: .venv on /mnt/c makes every file read cross the Windows bridge. Importing
# scikit-learn took 63 s cold there, and 3.4 s cold (1.0 s warm) from ~/.venvs (2 Oct). uv builds
# ~/.venvs/sever-demo from demo/uv.lock.
#
#   scripts/demo.sh setup        # once: build ~/.venvs/sever-demo from uv.lock
#   scripts/demo.sh repl         # the demo shell
#   scripts/demo.sh run [args]   # the full acceptance run (sever_demo.demo)
#   scripts/demo.sh test [args]  # pytest
#
#   scripts/demo.sh docker-build             # build the image, stamped with the current git commit
#   scripts/demo.sh docker repl|run|test|verify [args]
#                                            # same commands inside the container (compose.yaml)
set -euo pipefail
cd "$(dirname "$0")/.."
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/sever-demo" PYTHONHASHSEED=0 PYTHONPATH=python
cmd="${1:-repl}"
shift || true
case "$cmd" in
  setup) exec uv sync --frozen ;;
  repl)  exec uv run --frozen python -m sever_demo.repl "$@" ;;
  run)   exec uv run --frozen python -m sever_demo.demo "$@" ;;
  test)  exec uv run --frozen pytest -q "$@" ;;
  docker-build)
    SEVER_GIT_COMMIT="$(git rev-parse HEAD)"
    SEVER_GIT_DIRTY="$([ -n "$(git status --porcelain)" ] && echo true || echo false)"
    export SEVER_GIT_COMMIT SEVER_GIT_DIRTY
    exec docker compose build "$@" ;;
  docker) exec docker compose run --rm demo "$@" ;;
  *)     echo "usage: scripts/demo.sh setup|repl|run|test|docker-build|docker <cmd> [args]" >&2
         exit 2 ;;
esac
