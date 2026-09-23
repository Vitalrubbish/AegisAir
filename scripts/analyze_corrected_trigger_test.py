"""按场景分析冻结触发测试；不把开发重复参考组扩充为独立样本。"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from run_corrected_trigger_chain import verify_completed
from freeze_corrected_trigger_test import load_frozen_test
from marllib.analyze_c1_external_pcbf_sealed import _bootstrap_ci, _sign_flip_p, _holm

REFERENCE = 'AEGIS_HOCBF_V4_RESERVE_ONLY'
LABELS = {'AEGIS_HOCBF_V4_REACTIVE': 'Reactive', REFERENCE: 'Reserve-Only',
          'AEGIS_HOCBF_V4_DISTANCE': 'Distance', 'AEGIS_HOCBF_V4_TTC': 'TTC'}


def paired_statistics(groups):
    rng = np.random.default_rng(20260923)
    comparisons = []
    for scenario, rows in groups.items():
        pairs = defaultdict(dict)
        for row in rows:
            if row['method'] in pairs[row['seed']]:
                raise ValueError('同 seed 同方法重复')
            pairs[row['seed']][row['method']] = row
        if len(pairs) != 5 or any(set(pair) != set(LABELS) for pair in pairs.values()):
            raise ValueError('每场景应为五个完整配对 seed')
        for baseline in LABELS:
            if baseline == REFERENCE:
                continue
            metrics = {}
            for metric in ('min_rho', 'mean_control_effort'):
                delta = np.array([pairs[seed][REFERENCE][metric] - pairs[seed][baseline][metric]
                                  for seed in sorted(pairs)])
                metrics[metric] = dict(mean_difference=float(delta.mean()),
                    bootstrap_95_ci=_bootstrap_ci(delta, rng), exact_sign_flip_p=_sign_flip_p(delta))
            comparisons.append(dict(scenario=scenario, baseline=baseline, pairs=5, metrics=metrics))
    for metric in ('min_rho', 'mean_control_effort'):
        corrected = _holm({str(i): c['metrics'][metric]['exact_sign_flip_p'] for i, c in enumerate(comparisons)})
        for i, comparison in enumerate(comparisons):
            comparison['metrics'][metric]['holm_p'] = corrected[str(i)]
    return comparisons


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--frozen-test', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    settings = load_frozen_test(args.frozen_test)
    if json.loads((args.root / 'run_settings.json').read_text()) != settings:
        raise ValueError('测试配置与封存配置不同')
    verified = verify_completed(args.root)
    groups = {scenario: json.loads((args.root / scenario / 'results.json').read_text())
              for scenario in dict.fromkeys(t['scenario_id'] for t in settings['trials'])}
    summaries, excluded, inputs = [], [], {}
    for scenario, rows in groups.items():
        folder = args.root / scenario
        state = json.loads((folder / 'status.json').read_text())
        for name in ('run_settings.json', 'results.json', 'status.json'):
            path = folder / name
            inputs[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        for attempt in state['attempts']:
            if attempt['state'] != 'VALID':
                excluded.append(dict(scenario=scenario, **attempt))
        for method, label in LABELS.items():
            subset = [r for r in rows if r['method'] == method]
            summaries.append(dict(scenario=scenario, method=method, label=label, n=len(subset),
                completed=sum(r['mission_complete'] for r in subset),
                collisions=sum(r['collision'] for r in subset),
                minimum_rho=min(r['min_rho'] for r in subset),
                mean_min_rho=float(np.mean([r['min_rho'] for r in subset])),
                mean_effort=float(np.mean([r['mean_control_effort'] for r in subset])),
                infeasible_steps=sum(r['qp_infeasible_steps'] for r in subset),
                published_constraint_failures=sum(r['published_command_constraint_failure_count'] for r in subset)))
    report = dict(verified=verified, selection=json.loads((args.frozen_test.parent / 'selection.json').read_text()),
        summaries=summaries, paired=paired_statistics(groups), excluded_attempts=excluded, input_hashes=inputs,
        note='探索性测试分析，非追认预注册检验。场景各五配对seed，Reserve-Only减三对照；每指标九个对比做Holm校正。10000次配对bootstrap为逐对比非同时区间；小样本区间不代替精确检验。开发参考重复运行不合并进入测试。')
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / 'analysis.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    lines = [r'\begin{tabular}{llrrr}', r'\toprule',
             r'Geometry & Trigger & Mean min. $\rho$ & Effort [m/s] & Publication failures \\', r'\midrule']
    for row in summaries:
        scene = {'base': 'Nominal', 'wide_head_on': 'Wide', 'diagonal_crossing': 'Diagonal'}[row['scenario']]
        lines.append(f"{scene} & {row['label']} & {row['mean_min_rho']:.4f} & {row['mean_effort']:.4f} & {row['published_constraint_failures']} " + r'\\')
    lines += [r'\bottomrule', r'\end{tabular}']
    (args.out / 'trigger_test_table.tex').write_text('\n'.join(lines) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
