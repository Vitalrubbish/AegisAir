"""完整 C3 配对轨迹核验、描述统计与 seed 级差值；不填补未恢复事件。"""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from run_c3_corrected_v2 import audit_trace,paired_decision
from analyze_corrected_ablation import mcnemar_p


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    state=json.loads((args.root/'status.json').read_text())
    if state['state']!='COMPLETED':
        raise ValueError('不能把提前停止组当全量完成')
    settings=json.loads((args.root/'run_settings.json').read_text())
    rows=json.loads((args.root/'results.json').read_text())
    expected=[(trial['trial_id'],condition,trial['seed']) for trial in settings['trials'] for condition in trial['condition_order']]
    if [(row['trial_id'],row['condition'],row['seed']) for row in rows]!=expected:
        raise ValueError('配对缺失或重复')
    trace_reports=[]
    for row in rows:
        key=row['trial_id']+'/'+row['condition']
        summary=Path(state['condition_sources'][key])
        payload=json.loads(summary.read_text())
        if row not in payload['trials'] or not row['infrastructure_valid']:
            raise ValueError('有效结果与原摘要不一致')
        if hashlib.sha256(Path(payload['manifest']).read_bytes()).hexdigest()!=payload['manifest_sha256']:
            raise ValueError('C3 实际执行配置哈希变化')
        audit=audit_trace(summary,row,settings)
        if audit!=state['trajectory_audits'][key]:
            raise ValueError('审计结果变化')
        records=[json.loads(line) for line in (summary.parent/row['trajectory']).read_text().splitlines()]
        latencies=np.asarray([record['ra_solve_latency_ms'] for record in records])
        publication_failures=[record for record in records if any(
            drone.get('published_command_constraint_ok') is False for drone in record['drones'].values())]
        trace_reports.append(dict(trial_id=row['trial_id'],condition=row['condition'],**audit,
            selected_qp_infeasible_steps=sum(any(drone['feasible'] is False for drone in record['drones'].values()) for record in records),
            latency_p99_ms=float(np.quantile(latencies,.99)),latency_max_ms=float(max(latencies)),
            deadline_misses=int(sum(latencies>1000/settings['rate_hz'])),
            publication_failed_steps=len(publication_failures),
            publication_failed_steps_after_mission_change=sum(record['step']>=settings['change_step'] for record in publication_failures),
            publication_failed_steps_with_velocity_clipping=sum(any(drone.get('vel_saturated') for drone in record['drones'].values()) for record in publication_failures),
            publication_failed_steps_while_solver_feasible=sum(all(drone.get('solver_feasible') is True for drone in record['drones'].values()) for record in publication_failures),
            source_summary=str(summary),same_stack_pair=(
                state['condition_sources'][row['trial_id']+'/R0']==state['condition_sources'][row['trial_id']+'/R1'])))
    by={(row['trial_id'],row['condition']):row for row in rows}
    for trial in settings['trials']:
        pair=[by[trial['trial_id'],condition] for condition in trial['condition_order']]
        if paired_decision(pair,[state['trajectory_audits'][trial['trial_id']+'/'+row['condition']] for row in pair],settings['change_step'])!='CONTINUE':
            raise ValueError('已完成配对未通过原门')
    descriptions=[]
    for condition in ('R0','R1'):
        subset=[row for row in rows if row['condition']==condition]
        traces=[row for row in trace_reports if row['condition']==condition]
        descriptions.append(dict(condition=condition,trials=len(subset),coverage=sum(row['critical_reached'] for row in subset),
            collisions=sum(row['collision'] for row in subset),minimum_rho=min(row['min_rho'] for row in subset),
            mean_min_rho=float(np.mean([row['min_rho'] for row in subset])),mean_path_length_m=float(np.mean([row['path_length_m'] for row in subset])),
            selected_qp_infeasible_steps=sum(row['selected_qp_infeasible_steps'] for row in traces),
            maximum_episode_p99_ms=max(row['latency_p99_ms'] for row in traces),
            recovery_steps=[row['recovery_step'] for row in subset],
            published_constraint_failures=sum(row['published_command_constraint_failure_count'] for row in subset)))
    rng=np.random.default_rng(20260922)
    metrics={}
    for metric in ('min_rho','path_length_m','cbf_events'):
        delta=np.asarray([by[trial['trial_id'],'R1'][metric]-by[trial['trial_id'],'R0'][metric] for trial in settings['trials']])
        samples=rng.choice(delta,size=(10000,len(delta)),replace=True).mean(axis=1)
        metrics[metric]=dict(mean_r1_minus_r0=float(delta.mean()),bootstrap_95_ci=np.quantile(samples,[.025,.975]).tolist())
    a=sum(by[trial['trial_id'],'R1']['critical_reached'] and not by[trial['trial_id'],'R0']['critical_reached'] for trial in settings['trials'])
    b=sum(by[trial['trial_id'],'R0']['critical_reached'] and not by[trial['trial_id'],'R1']['critical_reached'] for trial in settings['trials'])
    excluded=[]
    for attempt in state['attempts']:
        if attempt['state']!='INFRASTRUCTURE_INVALID':
            continue
        for summary in (args.root/attempt['label']).glob('*/summary.json'):
            for row in json.loads(summary.read_text())['trials']:
                if not row['infrastructure_valid']:
                    excluded.append(dict(attempt=attempt['label'],summary=str(summary),
                        **{key:row[key] for key in ('trial_id','condition','seed','min_rho','collision',
                            'infrastructure_invalid_reasons','freshness_gate','trajectory_sha256')}))
    report=dict(conditions_verified=len(rows),paired_trials=len(settings['trials']),condition_summary=descriptions,
        paired_metrics=metrics,coverage_discordance=dict(r1_only=a,r0_only=b,exact_mcnemar_p=mcnemar_p(a,b)),
        trace_audits=trace_reports,attempts=state['attempts'],excluded_infrastructure_outcomes=excluded,
        note='统计单位为配对 seed。新增描述区间为事后 10000 次 seed bootstrap，随机种子 20260922，不冒称预注册。未观测恢复时间保留 null；补跑条件的 fresh-stack 上下文单列，不冒充原同栈配对。')
    with args.out.open('x') as stream:
        json.dump(report,stream,ensure_ascii=False,indent=2)
    print(json.dumps(dict(condition_summary=descriptions,paired_metrics=metrics,coverage_discordance=report['coverage_discordance']),ensure_ascii=False))


if __name__=='__main__':
    main()
