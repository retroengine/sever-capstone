"""Recompute EX-7 nq-10k per-arm means over seeds from per-seed raw values; compare to the file's summary.
Usage: python3 -I recompute_ex7.py results/p4-ex7-nq-10k-20261031T021052Z.json"""
import json, sys, statistics as st
d = json.load(open(sys.argv[1]))['found']
get = {
 'delete_call_p50_us': lambda r: r['delete']['latency_per_call']['p50_us'],
 'delete_call_p99_us': lambda r: r['delete']['latency_per_call']['p99_us'],
 'insert_p50_us': lambda r: r['insert']['latency']['p50_us'],
 'delete_bytes_per_record': lambda r: r['delete']['per_record']['bytes_per_op'],
 'delete_fsyncs_per_record': lambda r: r['delete']['per_record']['fsyncs_per_op'],
 'insert_bytes_per_op': lambda r: r['insert']['per_op']['bytes_per_op'],
}
for arm in ('sever', 'noerase', 'softdelete'):
    rs = [r for r in d['results'] if r['arm'] == arm]
    for k, f in get.items():
        v = [f(r) for r in rs]
        stated = d['summary'][arm][k]['mean']
        m = st.mean(v)
        print(arm, k, 'n', len(v), 'recomputed mean', repr(m), 'sample sd', repr(st.stdev(v)), 'stated mean', repr(stated), 'MATCH' if abs(m - stated) <= 1e-9 * max(1, abs(m)) else 'MISMATCH')
    print(arm, 'search p50 per seed', [r['search']['p50_us'] for r in rs])
