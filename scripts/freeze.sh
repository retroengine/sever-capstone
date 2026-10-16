#!/usr/bin/env bash
# F-1 (Build §0.3): hash every tracked file a part owns into freeze/PART-<N>.sha256. Run it on the
# commit that passed the part's Full gates; commit the manifest, then tag part-<N>-frozen.
# The fast CI tier (scripts/ci.sh, step freeze-guard) fails on any change to a listed file (F-2).
# FT-10 (docs/FAIR_TESTING.md): refuses unless a fair-testing run passed on these exact files.
#   scripts/freeze.sh 1
#   scripts/freeze.sh list 2      print the part's owned-file manifest without writing it
set -euo pipefail
cd "$(dirname "$0")/.."
list=0
if [ "${1:-}" = "list" ]; then list=1; shift; fi
part=${1:?usage: scripts/freeze.sh [list] <part>}
case "$part" in
  1) owned=(crates/sever-types crates/sever-quant crates/sever-partition crates/sever-index
            crates/sever-search crates/sever-tracekit crates/sever-p1 crates/sever-spec
            python/sever_partition python/sever_refmodel_core python/sever_testkit python/sever_demo
            fuzz/Cargo.toml fuzz/Cargo.lock fuzz/fuzz_targets fuzz/seeds 'golden/p1_*') ;;
  2) owned=(crates/sever-vfs crates/sever-format crates/sever-wal crates/sever-appendstore
            crates/sever-checkpoint crates/sever-txn crates/sever-engine crates/sever-crashkit
            crates/sever-p2 crates/sever-py-p2
            python/sever_refmodel_durable python/sever_testkit_p2 python/sever_db_p2
            fuzz-p2/Cargo.toml fuzz-p2/Cargo.lock fuzz-p2/fuzz_targets fuzz-p2/seeds 'golden/p2_*'
            tests/e2e/test_p2_e2e.py tests/architecture/test_architecture_p2.py tests/proofs/p2
            tests/errata/test_p2_e1_sdk_threads.py) ;;
  3) owned=(crates/sever-crypto crates/sever-commit crates/sever-log crates/sever-cert
            crates/sever-p3 crates/sever-py-p3 crates/sever-crashkit-p3 verifier audit fuzz-p3/Cargo.toml
            fuzz-p3/Cargo.lock fuzz-p3/fuzz_targets fuzz-p3/seeds
            python/sever_refmodel_certs python/sever_testkit_p3 python/sever_db_p3 python/sever_demo_p3
            python/sever_db_p3_native.pyi tests/e2e_p3 tests/architecture/test_architecture_p3.py
            scripts/p3-demo.sh
            'golden/p3_*' docs/SOUNDNESS.md tests/proofs/p3) ;;  # planned (Build 3-4 §1.4); final list at freeze
  *) echo "no ownership list for part $part yet"; exit 2 ;;
esac
if [ $list = 1 ]; then
  git ls-files -z -- "${owned[@]}" | sort -z | xargs -0 sha256sum
  exit 0
fi
if [ "$part" -ge 2 ] && ! scripts/fair.sh verify-freeze "$part"; then
  echo "freeze refused (FT-10)"; exit 1
fi
if [ -n "$(git status --porcelain -- "${owned[@]}")" ]; then
  echo "uncommitted changes in files Part $part owns; commit first"; exit 1
fi
mkdir -p freeze
git ls-files -z -- "${owned[@]}" | sort -z | xargs -0 sha256sum > "freeze/PART-$part.sha256"
echo "freeze/PART-$part.sha256: $(wc -l < "freeze/PART-$part.sha256") files"
