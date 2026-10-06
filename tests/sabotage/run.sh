#!/usr/bin/env bash
# Sabotage register runner (Build §2.6, test level L12; gate P1-T8 and later P2-T8, P3-T9, P4-T10).
# Each SB-N builds the code with exactly one deliberate bug (feature `sabotage-SB-N` in Rust,
# SEVER_SABOTAGE=SB-N in Python). PASS means at least one test went RED. Exit 1 if any sabotage
# leaves every test green: that means a test is missing.
set -u
cd "$(dirname "$0")/../.."
fail=0
rust() { # $1 = SB id, $2 = crate. PASS only when the build compiles and a test fails.
  out=$(cargo test -q -p "$2" --features "sabotage-$1" 2>&1)
  if grep -q "test result: FAILED" <<<"$out"; then
    echo "PASS $1 ($2): $(grep -c -- '--- FAILED\|FAILED$' <<<"$out") failing test line(s)"
  elif grep -q "^error" <<<"$out"; then
    echo "ERROR $1 ($2): the sabotage build does not compile"; fail=1
  else
    echo "FAIL $1 ($2): every test stayed green"; fail=1
  fi
}
python() { # $1 = SB id, $2 = test path. PASS only when pytest reports a failed test.
  out=$(PYTHONHASHSEED=0 SEVER_SABOTAGE="$1" uv run --no-sync pytest -q -p no:cacheprovider -m "not slow and not mustfail" "$2" 2>&1)
  if grep -qE "[0-9]+ failed" <<<"$out"; then
    echo "PASS $1 (python): $(grep -oE '[0-9]+ failed' <<<"$out")"
  else
    echo "FAIL $1 (python): every test stayed green"; fail=1
  fi
}
for sb in SB-1 SB-2 SB-3 SB-4 SB-5 SB-7 SB-8; do rust "$sb" sever-index; done
for sb in SB-6 SB-9; do
  if grep -q "sabotage-$sb" crates/sever-search/Cargo.toml 2>/dev/null; then rust "$sb" sever-search; else echo "SKIP $sb (sever-search not built yet)"; fi
done
python SB-10 python/sever_partition
exit $fail
