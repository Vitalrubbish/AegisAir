"""区分预设 OOD 指令保持与非预设发布偏差，原始计数不改写。"""
import hashlib
import json
import numpy as np
from c1_revision_policy import paired_decision


def audit_holds(records, *, seed, probability, drone_ids):
    if not records or not 0 < probability <= 1:
        raise ValueError('缺少轨迹或非预设扰动概率')
    rng = np.random.default_rng(seed)
    previous = {str(drone): np.zeros(2) for drone in drone_ids}
    held_count = mismatch_count = expected_mismatches = unexpected = 0
    for index, record in enumerate(records):
        if record['step'] != index or set(record['drones']) != set(previous):
            raise ValueError('不完整的周期或无人机集合，不能核对扰动序列')
        for drone in drone_ids:
            key = str(drone)
            row = record['drones'][key]
            if not row.get('telemetry_fresh') or not row.get('control_authority'):
                raise ValueError('有效 OOD 数据不应含遥测失效或撤销权限')
            expected_hold = bool(rng.random() < probability)
            if row.get('command_hold_jitter_applied') is not expected_hold:
                raise ValueError('实际保持序列与原 seed/概率不一致')
            published = np.asarray(row['published_velocity'], dtype=float)
            selected = np.asarray(row['solver_selected_velocity'], dtype=float)
            if (published.shape != (2,) or selected.shape != (2,) or
                    not np.all(np.isfinite(published)) or not np.all(np.isfinite(selected))):
                raise ValueError('发布速度格式无效')
            matches = bool(np.allclose(published, selected, atol=1e-9, rtol=0))
            if row['published_command_matches_selected'] is not matches:
                raise ValueError('原始发布审计标志与向量不一致')
            justified = bool(expected_hold and row.get('fallback_reason') == 'COMMAND_HOLD_JITTER'
                and row.get('published_action') == 'velocity'
                and np.allclose(published, previous[key], atol=1e-9, rtol=0))
            held_count += expected_hold
            mismatch_count += not matches
            expected_mismatches += not matches and justified
            unexpected += (not matches and not justified) or (expected_hold and not justified)
            previous[key] = published.copy()
    return dict(hold_count=int(held_count), raw_mismatch_count=int(mismatch_count),
                expected_hold_mismatch_count=int(expected_mismatches), unexpected_count=int(unexpected))


def decision_for(out, settings):
    def decide(rows, expected_methods):
        checked = []
        for row in rows:
            jitter = settings.get('command_hold_jitter', {}).get(row.get('scenario_id'), {})
            if not jitter.get('probability', 0):
                checked.append(row)
                continue
            paths = [path for path in out.glob(f"{row['trial_id']}_{row['method']}_attempt*/*/{row['trajectory']}")
                     if hashlib.sha256(path.read_bytes()).hexdigest() == row['trajectory_sha256']]
            if len(paths) != 1:
                raise ValueError('OOD 轨迹身份不唯一或哈希不符')
            audit = audit_holds([json.loads(line) for line in paths[0].read_text().splitlines()],
                seed=int(row['seed'])+int(jitter.get('seed_offset', 0)),
                probability=float(jitter['probability']), drone_ids=settings['drone_ids'])
            if audit['raw_mismatch_count'] != row['published_command_mismatch_count'] or audit['hold_count'] != row['command_hold_jitter_count']:
                raise ValueError('扰动/发布计数与摘要不一致')
            report = dict(trial_id=row['trial_id'], method=row['method'],
                trajectory_sha256=row['trajectory_sha256'], **audit,
                note='逐周期核对预设随机序列及上一条实际发布速度。预设保持不是未授权改写；其约束失败仍原样报告。原始发布偏差计数不覆盖。')
            destination = out / f"injected_hold_audit_{row['trial_id']}_{row['method']}.json"
            if destination.exists():
                if json.loads(destination.read_text()) != report:
                    raise ValueError('已有扰动审计与当前核验冲突')
            else:
                with destination.open('x') as stream:
                    json.dump(report, stream, ensure_ascii=False, indent=2)
            checked.append(dict(row, published_command_mismatch_count=audit['unexpected_count']))
        return paired_decision(checked, expected_methods)
    return decide
