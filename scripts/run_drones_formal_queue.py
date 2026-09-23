"""修正版正式实验队列：不覆盖、不调参，停止门只影响规定分支。"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
# 顺序、依赖在运行前冻结；B1/B2 不属于本次 GroupSlot 链。
JOBS = [
    ('03_ablation','c1_hocbf_v4_ablation_sealed_v1.json','c1',None),
    ('04_external_matched','c1_external_pcbf_buffer_matched_fresh_v1.json','c1',None),
    ('05_c2_bridge','c2_v4_execution_bridge_v1.json','c1',None),
    ('06_ood','c1_hocbf_v4_px4_postfreeze_ood_v1.json','c1',None),
    ('07_c3','c3_closed_loop_v3_hocbf_v4_validation_v1.json','c3',None),
    ('08a_admission_calibration','c_recoverability_admission_calibration_v4.json','admission',None),
    ('08b_admission_qualification','c_recoverability_admission_qualification_v4.json','admission','08a_admission_calibration/audit.json'),
    ('09a_group_calibration','c3_group_slot_4uav_calibration_smoke_v1.json','group',None),
    ('09b_group_qualification','c3_group_slot_4uav_qualification_v1.json','group','09a_group_calibration/RUN_COMPLETE.json'),
    ('09c_group_sealed','c3_group_slot_4uav_sealed_v1.json','group','09b_group_qualification/RUN_COMPLETE.json'),
    ('10_external_unmatched','c1_external_pcbf_sealed_v1.json','c1',None),
    ('11_certificate_calibration','c1_hocbf_v4_certificate_calibration_v1.json','c1',None),
    ('upgrade1_dev_grid1','trigger_comparison_development_grid1_v1.json','c1',None),
    ('upgrade1_dev_grid2','trigger_comparison_development_grid2_v1.json','c1',None),
    ('upgrade1_dev_grid3','trigger_comparison_development_grid3_v1.json','c1',None),
    ('upgrade3_admission_dev','admission_comparison_development_v1.json','admission','08b_admission_qualification/audit.json'),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--wait-existing', choices=[j[0] for j in JOBS])
    args = parser.parse_args()
    queue = args.root/'formal_queue'
    queue.mkdir(exist_ok=False)
    hashes = {name: hashlib.sha256((ROOT/'configs'/name).read_bytes()).hexdigest() for _,name,_,_ in JOBS}
    (queue/'frozen_jobs.json').write_text(json.dumps({'jobs':JOBS,'manifest_hashes':hashes},ensure_ascii=False,indent=2))
    status = []
    def save(state, **extra):
        (queue/'status.json').write_text(json.dumps({'state':state,'updated_unix_s':time.time(),'jobs':status,**extra},ensure_ascii=False,indent=2))
    try:
        if args.wait_existing:
            save('等待已经运行的实验组',waiting_for=args.wait_existing)
            deadline = time.monotonic()+3*3600
            existing = args.root/args.wait_existing
            while time.monotonic()<deadline:
                if (existing/'BLOCKED.txt').exists():
                    raise RuntimeError(f'已有实验基础设施阻塞：{existing}')
                if (existing/'RUN_COMPLETE.json').exists():
                    break
                time.sleep(5)
            else:
                raise RuntimeError('等待已有实验组超时')
            deadline = time.monotonic()+60
            while subprocess.run(['pgrep','-f','run_paper_c1_rerun.py'],stdout=subprocess.DEVNULL).returncode == 0:
                if time.monotonic()>deadline:
                    raise RuntimeError('已有实验控制器未退出，不并发启动')
                time.sleep(1)
        for label, name, family, dependency in JOBS:
            manifest = ROOT/'configs'/name
            if hashlib.sha256(manifest.read_bytes()).hexdigest()!=hashes[name]:
                raise RuntimeError(f'冻结配置被修改：{name}')
            out = args.root/label
            if dependency:
                parent = args.root/dependency
                if not parent.exists() or json.loads(parent.read_text()).get('decision')!='GO':
                    status.append(dict(job=label,state='前置门未通过，未启动',dependency=dependency))
                    save('运行中')
                    continue
            if out.exists():
                if not (out/'RUN_COMPLETE.json').exists() or (out/'BLOCKED.txt').exists():
                    raise RuntimeError(f'存在部分输出，不覆盖或自动重试：{out}')
                if (out/'manifest.json').read_bytes()!=manifest.read_bytes():
                    raise RuntimeError(f'已有运行配置不一致：{out}')
            else:
                command = [sys.executable,str(ROOT/'scripts/run_paper_c1_rerun.py'),'--manifest',str(manifest),'--out',str(out),'--family',family]
                if dependency:
                    command += ['--prerequisite',str(args.root/dependency)]
                save('运行中',active_job=label,command=command)
                print('START '+label,flush=True)
                with (queue/(label+'.log')).open('w') as stream:
                    completed = subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
                if completed.returncode:
                    raise RuntimeError(f'{label} 退出 {completed.returncode}，见该组日志；暂停队列')
            result = json.loads((out/'RUN_COMPLETE.json').read_text())
            status.append(dict(job=label,state='已结束',result=result))
            save('运行中')
            print('DONE '+label,flush=True)
        save('已冻结队列执行结束，待统计及条件性新协议',remaining=[
            '完整性检查、配对统计与主文/补充/图表更新',
            '若动态接纳 qualification GO：冻结修正版 admission sealed 后执行；否则标为前置门阻止',
            '若触发开发矩阵完整：按预声明规则选阈值、冻结并运行新测试；否则保留不完整/No-Go',
            '基于新轨迹的 slack coverage/机制诊断及 admission 离线审计',
        ])
    except BaseException as exc:
        save('队列暂停，需要检查',error=str(exc))
        raise


if __name__ == '__main__':
    main()
