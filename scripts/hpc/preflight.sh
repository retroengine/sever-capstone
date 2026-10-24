#!/usr/bin/env bash
# scripts/hpc/preflight.sh INSTANCE [--check] — runs before every start of sever-hpc@INSTANCE
# (ExecStartPre). Checks what a start needs and refuses clearly; it changes nothing but its own
# start counter. Exit 0 = go; 2 = refused (the reason is printed and sent as an alert; not 1, which
# the unit's SuccessExitStatus=1 would count as success, letting a refused start run). With
# --check (launch.sh, by hand) it only checks: no counter, no alert.
set -u
. "$(dirname "$0")/lib.sh"
load_instance "${1:-real}" || exit 2
check_only=0; [ "${2:-}" = --check ] && check_only=1
cd "$REPO" || exit 2
problems=()

[ "$(uname -s)-$(uname -m)" = "Linux-x86_64" ] || problems+=("not Linux x86-64 (spec §12.9)")
case "$(stat -f -c %T . 2>/dev/null)" in
  ext2/ext3|ext4|xfs) ;;
  *) problems+=("the repository is not on ext4 or XFS (spec §12.9): it must be ~/sever-db") ;;
esac
f=$(free_gb .); [ "$f" -ge "$DISK_MIN_GB" ] || problems+=("only ${f} GB free on the Linux disk (need ${DISK_MIN_GB}); free space on Windows drive C:")
m=$(mem_available_gb); [ "$m" -ge "$MEM_MIN_GB" ] || problems+=("only ${m} GB of memory available (need ${MEM_MIN_GB}); another program is using it")
touch "$STATE/.w" 2>/dev/null && rm -f "$STATE/.w" || problems+=("$STATE is not writable")
mkdir -p traces 2>/dev/null; [ -w traces ] || problems+=("traces/ is not writable")

if [ "${MOCK:-0}" != 1 ]; then
  # The two --locked-memory steps (spec §12.8): unlimited memory lock, no unencrypted swap.
  [ "$(ulimit -l)" = unlimited ] || problems+=("ulimit -l is $(ulimit -l), not unlimited (root-setup.sh not run, or WSL not restarted)")
  [ "$(awk 'NR>1' /proc/swaps | wc -l)" -eq 0 ] || problems+=("swap is on (.wslconfig needs swap=0, then wsl --shutdown)")
  [ -r /dev/fuse ] && [ -w /dev/fuse ] || problems+=("/dev/fuse is not usable (p4-forensics needs it)")
  (cd datasets && [ -f MANIFEST.sha256 ] && [ -d processed/nq_1m ]) || problems+=("datasets/processed is missing (fetch-data.sh)")
  command -v cargo >/dev/null && cargo --version >/dev/null 2>&1 || problems+=("cargo does not run (setup.sh)")
  PYTHONPATH=python timeout 120 uv run --no-sync python -c "import sever_db, sever_testkit_p4.gates" >/dev/null 2>&1 \
    || problems+=("the Python environment does not load (setup.sh)")
  # The run must test exactly the commit the owner approved, with no local change.
  head=$(git rev-parse HEAD 2>/dev/null)
  if [ -n "${EXPECTED_COMMIT:-}" ] && [ "$head" != "$EXPECTED_COMMIT" ]; then
    problems+=("HEAD is ${head:0:12}, not the approved ${EXPECTED_COMMIT:0:12}")
  fi
  [ -z "$(git status --porcelain --untracked-files=no -- . ':!docs/RUN_LEDGER.jsonl' ':!docs/*.md' ':!results' 2>/dev/null)" ] \
    || problems+=("tracked files differ from the commit (git status): the run must test the commit as it is")
fi

if [ ${#problems[@]} -gt 0 ]; then
  echo "preflight $INSTANCE: REFUSED"
  for p in "${problems[@]}"; do echo "  - $p"; done
  [ "$check_only" = 1 ] || notify refused "preflight refused the start: $(IFS='; '; echo "${problems[*]}")"
  exit 2
fi
if [ "$check_only" = 1 ]; then echo "preflight $INSTANCE: OK (check only)"; exit 0; fi
n=$(( $(cat "$STATE/starts" 2>/dev/null || echo 0) + 1 )); echo "$n" >"$STATE/starts"
date -u +%FT%TZ >"$STATE/running"   # on-exit.sh: the run itself started (not refused)
echo "preflight $INSTANCE: OK (start $n; ${f} GB disk free, ${m} GB memory available, ulimit -l $(ulimit -l))"
if [ "$n" -eq 1 ]; then notify start "run started on $(hostname), commit $(git rev-parse --short HEAD)"
else notify restart "run restarted (start $n); finished steps are kept"; fi
