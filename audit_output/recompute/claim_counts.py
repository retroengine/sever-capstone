"""Count claims in 02_CLAIMS_AND_EVIDENCE.md by status and grade (parses the table rows)."""
import re, sys, collections
rows = [l for l in open(sys.argv[1]) if re.match(r'^\| C\d+ \|', l)]
st = collections.Counter(); gr = collections.Counter(); per = {}
for l in rows:
    c = [x.strip() for x in l.strip().strip('|').split('|')]
    cid, grade, status = c[0], c[4], c[5]
    s = re.sub(r'\*', '', status).split()[0].strip('(').upper()
    s = {'STALE': 'STALE'}.get(s, s)
    if status.startswith('STALE / UNSUPPORTED'): s = 'STALE'
    g = re.findall(r'E[0-4]', grade); g = max(g) if g else '?'
    st[s] += 1; gr[g] += 1; per[cid] = (s, g)
print('claims', len(rows)); print('status', dict(st)); print('grade (strongest)', dict(sorted(gr.items())))
for k in sorted(set(v[0] for v in per.values())): print(k, [c for c, v in per.items() if v[0] == k])
for k in sorted(set(v[1] for v in per.values())): print(k, [c for c, v in per.items() if v[1] == k])
