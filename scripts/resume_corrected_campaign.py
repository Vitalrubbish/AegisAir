"""人工排查后的基础设施续跑；保留原条件与有效前缀，不自动反复解锁。"""
import argparse
import hashlib
import json
from pathlib import Path
import time

from c1_revision_policy import paired_decision
from run_c1_corrected_v2 import ROOT, has_episode_trajectory, run_remaining


def campaign_decision(out, settings):
    if settings.get('experiment') == 'ood':
        from corrected_ood_policy import decision_for
        return decision_for(out, settings)
    if settings.get('experiment') in {'trigger_development','trigger_test'}:
        from run_corrected_trigger_comparison import trigger_decision
        return trigger_decision
    return paired_decision


def load_resume(out, diagnosis):
    if not diagnosis.strip():
        raise ValueError('必须先排查并记录原因，不能空白解锁')
    state = json.loads((out / 'status.json').read_text())
    if state['state'] != 'PAUSED_FOR_DIAGNOSIS':
        raise ValueError('只恢复基础设施暂停，不覆盖主方法或安全链结局')
    settings = json.loads((out / 'run_settings.json').read_text())
    rows = json.loads((out / 'results.json').read_text()) if (out / 'results.json').exists() else []
    attempts = [dict(attempt) for attempt in state['attempts']]
    if not attempts or attempts[-1]['state'] == 'VALID':
        raise ValueError('不是缺失条件的基础设施暂停，须单独处理清理错误')
    for attempt in attempts:
        if attempt['state'] != 'NEEDS_DIAGNOSIS':
            continue
        folder = out / attempt['label']
        blocked = folder / 'BLOCKED.txt'
        # 此精确退出发生在起飞和正式测量前；仍要求无正式轨迹/摘要。
        runners = list(folder.glob('*_logs/runner.log'))
        preflight_arm_failure = (
            len(runners) == 1 and
            runners[0].read_text().strip() == 'PX4 did not arm cleanly before live episode')
        if (not blocked.exists() or has_episode_trajectory(folder) or
                list(folder.glob('*/summary.json')) or
                not (preflight_arm_failure or any(marker in blocked.read_text()
                    for marker in ('SITL 超时', 'wait_for_px4_telemetry.py')))):
            raise ValueError('未知失败并非已核验的无轨迹启动超时，不能自动重试')
        attempt.update(state='INFRASTRUCTURE_INVALID', diagnosis=diagnosis)
    if any(attempt['state'] not in {'VALID', 'INFRASTRUCTURE_INVALID'} for attempt in attempts):
        raise ValueError('存在未分类尝试')
    expected = [(trial['trial_id'], method, trial['seed'])
                for trial in settings['trials'] for method in trial['condition_order']]
    if [(row['trial_id'], row['method'], row['seed']) for row in rows] != expected[:len(rows)]:
        raise ValueError('已有结果不是有效顺序前缀')
    snapshots = [out / 'source_hashes.json']
    snapshots.extend(path for path in out.glob('*_resume_*.json') if not path.name.startswith('._'))
    latest = max(snapshots, key=lambda path: path.stat().st_mtime_ns)
    record = json.loads(latest.read_text())
    old = record.get('source_hashes', record)
    changed = [name for name, digest in old.items()
               if not (ROOT / name).exists() or hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest]
    if any(name.startswith(('swarm/', 'marllib/')) for name in changed):
        raise ValueError(f'实验实现变化，禁止混合续跑：{changed}')
    corrections = {}
    for pattern in ('audit_resume_*.json', 'pcbf_audit_resume_*.json'):
        for path in out.glob(pattern):
            for correction in json.loads(path.read_text()).get('corrections', []):
                key = correction['trial_id'], correction['method']
                if key in corrections and corrections[key] != correction:
                    raise ValueError('补审计记录冲突')
                corrections[key] = correction
    evaluated = []
    for row in rows:
        matching = [attempt for attempt in attempts if attempt['state'] == 'VALID'
                    and attempt['label'].startswith(f"{row['trial_id']}_{row['method']}_attempt")]
        if len(matching) != 1:
            raise ValueError('有效结果归属不唯一')
        summary = Path(matching[0]['summary'])
        if json.loads(summary.read_text())['trials'][0] != row:
            raise ValueError('摘要与结果不一致')
        if hashlib.sha256((summary.parent / row['trajectory']).read_bytes()).hexdigest() != row['trajectory_sha256']:
            raise ValueError('轨迹哈希不一致')
        checked = dict(row)
        correction = corrections.get((row['trial_id'], row['method']))
        if correction:
            if correction['trajectory_sha256'] != row['trajectory_sha256']:
                raise ValueError('补审计身份不一致')
            checked['published_command_constraint_unknown_count'] = correction.get(
                'corrected_unknown', correction.get('published_command_constraint_unknown_count'))
            checked['published_command_constraint_failure_count'] = correction.get(
                'corrected_failure', correction.get('published_command_constraint_failure_count'))
        if checked.get('published_command_constraint_unknown_count', 0):
            raise ValueError('有效结果仍有审计未知，不能用基础设施续跑入口绕过')
        evaluated.append(checked)
    # 每次尝试保留原始完整配置及外部运行时哈希；新入口不放宽数值条件。
    for attempt in attempts:
        folder = out / attempt['label']
        if json.loads((folder / 'manifest.json').read_text()) != settings:
            raise ValueError('运行参数或顺序变化')
    runtime = out / attempts[-1]['label'] / 'runtime_hashes.json'
    for name, digest in json.loads(runtime.read_text()).items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest:
            raise ValueError(f'外部运行时发生变化：{name}')
    completed = offset = 0
    evaluate_pair = campaign_decision(out, settings)
    for trial in settings['trials']:
        n = len(trial['condition_order'])
        if offset + n > len(rows):
            break
        if evaluate_pair(evaluated[offset:offset+n], trial['condition_order']) != 'CONTINUE':
            raise ValueError('已有完整配对不允许继续，先处理主方法或安全链问题')
        completed += 1
        offset += n
    with (out / f'infrastructure_resume_{time.time_ns()}.json').open('x') as stream:
        json.dump(dict(previous_status=state, diagnosis=diagnosis, changed_sources=changed,
            completed_pairs=completed, valid_prefix=len(rows), source_reference=latest.name,
            source_hashes={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                for base in ('swarm', 'marllib', 'scripts') for path in (ROOT / base).rglob('*.py')},
            note='经排查后手工续跑；不改变参数，不删除无效尝试，不重复有效条件。下一批最多三次基础设施尝试；本入口不循环解锁。'),
            stream, ensure_ascii=False, indent=2)
    return settings, rows, attempts, completed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--diagnosis', required=True)
    args = parser.parse_args()
    settings, rows, attempts, completed = load_resume(args.out, args.diagnosis)
    run_remaining(args.out, settings, rows, attempts, completed,
        decision_fn=campaign_decision(args.out, settings))


if __name__ == '__main__':
    main()
