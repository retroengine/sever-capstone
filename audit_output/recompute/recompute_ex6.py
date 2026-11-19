"""Recompute EX-6 / P4-T12 (T-5) statistics from per-rung recall values in the result JSON.
Independent re-implementation of the definitions in docs/SEVER-DB_PROJECT_OVERVIEW.md §3.4
(T-5: per-seed std ddof=0 of Recall@10 across the five deletion rungs; Welch two-sided vs
soft-delete IVF, alpha 0.005; TOST delta 0.005). Rung 0 (before deletions) is excluded, rungs 1-5 used.
Usage: .venv/bin/python -I recompute_ex6.py results/p4-ex6-nq-10k-20261030T154119Z.json"""
import json, sys
import numpy as np
from scipy import stats
d = json.load(open(sys.argv[1]))
f = d['found']; st = f['statistics']
arms = list(f['seeds'][0]['arms'].keys())
dr = {a: {} for a in arms}
print('seed | arm | rungs recall@10 (0..5) | std ddof0 rungs1-5 | ddof1 | stated ddof0 (sever_db only)')
for s in f['seeds']:
    for a in arms:
        r = [x['recall10'] for x in s['arms'][a]['rungs']]
        x = np.asarray(r[1:], dtype=np.float64)
        d0, d1 = float(x.std(ddof=0)), float(x.std(ddof=1))
        dr[a][s['seed']] = d0
        stated = st['t5_per_seed'][str(s['seed'])]['ddof0'] if a == 'sever_db' else s['arms'][a]['drift']['ddof0']
        print(s['seed'], a, len(r), [round(v, 4) for v in r], repr(d0), repr(d1), 'stated', repr(stated), 'MATCH' if abs(d0 - stated) < 1e-12 else 'MISMATCH')
a = np.array(list(dr['sever_db'].values())); b = np.array(list(dr['soft_delete_ivf'].values()))
print('T-5 met (all sever_db ddof0 <= 0.005):', bool(np.all(a <= 0.005)), '| stated', st['t5_met'])
print('seeds meeting T-5:', int(np.sum(a <= 0.005)), 'of', len(a))
w = stats.ttest_ind(a, b, equal_var=False)
print('Welch t', repr(float(w.statistic)), 'p', repr(float(w.pvalue)), '| stated', st['welch'])
lo = stats.ttest_ind(a + 0.005, b, equal_var=False, alternative='greater')
hi = stats.ttest_ind(a - 0.005, b, equal_var=False, alternative='less')
print('TOST p', repr(float(max(lo.pvalue, hi.pvalue))), '| stated', st['tost'])
for arm in arms:
    v = np.array(list(dr[arm].values()))
    print('mean drift', arm, repr(float(v.mean())), 'sample std', repr(float(v.std(ddof=1))), 'n', len(v))
rng = np.random.Generator(np.random.PCG64(0))
for arm in arms:
    v = np.array(list(dr[arm].values()))
    boots = [float(rng.choice(v, len(v)).mean()) for _ in range(10_000)]
    print('bootstrap95', arm, [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))], '| stated', st['bootstrap_mean_drift_95'][arm])
