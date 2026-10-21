#!/usr/bin/env bash
# CI tiers (Build §2.8), runnable locally from any directory:
#   scripts/ci.sh fast         every push: format, lint, types, L1, bounded L2, L3 + spec-trace,
#                              golden vectors, L5, L7, L13 (with the freeze guard), §20.3 check 1
#   scripts/ci.sh full-checks  fast + the Full-tier ignored tests, the slow Python tests, the sabotage
#                              register (P1-T8, P2-T8), the MSRV build, cargo deny, the API docs
# Part 2 adds the SDK's native module and Part 2's spec-trace to fast; its Full-tier gates are
# python -m sever_testkit_p2.gates p2-crash | p2-replay | p2-fuzz | p2-sabotage | p2-spikes.
# Part 3 adds its spec-trace, oracle, proof and register checks to fast (sever_testkit_p3; CLAUDE.md §6.3); its
# Full-tier gates are python -m sever_testkit_p3.gates p3-mutants | ….
# Part 4 adds the same checks for its paths (sever_testkit_p4), its registers and the RFC 8452 vectors.
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
no_duplicate_crypto_deps() { # spec §20.3 check 1, in the main workspace and (once it exists) verifier/
  ! cargo tree -d --workspace 2>/dev/null | grep -E "^(rand_core|digest|getrandom|curve25519-dalek) v" || return 1
  [ ! -e verifier/Cargo.toml ] || ! (cd verifier && cargo tree -d --workspace 2>/dev/null) \
    | grep -E "^(rand_core|digest|getrandom|curve25519-dalek) v"
}
dalek_pinned() { # spec §20.3 check 2: every lockfile that has curve25519-dalek has exactly 4.1.3
  local lock v
  for lock in Cargo.lock verifier/Cargo.lock audit/Cargo.lock; do
    [ -e "$lock" ] || continue
    v=$(awk '$0 == "name = \"curve25519-dalek\"" { getline; gsub(/"/, "", $3); print $3 }' "$lock" | sort -u)
    [ -z "$v" ] || [ "$v" = "4.1.3" ] || { echo "$lock: curve25519-dalek ${v//$'\n'/ }, spec §20.1 pins 4.1.3"; return 1; }
  done
}
freeze_guard() { # F-2: no file of a frozen part changes (Build §0.3)
  local m; for m in freeze/PART-*.sha256; do [ -e "$m" ] || continue; sha256sum --quiet -c "$m" || return 1; done
}
fast() {
  step fmt cargo fmt --all --check
  step clippy cargo clippy --workspace --all-targets -- -D warnings
  step clippy-sabotage cargo clippy --workspace --all-targets --all-features -- -D warnings
  step rust-tests cargo test --workspace -q
  # The verifier is its own workspace (Build 3-4 §1.4): checked on its own.
  step verifier-fmt cargo fmt --manifest-path verifier/Cargo.toml --check
  step verifier-clippy cargo clippy --manifest-path verifier/Cargo.toml --locked --all-targets -- -D warnings
  step verifier-tests cargo test --manifest-path verifier/Cargo.toml --locked -q
  step audit-fmt cargo fmt --manifest-path audit/Cargo.toml --check
  step audit-clippy cargo clippy --manifest-path audit/Cargo.toml --locked --all-targets -- -D warnings
  step audit-tests cargo test --manifest-path audit/Cargo.toml --locked -q
  step ruff uv run --no-sync ruff check
  step ruff-format uv run --no-sync ruff format --check
  step mypy uv run --no-sync mypy python
  # The Part 2 SDK's native module (removed by every `uv sync`) must exist before the Python tests.
  step sdk-native uv run --no-sync maturin develop -q --release --uv -m crates/sever-py-p2/Cargo.toml
  step sdk-native-p3 uv run --no-sync maturin develop -q --release --uv -m crates/sever-py-p3/Cargo.toml
  step sdk-native-p4 uv run --no-sync maturin develop -q --release --uv -m crates/sever-py/Cargo.toml
  step python-tests uv run --no-sync pytest -q -m "not slow"
  step spec-trace uv run --no-sync python -m sever_testkit.spec_trace check --part 1 --complete
  step spec-trace-p2 uv run --no-sync python -m sever_testkit_p2.spec_trace check --part 2 --complete
  step oracle-check-p2 uv run --no-sync python -m sever_testkit_p2.oracle_check check
  step proofs-check-p2 uv run --no-sync python -m sever_testkit_p2.proofs check
  # Parts 3 and 4 are built: every owned requirement needs a test (BH-1).
  step spec-trace-p3 uv run --no-sync python -m sever_testkit_p3.spec_trace check --part 3 --complete
  step oracle-check-p3 uv run --no-sync python -m sever_testkit_p3.oracle_check check
  step proofs-check-p3 uv run --no-sync python -m sever_testkit_p3.proofs check
  step registers-p3 uv run --no-sync python -m sever_testkit_p3.registers check
  step rfc-vectors-p3 uv run --no-sync python -m sever_testkit_p3.rfc_vectors check
  step refmodel-golden-p3 uv run --no-sync python -m sever_refmodel_certs.golden check
  step spec-trace-p4 uv run --no-sync python -m sever_testkit_p4.spec_trace check --part 4 --complete
  step oracle-check-p4 uv run --no-sync python -m sever_testkit_p4.oracle_check check
  step proofs-check-p4 uv run --no-sync python -m sever_testkit_p4.proofs check
  step registers-p4 uv run --no-sync python -m sever_testkit_p4.registers check
  step rfc-vectors-p4 uv run --no-sync python -m sever_testkit_p4.rfc_vectors check
  step crypto-deps no_duplicate_crypto_deps
  step dalek-pinned dalek_pinned
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
