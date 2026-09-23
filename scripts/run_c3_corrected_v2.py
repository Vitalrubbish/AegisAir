"""原 C3 完整配对运行；基础设施部分失败只补缺失条件，保留已有效记录。"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from run_c1_corrected_v2 import ROOT, has_episode_trajectory


def settings_for():
    parent=ROOT/'configs/c3_closed_loop_v3_hocbf_v4_validation_v1.json'
    settings=json.loads(parent.read_text())
    settings.update(revision_id='c3-corrected-v2', phase='修正版正式 C3；不冒称新盲测',
        previous_settings_sha256=hashlib.sha256(parent.read_bytes()).hexdigest(),
        retry_rule='首次保持原同栈 reset 的 R0/R1 配对及原顺序；仅基础设施无效条件同 seed 补跑，新建栈。已有效条件不重跑，所有尝试与初始化上下文保留。每批最多三次，之后须排查。')
    return settings


def paired_decision(rows, audits, change_step):
    if len(rows)!=2 or {row['condition'] for row in rows}!={'R0','R1'}:
        raise ValueError('C3 配对不完整或重复')
    if any(not row['infrastructure_valid'] for row in rows):
        return 'RETRY_INFRASTRUCTURE'
    if any(audit['safety_bypass_count'] or audit['revoked_authority_failures'] for audit in audits):
        return 'STOP_SAFETY_CHAIN'
    if any(row['published_command_mismatch_count'] or row['published_command_constraint_unknown_count'] for row in rows):
        return 'STOP_SAFETY_CHAIN'
    if any(row['collision'] or row['min_rho'] is None or not math.isfinite(row['min_rho']) or row['min_rho']<=0 for row in rows):
        return 'STOP_C3_SAFETY_DIAGNOSIS'
    r0=next(row for row in rows if row['condition']=='R0')
    r1=next(row for row in rows if row['condition']=='R1')
    counters=r1.get('counters') or {}
    if (r0['critical_reached'] or not r1['critical_reached'] or
            counters.get('mission_changes')!=1 or counters.get('plans_committed',0)<1 or
            r1.get('recovery_step') is None or r1['recovery_step']<change_step):
        return 'STOP_C3_MECHANISM_DIAGNOSIS'
    return 'CONTINUE'


def audit_trace(summary, row, settings):
    path=summary.parent/row['trajectory']
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=row['trajectory_sha256']:
        raise ValueError('C3 轨迹哈希不一致')
    records=[json.loads(line) for line in raw.splitlines()]
    if min(record['min_rho'] for record in records)!=row['min_rho']:
        raise ValueError('C3 摘要最低裕度不一致')
    bypass=sum(bool(drone['ra_bypass']) for record in records for drone in record['drones'].values())
    revoked=0
    for record in records:
        if record['step']<settings['change_step']:
            continue
        drone=record['drones'][str(settings['failed_drone'])]
        velocity=drone['published_velocity']
        revoked+=bool(drone['control_authority'] or velocity is None or any(abs(value)>1e-9 for value in velocity))
    return dict(trajectory_sha256=row['trajectory_sha256'], safety_bypass_count=bypass,
                revoked_authority_failures=revoked, cycles=len(records))


def load_resume(out, diagnosis):
    if not diagnosis.strip():
        raise ValueError('需填写已完成的诊断，不自动反复解锁')
    state=json.loads((out/'status.json').read_text())
    if state['state']!='PAUSED_FOR_DIAGNOSIS':
        raise ValueError('仅恢复基础设施暂停，不覆盖机制或安全结局')
    settings=json.loads((out/'run_settings.json').read_text())
    if settings!=settings_for():
        raise ValueError('原定参数变化，不能混合续跑')
    rows=json.loads((out/'results.json').read_text())
    attempts=state['attempts']
    if not attempts or any(attempt['state'] not in {'VALID','INFRASTRUCTURE_INVALID'} for attempt in attempts):
        raise ValueError('存在未分类错误，应先逐条排查')
    hashes=json.loads((out/'source_hashes.json').read_text())
    changed=[name for name,digest in hashes.items() if not (ROOT/name).exists() or
             hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest]
    if any(name.startswith(('swarm/','marllib/')) for name in changed):
        raise ValueError('实验实现变化，禁止混合续跑')
    for attempt in attempts:
        folder=out/attempt['label']
        if json.loads((folder/'manifest.json').read_text())!=settings:
            raise ValueError('原始完整配置不一致')
    for name,digest in json.loads((out/attempts[-1]['label']/'runtime_hashes.json').read_text()).items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:
            raise ValueError('外部运行时变化')
    sources=state['condition_sources']
    audits=state['trajectory_audits']
    expected={(trial['trial_id'],condition,trial['seed']) for trial in settings['trials'] for condition in trial['condition_order']}
    identities=[(row['trial_id'],row['condition'],row['seed']) for row in rows]
    if len(set(identities))!=len(identities) or not set(identities)<=expected:
        raise ValueError('有效条件重复或身份不匹配')
    for row in rows:
        key=row['trial_id']+'/'+row['condition']
        summary=Path(sources[key])
        if row not in json.loads(summary.read_text())['trials'] or not row['infrastructure_valid']:
            raise ValueError('有效结果与原始摘要不一致')
        if audit_trace(summary,row,settings)!=audits[key]:
            raise ValueError('轨迹审计变化')
    for trial in settings['trials']:
        pair=[row for row in rows if row['trial_id']==trial['trial_id']]
        if len(pair)==2 and paired_decision(pair,[audits[trial['trial_id']+'/'+row['condition']] for row in pair],settings['change_step'])!='CONTINUE':
            raise ValueError('已完成配对存在安全/机制问题，不作为基础设施恢复')
    with (out/f'infrastructure_resume_{time.time_ns()}.json').open('x') as stream:
        json.dump(dict(previous_status=state,diagnosis=diagnosis,changed_sources=changed,
            note='保留全部有效条件及无效尝试；不改变原参数。'),stream,ensure_ascii=False,indent=2)
    return settings,rows,attempts,sources,audits


def run(out,settings,rows,attempts,sources,audits):
    order={(trial['trial_id'],condition):i for i,(trial,condition) in enumerate(
        (trial,condition) for trial in settings['trials'] for condition in trial['condition_order'])}
    def save(state,**extra):
        rows.sort(key=lambda row:order[(row['trial_id'],row['condition'])])
        (out/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
        (out/'status.json').write_text(json.dumps(dict(state=state,updated_unix_s=time.time(),
            valid_conditions=len(rows),attempts=attempts,condition_sources=sources,trajectory_audits=audits,**extra),ensure_ascii=False,indent=2))
    try:
        for trial in settings['trials']:
            missing=[condition for condition in trial['condition_order'] if not any(
                row['trial_id']==trial['trial_id'] and row['condition']==condition for row in rows)]
            first=max((attempt['index'] for attempt in attempts if attempt['trial_id']==trial['trial_id']),default=0)+1
            for index in range(first,first+3):
                if not missing:
                    break
                label=f"{trial['trial_id']}_attempt{index}"
                destination=out/label
                if destination.exists():
                    raise ValueError('存在未归类尝试，拒绝覆盖')
                command=[sys.executable,str(ROOT/'scripts/run_paper_c1_rerun.py'),
                    '--manifest',str(out/'run_settings.json'),'--out',str(destination),
                    '--family','c3','--single-trial',trial['trial_id']]
                if len(missing)==1:
                    command+=['--single-method',missing[0]]
                save('RUNNING',trial=trial['trial_id'],conditions=missing,attempt=index)
                print('START '+label+' '+','.join(missing),flush=True)
                with (out/(label+'.log')).open('x') as stream:
                    completed=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
                summaries=list(destination.glob('*/summary.json'))
                found=json.loads(summaries[0].read_text())['trials'] if len(summaries)==1 else []
                if found and [(row['trial_id'],row['condition'],row['seed']) for row in found]!=[(trial['trial_id'],condition,trial['seed']) for condition in missing]:
                    raise ValueError('C3 实测条件与缺失条件不一致')
                accepted=[]
                for row in found:
                    if not row['infrastructure_valid']:
                        continue
                    key=row['trial_id']+'/'+row['condition']
                    audits[key]=audit_trace(summaries[0],row,settings)
                    sources[key]=str(summaries[0])
                    rows.append(row)
                    accepted.append(row['condition'])
                missing=[condition for condition in missing if condition not in accepted]
                blocked=(destination/'BLOCKED.txt').read_text() if (destination/'BLOCKED.txt').exists() else ''
                known_infra=(bool(found) and any(not row['infrastructure_valid'] for row in found)
                    and 'infrastructure_invalid' in blocked) or (not found and not has_episode_trajectory(destination)
                    and any(marker in blocked for marker in ('SITL 超时','wait_for_px4_telemetry.py')))
                attempt=dict(label=label,trial_id=trial['trial_id'],index=index,returncode=completed.returncode,
                    accepted=accepted,state='VALID' if not missing and completed.returncode==0 else
                    'INFRASTRUCTURE_INVALID' if known_infra else 'NEEDS_DIAGNOSIS')
                attempts.append(attempt)
                save('RUNNING',trial=trial['trial_id'],conditions=missing)
                if attempt['state']=='NEEDS_DIAGNOSIS':
                    raise RuntimeError('未分类错误；有效测量已保存，不重复采样，先排查')
                print('ACCEPTED '+trial['trial_id']+' '+','.join(accepted),flush=True)
            if missing:
                raise RuntimeError('连续三次基础设施失败，需排查；已有效条件不重跑')
            pair=[row for row in rows if row['trial_id']==trial['trial_id']]
            decision=paired_decision(pair,[audits[trial['trial_id']+'/'+row['condition']] for row in pair],settings['change_step'])
            save(decision,trial=trial['trial_id'])
            if decision!='CONTINUE':
                return
        save('COMPLETED',paired_trials=len(settings['trials']))
    except BaseException as exc:
        save('PAUSED_FOR_DIAGNOSIS',error=str(exc))
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--resume-diagnosis',help='仅经人工诊断后恢复基础设施暂停')
    args=parser.parse_args()
    if args.resume_diagnosis:
        run(args.out,*load_resume(args.out,args.resume_diagnosis))
        return
    settings=settings_for()
    args.out.mkdir(parents=True,exist_ok=False)
    (args.out/'run_settings.json').write_text(json.dumps(settings,ensure_ascii=False,indent=2))
    (args.out/'source_hashes.json').write_text(json.dumps({str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()
        for base in ('swarm','marllib','scripts') for path in (ROOT/base).rglob('*.py')},indent=2))
    run(args.out,settings,[],[],{}, {})


if __name__=='__main__':
    main()
