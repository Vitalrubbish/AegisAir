"""动态接纳修正版：保留原数值与门，只重试基础设施无效条件。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from run_c1_corrected_v2 import ROOT,has_episode_trajectory
from marllib.analyze_c_recoverability_admission_calibration import analyze,_common_integrity
from marllib.run_c_recoverability_admission_gazebo import _trajectory_audit

CONFIGS={
    'calibration':'c_recoverability_admission_calibration_v4.json',
    'qualification':'c_recoverability_admission_qualification_v4.json',
    'comparison':'admission_comparison_development_v1.json',
}
CONFIGS_V5={
    'calibration_v5':'c_recoverability_admission_calibration_v4.json',
    'qualification_v5':'c_recoverability_admission_qualification_v4.json',
    'comparison_v5':'admission_comparison_development_v1.json',
    'sealed_v5':'c_recoverability_admission_sealed_corrected_v5.json',
}
CONFIGS_V6={
    'calibration_v6':'c_recoverability_admission_calibration_v4.json',
    'qualification_v6':'c_recoverability_admission_qualification_v4.json',
    'sealed_v6':'c_recoverability_admission_sealed_corrected_v6.json',
    'comparison_v6':'admission_comparison_development_v1.json',
}


def settings_for(stage):
    parent=ROOT/'configs'/(CONFIGS|CONFIGS_V5|CONFIGS_V6)[stage]
    settings=json.loads(parent.read_text())
    if stage in {'sealed_v5','sealed_v6'}:
        expected_revision = 'admission-corrected-v6' if stage=='sealed_v6' else 'admission-corrected-v5'
        if settings.get('revision_id')!=expected_revision:
            raise ValueError('正式组不是冻结的对应版本配置')
        return settings
    if stage in CONFIGS_V5 or stage in CONFIGS_V6:
        overlay_path=ROOT/'configs/admission_stabilize_reevaluate_v5.json'
        overlay=json.loads(overlay_path.read_text())
        settings['protocol_id']=settings['protocol_id'].replace('-v4','-v5')
        if stage in {'comparison_v5','comparison_v6'}:
            settings['protocol_id']='aegisair-admission-comparison-development-v5'
        if stage in CONFIGS_V6:
            settings['protocol_id']=settings['protocol_id'].replace('-v5','-v6')
        settings['implementation_version']=('dynamic_admission_v6_arc_candidates_probe'
            if stage in CONFIGS_V6 else 'dynamic_admission_v5_stabilize_reevaluate')
        settings['recoverability_admission'].update(
            stabilization_wait_s=overlay['stabilization_wait_s'],
            stabilization_speed_margin_mps=overlay['stabilization_speed_margin_mps'],
            stabilization_consecutive_samples=overlay['stabilization_consecutive_samples'])
        settings['stabilization_revision']=overlay
        settings['stabilization_revision_sha256']=hashlib.sha256(overlay_path.read_bytes()).hexdigest()
        if stage in CONFIGS_V6:
            arc_path=ROOT/'configs/admission_arc_development_v6.json'
            arc=json.loads(arc_path.read_text())
            settings['recoverability_admission'].update(
                arc_extra_m=arc['arc_extra_m'], arc_segments=arc['arc_segments'])
            settings['arc_revision']=arc
            settings['arc_revision_sha256']=hashlib.sha256(arc_path.read_bytes()).hexdigest()
        if stage=='qualification_v5':
            settings['parent_calibration_manifest']='generated:admission-corrected-v5-calibration'
            settings['parent_calibration_manifest_sha256']=hashlib.sha256(
                json.dumps(settings_for('calibration_v5'),sort_keys=True).encode()).hexdigest()
        if stage=='qualification_v6':
            settings['parent_calibration_manifest']='generated:admission-corrected-v6-calibration'
            settings['parent_calibration_manifest_sha256']=hashlib.sha256(
                json.dumps(settings_for('calibration_v6'),sort_keys=True).encode()).hexdigest()
        settings.update(revision_id='admission-corrected-v6' if stage in CONFIGS_V6 else 'admission-corrected-v5',
            corrected_phase=('独立 v6：多航点绕障候选；从开发首例重跑并保留 v5 有效拒绝'
                if stage in CONFIGS_V6 else '独立新版本：速度超限后限时稳定再评价；旧有效拒绝保留'),
            previous_settings_sha256=hashlib.sha256(parent.read_bytes()).hexdigest(),
            retry_rule=(arc['stop_rule'] if stage in CONFIGS_V6 else overlay['stop_rule']))
    else:
        settings.update(revision_id='admission-corrected-v2',
            corrected_phase='修 bug 后正式重跑；不冒称新盲测',
            previous_settings_sha256=hashlib.sha256(parent.read_bytes()).hexdigest(),
            retry_rule='完整配对后按原 admission/hold 门判断；基线有效失败保留。仅基础设施无效同 seed 同条件最多重试三次，之后诊断。')
    return settings


def validate_prerequisite(stage, prerequisite):
    if stage in {'calibration','calibration_v5','calibration_v6'}:
        if prerequisite is not None:
            raise ValueError('calibration 不使用历史父结果')
        return
    if prerequisite is None:
        raise ValueError('缺少本次前置 GO')
    prior=json.loads(prerequisite.read_text())
    parent_stage=('calibration_v6' if stage=='qualification_v6' else
                  'calibration_v5' if stage=='qualification_v5' else
                  'qualification_v6' if stage in {'sealed_v6','comparison_v6'} else
                  'qualification_v5' if stage in {'comparison_v5','sealed_v5'} else
                  'calibration' if stage=='qualification' else 'qualification')
    if prior.get('decision')!='GO' or prior.get('protocol_id')!=settings_for(parent_stage)['protocol_id']:
        raise ValueError('本次正确版本的前置门未通过')
    parent_root=prerequisite.parent
    if (json.loads((parent_root/'status.json').read_text())['state']!='COMPLETED' or
        json.loads((parent_root/'run_settings.json').read_text())!=settings_for(parent_stage)):
        raise ValueError('父结果不是本次修正版完成组')


def verify_trace(summary,row,settings):
    path=summary.parent/row['trajectory']
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=row['trajectory_sha256']:
        raise ValueError('接纳轨迹哈希不一致')
    records=[json.loads(line) for line in raw.splitlines()]
    if min(record['min_rho'] for record in records)!=row['min_rho']:
        raise ValueError('接纳最低裕度不一致')
    geometry=settings['geometries'][row['geometry_id']]
    audit=_trajectory_audit(path,failed_drone=settings['failed_drone'],
        healthy_drone=next(drone for drone in settings['drone_ids'] if drone!=settings['failed_drone']),
        change_step=settings['change_step'],critical_goal=tuple(geometry['critical_goal']),goal_epsilon=settings['goal_epsilon'])
    if audit!=row['trajectory_audit'] or audit['post_failure_critical_reached_by_healthy']!=row['post_failure_critical_reached']:
        raise ValueError('接纳轨迹审计不一致')


def paired_decision(settings,rows):
    # 比较组有额外几何基线；它不改变动态接纳与 HOLD 的原门。
    if any(not row['infrastructure_valid'] for row in rows):
        return 'RETRY_INFRASTRUCTURE'
    if any(not chain_integrity(row) for row in rows):
        return 'STOP_INTEGRITY_DIAGNOSIS'
    report=analyze(settings,rows)
    if any(not check['passed'] for key in ('admission_checks','hold_checks') for check in report[key]):
        return 'STOP_ADMISSION_DIAGNOSIS'
    return 'CONTINUE'


def chain_integrity(row):
    # 基线超时、QP 不可行、发布后约束不满足是比较结局，不当成权限链失效。
    audit=row['trajectory_audit']
    return bool(row['infrastructure_valid'] and row['safety_bypass_count']==0 and
        audit['ra_bypass_count']==0 and audit['failed_authority_revoked_all_steps'] and
        audit['failed_horizontal_command_zero_all_steps'] and
        row['published_command_mismatch_count']==0 and row['published_command_constraint_unknown_count']==0)


def pre_episode_reset_failure(out, label):
    if has_episode_trajectory(out):
        return False
    runner=out/(label.replace('_attempt'+label.rsplit('_attempt',1)[-1],'')+'_logs')/'runner.log'
    return runner.exists() and 'PX4 velocity reset failed to settle within 45s' in runner.read_text(errors='replace')


def final_audit(settings,rows):
    original_conditions=['IMMEDIATE_COMMIT_RA','RECOVERABILITY_ADMISSION_RA','RA_ONLY_HOLD']
    original=[row for row in rows if row['condition'] in original_conditions]
    result=analyze(dict(settings,conditions=original_conditions),original)
    result['all_conditions']=len(rows)
    result['comparator_integrity']=[dict(trial_id=row['trial_id'],condition=row['condition'],passed=chain_integrity(row),
        original_common_integrity_diagnostic=_common_integrity(row)) for row in rows]
    if not all(row['passed'] for row in result['comparator_integrity']):
        result['decision']='NO_GO'
    return result


def load_resume(out,stage,diagnosis):
    if not diagnosis.strip():
        raise ValueError('必须填写实际诊断')
    state=json.loads((out/'status.json').read_text())
    if state['state']!='PAUSED_FOR_DIAGNOSIS':
        raise ValueError('只恢复基础设施暂停')
    settings=json.loads((out/'run_settings.json').read_text())
    if settings!=settings_for(stage):
        raise ValueError('配置变化，不能混合续跑')
    rows=json.loads((out/'results.json').read_text())
    attempts=state['attempts']
    reclassified=[]
    for attempt in attempts:
        if attempt['state']=='NEEDS_DIAGNOSIS' and attempt.get('summary') is None and pre_episode_reset_failure(out/attempt['label'],attempt['label']):
            reclassified.append(attempt['label'])
            attempt['state']='INFRASTRUCTURE_INVALID'
            attempt['diagnostic_reason']='pre_episode_px4_velocity_reset_timeout_no_trajectory'
    if not attempts or any(a['state'] not in {'VALID','INFRASTRUCTURE_INVALID'} for a in attempts):
        raise ValueError('存在未分类错误，不能解锁')
    expected=[(trial['trial_id'],condition,trial['seed']) for trial in settings['trials'] for condition in trial['condition_order']]
    if [(row['trial_id'],row['condition'],row['seed']) for row in rows]!=expected[:len(rows)]:
        raise ValueError('已有结果不是有效前缀')
    old=json.loads((out/'source_hashes.json').read_text())
    changed=[name for name,digest in old.items() if not (ROOT/name).exists() or hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest]
    if any(name.startswith(('swarm/','marllib/')) for name in changed):
        raise ValueError('实验实现变化，不能混合续跑')
    for attempt in attempts:
        if json.loads((out/attempt['label']/'manifest.json').read_text())!=settings:
            raise ValueError('尝试参数与冻结记录不一致')
    for name,digest in json.loads((out/attempts[-1]['label']/'runtime_hashes.json').read_text()).items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:
            raise ValueError('外部运行时变化')
    for row in rows:
        matching=[a for a in attempts if a['state']=='VALID' and a['label'].startswith(row['trial_id']+'_'+row['condition']+'_attempt')]
        if len(matching)!=1:
            raise ValueError('有效结果归属不唯一')
        summary=Path(matching[0]['summary'])
        if json.loads(summary.read_text())['trials']!=[row]:
            raise ValueError('原始摘要变化')
        verify_trace(summary,row,settings)
    for trial in settings['trials']:
        pair=[row for row in rows if row['trial_id']==trial['trial_id']]
        if len(pair)==len(trial['condition_order']) and paired_decision(settings,pair)!='CONTINUE':
            raise ValueError('完整配对有有效失败，不能作为基础设施继续')
    with (out/f'infrastructure_resume_{time.time_ns()}.json').open('x') as stream:
        json.dump(dict(previous_status=state,diagnosis=diagnosis,changed_sources=changed,reclassified_pre_episode_attempts=reclassified),stream,ensure_ascii=False,indent=2)
    return settings,rows,attempts


def run(out,settings,rows,attempts,prerequisite):
    def save(state,**extra):
        (out/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
        (out/'status.json').write_text(json.dumps(dict(state=state,updated_unix_s=time.time(),valid_conditions=len(rows),attempts=attempts,**extra),ensure_ascii=False,indent=2))
    try:
        for trial in settings['trials']:
            for condition in trial['condition_order']:
                if any(row['trial_id']==trial['trial_id'] and row['condition']==condition for row in rows):
                    continue
                prefix=trial['trial_id']+'_'+condition+'_attempt'
                first=max((int(a['label'][len(prefix):]) for a in attempts if a['label'].startswith(prefix)),default=0)+1
                accepted=False
                for index in range(first,first+3):
                    label=prefix+str(index)
                    destination=out/label
                    if destination.exists():
                        raise ValueError('已有未分类输出，不覆盖')
                    command=[sys.executable,str(ROOT/'scripts/run_paper_c1_rerun.py'),
                        '--manifest',str(out/'run_settings.json'),'--out',str(destination),'--family','admission',
                        '--single-trial',trial['trial_id'],'--single-method',condition]
                    if prerequisite:
                        command+=['--prerequisite',str(prerequisite)]
                    save('RUNNING',trial=trial['trial_id'],condition=condition,attempt=index)
                    print('START '+label,flush=True)
                    with (out/(label+'.log')).open('x') as stream:
                        completed=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
                    summaries=list(destination.glob('*/summary.json'))
                    found=json.loads(summaries[0].read_text())['trials'] if len(summaries)==1 else []
                    if found and (len(found)!=1 or (found[0]['trial_id'],found[0]['condition'],found[0]['seed'])!=(trial['trial_id'],condition,trial['seed'])):
                        raise ValueError('接纳条件身份不匹配')
                    if found and found[0]['infrastructure_valid']:
                        verify_trace(summaries[0],found[0],settings)
                        rows.append(found[0])
                        accepted=True
                    blocked=(destination/'BLOCKED.txt').read_text() if (destination/'BLOCKED.txt').exists() else ''
                    infra=(bool(found) and not found[0]['infrastructure_valid'] and 'infrastructure_invalid' in blocked) or (
                        not found and not has_episode_trajectory(destination) and any(marker in blocked for marker in ('SITL 超时','wait_for_px4_telemetry.py')))
                    infra=infra or (not found and pre_episode_reset_failure(destination,label))
                    state='VALID' if accepted and completed.returncode==0 else 'INFRASTRUCTURE_INVALID' if infra else 'NEEDS_DIAGNOSIS'
                    attempts.append(dict(label=label,state=state,returncode=completed.returncode,summary=str(summaries[0]) if found else None))
                    save('RUNNING',trial=trial['trial_id'],condition=condition)
                    if state=='NEEDS_DIAGNOSIS':
                        raise RuntimeError('未分类错误；已有效数据保留，不重复采样')
                    if accepted:
                        print('DONE '+trial['trial_id']+' '+condition,flush=True)
                        break
                if not accepted:
                    raise RuntimeError('连续三次基础设施无效，暂停诊断')
            pair=[row for row in rows if row['trial_id']==trial['trial_id']]
            if [row['condition'] for row in pair]!=trial['condition_order']:
                raise ValueError('接纳配对不完整')
            decision=paired_decision(settings,pair)
            (out/'audit.json').write_text(json.dumps(final_audit(settings,rows),ensure_ascii=False,indent=2))
            if decision!='CONTINUE':
                save(decision,trial=trial['trial_id'])
                return
        audit=final_audit(settings,rows)
        save('COMPLETED',decision=audit['decision'])
    except BaseException as exc:
        save('PAUSED_FOR_DIAGNOSIS',error=str(exc))
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',choices=tuple(CONFIGS|CONFIGS_V5|CONFIGS_V6),required=True)
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
