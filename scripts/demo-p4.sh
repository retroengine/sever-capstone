#!/usr/bin/env bash
# Part 4's demo (Build 3-4 §2.11): the erasure, then the same run with group-key rotation skipped
# (SB-24) so the leak is visible. Simulated disks laid out as one image; the forensic run on a
# real ext4 image is EX-2.
set -euo pipefail
cd "$(dirname "$0")/.."
cargo run -q --release -p sever-scan --features demo --bin sever-demo-p4
echo
echo "------------------------------------------------------------------------------------------"
echo
CARGO_TARGET_DIR=target/demo-sb24 cargo run -q --release -p sever-scan --features demo-sb24 --bin sever-demo-p4
