"""Phase 6: re-read numbers quoted in the audit docs at their sources, and confirm the doc text contains them.
Usage: python3 -I selfcheck.py <repo_root>"""
import json, os, sys, random, re
R = sys.argv[1]; A = os.path.join(R, 'audit_output')
docs = ''.join(open(os.path.join(A, f)).read() for f in os.listdir(A) if f.endswith('.md'))
def J(p): return json.load(open(os.path.join(R, p)))
def led(n): return [json.loads(l) for l in open(os.path.join(R, 'docs/RUN_LEDGER.jsonl')) if l.strip()][n - 1]
ex6 = 'results/p4-ex6-nq-10k-20261030T154119Z.json'; ex7 = 'results/p4-ex7-nq-100k-20261031T073714Z.json'
checks = [
 ('recall nq-1m', lambda: J('results/p1-quant-recall-nq-1m-20261030T232039Z.json')['seconds'], '917.4'),
 ('recall nq-100k seconds', lambda: J('results/p1-quant-recall-nq-100k-20261005T131137Z.json')['seconds'], '86.3'),
 ('ex6 seed42 drift', lambda: J(ex6)['found']['statistics']['t5_per_seed']['42']['ddof0'], '0.012954464183038068'),
 ('ex6 seed2024 drift', lambda: J(ex6)['found']['statistics']['t5_per_seed']['2024']['ddof0'], '0.007905761024394675'),
 ('welch t', lambda: J(ex6)['found']['statistics']['welch']['t'], '-9.570522849699275'),
 ('tost p', lambda: J(ex6)['found']['statistics']['tost']['p'], '0.9974696929884848'),
 ('ex7 sever p50', lambda: J(ex7)['found']['results'][0]['delete']['latency_per_call']['p50_us'], '109129.15'),
 ('ex7 softdelete per_second', lambda: [r for r in J(ex7)['found']['results'] if r['arm'] == 'softdelete'][0]['delete']['latency_per_call']['per_second'], '741.3707917259521'),
 ('ex7 noerase reopen', lambda: [r for r in J(ex7)['found']['results'] if r['arm'] == 'noerase'][0]['reopen_seconds'], '21.058904848'),
 ('p2 measures VmHWM', lambda: J('results/p2-measures-nq-100k-20261008T013402Z.json')['found']['memory_end']['VmHWM_kb'], '1093044'),
 ('p2 measures wal_only', lambda: J('results/p2-measures-nq-100k-20261008T013402Z.json')['found']['recovery_seconds']['wal_only'], '0.847202078'),
 ('p3 measures prove median', lambda: J('results/p3-measures-nq-10k-20261030T232049Z.json')['found']['prove_ms']['median'], '15.783409000000002'),
 ('p3 coverage log final', lambda: round(J('results/p3-coverage-20261101T022656Z.json')['rates']['crates/sever-log/src/'], 6), '0.930937'),
 ('p4 coverage erasure final', lambda: J('results/p4-coverage-20261101T023206Z.json')['rates']['sever-erasure'], '0.9557522123893806'),
 ('p4 mutants erasure L220', lambda: J('results/p4-mutants-20261101T175053Z.json')['scores']['sever-erasure']['score'], '0.9044117647058824'),
 ('p3 mutants cert', lambda: J('results/p3-mutants-20261030T134222Z.json')['scores']['sever-cert']['score'], '0.8516129032258064'),
 ('p1 coverage rust lines', lambda: J('results/p1-coverage-20261006T150803Z.json')['rust']['lines'][0], '1127'),
 ('p2 mutants caught', lambda: J('results/p2-mutants-20261008T072950Z.json')['counts']['caught'], '652'),
 ('p3 crash seed42 points', lambda: J('results/p3-crash-nq-10k-20261029T225309Z.json')['seeds'][0]['verdict']['crash_points'], '187,795'),
 ('p4 crash seed2024 points', lambda: J('results/p4-crash-nq-10k-20261031T124815Z.json')['seeds'][0]['verdict']['crash_points'], '7,915'),
 ('forensics SB-29', lambda: J('results/p4-forensics-nq-10k-20261030T141339Z.json')['sensitivity']['items']['SB-29']['findings'], '65,738'),
 ('fair p3 pass tests', lambda: J('results/fair-20261101T134211Z-p3-bb4bac5e.json')['tests'], '180'),
 ('ledger L211 outcome', lambda: led(211)['outcome'], 'started'),
 ('ledger L224 dirty', lambda: 'git_dirty: ' + str(led(224)['git_dirty']).lower(), 'git_dirty: true'),
 ('cleanroom e2 passed', lambda: J('results/cleanroom-p2-after-e2.json')['passed'], '255'),
 ('D4 seed42 points (progress)', lambda: json.load(open(os.path.join(R, 'traces/p4-crash-nq-10k-seed42.jsonl.progress')))['progress']['points'], '4,910'),
 ('D4 seed123 raw records', lambda: sum(1 for _ in open(os.path.join(R, 'traces/p4-crash-nq-10k-seed123.jsonl'))), '4,961'),
 ('D4 seed777 main_mismatches', lambda: json.load(open(os.path.join(R, 'traces/p4-crash-nq-10k-seed777.jsonl.progress')))['progress']['sum']['main_mismatches'], 'main_mismatches 0'),
 ('meta truncation', lambda: J('datasets/processed/meta.json')['encode']['nq']['truncation_rate'], '0.049148'),
]
random.seed(20261109)
ok = 0
for name, get, doctext in checks:
    v = get()
    src_ok = str(v).replace(',', '') in (doctext.replace(',', ''), doctext.replace(',', '').split()[-1])
    in_doc = doctext in docs
    ok += src_ok and in_doc
    print(f"{'OK ' if src_ok and in_doc else 'BAD'} {name}: source={v!r} doc_text={doctext!r} in_docs={in_doc}")
print(f'{ok}/{len(checks)} checks pass')
