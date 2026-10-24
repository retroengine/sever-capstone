#!/usr/bin/env bash
# Applies each scan proof patch to HEAD in a throwaway worktree and checks its test goes red.
set -euo pipefail
root=$(git rev-parse --show-toplevel)
here="$root/tests/proofs/scan"
fail=0
while IFS=$'\t' read -r id patch features test; do
  wt=$(mktemp -d "${TMPDIR:-/tmp}/scan-proof-XXXX")
  git -C "$root" worktree add -q --detach "$wt" HEAD
  git -C "$wt" apply "$here/$patch"
  [ "$features" = - ] && features=""
  feat=(); [ -n "$features" ] && feat=(--features "$features")
  out=$(cd "$wt" && CARGO_TARGET_DIR="$root/target/proofs-scan" \
      cargo test -q -p sever-scan "${feat[@]}" "$test" 2>&1 || true)
  if grep -q "test result: FAILED" <<<"$out"; then
    echo "$id: red ($test${features:+, --features $features})"
  else  # green, or a patch that does not compile: either way it proves nothing
    echo "$id: NOT RED ($test${features:+, --features $features})"; fail=1
  fi
  git -C "$root" worktree remove --force "$wt"
done < <(python3 - "$here/MANIFEST.yaml" <<'PY'
import sys, yaml
for e in yaml.safe_load(open(sys.argv[1])):
    print(e["id"], e["patch"], e.get("features") or "-", e["test"], sep="\t")
PY
)
exit $fail
