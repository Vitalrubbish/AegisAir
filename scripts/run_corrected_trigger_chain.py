"""一次性串行触发实验链；不是定时任务，不解锁失败或覆盖既有数据。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from run_c1_corrected_v2 import ROOT
from run_corrected_trigger_comparison import trigger_decision


def verify_completed(root):
    settings = json.loads((root / 'run_settings.json').read_text())
    state = json.loads((root / 'status.json').read_text())
    if state['state'] != 'COMPLETED':
        raise ValueError(f'实验未完整完成，禁止自动越过：{root}')
    verified = []
    for scenario in dict.fromkeys(t['scenario_id'] for t in settings['trials']):
        folder = root / scenario
        child = json.loads((folder / 'status.json').read_text())
        trials = [t for t in settings['trials'] if t['scenario_id'] == scenario]
        if json.loads((folder / 'run_settings.json').read_text()) != dict(settings, trials=trials):
            raise ValueError('子组配置变化')
        rows = json.loads((folder / 'results.json').read_text())
        expected = [(t['trial_id'], m, t['seed']) for t in trials for m in t['condition_order']]
        if child['state'] != 'COMPLETED' or [(r['trial_id'], r['method'], r['seed']) for r in rows] != expected:
            raise ValueError('子组未完成或身份缺失/重复')
        for row in rows:
            attempts = [a for a in child['attempts'] if a['state'] == 'VALID'
                and a['label'].startswith(f"{row['trial_id']}_{row['method']}_attempt")]
            if len(attempts) != 1:
                raise ValueError('原摘要归属不唯一')
            summary = Path(attempts[0]['summary'])
            trajectory = summary.parent / row['trajectory']
            if json.loads(summary.read_text())['trials'] != [row] or hashlib.sha256(trajectory.read_bytes()).hexdigest() != row['trajectory_sha256']:
                raise ValueError('原摘要或轨迹哈希变化')
            records = [json.loads(line) for line in trajectory.read_text().splitlines()]
            if min(record['min_rho'] for record in records) != row['min_rho']:
                raise ValueError('摘要裕度与原轨迹不同')
        for trial in trials:
            if trigger_decision([r for r in rows if r['trial_id'] == trial['trial_id']], trial['condition_order']) != 'CONTINUE':
                raise ValueError('存在未解决的场景/安全链结局')
        verified.append(dict(scenario=scenario, conditions=len(rows),
            infrastructure_invalid_attempts=sum(a['state'] != 'VALID' for a in child['attempts'])))
    return dict(root=str(root), scenarios=verified,
                conditions_verified=sum(item['conditions'] for item in verified))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--queue-out', type=Path, required=True)
    args = parser.parse_args()
    if not Path('/Volumes/Expansion').is_mount() or not args.data_root.resolve().is_relative_to(Path('/Volumes/Expansion').resolve()):
        raise ValueError('实验数据必须在已挂载外置盘')
    args.queue_out.mkdir(parents=True, exist_ok=False)
    grids = [args.data_root / f'drones_corrected_trigger_grid{n}_v2_20260922' for n in (1, 2, 3)]
    freeze = args.data_root / 'drones_corrected_trigger_test_freeze_v1_20260922'
    test = args.data_root / 'drones_corrected_trigger_test_v1_20260922'
    completed = []
    sources = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for base in ('swarm', 'marllib', 'scripts', 'configs') for p in (ROOT / base).rglob('*')
        if p.suffix in ('.py', '.json')}
    (args.queue_out / 'source_hashes.json').write_text(json.dumps(sources, indent=2))

    def save(state, **extra):
        (args.queue_out / 'status.json').write_text(json.dumps(dict(state=state,
            updated_unix_s=time.time(), completed=completed, **extra), ensure_ascii=False, indent=2))

    def run(label, script, arguments):
        processes = subprocess.check_output(['ps', '-axo', 'command'], text=True)
        if any(marker in line for line in processes.splitlines() for marker in (
            'scripts/run_paper_c1_rerun.py', 'scripts/run_corrected_c1_family.py',
            'scripts/resume_corrected_campaign.py', 'scripts/run_corrected_trigger_comparison.py')):
            raise RuntimeError('仍有其他实验运行器，不并发启动')
        if any(hashlib.sha256(Path(p).read_bytes()).hexdigest() != digest for p, digest in sources.items()):
            raise ValueError('实验链源码或配置变化，暂停避免混合实现')
        command = [sys.executable, str(ROOT / script), *map(str, arguments)]
        save('RUNNING', active=label, command=command)
        print('START ' + label, flush=True)
        with (args.queue_out / (label + '.log')).open('x') as stream:
            subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)

    try:
        if any(p.exists() for p in [*grids, freeze, test]):
            raise ValueError('目标已存在；不覆盖、不重复启动，需按现有检查点继续')
        for n, root in enumerate(grids, 1):
            run(f'grid{n}', 'scripts/run_corrected_trigger_comparison.py', ['--grid', n, '--out', root])
            completed.append(verify_completed(root))
            save('VERIFIED', active=f'grid{n}')
        run('freeze', 'scripts/freeze_corrected_trigger_test.py', ['--grid-roots', *grids, '--out', freeze])
        run('test', 'scripts/run_corrected_trigger_comparison.py', ['--frozen-test', freeze / 'run_settings.json', '--out', test])
        completed.append(verify_completed(test))
        save('COMPLETED', note='开发与测试的原始结果完整性核验完成；配对统计、论文统一与最终渲染仍待执行。')
    except BaseException as exc:
        save('PAUSED_FOR_DIAGNOSIS', error=str(exc))
        raise


if __name__ == '__main__':
    main()
