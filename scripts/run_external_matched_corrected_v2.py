"""按原数值条件运行修正版外部 PCBF 匹配比较，保留基线失败。"""
import argparse
import hashlib
import json
from pathlib import Path
from run_c1_corrected_v2 import ROOT, run_remaining


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--resume-after-pcbf-audit',action='store_true')
    args=parser.parse_args()
    if args.resume_after_pcbf_audit:
        from pcbf_audit_recovery import resume
        settings,rows,attempts,completed=resume(args.out,ROOT)
        run_remaining(args.out,settings,rows,attempts,completed)
        return
    parent=ROOT/'configs/c1_external_pcbf_buffer_matched_fresh_v1.json'
    settings=json.loads(parent.read_bytes())
    for key in ('safety_gate','stopping_rule','go_criteria'):
        if key in settings:
            settings['superseded_'+key]=settings.pop(key)
    settings.update(protocol_id='aegisair-c1-corrected-external-matched-v2',
        phase='修 bug 后正式重跑，不称为新盲测',
        previous_settings_sha256=hashlib.sha256(parent.read_bytes()).hexdigest(),
        stopping_rule='完整配对后仅完整 V4 的碰撞、rho<=0、未完成或安全链问题暂停；其他方法失败保留，不停止主方法。基础设施失败同 seed 同条件重试，三次无效或未知故障暂停诊断。')
    settings.pop('output_root',None)
    args.out.mkdir(parents=True,exist_ok=False)
    (args.out/'run_settings.json').write_text(json.dumps(settings,ensure_ascii=False,indent=2)+'\n')
    (args.out/'source_hashes.json').write_text(json.dumps({str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest()
        for base in ('swarm','marllib','scripts') for f in (ROOT/base).rglob('*.py')},indent=2))
    run_remaining(args.out,settings,[],[],0)


if __name__=='__main__':
    main()
