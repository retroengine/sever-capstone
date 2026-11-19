"""Freshness of each results/*.json: producing commit (ledger result_file -> run_commit/commit), whether
the result file's sha256 matches the ledger, git_dirty, and source files changed from that commit to HEAD.
Relevant sources = files owned by Parts 1..N per freeze/PART-k.sha256 (N = the result's part) plus
Cargo.lock, uv.lock, rust-toolchain.toml, configs/. Usage: python3 -I freshness.py <repo_root>"""
import json, os, sys, subprocess, hashlib, glob, csv
R = sys.argv[1]
def git(*a): return subprocess.run(['git', '-C', R, *a], capture_output=True, text=True).stdout
owned = {}
for n in range(1, 5):
    owned[n] = [l.split(None, 1)[1].strip() for l in open(os.path.join(R, f'freeze/PART-{n}.sha256')) if l.strip()]
extra = ['Cargo.lock', 'uv.lock', 'rust-toolchain.toml', 'configs']
rows = [json.loads(l) for l in open(os.path.join(R, 'docs/RUN_LEDGER.jsonl')) if l.strip()]
by_file = {}
for i, r in enumerate(rows, 1):
    if r.get('result_file'): by_file.setdefault(os.path.basename(r['result_file']), []).append((i, r))
out = []
for f in sorted(glob.glob(os.path.join(R, 'results/*.json'))):
    b = os.path.basename(f)
    sha = hashlib.sha256(open(f, 'rb').read()).hexdigest()
    part = None
    if b.startswith('p') and b[1].isdigit(): part = int(b[1])
    elif b.startswith('fair-'): part = int(b.split('-p')[1][0])
    elif b.startswith('cleanroom-p2'): part = 2
    led = by_file.get(b, [])
    if led:
        line, r = led[-1]; commit = r.get('run_commit') or r.get('commit'); dirty = r.get('git_dirty'); dp = r.get('dirty_paths'); lsha = r.get('result_sha256')
    else:
        line = commit = dirty = dp = lsha = None
        if b.startswith('fair-'): commit = json.load(open(f)).get('commit')
    paths = sorted(set(p for n in range(1, (part or 4) + 1) for p in owned[n])) + extra
    changed = []
    if commit:
        changed = [x for x in git('diff', '--name-only', f'{commit}..HEAD', '--', *[p for p in paths if os.path.exists(os.path.join(R, p))]).split('\n') if x]
    status = 'UNKNOWN' if not commit else ('CURRENT' if not changed else 'STALE-POSSIBLE')
    out.append(dict(file=b, part=part, ledger_line=line, commit=(commit or '')[:9], git_dirty=dirty, dirty_paths=';'.join(dp or [])[:200],
                    sha_matches_ledger=(None if lsha is None else lsha == sha), sha256=sha, status=status, n_changed=len(changed), changed=';'.join(changed)[:600],
                    git_last_commit_date=git('log', '-1', '--format=%aI', '--', f'results/{b}').strip()))
w = csv.DictWriter(sys.stdout, fieldnames=list(out[0].keys())); w.writeheader(); [w.writerow(o) for o in out]
