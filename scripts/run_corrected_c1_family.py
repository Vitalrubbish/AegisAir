"""后续双机比较分组入口：原数值配置不变，基线失败不触发全方法门。"""
import argparse
import hashlib
import json
from pathlib import Path
from run_c1_corrected_v2 import ROOT, run_remaining

CONFIGS={
    'c2':'c2_v4_execution_bridge_v1.json',
    'ood':'c1_hocbf_v4_px4_postfreeze_ood_v1.json',
    'external_unmatched':'c1_external_pcbf_sealed_v1.json',
    'certificate':'c1_hocbf_v4_certificate_calibration_v1.json',
}


def settings_for(experiment):
    parent=ROOT/'configs'/CONFIGS[experiment]
    settings=json.loads(parent.read_text())
    for key in ('stopping_rule','safety_gate','go_criteria'):
        if key in settings:
            settings['superseded_'+key]=settings.pop(key)
    settings.update(protocol_id='aegisair-corrected-c1-family-v1',
        experiment=experiment,phase='修正版正式运行；不冒称新盲测',
        previous_settings_sha256=hashlib.sha256(parent.read_bytes()).hexdigest(),
        stopping_rule='完整配对后判断完整 V4 的碰撞、非正 rho、未完成及所有方法安全链疑点。基线失败保留，不触发全方法安全门；OOD 的主方法失败只停止当前场景。基础设施最多三次同条件尝试，之后排查。')
    settings.pop('output_root',None)
    if experiment=='ood':
        settings['injected_hold_audit']='指令保持按原 seed/概率重建序列，并逐步核对上一条发布速度；预设偏差单列，不作为未授权改写。非预设偏差/审计未知仍暂停，V4 真实失败规则不变。'
    return settings


def run_group(out,settings):
    out.mkdir(parents=True,exist_ok=False)
    (out/'run_settings.json').write_text(json.dumps(settings,ensure_ascii=False,indent=2)+'\n')
    (out/'source_hashes.json').write_text(json.dumps({str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest()
        for base in ('swarm','marllib','scripts') for f in (ROOT/base).rglob('*.py')},indent=2))
    from corrected_ood_policy import decision_for
    run_remaining(out,settings,[],[],0,
        decision_fn=decision_for(out,settings) if settings.get('experiment')=='ood' else None)
    return json.loads((out/'status.json').read_text())


def existing_group(out, settings, terminal_states):
    if json.loads((out/'run_settings.json').read_text()) != settings:
        raise ValueError('已有场景的配置变化，拒绝混合续跑')
    state=json.loads((out/'status.json').read_text())
    if state['state'] not in terminal_states:
        raise ValueError(f'场景仍需排查或正在运行，不跳过：{out}')
    hashes=json.loads((out/'source_hashes.json').read_text())
    for name,digest in hashes.items():
        if name.startswith(('swarm/','marllib/')) and hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:
            raise ValueError('实验实现已变化，不能把旧场景跳过当成同批完成')
    return state


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment',choices=CONFIGS,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--resume-scenarios',action='store_true',help='仅 OOD；当前暂停场景须先完成诊断续跑')
    args=parser.parse_args()
    settings=settings_for(args.experiment)
    if args.experiment!='ood':
        if args.resume_scenarios:
            parser.error('非分场景组使用 resume_corrected_campaign.py 诊断续跑')
        run_group(args.out,settings)
        return
    if args.resume_scenarios:
        if json.loads((args.out/'run_settings.json').read_text())!=settings:
            raise ValueError('完整 OOD 配置变化')
    else:
        args.out.mkdir(parents=True,exist_ok=False)
        (args.out/'run_settings.json').write_text(json.dumps(settings,ensure_ascii=False,indent=2))
    states=[]
    for scenario in dict.fromkeys(t['scenario_id'] for t in settings['trials']):
        group=dict(settings,trials=[t for t in settings['trials'] if t['scenario_id']==scenario])
        destination=args.out/scenario
        state=(existing_group(destination,group,{'COMPLETED','STOP_PRIMARY_FAILURE'})
               if args.resume_scenarios and destination.exists() else run_group(destination,group))
        states.append(dict(scenario=scenario,state=state['state'],valid_conditions=state['valid_conditions']))
        (args.out/'scenario_status.json').write_text(json.dumps(states,ensure_ascii=False,indent=2))
        if state['state'] not in ('COMPLETED','STOP_PRIMARY_FAILURE'):
            raise RuntimeError('非场景算法结局，暂停排查基础设施或安全链')
    (args.out/'status.json').write_text(json.dumps(dict(
        state='COMPLETED' if all(item['state']=='COMPLETED' for item in states) else 'PARTIAL_SCENARIO_STOP',
        scenarios=states),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
