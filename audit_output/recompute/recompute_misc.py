"""Recompute crash-kind breakdowns, EX-2 live-record recovery, EX-7 summaries from raw per-seed data.
Usage: python3 -I recompute_misc.py <repo_root>"""
import json, sys, os, statistics as stt
R = sys.argv[1]
def L(p): return json.load(open(os.path.join(R, p)))
for f in ['results/p2-crash-nq-10k-20261008T012927Z.json', 'results/p3-crash-nq-10k-20261029T225309Z.json', 'results/p3-crash-nq-10k-20261019T014621Z.json', 'results/p4-crash-nq-10k-20261030T175146Z.json', 'results/p4-crash-nq-10k-20261031T124815Z.json']:
    d = L(f); k = {}; dbl = 0; gen = 0
    for s in d['seeds']:
        for a, b in s['verdict']['by_kind'].items(): k[a] = k.get(a, 0) + b
        sm = s.get('summary') or s.get('campaign') or {}
        dbl += sm.get('double', 0); gen += (s.get('generic') or {}).get('points', 0)
    print(os.path.basename(f), 'by_kind totals', k, 'sum', sum(k.values()), 'double', dbl, 'generic points', gen)
d = L('results/p4-forensics-nq-10k-20261030T141339Z.json')
print('EX-2 live_records_recovered per seed per scan (after):')
for s in d['seeds']:
    print(' ', s['seed'], [(sc['after'], sc['live_records_recovered']) for sc in s['scans']], 'scan bytes', s['scans'][0]['scan']['bytes'])
print('EX-2 sensitivity', {k: v['findings'] for k, v in d['sensitivity']['items'].items()}, 'all ok', all(v['ok'] for v in d['sensitivity']['items'].values()))
print('EX-2 sensitivity keys', list(d['sensitivity'].keys()))
for f in ['results/p4-ex7-nq-100k-20261031T073714Z.json', 'results/p4-ex7-nq-10k-20261031T021052Z.json']:
    d = L(f)['found']
    print(os.path.basename(f))
    for r in d['results']:
        dl = r['delete']; ins = r['insert']; se = r['search']
        print('  ', r['arm'], 'seed', r['seed'], 'delete p50/p99 us', dl['latency_per_call'].get('p50_us'), dl['latency_per_call'].get('p99_us'), 'per_second', dl['latency_per_call'].get('per_second'),
              'per_record', json.dumps(dl.get('per_record'))[:160], '| insert', json.dumps(ins)[:200], '| search', json.dumps(se)[:160], '| peak mem', json.dumps(r.get('memory'))[:120], 'reopen', r.get('reopen_seconds'), 'refused', r.get('refused_inserts'))
    print('  summary', json.dumps(d.get('summary'))[:1500])
