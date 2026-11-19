"""Recompute per-file totals and rates from per-seed / per-crate raw values in results/*.json.
Read-only. Usage: python3 -I recompute_gates.py <repo_root>"""
import json, glob, os, sys
root = sys.argv[1]
def L(f): return json.load(open(f))
out = []
def p(*a): out.append(' '.join(str(x) for x in a))
for f in sorted(glob.glob(os.path.join(root, 'results/*.json'))):
    b = os.path.basename(f); d = L(f)
    try:
        if '-crash-' in b:
            tot = {}
            for s in d['seeds']:
                v = s.get('verdict', {})
                for k, x in v.items():
                    if isinstance(x, int): tot[k] = tot.get(k, 0) + x
                sm = s.get('summary') or s.get('campaign') or {}
                for k in ('certificates_checked', 'key_loss_injected', 'key_loss_refused', 'bad_certificates', 'orphaned_leaves', 'rolled_back_certificates', 'unreadable_records', 'stale_key_slots', 'method_mismatches', 'ops'):
                    if k in sm: tot['sum_' + k] = tot.get('sum_' + k, 0) + sm[k]
            p(b, d['outcome'], 'seeds', [s['seed'] for s in d['seeds']], 'per-seed crash_points', [s.get('verdict', {}).get('crash_points') for s in d['seeds']], 'per-seed ops', [(s.get('summary') or s.get('campaign') or {}).get('ops') for s in d['seeds']], 'TOTALS', json.dumps(tot))
        elif '-attacks-' in b:
            hon = [0, 0]; att = [0, 0]; wrong = 0
            for s in d['seeds']:
                j = s.get('judged') or {}
                if 'honest' in j: hon[0] += j['honest'][0]; hon[1] += j['honest'][1]
                for k, x in (j.get('attacks') or {}).items(): att[0] += x[0]; att[1] += x[1]
                wrong += len(j.get('wrong') or [])
            p(b, d['outcome'], 'seeds', len(d['seeds']), 'honest accepted/total', hon, 'attacks rejected/total', att, 'wrong', wrong, 'seed outcomes', [s.get('outcome') for s in d['seeds']])
        elif '-differential-' in b or 'synthetic' in b:
            tot = {}
            for s in d.get('seeds', []):
                r = s.get('replay', s)
                for k in ('ops', 'compared', 'mismatches', 'deleted_returned', 'survivor_groups_checked', 'survivor_failures', 'kernel_pairs', 'kernel_mismatches'):
                    if isinstance(r.get(k), int): tot[k] = tot.get(k, 0) + r[k]
            p(b, d['outcome'], 'seeds', [s.get('seed') for s in d.get('seeds', [])], 'TOTALS', json.dumps(tot))
        elif '-replay-' in b:
            tot = {}
            for r in d['runs']:
                rep = r.get('report') or {}
                for k, x in rep.items():
                    if isinstance(x, int) and not isinstance(x, bool): tot[k] = tot.get(k, 0) + x
            p(b, d['outcome'], 'runs', [(r.get('seed'), r.get('mode')) for r in d['runs']], 'TOTALS', json.dumps(tot))
        elif '-mutants-' in b:
            if 'scores' in d:
                for c, v in d['scores'].items():
                    den = v['caught'] + v['missed'] + v['timeout']
                    p(b, d['outcome'], c, 'stated', v['score'], 'recomputed caught/(caught+missed+timeout)', v['caught'] / den if den else None, f"{v['caught']}/{den}", 'min', v.get('minimum'))
            else:
                v = d['counts']; den = v['caught'] + v['missed'] + v['timeout']
                p(b, d['outcome'], 'stated', d['score'], 'recomputed', v['caught'] / den, f"{v['caught']}/{den}", 'total', v.get('total_mutants'))
            p(b, 'untriaged', d.get('untriaged'), 'cargo_mutants_exit', d.get('cargo_mutants_exit'))
        elif '-coverage-' in b:
            if 'rates' in d:
                mins = d.get('minimums') or {k: d.get('minimum') for k in d['rates']}
                p(b, d['outcome'], json.dumps({k: [round(v, 6), mins.get(k), v >= (mins.get(k) or 0)] for k, v in d['rates'].items()}))
            else:
                for part in ('rust', 'python'):
                    if part in d:
                        for m in ('lines', 'branches'):
                            if m in d[part]: x = d[part][m]; p(b, d['outcome'], part, m, x, 'recomputed', x[0] / x[1])
                for m in ('lines', 'branches'):
                    if m in d: x = d[m]; p(b, d['outcome'], m, x, 'recomputed', x[0] / x[1])
        elif '-fuzz-' in b:
            t = d['targets']
            p(b, d['outcome'], 'runs_per_target', d['runs_per_target'], 'targets', len(t), json.dumps(t)[:600])
        elif '-forensics-' in b:
            for s in d['seeds']:
                nf = [sc['scan']['n_findings'] for sc in s['scans']]
                pf = [all(sc['planted_found'].values()) for sc in s['scans']]
                p(b, d['outcome'], 'seed', s['seed'], 'image_gib', s.get('image_gib'), 'scans', len(s['scans']), 'findings per scan', nf, 'all planted found', pf, 'overrides', s.get('overrides'))
            p(b, 'sensitivity', json.dumps(d.get('sensitivity'))[:1500])
        elif b.startswith('fair-'):
            p(b, d['outcome'], 'part', d['part'], 'commit', d['commit'][:8], 'tests', d['tests'], 'failing', d['failing'], 'planted', json.dumps(d.get('planted'))[:300], 'escapes', json.dumps(d.get('escapes'))[:200])
        elif '-checks-' in b or '-spikes-' in b or '-sabotage-' in b:
            st = d.get('steps') or d.get('tests') or d.get('lines')
            fails = [x for x in (st if isinstance(st, list) else []) if isinstance(x, dict) and str(x.get('outcome', x.get('status', 'PASS'))).upper() not in ('PASS', 'OK')]
            p(b, d['outcome'], 'seconds', d.get('seconds'), 'n_steps', len(st) if isinstance(st, (list, dict)) else st, 'non-pass steps', json.dumps(fails)[:400])
        else:
            p(b, d.get('outcome'), json.dumps(d)[:600])
    except Exception as e:
        p(b, 'PARSE-ERROR', repr(e))
print('\n'.join(out))
