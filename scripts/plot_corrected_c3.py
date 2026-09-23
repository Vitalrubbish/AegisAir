"""核验完整 C3 后重绘固定 seed 9445；不按新结果挑选代表轨迹。"""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    state = json.loads((args.root / 'status.json').read_text())
    settings = json.loads((args.root / 'run_settings.json').read_text())
    rows = json.loads((args.root / 'results.json').read_text())
    analysis = json.loads((args.root / 'paired_analysis_v2.json').read_text())
    if state['state'] != 'COMPLETED' or analysis['conditions_verified'] != len(rows) or len(rows) != 60:
        raise ValueError('C3 必须完成且核验全部 60 条')
    selected = [row for row in rows if row['seed'] == 9445]
    if sorted(row['condition'] for row in selected) != ['R0', 'R1']:
        raise ValueError('代表 seed 配对不完整')
    args.out.mkdir(parents=True, exist_ok=False)
    plt.rcParams.update({'font.size': 9, 'axes.spines.top': False,
                         'axes.spines.right': False, 'savefig.facecolor': 'white'})
    fig, axes = plt.subplots(2, 2, figsize=(9, 6.2), layout='constrained',
                             gridspec_kw={'height_ratios': [1.5, 1]})
    provenance = {}
    colors = {'2': '#A45430', '3': '#186A8C'}
    for column, row in enumerate(sorted(selected, key=lambda item: item['condition'])):
        summary = Path(state['condition_sources'][row['trial_id'] + '/' + row['condition']])
        path = summary.parent / row['trajectory']
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != row['trajectory_sha256']:
            raise ValueError('代表轨迹哈希变化')
        records = [json.loads(line) for line in raw.splitlines()]
        provenance[row['condition']] = dict(path=str(path), sha256=digest)
        axis = axes[0, column]
        for drone in ('2', '3'):
            position = np.asarray([record['drones'][drone]['pos'] for record in records])
            axis.plot(position[:, 0], position[:, 1], color=colors[drone], label='UAV ' + drone)
            axis.scatter(*position[0, :2], color=colors[drone], s=24)
            axis.scatter(*position[settings['change_step'], :2], color=colors[drone], s=35, marker='x')
        axis.scatter(*settings['critical_goal'], marker='*', s=130, color='#222222', label='Orphan goal', zorder=4)
        healthy_goal = settings['base_goals']['3']
        axis.scatter(*healthy_goal[:2], marker='s', s=30, facecolor='none', edgecolor=colors['3'], label='Original goal')
        axis.set(xlabel='x [m]', ylabel='y [m]', xlim=(-4.5, 4.7), ylim=(-3.1, 1.1),
                 title='RA-Only' if row['condition'] == 'R0' else 'Recovery + RA', aspect='equal')
        axis.legend(loc='upper center', bbox_to_anchor=(.5, 1.02), ncol=2, frameon=False, fontsize=8)
        axis.grid(alpha=.15)
        times = np.asarray([record['t'] for record in records])
        margin_axis = axes[1, column]
        margin_axis.plot(times, [record['min_rho'] for record in records], color=colors['3'])
        margin_axis.axhline(0, color='black', linewidth=.7, linestyle=':')
        margin_axis.axvline(settings['change_step']/settings['rate_hz'], color=colors['2'], linestyle='--', linewidth=.8)
        margin_axis.set(xlabel='Nominal control time [s]', ylabel='Min. normalized margin', xlim=(0, 30))
        margin_axis.grid(alpha=.15)
    fig.savefig(args.out / 'fig3_mission_recovery_corrected.png', dpi=300)
    plt.close(fig)
    provenance['analysis_sha256'] = hashlib.sha256((args.root/'paired_analysis_v2.json').read_bytes()).hexdigest()
    provenance['note'] = '固定旧图代表 seed 9445；叉号为失效步观测位置，时间为 step/20，不是实测墙钟。'
    (args.out/'provenance.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
