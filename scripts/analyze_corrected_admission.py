"""独立核验动态接纳条件与原始轨迹；完整结果和有效提前停止分开报告。"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
from run_admission_corrected_v2 import verify_trace, final_audit, paired_decision


def analyze_root(root):
    state = json.loads((root/'status.json').read_text())
    if state['state'] not in {'COMPLETED', 'STOP_ADMISSION_DIAGNOSIS', 'STOP_INTEGRITY_DIAGNOSIS'}:
        raise ValueError('只分析已结束的有效结局；运行或基础设施暂停不当成最终结果')
    settings = json.loads((root/'run_settings.json').read_text())
    rows = json.loads((root/'results.json').read_text())
    expected = [(trial['trial_id'], condition, trial['seed'])
                for trial in settings['trials'] for condition in trial['condition_order']]
    identities = [(row['trial_id'], row['condition'], row['seed']) for row in rows]
    if identities != expected[:len(rows)] or not rows:
        raise ValueError('条件不是唯一有序有效前缀')
    if state['state'] == 'COMPLETED' and identities != expected:
        raise ValueError('完成标记与样本量不一致')
    sources = []
    for row in rows:
        prefix = row['trial_id']+'_'+row['condition']+'_attempt'
        matches = [attempt for attempt in state['attempts']
                   if attempt['state'] == 'VALID' and attempt['label'].startswith(prefix)]
        if len(matches) != 1 or not row['infrastructure_valid']:
            raise ValueError('有效尝试归属不唯一')
        summary = Path(matches[0]['summary'])
        payload = json.loads(summary.read_text())
        if payload['trials'] != [row]:
            raise ValueError('原始摘要不一致')
        if hashlib.sha256((summary.parent.parent/'manifest.json').read_bytes()).hexdigest() != payload['manifest_sha256']:
            raise ValueError('实际执行配置哈希变化')
        verify_trace(summary, row, settings)
        sources.append(dict(trial_id=row['trial_id'], condition=row['condition'], summary=str(summary),
                            trajectory_sha256=row['trajectory_sha256']))
    pairs = []
    for trial in settings['trials']:
        subset = [row for row in rows if row['trial_id'] == trial['trial_id']]
        if not subset:
            continue
        if [row['condition'] for row in subset] != trial['condition_order']:
            raise ValueError('结束状态含不完整配对')
        pairs.append(dict(trial_id=trial['trial_id'], decision=paired_decision(settings, subset)))
    audit = final_audit(settings, rows)
    if audit != json.loads((root/'audit.json').read_text()):
        raise ValueError('重新计算的门与保存的审计不一致')
    descriptions = []
    for condition in settings['conditions']:
        subset = [row for row in rows if row['condition'] == condition]
        if not subset:
            continue
        descriptions.append(dict(condition=condition, episodes=len(subset),
            critical_coverage=sum(row['post_failure_critical_reached'] for row in subset),
            collisions=sum(row['collision'] for row in subset),
            nonpositive_margin_episodes=sum(row['min_rho'] <= 0 for row in subset),
            minimum_rho=min(row['min_rho'] for row in subset),
            mean_min_rho=statistics.mean(row['min_rho'] for row in subset),
            selected_qp_infeasible_steps=sum(row['trajectory_audit']['selected_qp_infeasible_steps'] for row in subset),
            maximum_episode_p99_ms=max(row['ra_solve_latency_summary_ms']['p99'] for row in subset),
            deadline_misses=sum(row['ra_solve_latency_summary_ms']['deadline_misses'] for row in subset),
            published_constraint_failures=sum(row['published_command_constraint_failure_count'] for row in subset),
            published_constraint_unknowns=sum(row['published_command_constraint_unknown_count'] for row in subset),
            published_mismatches=sum(row['published_command_mismatch_count'] for row in subset)))
    return dict(state=state['state'], conditions_verified=len(rows), planned_conditions=len(expected),
                complete=len(rows)==len(expected), decision=audit['decision'],
                condition_summary=descriptions, paired_decisions=pairs, audit=audit,
                sources=sources, attempts=state['attempts'],
                note='所有有效基线负结果保留。提前停止组不报为完整样本；接纳/HOLD 仍保留原门。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = analyze_root(args.root)
    with args.out.open('x') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps({key: report[key] for key in ('state', 'conditions_verified', 'condition_summary')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
