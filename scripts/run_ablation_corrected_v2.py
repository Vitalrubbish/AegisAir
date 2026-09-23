"""正式重跑独立消融，不重复已完成的 C1 主比较。"""
import argparse
import hashlib
import json
import time
from pathlib import Path

from run_c1_corrected_v2 import ROOT, run_remaining
from c1_revision_policy import paired_decision


def load_resume(out):
    settings = json.loads((out/'run_settings.json').read_text())
    if settings != revised_settings(ROOT/'configs/c1_hocbf_v4_ablation_sealed_v1.json'):
        raise ValueError('运行参数变化，不允许混合续跑')
    state = json.loads((out/'status.json').read_text())
    if state['state'] != 'PAUSED_FOR_DIAGNOSIS':
        raise ValueError('只允许恢复已暂停并排查的运行')
    rows = json.loads((out/'results.json').read_text())
    expected = [(t['trial_id'],m,t['seed']) for t in settings['trials'] for m in t['condition_order']]
    if [(r['trial_id'],r['method'],r['seed']) for r in rows] != expected[:len(rows)]:
        raise ValueError('有效结果不是原计划前缀')
    attempts = state['attempts']
    for row in rows:
        valid = [a for a in attempts if a['state']=='VALID' and a['label'].startswith(f"{row['trial_id']}_{row['method']}_attempt")]
        if len(valid)!=1:
            raise ValueError('有效结果归属不唯一')
        p=Path(valid[0]['summary'])
        if json.loads(p.read_text())['trials'][0]!=row or hashlib.sha256((p.parent/row['trajectory']).read_bytes()).hexdigest()!=row['trajectory_sha256']:
            raise ValueError('原摘要或轨迹校验失败')
    for trial in settings['trials']:
        pair=[r for r in rows if r['trial_id']==trial['trial_id']]
        if len(pair)==len(trial['condition_order']) and paired_decision(pair,trial['condition_order'])!='CONTINUE':
            raise ValueError('已有完整配对不允许继续')
    old_hashes=json.loads((out/'source_hashes.json').read_text())
    allowed={'scripts/run_c1_corrected_v2.py','scripts/run_ablation_corrected_v2.py',
             'scripts/run_paper_c1_rerun.py'}
    changed=[p for p,h in old_hashes.items() if hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=h]
    if set(changed)-allowed:
        raise ValueError(f'存在控制实现或参数变化：{changed}')
    with (out/f'infrastructure_resume_{time.time_ns()}.json').open('x') as stream:
        json.dump(dict(previous_status=state,changed_sources=changed,
            note='用户授权排查后续跑。保留所有无效尝试，从缺失条件的新 attempt 编号开始；每批最多三次，不改安全阈值。',
            source_hashes={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest()
                for base in ('swarm','marllib','scripts') for f in (ROOT/base).rglob('*.py')}),stream,ensure_ascii=False,indent=2)
    return settings,rows,attempts


def revised_settings(parent):
    settings = json.loads(parent.read_bytes())
    old_gate = settings.pop('safety_gate')
    settings.update(
        protocol_id='aegisair-c1-corrected-ablation-v2',
        phase='修 bug 后正式消融重跑；规则已修订，不称为新盲测',
        previous_settings_sha256=hashlib.sha256(parent.read_bytes()).hexdigest(),
        superseded_safety_gate=old_gate,
        stopping_rule='完整四条件配对后，仅完整 V4 碰撞、rho<=0、未完成或任一条件安全链待核查时暂停后续 seed。V3、Reactive、Reserve-only 失败作为结局保留，不自动停止全组。基础设施同 seed 同条件最多三次尝试，全部留档；未知故障暂停诊断。',
        previous_result='旧消融部分运行保留在 paper_full_rerun_20260921_441c8f1/03_ablation，不混入本批。C1 主比较 80/80 已结束，本入口不重跑它。',
    )
    settings.pop('output_root', None)
    return settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--resume-after-diagnosis', action='store_true')
    args = parser.parse_args()
    if args.resume_after_diagnosis:
        settings,rows,attempts=load_resume(args.out)
        run_remaining(args.out,settings,rows,attempts,0)
        return
    parent = ROOT/'configs/c1_hocbf_v4_ablation_sealed_v1.json'
    settings = revised_settings(parent)
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out/'run_settings.json').write_text(json.dumps(settings, ensure_ascii=False, indent=2)+'\n')
    (args.out/'source_hashes.json').write_text(json.dumps({
        str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest()
        for base in ('swarm','marllib','scripts') for f in (ROOT/base).rglob('*.py')}, indent=2))
    run_remaining(args.out, settings, [], [], 0)


if __name__ == '__main__':
    main()
