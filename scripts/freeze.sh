#!/usr/bin/env bash
# F-1 (Build §0.3): hash every tracked file a part owns into freeze/PART-<N>.sha256. Run it on the
# commit that passed the part's Full gates; commit the manifest, then tag part-<N>-frozen.
# The fast CI tier (scripts/ci.sh, step freeze-guard) fails on any change to a listed file (F-2).
#   scripts/freeze.sh 1
set -euo pipefail
cd "$(dirname "$0")/.."
part=${1:?usage: scripts/freeze.sh <part>}
case "$part" in
  1) owned=(crates/sever-types crates/sever-quant crates/sever-partition crates/sever-index
            crates/sever-search crates/sever-tracekit crates/sever-p1 crates/sever-spec
            python/sever_partition python/sever_refmodel_core python/sever_testkit python/sever_demo
            fuzz/Cargo.toml fuzz/Cargo.lock fuzz/fuzz_targets fuzz/seeds 'golden/p1_*') ;;
  *) echo "no ownership list for part $part yet"; exit 2 ;;
esac
if [ -n "$(git status --porcelain -- "${owned[@]}")" ]; then
  echo "uncommitted changes in files Part $part owns; commit first"; exit 1
fi
mkdir -p freeze
git ls-files -z -- "${owned[@]}" | sort -z | xargs -0 sha256sum > "freeze/PART-$part.sha256"
echo "freeze/PART-$part.sha256: $(wc -l < "freeze/PART-$part.sha256") files"
