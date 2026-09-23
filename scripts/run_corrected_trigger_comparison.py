"""按原距离/TTC 开发网格运行；不把缺失的完整 V4 当成主方法。"""
import argparse
import hashlib
import json
from pathlib import Path
from run_c1_corrected_v2 import ROOT, run_remaining


def trigger_decision(rows, expected_methods):
    methods = [row['method'] for row in rows]
    if len(methods) != len(expected_methods) or set(methods) != set(expected_methods):
        raise ValueError('触发对照配对缺失或重复')
    if any(not row.get('infrastructure_valid', False) for row in rows):
        return 'RETRY_INFRASTRUCTURE'
    if any(row.get('safety_bypass_count', 0) or row.get('published_command_mismatch_count', 0)
           or row.get('published_command_constraint_unknown_count', 0) for row in rows):
        return 'STOP_SAFETY_CHAIN'
    if any(row['collision'] for row in rows):
        return 'STOP_SCENARIO_COLLISION'
    return 'CONTINUE'


def settings_for(grid):
    parent = ROOT / 'configs' / f'trigger_comparison_development_grid{grid}_v1.json'
    settings = json.loads(parent.read_text())
    settings.update(parent_protocol_id=settings['protocol_id'],
        protocol_id='aegisair-corrected-c1-family-v1', experiment='trigger_development',
        previous_settings_sha256=hashlib.sha256(parent.read_bytes()).hexdigest(),
        stopping_rule='保留原触发开发规则：完整配对后碰撞仅停止当前几何后续 seed；非正裕度和未完成是比较结果。基础设施同条件最多三次尝试后排查，全部尝试保留；非预设安全链疑点暂停。')
    return settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection=parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--grid', type=int, choices=(1, 2, 3))
    selection.add_argument('--frozen-test',type=Path,help='由完整开发网格按原词典序生成的测试配置')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--resume-scenarios', action='store_true')
    args = parser.parse_args()
    if args.frozen_test:
        from freeze_corrected_trigger_test import load_frozen_test
        settings=load_frozen_test(args.frozen_test)
    else:
        settings = settings_for(args.grid)
    if args.resume_scenarios:
        if json.loads((args.out / 'run_settings.json').read_text()) != settings:
            raise ValueError('触发网格配置变化')
    else:
        args.out.mkdir(parents=True, exist_ok=False)
        (args.out / 'run_settings.json').write_text(json.dumps(settings, ensure_ascii=False, indent=2))
    states = []
    for scenario in dict.fromkeys(trial['scenario_id'] for trial in settings['trials']):
        group = dict(settings, trials=[trial for trial in settings['trials'] if trial['scenario_id'] == scenario])
        out = args.out / scenario
        if args.resume_scenarios and out.exists():
            from run_corrected_c1_family import existing_group
            state = existing_group(out, group, {'COMPLETED', 'STOP_SCENARIO_COLLISION'})
            states.append(dict(scenario=scenario, state=state['state'], valid_conditions=state['valid_conditions']))
            (args.out / 'scenario_status.json').write_text(json.dumps(states, ensure_ascii=False, indent=2))
            continue
        out.mkdir()
        (out / 'run_settings.json').write_text(json.dumps(group, ensure_ascii=False, indent=2))
        (out / 'source_hashes.json').write_text(json.dumps({str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for base in ('swarm', 'marllib', 'scripts') for path in (ROOT / base).rglob('*.py')}, indent=2))
        run_remaining(out, group, [], [], 0, decision_fn=trigger_decision)
        state = json.loads((out / 'status.json').read_text())
        states.append(dict(scenario=scenario, state=state['state'], valid_conditions=state['valid_conditions']))
        (args.out / 'scenario_status.json').write_text(json.dumps(states, ensure_ascii=False, indent=2))
        if state['state'] not in {'COMPLETED', 'STOP_SCENARIO_COLLISION'}:
            raise RuntimeError('需排查的安全链或基础设施问题，不继续推进网格')
    complete = all(state['state'] == 'COMPLETED' for state in states)
    (args.out / 'status.json').write_text(json.dumps(dict(
        state='COMPLETED' if complete else 'PARTIAL_SCENARIO_STOP', scenarios=states,
        note='独立测试不再选择阈值。' if args.frozen_test else
        '当前仅一个开发网格；三个完整网格都核验后才能按原词典序选择阈值并冻结新测试。'), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
