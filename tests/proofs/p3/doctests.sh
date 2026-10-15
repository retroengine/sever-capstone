#!/usr/bin/env bash
# Red proofs for compile_fail doc tests, which `sever_testkit_p3.proofs` cannot name (doc-test names
# carry spaces and line numbers). Each patch must turn `cargo test --doc` red; run on a clean tree:
#   tests/proofs/p3/doctests.sh
# PR3-D01: `prove` made generic over any RNG (§9.6: it must accept only StrictProofRng).
# PR3-D02: StrictProofRng made SeedableRng (§9.6: it must not be seedable).
set -u
cd "$(dirname "$0")/../../.."
fail=0
for p in PR3-D01 PR3-D02; do
  git apply "tests/proofs/p3/$p.patch" || { echo "$p: NOT PROVEN (patch does not apply)"; fail=1; continue; }
  if cargo test -q -p sever-crypto --doc >/dev/null 2>&1; then echo "$p: NOT PROVEN (doc tests stayed green)"; fail=1
  else echo "$p: PROVEN (a compile_fail doc test went red)"; fi
  git apply -R "tests/proofs/p3/$p.patch"
done
exit $fail
