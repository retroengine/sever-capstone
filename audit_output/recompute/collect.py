"""Copy relied-on evidence files (<= 50 MB) into audit_output/results_collected/ and write MANIFEST.csv.
Never copies keys/, studio/work/, database dirs, datasets data, .env. Usage: python3 -I collect.py <repo_root>"""
import os, sys, glob, shutil, hashlib, csv, subprocess, datetime, json
R = sys.argv[1]; OUT = os.path.join(R, 'audit_output/results_collected')
fresh = {r['file']: r for r in csv.DictReader(open(os.path.join(R, 'audit_output/recompute/freshness.csv')))}
def gitdate(p): return subprocess.run(['git', '-C', R, 'log', '-1', '--format=%aI', '--', p], capture_output=True, text=True).stdout.strip() or 'untracked/ignored'
def link(b):
    m = [('p4-crash-nq-10k-seed', 'EX1 (D4)'), ('crash', 'EX1'), ('forensics', 'EX2'), ('differential', 'EX3'), ('synthetic', 'EX3'), ('replay', 'EX3'), ('attacks', 'EX4'), ('quant-recall', 'EX5'), ('ex6', 'EX6'), ('ex7', 'EX7'), ('ex8', 'EX8'), ('p2-measures', 'EX9'), ('p3-measures', 'EX10'), ('idea-', 'EX11'), ('fair', 'EX12'), ('cleanroom', 'T12'),
         ('checks', 'T3'), ('coverage', 'T4'), ('cov-', 'T4'), ('mutants', 'T5'), ('fuzz', 'T6'), ('sabotage', 'T7'), ('spikes', 'T8'), ('TRACE_', 'T9'), ('PROOFS_', 'T10'), ('TEST_ORACLES', 'T11'), ('FAIRNESS', 'EX12'), ('MUTANTS_', 'T5'),
         ('PART-', 'T13'), ('MANIFEST.sha256', 'T14'), ('PINS', 'T14'), ('meta.json', 'T14'), ('rerun_pytest', 'T1'), ('rerun_verifier', 'T15'), ('rerun_sha256', 'T13;T14'), ('partition-seed', 'EX3 (P1-T6)'), ('RUN_LEDGER', 'ALL'), ('hpc-summary', 'ALL'), ('hpc-run', 'ALL'), ('durable-', 'EX9 (demo)'), ('receipt-', 'EX4 (demo)'), ('certificate.bin', 'T15'), ('anchors.json', 'T15'), ('flipped.bin', 'T15'), ('experiments.yaml', 'ALL'), ('fair.yaml', 'EX12'), ('RESULTS.md', 'ALL'), ('ci-fast', 'T3'), ('full-checks', 'T3'), ('oomguard', 'ALL')]
    for k, v in m:
        if k in b: return v
    return ''
srcs = []
srcs += [(p, 'gate runner (python -m sever_testkit*.gates / sever_fair); see ledger result_file') for p in sorted(glob.glob('results/*.json'))]
srcs += [('docs/RUN_LEDGER.jsonl', 'gate runners (append-only)')]
for p in sorted(glob.glob('traces/*')):
    if os.path.isfile(p) and os.path.getsize(p) <= 50 * 2**20 and not p.endswith(('.jsonl', '.progress', '.xz')) and os.path.basename(p) not in ('dbg.jsonl',):
        srcs.append((p, 'scripts/hpc/*.sh step logs or gate stdout'))
srcs += [(f'traces/p4-crash-nq-10k-seed{x}.jsonl{e}', 'sever-crashkit-p4 (final-commit p4-crash-a, stopped 1 Nov; D4)') for x in (42, 123, 777) for e in ('', '.progress')]
srcs += [(p, 'sever_partition.build (C-15)') for p in sorted(glob.glob('artefacts/partition-seed*.json'))]
srcs += [(p, 'sever-demo (Part 1/2/3 demo binaries)') for p in sorted(glob.glob('artefacts/demo/*.json'))]
srcs += [(f'artefacts/demo/receipt-nq-10k-seed42/verifier-only/{x}', 'sever-demo receipt (public verifier inputs)') for x in ('anchors.json', 'certificate.bin', 'flipped.bin')]
srcs += [(p, 'scripts/freeze.sh') for p in sorted(glob.glob('freeze/*.sha256'))]
srcs += [('datasets/MANIFEST.sha256', 'P0 prepare_data.py'), ('datasets/PINS.json', 'P0'), ('datasets/processed/meta.json', 'P0 prepare_data.py')]
srcs += [(p, 'python -m sever_fair (generated report)') for p in sorted(glob.glob('docs/audit/FAIRNESS_*.md'))]
srcs += [(p, 'generated (proofs run / oracle_check report / spec-trace / triage)') for p in sorted(glob.glob('docs/PROOFS_P*.md') + glob.glob('docs/TEST_ORACLES_P*.md') + glob.glob('docs/TRACE_PART_*.md') + glob.glob('docs/MUTANTS_P*.md'))]
srcs += [('docs/RESULTS.md', 'scripts/index.py (generated from ledger)')]
srcs += [(p, 'config (pre-registered)') for p in sorted(glob.glob('configs/*.yaml'))]
bad = ('/keys/', 'studio/work', '.env', 'SECRETS')
rows = []; names = {}
for p, prod in srcs:
    if any(b in p for b in bad): continue
    b = os.path.basename(p)
    if b in names and names[b] != p: b = p.replace('/', '__')
    names[b] = p
    shutil.copy2(os.path.join(R, p), os.path.join(OUT, b))
    data = open(os.path.join(R, p), 'rb').read()
    f = fresh.get(os.path.basename(p))
    status = f['status'] if f else 'UNKNOWN'
    note = ''
    if f: note = f"ledger L{f['ledger_line']} commit {f['commit']} dirty={f['git_dirty']} sha_matches_ledger={f['sha_matches_ledger']}; {f['n_changed']} owned/lock/config files changed since"
    if 'archive' in p: status = 'STALE'
    if 'p4-crash-nq-10k-seed' in p:
        status = 'CURRENT'; note = 'final commit 94d0b24 (header of traces/final-p4-crash-a.log; file mtimes 13:00:39-13:01:20 match that log); run stopped by owner, partial; only crates/sever-py changed since (DB-118)'
    rows.append(dict(copied_name=b, original_path=p, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                     last_modified=datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(R, p)), datetime.timezone.utc).isoformat(timespec='seconds'),
                     git_last_commit_date=gitdate(p), produced_by=prod, linked_experiment_or_test_ID=link(p), status=status, notes=note))
