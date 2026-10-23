#!/usr/bin/env bash
# Applies each inspect proof patch to HEAD in a throwaway worktree and checks its test goes red.
set -euo pipefail
root=$(git rev-parse --show-toplevel)
here="$root/tests/proofs/inspect"
fail=0
while read -r id patch test; do
  wt=$(mktemp -d "${TMPDIR:-/tmp}/inspect-proof-XXXX")
  git -C "$root" worktree add -q --detach "$wt" HEAD
  git -C "$wt" apply "$here/$patch"
  out=$(cd "$wt" && CARGO_TARGET_DIR="$root/target/proofs-inspect" \
      cargo test -q -p sever-db --features inspect "$test" 2>&1 || true)
  if grep -q "test result: FAILED" <<<"$out"; then
    echo "$id: red ($test)"
  else  # green, or a patch that does not compile: either way it proves nothing
    echo "$id: NOT RED ($test)"; fail=1
  fi
  git -C "$root" worktree remove --force "$wt"
done < <(python3 - "$here/MANIFEST.yaml" <<'PY'
import sys, yaml
for e in yaml.safe_load(open(sys.argv[1])):
    print(e["id"], e["patch"], e["test"])
PY
)
exit $fail
