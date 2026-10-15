#!/usr/bin/env bash
# CI tiers (Build §2.8), runnable locally from any directory:
#   scripts/ci.sh fast         every push: format, lint, types, L1, bounded L2, L3 + spec-trace,
#                              golden vectors, L5, L7, L13 (with the freeze guard), §20.3 check 1
#   scripts/ci.sh full-checks  fast + the Full-tier ignored tests, the slow Python tests, the sabotage
#                              register (P1-T8, P2-T8), the MSRV build, cargo deny, the API docs
# Part 2 adds the SDK's native module and Part 2's spec-trace to fast; its Full-tier gates are
# python -m sever_testkit_p2.gates p2-crash | p2-replay | p2-fuzz | p2-sabotage | p2-spikes.
# Part 3 adds its spec-trace, oracle and proof checks to fast (sever_testkit_p3; CLAUDE.md §6.3); its
# Full-tier gates are python -m sever_testkit_p3.gates p3-mutants | ….
# The long Full-tier gates write the run ledger themselves (python -m sever_testkit.gates …).
# Prints one "STEP <name>: PASS|FAIL" line per step; exits 1 if any step failed.
set -u
cd "$(dirname "$0")/.."
export PYTHONHASHSEED=0 PYTHONPATH=python
failed=0
step() { # $1 = name, rest = command
  local name=$1; shift
  if "$@" >"/tmp/sever-ci-$name.log" 2>&1; then echo "STEP $name: PASS"
  else echo "STEP $name: FAIL (log: /tmp/sever-ci-$name.log)"; tail -20 "/tmp/sever-ci-$name.log"; failed=1; fi
}
no_duplicate_crypto_deps() { # spec §20.3 check 1
  ! cargo tree -d --workspace 2>/dev/null | grep -E "^(rand_core|digest|getrandom|curve25519-dalek) v"
}
freeze_guard() { # F-2: no file of a frozen part changes (Build §0.3)
  local m; for m in freeze/PART-*.sha256; do [ -e "$m" ] || continue; sha256sum --quiet -c "$m" || return 1; done
}
fast() {
  step fmt cargo fmt --all --check
  step clippy cargo clippy --workspace --all-targets -- -D warnings
  step clippy-sabotage cargo clippy --workspace --all-targets --all-features -- -D warnings
  step rust-tests cargo test --workspace -q
  step ruff uv run --no-sync ruff check
  step ruff-format uv run --no-sync ruff format --check
  step mypy uv run --no-sync mypy python
  # The Part 2 SDK's native module (removed by every `uv sync`) must exist before the Python tests.
  step sdk-native uv run --no-sync maturin develop -q --release --uv -m crates/sever-py-p2/Cargo.toml
  step python-tests uv run --no-sync pytest -q -m "not slow"
  step spec-trace uv run --no-sync python -m sever_testkit.spec_trace check --part 1 --complete
  step spec-trace-p2 uv run --no-sync python -m sever_testkit_p2.spec_trace check --part 2 --complete
  step oracle-check-p2 uv run --no-sync python -m sever_testkit_p2.oracle_check check
  step proofs-check-p2 uv run --no-sync python -m sever_testkit_p2.proofs check
  # Part 3 is being built: unknown IDs fail now; --complete joins when its modules are done.
  step spec-trace-p3 uv run --no-sync python -m sever_testkit_p3.spec_trace check --part 3
  step oracle-check-p3 uv run --no-sync python -m sever_testkit_p3.oracle_check check
  step proofs-check-p3 uv run --no-sync python -m sever_testkit_p3.proofs check
  step crypto-deps no_duplicate_crypto_deps
  step freeze-guard freeze_guard
  step fair-check scripts/fair.sh check
}
full_checks() {
  fast
  step rust-ignored cargo test --workspace --release -q -- --include-ignored
  step python-slow uv run --no-sync pytest -q -m slow
  step sabotage tests/sabotage/run.sh
  step msrv cargo +1.85 build -q --workspace --target-dir target/msrv
  step deny cargo deny check licenses advisories bans sources
  step docs env RUSTDOCFLAGS="-D warnings" cargo doc -q --no-deps --workspace
}
case "${1:-fast}" in
  fast) fast ;;
  full-checks) full_checks ;;
  *) echo "usage: scripts/ci.sh fast|full-checks"; exit 2 ;;
esac
exit $failed
