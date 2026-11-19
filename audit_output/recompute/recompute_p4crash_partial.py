"""D4: recompute the stopped final-commit p4-crash-a run (94d0b24, 1 Nov 2026) from its raw per-point
records traces/p4-crash-nq-10k-seed{42,123,777}.jsonl, and compare with each .progress summary.
Usage: python3 -I recompute_p4crash_partial.py <repo_root>"""
import json, sys, os, collections
R = sys.argv[1]
for s in (42, 123, 777):
    base = os.path.join(R, f'traces/p4-crash-nq-10k-seed{s}.jsonl')
    prog = json.load(open(base + '.progress'))
    t = collections.Counter(); kind = collections.Counter(); keys = collections.Counter(); ops = set(); odd = []
    for line in open(base):
        r = json.loads(line); t[r.get('t')] += 1
        if r.get('t') == 'crash':
            kind[r.get('kind')] += 1; ops.add(r.get('op'))
            if r.get('retry') not in ('ok', None): odd.append(r)
        for k, v in r.items():
            if k not in ('acked','double','k','kind','op','policy','retry','state','t','tear') : keys[k] += 1
    print(f"seed {s}: progress.done={prog['progress']['done']} progress.points={prog['progress']['points']} sum={json.dumps(prog['progress']['sum'])}")
    print(f"   raw: record types {dict(t)}; crash kinds {dict(kind)}; crash records {sum(kind.values())}; ops covered {min(ops)}..{max(ops)} ({len(ops)} ops); non-ok retries {len(odd)}; other keys {dict(keys)}")
    if odd: print('   first non-ok:', json.dumps(odd[0])[:300])
    print(f"   args: {prog['args']}")
