"""Parse docs/RUN_LEDGER.jsonl (read-only). Prints one line per row and a summary.
Usage: python3 -I ledger.py <repo_root>"""
import json, sys, os, collections
root = sys.argv[1]
rows = []
with open(os.path.join(root, 'docs/RUN_LEDGER.jsonl')) as f:
    for i, l in enumerate(f, 1):
        l = l.strip()
        if l:
            r = json.loads(l); r['_line'] = i; rows.append(r)
print('rows', len(rows))
for r in rows:
    p = r.get('platform') or {}
    art = r.get('artefacts')
    arts = json.dumps(art)[:160] if art else ''
    print(f"L{r['_line']}|{r.get('utc')}|{(r.get('commit') or '')[:8]}|dirty={r.get('git_dirty')}|{r.get('outcome')}|{r.get('gate')}|{r.get('data')}|{p.get('kernel','')[:30]}|{p.get('machine','')}|{(r.get('command') or '')[:90]}|{arts}")
c = collections.Counter(r.get('outcome') for r in rows); print('outcomes', dict(c))
print('dirty rows', sum(1 for r in rows if r.get('git_dirty')))
kern = collections.Counter((r.get('platform') or {}).get('kernel') for r in rows); print('kernels', dict(kern))
