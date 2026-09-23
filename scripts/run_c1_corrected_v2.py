"""从首 seed 开始 C1 修订版正式比较，不使用全方法安全门。"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys
import time
from c1_revision_policy import paired_decision

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def has_episode_trajectory(out):
    """旁路观测日志不是正式实验轨迹，不能阻止启动失败分类。"""
    return any(not p.parent.name.endswith('_logs') and not p.name.startswith('._')
               for p in out.glob('*/*.jsonl'))


def resume_rows(out):
    """只恢复完整配对前缀，验证原始结果并为 PB 缺失审计生成旁文件。"""
    from c1_pb_audit_backfill import audit_trajectory
    settings = json.loads((out/'run_settings.json').read_text())
    rows = json.loads((out/'results.json').read_text())
    previous = json.loads((out/'status.json').read_text())
    if previous['state'] != 'STOP_SAFETY_CHAIN':
        raise ValueError('此恢复入口只处理已诊断的 PB 审计暂停')
    old_hashes = json.loads((out/'source_hashes.json').read_text())
    permitted = {'swarm/ra/runtime_assurance.py', 'scripts/run_c1_corrected_v2.py'}
    for name, digest in old_hashes.items():
        if name not in permitted and hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != digest:
            raise ValueError(f'存在审计补丁以外的源文件变化：{name}')
    expected = [(t['trial_id'], m, t['seed']) for t in settings['trials'] for m in t['condition_order']]
    if [(r['trial_id'], r['method'], r['seed']) for r in rows] != expected[:len(rows)]:
        raise ValueError('已有结果不是原定顺序前缀')
    attempts = previous['attempts']
    audited = []
    corrections = []
    for row in rows:
        matches = [a for a in attempts if a['state']=='VALID' and
                   a['label'].startswith(f"{row['trial_id']}_{row['method']}_attempt")]
        if len(matches) != 1:
            raise ValueError('有效条件归属不唯一')
        summary_path = Path(matches[0]['summary'])
        if json.loads(summary_path.read_text())['trials'][0] != row:
            raise ValueError('汇总行与原始摘要不一致')
        path = summary_path.parent/row['trajectory']
        if hashlib.sha256(path.read_bytes()).hexdigest() != row['trajectory_sha256']:
            raise ValueError('轨迹哈希不一致')
        checked = dict(row)
        if row.get('published_command_constraint_unknown_count',0):
            if row['method'] != 'PB_CBF':
                raise ValueError('非 PB 审计未知，需单独诊断')
            report = audit_trajectory(path, row['trajectory_sha256'], settings['methods']['PB_CBF'])
            if report['original_unknown_count'] != row['published_command_constraint_unknown_count']:
                raise ValueError('未知计数与原始轨迹不符')
            for key in ('published_command_constraint_unknown_count','published_command_constraint_failure_count'):
                checked[key] = report[key]
            corrections.append(dict(trial_id=row['trial_id'],method=row['method'],**report))
        audited.append(checked)
    offset = completed = 0
    for trial in settings['trials']:
        count = len(trial['condition_order'])
        if offset == len(rows):
            break
        if paired_decision(audited[offset:offset+count],trial['condition_order']) != 'CONTINUE':
            raise ValueError('补审计后仍不满足继续条件')
        offset += count
        completed += 1
    stamp = time.time_ns()
    record = dict(previous_status=previous, corrections=corrections,
                  note='审计补丁续跑；原轨迹、摘要、结果行均不覆盖；仅补齐发布后约束诊断',
                  source_hashes={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest()
                      for base in ('swarm','marllib','scripts') for f in (ROOT/base).rglob('*.py')})
    with (out/f'audit_resume_{stamp}.json').open('x') as stream:
        json.dump(record,stream,ensure_ascii=False,indent=2)
    return settings, rows, attempts, completed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--resume-after-pb-audit',action='store_true')
    args = parser.parse_args()
    if args.resume_after_pb_audit:
        settings, rows, attempts, completed = resume_rows(args.out)
        run_remaining(args.out, settings, rows, attempts, completed)
        return
    args.out.mkdir(parents=True,exist_ok=False)
    parent = ROOT/'configs/c1_hocbf_v4_px4_validation_v1.json'
    settings = json.loads(parent.read_bytes())
    settings.update(protocol_id='aegisair-c1-corrected-comparison-v2',
        phase='修 bug 后正式比较；已知旧版负结果后的规则修订，非新盲测',
        previous_settings_sha256=hashlib.sha256(parent.read_bytes()).hexdigest(),
        previous_result='旧版 v4val02 V3 min_rho=-0.012755，保留不混合',
        stopping_rule='基线失败是结局；完整配对后仅 V4 collision/rho/任务失败或安全链问题停止后续 seed。基础设施失败同 seed 同条件重试；连续三次失败暂停排障，不判论文失败。')
    settings.pop('go_criteria',None)
    config = args.out/'run_settings.json'
    config.write_text(json.dumps(settings,ensure_ascii=False,indent=2)+'\n')
    (args.out/'source_hashes.json').write_text(json.dumps({str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for base in ('swarm','marllib','scripts') for f in (ROOT/base).rglob('*.py')},indent=2))
    rows, attempts = [], []
    run_remaining(args.out, settings, rows, attempts, 0)


def run_remaining(out, settings, rows, attempts, completed, *, decision_fn=None):
    decision_fn = paired_decision if decision_fn is None else decision_fn
    args = argparse.Namespace(out=out)
    config = out/'run_settings.json'
    def status(state, **extra):
        (args.out/'status.json').write_text(json.dumps(dict(state=state,updated_unix_s=time.time(),valid_conditions=len(rows),attempts=attempts,**extra),ensure_ascii=False,indent=2))
    try:
        for trial in settings['trials'][completed:]:
            paired = []
            for method in trial['condition_order']:
                existing = [r for r in rows if r['trial_id']==trial['trial_id'] and r['method']==method]
                if existing:
                    if len(existing)!=1:
                        raise RuntimeError('存在重复有效条件，拒绝续跑')
                    paired.append(existing[0])
                    continue
                accepted = None
                prefix = f"{trial['trial_id']}_{method}_attempt"
                prior = [int(a['label'][len(prefix):]) for a in attempts if a['label'].startswith(prefix)]
                first_index = max(prior, default=0)+1
                for index in range(first_index,first_index+3):
                    label = f"{trial['trial_id']}_{method}_attempt{index}"
                    out = args.out/label
                    command = [sys.executable,str(ROOT/'scripts/run_paper_c1_rerun.py'),
                        '--manifest',str(config),'--out',str(out),
                        '--single-trial',trial['trial_id'],'--single-method',method]
                    status('RUNNING',trial=trial['trial_id'],method=method,attempt=index)
                    print('START '+label,flush=True)
                    if out.exists():
                        raise RuntimeError(f'存在未归类输出，拒绝覆盖：{out}')
                    with (args.out/(label+'.log')).open('x') as stream:
                        result = subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
                    summaries = list(out.glob('*/summary.json'))
                    row = json.loads(summaries[0].read_text())['trials'][0] if len(summaries)==1 else None
                    if row is not None and row.get('infrastructure_valid',False):
                        if result.returncode:
                            raise RuntimeError('已有有效结果但清理/完整性出错，暂停排查，不重跑有效结果')
                        accepted = row
                        attempts.append(dict(label=label,state='VALID',summary=str(summaries[0])))
                        break
                    # 无轨迹且 telemetry readiness 明确失败，才自动标为启动基础设施失败。
                    readiness_failure = any(p.exists() and 'telemetry' in p.read_text().lower() for p in [out/'BLOCKED.txt']) and not has_episode_trajectory(out)
                    invalid_episode = row is not None and row.get('infrastructure_valid') is False
                    attempts.append(dict(label=label,state='INFRASTRUCTURE_INVALID' if readiness_failure or invalid_episode else 'NEEDS_DIAGNOSIS',returncode=result.returncode))
                    if not (readiness_failure or invalid_episode):
                        raise RuntimeError(f'{label} 原因尚未分类；保留输出并暂停诊断')
                    print('RETRY SAME SEED '+label,flush=True)
                if accepted is None:
                    raise RuntimeError(f'{trial["trial_id"]} {method} 连续三次基础设施失败，需排障')
                paired.append(accepted); rows.append(accepted)
                (args.out/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
                print('DONE '+trial['trial_id']+' '+method,flush=True)
            decision = decision_fn(paired,trial['condition_order'])
            status(decision,trial=trial['trial_id'])
            if decision!='CONTINUE':
                return
        status('COMPLETED',paired_trials=len(settings['trials']),note='全部条件已执行，统计和论文更新待完成；不等于全部方法通过')
    except BaseException as exc:
        status('PAUSED_FOR_DIAGNOSIS',error=str(exc))
        raise


if __name__ == '__main__':
    main()
