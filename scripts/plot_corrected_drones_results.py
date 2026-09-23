"""从修正版已核验数据重绘机制与外部比较图，旧图不覆盖。"""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def verified_trace(root, method, seed):
    rows = json.loads((root / 'results.json').read_text())
    matches = [row for row in rows if row['method'] == method and row['seed'] == seed]
    if len(matches) != 1:
        raise ValueError('代表轨迹归属不唯一')
    row = matches[0]
    state = json.loads((root / 'status.json').read_text())
    attempts = [attempt for attempt in state['attempts'] if attempt['state'] == 'VALID'
                and attempt['label'].startswith(f"{row['trial_id']}_{method}_attempt")]
    if len(attempts) != 1:
        raise ValueError('代表轨迹尝试不唯一')
    path = Path(attempts[0]['summary']).parent / row['trajectory']
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != row['trajectory_sha256']:
        raise ValueError('代表轨迹哈希变化')
    return [json.loads(line) for line in raw.splitlines()], row['trajectory_sha256']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c1-root', type=Path, required=True)
    parser.add_argument('--external-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    for root in (args.c1_root, args.external_root):
        if json.loads((root / 'status.json').read_text())['state'] != 'COMPLETED':
            raise ValueError('不能把未完成组绘成完整证据')
    args.out.mkdir(parents=True, exist_ok=False)
    plt.rcParams.update({'font.size': 9, 'axes.spines.top': False,
                         'axes.spines.right': False, 'savefig.facecolor': 'white'})
    v4, v4_hash = verified_trace(args.c1_root, 'AEGIS_HOCBF_V4', 8910)
    v3, v3_hash = verified_trace(args.c1_root, 'AEGIS_HOCBF_V3', 8910)
    t4 = np.array([record['t'] for record in v4])
    t3 = np.array([record['t'] for record in v3])
    active = np.array([any(row.get('recovery_active') for row in record['drones'].values()) for record in v4])
    infeasible = np.array([any(row.get('primary_feasible') is False for row in record['drones'].values()) for record in v4])
    takeover = float(t4[np.flatnonzero(active)[0]])
    primary_bad = float(t4[np.flatnonzero(infeasible)[0]])
    fig, axes = plt.subplots(3, 1, figsize=(8.0, 5.8), sharex=True, layout='constrained')
    axes[0].plot(t4, [record['min_rho'] for record in v4], label='Hybrid RA', color='#186A8C')
    axes[0].plot(t3, [record['min_rho'] for record in v3], label='HOCBF-Fallback', color='#A45430', alpha=.85)
    axes[0].axhline(0, color='black', linewidth=.7, linestyle=':')
    axes[0].set_ylabel('Min. normalized margin')
    axes[0].legend(loc='upper right', frameon=False)
    axes[0].set_title('Corrected C1 encounter, seed 8910 (fixed representative)')
    reserve = [min(row['feasibility_reserve'] for row in record['drones'].values()) for record in v4]
    axes[1].plot(t4, reserve, color='#186A8C', label='Hybrid RA primary reserve')
    axes[1].axhline(1, color='#777777', linewidth=.8, linestyle='--', label='Trigger threshold')
    axes[1].axhline(0, color='black', linewidth=.7, linestyle=':')
    axes[1].set_ylabel('Authority reserve')
    axes[1].legend(loc='upper right', frameon=False)
    axes[2].step(t4, active.astype(int), where='post', color='#186A8C', label='PB recovery active')
    axes[2].step(t4, infeasible.astype(int), where='post', color='#A45430', linestyle='--', label='Primary infeasible')
    axes[2].set_yticks([0, 1], ['No', 'Yes'])
    axes[2].set_xlabel('Nominal control time [s]')
    axes[2].set_ylabel('Logged state')
    axes[2].legend(loc='lower right', bbox_to_anchor=(1, 1.01), ncol=2, frameon=False)
    for axis in axes:
        axis.axvline(takeover, color='#186A8C', alpha=.5, linewidth=.8)
        axis.axvline(primary_bad, color='#A45430', alpha=.5, linewidth=.8, linestyle=':')
        axis.set_xlim(0, 5)
        axis.grid(axis='y', alpha=.18)
    fig.savefig(args.out / 'fig2_takeover_timeline_corrected.png', dpi=300)
    plt.close(fig)

    rows = json.loads((args.external_root / 'results.json').read_text())
    report = json.loads((args.external_root / 'paired_analysis_v2.json').read_text())
    if report['conditions_verified'] != len(rows):
        raise ValueError('外部分析与结果数量不一致')
    pcbf = next(item for item in report['paired'] if item['baseline'] == 'PCBF_HUANG_ECC2025')
    seeds = sorted({row['seed'] for row in rows})
    by = {(row['seed'], row['method']): row for row in rows}
    metrics = [('min_rho', 'Minimum normalized margin'),
               ('mean_control_effort', 'Velocity correction [m/s]'),
               ('path_length_m', 'Fleet path [m]'),
               ('latency_p99_ms', 'Episode P99 [ms]')]
    fig, axes = plt.subplots(2, 2, figsize=(8.8, 6.6), layout='constrained')
    for axis, (metric, label) in zip(axes.flat, metrics):
        def value(row):
            return row['ra_solve_latency_summary_ms']['p99'] if metric == 'latency_p99_ms' else row[metric]
        delta = [value(by[seed, 'AEGIS_HOCBF_V4']) - value(by[seed, 'PCBF_HUANG_ECC2025']) for seed in seeds]
        summary = pcbf['metrics'][metric]
        mean = summary['mean_aegis_minus_baseline']
        low, high = summary['bootstrap_95_ci']
        axis.scatter(delta, range(len(seeds)), s=22, color='#186A8C')
        axis.errorbar(mean, len(seeds)+1, xerr=[[mean-low], [high-mean]],
                      fmt='D', markersize=5, color='black', capsize=3)
        axis.axvline(0, color='#777777', linewidth=.8, linestyle=':')
        axis.set_yticks([*range(len(seeds)), len(seeds)+1], [*map(str, seeds), 'Mean / CI'])
        axis.invert_yaxis()
        axis.set_xlabel('Hybrid RA minus PCBF')
        axis.set_title(label)
        axis.grid(axis='x', alpha=.18)
    fig.savefig(args.out / 'fig_external_pcbf_corrected.png', dpi=300)
    plt.close(fig)
    provenance = dict(c1_seed=8910, c1_trajectory_hashes=dict(v4=v4_hash, v3=v3_hash),
        takeover_nominal_time_s=takeover, primary_infeasible_nominal_time_s=primary_bad,
        external_analysis_sha256=hashlib.sha256((args.external_root / 'paired_analysis_v2.json').read_bytes()).hexdigest(),
        note='代表 seed 沿用旧图规定，不按新结果挑选；机制图仅显示前五秒，统计仍用完整时域。外部图包含全部十个配对 seed，CI 为逐比较 95% bootstrap。')
    (args.out / 'provenance.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2))
    print(json.dumps(provenance, ensure_ascii=False))


if __name__ == '__main__':
    main()
