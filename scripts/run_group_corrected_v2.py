"""四机原 GroupSlot 修正版，独立 cal→qual→sealed；不接入 B1/B2。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from run_c1_corrected_v2 import ROOT,has_episode_trajectory
from marllib.run_c3_group_slot_gazebo import _audit

CONFIGS={
    'calibration':'c3_group_slot_4uav_calibration_smoke_v1.json',
    'qualification':'c3_group_slot_4uav_qualification_v1.json',
    'sealed':'c3_group_slot_4uav_sealed_v1.json',
}


def settings_for(stage):
    parent=ROOT/'configs'/CONFIGS[stage]
    settings=json.loads(parent.read_text())
    settings.update(revision_id='group-corrected-v2',
        corrected_phase='修 bug 后正式重跑，不冒称新增独立样本或新盲测',
        previous_settings_sha256=hashlib.sha256(parent.read_bytes()).hexdigest(),
        prerequisite_rule='历史父路径只留档；本次必须使用本修正版当前 cal/qual 的完整 GO。')
    return settings


def seeds_for(settings):
    return settings.get('sealed_seeds',settings.get('qualification_seeds',[settings.get('gazebo_seed')]))


def validate_prerequisite(stage,prerequisite):
    if stage=='calibration':
        if prerequisite is not None:
            raise ValueError('本次 calibration 不使用历史父结果')
        return
    if prerequisite is None:
        raise ValueError('缺少当前前置门')
    expected='calibration' if stage=='qualification' else 'qualification'
    prior=json.loads(prerequisite.read_text())
    root=prerequisite.parent
    if (prior.get('decision')!='GO' or prior.get('protocol_id')!=settings_for(expected)['protocol_id'] or
        json.loads((root/'status.json').read_text())['state']!='COMPLETED' or
        json.loads((root/'run_settings.json').read_text())!=settings_for(expected)):
        raise ValueError('当前 GroupSlot 前置阶段未完成或未通过')


def verify_summary(path,settings,seed):
    payload=json.loads(path.read_text())
    if payload['gazebo_seed']!=seed or payload['manifest_sha256']!=hashlib.sha256((path.parent.parent/'manifest.json').read_bytes()).hexdigest():
        raise ValueError('GroupSlot seed/参数哈希不一致')
    row=payload['trial']
    trajectory=path.parent/row['trajectory']
    raw=trajectory.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=row['trajectory_sha256']:
        raise ValueError('GroupSlot 轨迹哈希不一致')
    records=[json.loads(line) for line in raw.splitlines()]
    if min(record['min_rho'] for record in records)!=row['min_rho'] or _audit(trajectory,settings['c3_group_slot']['group_order'])!=row['audit']:
        raise ValueError('GroupSlot 摘要与轨迹不一致')
    return dict(seed=seed,m4_go=payload['m4_go'],**row)


def decision_for(row):
    if not row['infrastructure_valid']:
        return 'RETRY_INFRASTRUCTURE'
    if row['published_command_mismatch_count'] or row['published_command_constraint_unknown_count']:
        return 'STOP_SAFETY_CHAIN'
    return 'CONTINUE' if row['m4_go'] else 'STOP_GROUP_DIAGNOSIS'


def load_resume(out,stage,diagnosis):
    if not diagnosis.strip():
        raise ValueError('须先完成实际诊断')
    state=json.loads((out/'status.json').read_text())
    if state['state']!='PAUSED_FOR_DIAGNOSIS':
        raise ValueError('不覆盖有效失败结局')
    settings=json.loads((out/'run_settings.json').read_text())
    if settings!=settings_for(stage):
        raise ValueError('配置变化')
    rows=json.loads((out/'results.json').read_text())
    attempts=state['attempts']
    if not attempts or any(a['state'] not in {'VALID','INFRASTRUCTURE_INVALID'} for a in attempts):
        raise ValueError('存在未分类错误，不能解锁')
    if [row['seed'] for row in rows]!=seeds_for(settings)[:len(rows)]:
        raise ValueError('有效 seed 前缀变化')
    old=json.loads((out/'source_hashes.json').read_text())
    changed=[name for name,digest in old.items() if not (ROOT/name).exists() or hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest]
    if any(name.startswith(('swarm/','marllib/')) for name in changed):
        raise ValueError('实验实现变化，不混合续跑')
    for attempt in attempts:
        if json.loads((out/attempt['label']/'manifest.json').read_text())!=settings:
            raise ValueError('尝试配置变化')
    for name,digest in json.loads((out/attempts[-1]['label']/'runtime_hashes.json').read_text()).items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:
            raise ValueError('运行时变化')
    for row in rows:
        matching=[a for a in attempts if a['state']=='VALID' and a['seed']==row['seed']]
        if len(matching)!=1 or verify_summary(Path(matching[0]['summary']),settings,row['seed'])!=row or decision_for(row)!='CONTINUE':
            raise ValueError('已有有效结果不一致或未通过，不能当基础设施恢复')
    with (out/f'infrastructure_resume_{time.time_ns()}.json').open('x') as stream:
        json.dump(dict(previous_status=state,diagnosis=diagnosis,changed_sources=changed),stream,ensure_ascii=False,indent=2)
    return settings,rows,attempts


def run(out,settings,rows,attempts,prerequisite):
    def save(state,**extra):
        (out/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
        (out/'status.json').write_text(json.dumps(dict(state=state,valid_trials=len(rows),attempts=attempts,updated_unix_s=time.time(),**extra),ensure_ascii=False,indent=2))
    try:
        for seed in seeds_for(settings):
            existing=[row for row in rows if row['seed']==seed]
            if existing:
                if len(existing)!=1 or decision_for(existing[0])!='CONTINUE':
                    raise ValueError('已有有效 trial 不允许继续，不能重跑')
                continue
            first=max((a['index'] for a in attempts if a['seed']==seed),default=0)+1
            accepted=None
            for index in range(first,first+3):
                label=f'group_{seed}_attempt{index}'
                destination=out/label
                if destination.exists():
                    raise ValueError('已有未分类尝试，拒绝覆盖')
                command=[sys.executable,str(ROOT/'scripts/run_paper_c1_rerun.py'),'--family','group',
                    '--manifest',str(out/'run_settings.json'),'--out',str(destination),'--single-group-seed',str(seed)]
                if prerequisite:
                    command+=['--prerequisite',str(prerequisite)]
                save('RUNNING',seed=seed,attempt=index)
                print('START '+label,flush=True)
                with (out/(label+'.log')).open('x') as stream:
                    completed=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
                summaries=list(destination.glob('*/summary.json'))
                row=verify_summary(summaries[0],settings,seed) if len(summaries)==1 else None
                if row and row['infrastructure_valid']:
                    rows.append(row);accepted=row
                blocked=(destination/'BLOCKED.txt').read_text() if (destination/'BLOCKED.txt').exists() else ''
                infra=(row is not None and not row['infrastructure_valid'] and 'infrastructure_invalid' in blocked) or (
                    row is None and not has_episode_trajectory(destination) and any(marker in blocked for marker in ('SITL 超时','wait_for_px4_telemetry.py')))
                state='VALID' if accepted is not None and completed.returncode==0 else 'INFRASTRUCTURE_INVALID' if infra else 'NEEDS_DIAGNOSIS'
                attempts.append(dict(label=label,seed=seed,index=index,state=state,returncode=completed.returncode,summary=str(summaries[0]) if row else None))
                save('RUNNING',seed=seed)
                if state=='NEEDS_DIAGNOSIS':
                    raise RuntimeError('未分类错误；有效结果保留，不重复采样')
                if accepted is not None:
                    print('DONE '+str(seed),flush=True)
                    break
            if accepted is None:
                raise RuntimeError('连续三次基础设施失败，暂停诊断')
            decision=decision_for(accepted)
            if decision!='CONTINUE':
                save(decision,seed=seed)
                (out/'audit.json').write_text(json.dumps(dict(protocol_id=settings['protocol_id'],decision='NO_GO',rows=rows),ensure_ascii=False,indent=2))
                return
        (out/'audit.json').write_text(json.dumps(dict(protocol_id=settings['protocol_id'],decision='GO',rows=rows),ensure_ascii=False,indent=2))
        save('COMPLETED',decision='GO')
    except BaseException as exc:
        save('PAUSED_FOR_DIAGNOSIS',error=str(exc))
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',choices=CONFIGS,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--prerequisite',type=Path)
    parser.add_argument('--resume-diagnosis')
    args=parser.parse_args()
    validate_prerequisite(args.stage,args.prerequisite)
    if args.resume_diagnosis:
        if args.prerequisite and (args.out/'prerequisite.json').read_bytes()!=args.prerequisite.read_bytes():
            raise ValueError('前置证据变化')
        run(args.out,*load_resume(args.out,args.stage,args.resume_diagnosis),args.prerequisite)
        return
    settings=settings_for(args.stage)
    args.out.mkdir(parents=True,exist_ok=False)
    (args.out/'run_settings.json').write_text(json.dumps(settings,ensure_ascii=False,indent=2))
    (args.out/'source_hashes.json').write_text(json.dumps({str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()
        for base in ('swarm','marllib','scripts') for path in (ROOT/base).rglob('*.py')},indent=2))
    if args.prerequisite:
        (args.out/'prerequisite.json').write_bytes(args.prerequisite.read_bytes())
    run(args.out,settings,[],[],args.prerequisite)


if __name__=='__main__':
    main()
