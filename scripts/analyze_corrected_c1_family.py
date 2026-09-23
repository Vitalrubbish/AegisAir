"""核验修正版 C1/C2/单场景 OOD 的完整有效配对并计算原定统计。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from marllib.analyze_c1_hocbf_v4_px4_validation import _method_summary, _paired


def mechanism(records):
    recovery = next((record for record in records if any(
        drone.get('recovery_active') for drone in record['drones'].values())), None)
    primary_bad = next((record['step'] for record in records if any(
        drone.get('primary_feasible') is False for drone in record['drones'].values())), None)
    return dict(first_recovery_step=None if recovery is None else recovery['step'],
        first_recovery_reasons=[] if recovery is None else sorted({
            drone['recovery_reason'] for drone in recovery['drones'].values()
            if drone.get('recovery_reason') is not None}),
        primary_feasible_at_first_recovery=None if recovery is None else all(
            drone.get('primary_feasible') is True for drone in recovery['drones'].values()),
        first_primary_infeasible_step=primary_bad,
        lead_steps=None if recovery is None or primary_bad is None else primary_bad-recovery['step'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    state = json.loads((args.root / 'status.json').read_text())
    if state['state'] != 'COMPLETED':
        raise ValueError('仅分析全量完成组；提前停止场景须单独报告，不能冒充全量')
    settings = json.loads((args.root / 'run_settings.json').read_text())
    rows = json.loads((args.root / 'results.json').read_text())
    expected = [(trial['trial_id'], method, trial['seed'])
                for trial in settings['trials'] for method in trial['condition_order']]
    if [(row['trial_id'], row['method'], row['seed']) for row in rows] != expected:
        raise ValueError('有效配对缺失或重复')
    if len({row.get('scenario_id', 'nominal') for row in rows}) > 1:
        raise ValueError('不同 OOD 场景不得合并为一个样本池')
    corrections = {}
    for path in args.root.glob('audit_resume_*.json'):
        for correction in json.loads(path.read_text()).get('corrections', []):
            key = correction['trial_id'], correction['method']
            if key in corrections and corrections[key] != correction:
                raise ValueError('补审计记录冲突')
            corrections[key] = correction
    timing = []
    for row in rows:
        if not row['infrastructure_valid']:
            raise ValueError('有效结果混入基础设施失败')
        attempts = [attempt for attempt in state['attempts'] if attempt['state'] == 'VALID'
                    and attempt['label'].startswith(f"{row['trial_id']}_{row['method']}_attempt")]
        if len(attempts) != 1:
            raise ValueError('有效条件归属不唯一')
        summary = Path(attempts[0]['summary'])
        if json.loads(summary.read_text())['trials'][0] != row:
            raise ValueError('原始摘要与结果不一致')
        path = summary.parent / row['trajectory']
        if hashlib.sha256(path.read_bytes()).hexdigest() != row['trajectory_sha256']:
            raise ValueError('原始轨迹哈希不一致')
        records = [json.loads(line) for line in path.read_text().splitlines()]
        if min(record['min_rho'] for record in records) != row['min_rho']:
            raise ValueError('最低裕度不一致')
        correction = corrections.get((row['trial_id'], row['method']))
        if correction:
            if correction['trajectory_sha256'] != row['trajectory_sha256']:
                raise ValueError('补审计身份不一致')
            for key in ('published_command_constraint_unknown_count', 'published_command_constraint_failure_count'):
                row[key] = correction[key]
        if row.get('published_command_constraint_unknown_count', 0):
            raise ValueError('存在未解决的审计未知')
        if row['method'] == 'AEGIS_HOCBF_V4':
            timing.append(dict(trial_id=row['trial_id'], seed=row['seed'], **mechanism(records)))
    methods = sorted({row['method'] for row in rows})
    from c1_revision_policy import paired_decision
    if settings.get('experiment')=='ood':
        from corrected_ood_policy import decision_for
        decide=decision_for(args.root,settings)
    else:
        decide=paired_decision
    for trial in settings['trials']:
        pair=[row for row in rows if row['trial_id']==trial['trial_id']]
        if decide(pair,trial['condition_order'])!='CONTINUE':
            raise ValueError('完整组仍存在未解决的主方法/安全链结局')
    excluded=[]
    for attempt in state['attempts']:
        if attempt['state']=='VALID':
            continue
        item=dict(attempt)
        summaries=list((args.root/attempt['label']).glob('*/summary.json'))
        if len(summaries)==1:
            raw_row=json.loads(summaries[0].read_text())['trials'][0]
            item['observed_outcome']={key:raw_row.get(key) for key in (
                'trial_id','method','seed','min_rho','collision','mission_complete',
                'infrastructure_valid','infrastructure_invalid_reasons','freshness_gate')}
        excluded.append(item)
    report = dict(conditions_verified=len(rows), paired_trials=len(settings['trials']),
        protocol_id=settings['protocol_id'], method_summary=_method_summary(rows),
        paired=[_paired(rows, method) for method in methods if method != 'AEGIS_HOCBF_V4'],
        mechanism_audit=timing, audit_correction_keys=[list(key) for key in corrections],
        publication_summary={method:dict(
            raw_mismatches=sum(row['published_command_mismatch_count'] for row in rows if row['method']==method),
            constraint_failures=sum(row['published_command_constraint_failure_count'] for row in rows if row['method']==method),
            constraint_unknown=sum(row['published_command_constraint_unknown_count'] for row in rows if row['method']==method),
            injected_holds=sum(row.get('command_hold_jitter_count',0) for row in rows if row['method']==method)) for method in methods},
        injected_hold_audits=[json.loads(path.read_text()) for path in sorted(args.root.glob('injected_hold_audit_*.json'))],
        excluded_attempts=excluded,
        note='沿用原定 seed 级 10000 次配对 bootstrap 与随机种子，区间不是同时区间。机制提前步数来自同一实际轨迹，不是无接管反事实；未观测主约束不可行时记空，不补零。原始数据不覆盖。')
    with args.out.open('x') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(dict(conditions_verified=len(rows), method_summary=report['method_summary']), ensure_ascii=False))


if __name__ == '__main__':
    main()
