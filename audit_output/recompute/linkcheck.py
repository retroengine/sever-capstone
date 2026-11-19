"""Every evidence file named in the audit docs is copied to results_collected/ or listed in MANIFEST.csv
(or is a recompute script/output). Usage: python3 -I linkcheck.py <repo_root>"""
import os, re, sys, csv
R = sys.argv[1]; A = os.path.join(R, 'audit_output'); RC = os.path.join(A, 'results_collected')
man = list(csv.DictReader(open(os.path.join(RC, 'MANIFEST.csv'))))
copied = set(os.listdir(RC)); paths = {m['original_path'] for m in man}; bases = {os.path.basename(p) for p in paths}
rec = set(os.listdir(os.path.join(A, 'recompute')))
refs = set()
for f in os.listdir(A):
    if f.endswith('.md'):
        refs |= set(re.findall(r'[\w./-]+\.(?:json|jsonl|log|sha256|csv|out|py|bin)\b', open(os.path.join(A, f)).read()))
missing = []
for r in sorted(refs):
    b = os.path.basename(r)
    if b in copied or b in bases or r in paths or b in rec or any(b in p for p in paths) or '*' in r: continue
    if b.endswith('.py') and os.path.exists(os.path.join(R, r)): continue  # source code reference
    if re.match(r'.*(-\.\.\.|…)', r): continue
    missing.append(r)
print('references', len(refs), 'unresolved', len(missing)); [print('  ', m) for m in missing]