for b in sorted(os.listdir(OUT)):
    if b.startswith('rerun_'):
        data = open(os.path.join(OUT, b), 'rb').read()
        rows.append(dict(copied_name=b, original_path='(created by this audit)', size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), last_modified=datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(OUT, b)), datetime.timezone.utc).isoformat(timespec='seconds'), git_last_commit_date='n/a', produced_by='this audit (EXECUTED-NOW at HEAD af8fed2)', linked_experiment_or_test_ID=link(b), status='CURRENT', notes='re-run output'))
# not copied: > 50 MB
big = subprocess.run(['find', R, '-path', f'{R}/.git', '-prune', '-o', '-path', f'{R}/.venv', '-prune', '-o', '-path', f'{R}/studio/.venv', '-prune', '-o', '-path', '*/target', '-prune', '-o', '-path', '*/corpus', '-prune', '-o', '-type', 'f', '-size', '+50M', '-print'], capture_output=True, text=True).stdout.split()
for p in sorted(big):
    rp = os.path.relpath(p, R)
    rows.append(dict(copied_name='NOT COPIED (>50 MB)', original_path=rp, size_bytes=os.path.getsize(p), sha256='not computed', last_modified=datetime.datetime.fromtimestamp(os.path.getmtime(p), datetime.timezone.utc).isoformat(timespec='seconds'), git_last_commit_date=gitdate(rp), produced_by='gate runners (traces) / P0 / Studio', linked_experiment_or_test_ID=('EX4' if 'attacks' in rp else 'EX3' if rp.startswith('traces/p1-') else 'EX5;EX8' if 'nq_1m' in rp else ''), status='UNKNOWN', notes='raw per-op trace or dataset; secret-bearing studio/work files excluded by rule' if 'studio/work' not in rp else 'studio work dir: not copied (may hold keys/db state)'))
for d, why in [('traces/archive-before-final', 'archived earlier run traces (not copied; STALE by name)'), ('traces/archive-pre-laptop-run', 'archived pre-laptop-run traces (not copied; STALE by name)'), ('docs/archive', 'archived docs (not copied)'), ('tests/cleanroom', 'sealed clean-room suites (not copied; hashed by fair.sh)'), ('artefacts/demo/receipt-nq-10k-seed42/keys', 'KEY DIRECTORY: excluded (secrets)'), ('studio/work', 'Studio databases and keys: excluded (secrets)'), ('jobs', 'job-queue logs (not copied)'), ('spikes', 'proof spike crates and outputs (not copied)')]:
    if os.path.exists(os.path.join(R, d)):
        rows.append(dict(copied_name='NOT COPIED (directory)', original_path=d, size_bytes=subprocess.run(['du', '-sb', os.path.join(R, d)], capture_output=True, text=True).stdout.split()[0], sha256='n/a', last_modified='', git_last_commit_date=gitdate(d), produced_by='', linked_experiment_or_test_ID='', status='STALE' if 'archive' in d else 'UNKNOWN', notes=why))
for p in sorted(glob.glob(os.path.join(R, 'traces/*.xz'))):
    rp = os.path.relpath(p, R)
    rows.append(dict(copied_name='NOT COPIED (compressed raw trace)', original_path=rp, size_bytes=os.path.getsize(p), sha256='see traces/COMPRESSED.sha256', last_modified=datetime.datetime.fromtimestamp(os.path.getmtime(p), datetime.timezone.utc).isoformat(timespec='seconds'), git_last_commit_date=gitdate(rp), produced_by='gate runners', linked_experiment_or_test_ID=link(rp), status='UNKNOWN', notes='raw per-operation trace; not needed (result JSONs hold per-seed values); excluded to keep raw engine state out of the copy'))
with open(os.path.join(OUT, 'MANIFEST.csv'), 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); [w.writerow(r) for r in rows]
print('rows', len(rows), 'copied', sum(1 for r in rows if not r['copied_name'].startswith('NOT')))
