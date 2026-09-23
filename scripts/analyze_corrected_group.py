"""核验原 GroupSlot 的当前批次，按 seed 汇总并保留无效尝试。"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from run_group_corrected_v2 import seeds_for, verify_summary, decision_for


def analyze_root(root):
    state = json.loads((root/'status.json').read_text())
    if state['state'] not in {'COMPLETED','STOP_GROUP_DIAGNOSIS','STOP_SAFETY_CHAIN'}:
        raise ValueError('当前组尚非有效终态')
    settings = json.loads((root/'run_settings.json').read_text())
    rows = json.loads((root/'results.json').read_text())
    seeds = seeds_for(settings)
    if not rows or [row['seed'] for row in rows] != seeds[:len(rows)]:
        raise ValueError('有效 seed 前缀不一致')
    if state['state'] == 'COMPLETED' and len(rows) != len(seeds):
        raise ValueError('完成标记缺少 seed')
    all_latencies = []
    sources = []
    for row in rows:
        matches = [attempt for attempt in state['attempts'] if attempt['state']=='VALID' and attempt['seed']==row['seed']]
        if len(matches) != 1:
            raise ValueError('有效尝试归属不唯一')
        summary = Path(matches[0]['summary'])
        if verify_summary(summary, settings, row['seed']) != row:
            raise ValueError('摘要或轨迹审计变化')
        records = [json.loads(line) for line in (summary.parent/row['trajectory']).read_text().splitlines()]
        if len(records) != settings['max_steps']:
            raise ValueError('控制周期数不完整')
        latency = np.asarray([record['ra_solve_latency_ms'] for record in records])
        for key, value in (('p99',np.quantile(latency,.99)),('max',max(latency)),('deadline_misses',sum(latency>50))):
            if not np.isclose(row['ra_solve_latency_summary_ms'][key], value, atol=1e-9, rtol=0):
                raise ValueError('延迟摘要不一致：'+key)
        actual_complete = all(np.linalg.norm(np.asarray(row['final_positions'][str(drone)][:2])-
            np.asarray(settings['base_goals'][str(drone)][:2])) < settings['goal_epsilon'] for drone in settings['drone_ids'])
        audit = row['audit']; coordinator = row['c3_group_slot_summary']
        go = bool(actual_complete and row['infrastructure_valid'] and not row['collision'] and row['min_rho']>0
            and audit['selected_qp_infeasible_steps']==0 and row['safety_bypass_count']==0 and audit['ra_bypass_count']==0
            and audit['required_modes_seen'] and audit['frozen_hold_goals_stable'] and audit['authorized_groups_valid']
            and audit['authorized_groups_seen']==settings['c3_group_slot']['group_order']
            and coordinator['complete'] is True and coordinator['completed']==settings['drone_ids']
            and np.quantile(latency,.99)<50 and sum(latency>50)/settings['max_steps']<.01)
        if actual_complete != row['mission_complete'] or go != row['m4_go']:
            raise ValueError('原始 GroupSlot 门重算不一致')
        all_latencies.extend(latency.tolist())
        sources.append(dict(seed=row['seed'], summary=str(summary), trajectory_sha256=row['trajectory_sha256']))
    success = sum(decision_for(row)=='CONTINUE' for row in rows)
    n = len(rows); z = 1.959963984540054; p = success/n
    center = (p+z*z/(2*n))/(1+z*z/n)
    radius = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
    margins = np.asarray([row['min_rho'] for row in rows])
    rng = np.random.default_rng(20260922)
    interval = np.quantile(rng.choice(margins,size=(10000,n),replace=True).mean(axis=1),[.025,.975]).tolist()
    ranked = sorted(rows,key=lambda row:(row['min_rho'],row['seed']))
    excluded = []
    for attempt in state['attempts']:
        if attempt['state']=='INFRASTRUCTURE_INVALID':
            raw = json.loads(Path(attempt['summary']).read_text())['trial'] if attempt.get('summary') else None
            excluded.append(dict(attempt=attempt,observed_outcome=raw))
    return dict(state=state['state'], trials_verified=n, planned_trials=len(seeds), complete=n==len(seeds),
        joint_success=success, joint_success_wilson_95_ci=[max(0,center-radius),min(1,center+radius)],
        collisions=sum(row['collision'] for row in rows), minimum_rho=float(min(margins)), mean_min_rho=float(margins.mean()),
        mean_min_rho_bootstrap_95_ci=interval, total_control_steps=len(all_latencies),
        pooled_latency_p99_ms=float(np.quantile(all_latencies,.99)), max_latency_ms=max(all_latencies),
        deadline_misses=sum(value>50 for value in all_latencies),
        selected_qp_infeasible_steps=sum(row['audit']['selected_qp_infeasible_steps'] for row in rows),
        published_constraint_failures=sum(row['published_command_constraint_failure_count'] for row in rows),
        published_constraint_unknowns=sum(row['published_command_constraint_unknown_count'] for row in rows),
        published_mismatches=sum(row['published_command_mismatch_count'] for row in rows),
        representative_seeds=dict(lower_median=ranked[(n-1)//2]['seed'],lowest_margin=ranked[0]['seed']),
        sources=sources,excluded_infrastructure_attempts=excluded,
        note='仅原 GroupSlot 中等密度走廊；不是通用四机能力。描述区间按 seed，bootstrap 10000 次种子 20260922，不把周期当独立样本。单个 calibration seed 的区间不支持泛化。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args = parser.parse_args()
    report = analyze_root(args.root)
    with args.out.open('x') as stream:
        json.dump(report,stream,ensure_ascii=False,indent=2)
    print(json.dumps({key:value for key,value in report.items() if key not in ('sources','excluded_infrastructure_attempts')},ensure_ascii=False))


if __name__ == '__main__':
    main()
