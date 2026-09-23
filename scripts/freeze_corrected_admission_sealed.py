"""当前动态资格组通过后，沿用原 20 案例冻结修正版配置，不借用历史父 GO。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
from analyze_corrected_admission import analyze_root
from run_admission_corrected_v2 import ROOT, settings_for, validate_prerequisite


def build_settings(qualification_root, *, revision='v4'):
    if revision not in {'v4','v5','v6'}:
        raise ValueError('接纳修订版未知')
    validate_prerequisite('sealed_v6' if revision=='v6' else 'sealed_v5' if revision=='v5' else 'sealed', qualification_root/'audit.json')
    report = analyze_root(qualification_root)
    if not report['complete'] or report['decision'] != 'GO':
        raise ValueError('本轮动态资格组未完整通过')
    old_path = ROOT/'configs/c_recoverability_admission_sealed_v1.json'
    old = json.loads(old_path.read_text())
    qualified = settings_for('qualification_v6' if revision=='v6' else 'qualification_v5' if revision=='v5' else 'qualification')
    current = copy.deepcopy(old)
    current['historical_parent_qualification_sha256'] = current.pop('parent_qualification_sha256')
    current.update(
        protocol_id=f'aegisair-c-recoverability-admission-sealed-corrected-{revision}',
        phase='修 bug 后正式重跑原二十案例；不是新增独立盲测',
        implementation_version=qualified['implementation_version'],
        adapter_mqtt_publish_mode=qualified['adapter_mqtt_publish_mode'],
        recoverability_admission=copy.deepcopy(qualified['recoverability_admission']),
        ra_config=copy.deepcopy(qualified['ra_config']),
        parent_qualification_root=str(qualification_root.resolve()),
        parent_qualification_sha256=hashlib.sha256((qualification_root/'run_settings.json').read_bytes()).hexdigest(),
        parent_qualification_audit_sha256=hashlib.sha256((qualification_root/'audit.json').read_bytes()).hexdigest(),
        original_case_source_sha256=hashlib.sha256(old_path.read_bytes()).hexdigest(),
        corrected_scope=f'沿用原几何、预期决策、seed、条件顺序、样本量与时域；使用本轮 {revision} 动态模型，不混用旧静态障碍采样参数。')
    if revision in {'v5','v6'}:
        current['revision_id']='admission-corrected-'+revision
        current['stabilization_revision']=copy.deepcopy(qualified['stabilization_revision'])
        current['stabilization_revision_sha256']=qualified['stabilization_revision_sha256']
    if revision=='v6':
        current['arc_revision']=copy.deepcopy(qualified['arc_revision'])
        current['arc_revision_sha256']=qualified['arc_revision_sha256']
    for key in ('rate_hz','max_steps','goal_epsilon','drone_ids','failed_drone','mission_change',
                'change_step','velocity_command_mode','tau_command_s','conditions','ra_config'):
        if current[key] != qualified[key]:
            raise ValueError('资格组与原测试运行参数不同，需明确修订，不能静默拼接：'+key)
    if current['geometries'] != old['geometries'] or current['trials'] != old['trials']:
        raise ValueError('原二十案例被改变')
    return current


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qualification', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--revision', choices=['v4','v5','v6'], default='v4')
    args = parser.parse_args()
    result = build_settings(args.qualification, revision=args.revision)
    with args.out.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(dict(protocol_id=result['protocol_id'], trials=len(result['trials']),
                          parent_qualification_sha256=result['parent_qualification_sha256'])))


if __name__ == '__main__':
    main()
