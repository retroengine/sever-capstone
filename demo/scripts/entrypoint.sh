#!/bin/sh
# Container entry point (Dockerfile): one word picks the demo command, the rest are its arguments.
set -eu
cmd="${1:-repl}"
[ $# -gt 0 ] && shift
case "$cmd" in
  repl)   exec uv run --frozen --no-sync python -m sever_demo.repl "$@" ;;
  run)    exec uv run --frozen --no-sync python -m sever_demo.demo "$@" ;;
  test)   exec uv run --frozen --no-sync pytest -q -p no:cacheprovider "$@" ;;
  verify) exec uv run --frozen --no-sync python -m sever_verify "$@" ;;
  *)      exec "$cmd" "$@" ;;
esac
