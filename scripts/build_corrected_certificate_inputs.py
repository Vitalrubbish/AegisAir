"""把有效 V4 轨迹的校验副本整理成旧审计器布局；不覆盖原数据。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def copy_verified_trace(entry,destination):
    # 外置盘为 ExFAT，不支持符号链接。仅创建专用分析副本并再次核对哈希。
    with Path(entry['trajectory']).open('rb') as source, destination.open('xb') as target:
        shutil.copyfileobj(source,target)
    if hashlib.sha256(destination.read_bytes()).hexdigest()!=entry['trajectory_sha256']:
        raise ValueError('分析副本与已核验原轨迹不一致')


def selected_traces(root,allow_stopped=False):
    settings=json.loads((root/'run_settings.json').read_text())
    state=json.loads((root/'status.json').read_text())
    permitted={'COMPLETED','STOP_PRIMARY_FAILURE'} if allow_stopped else {'COMPLETED'}
    if state['state'] not in permitted:
        raise ValueError('数据组未完成或仍处于待诊断状态')
    rows=json.loads((root/'results.json').read_text())
    expected=[(trial['trial_id'],method,trial['seed']) for trial in settings['trials'] for method in trial['condition_order']]
    actual=[(row['trial_id'],row['method'],row['seed']) for row in rows]
    if actual!=expected[:len(rows)] or (state['state']=='COMPLETED' and len(actual)!=len(expected)):
        raise ValueError('配对身份或完整性错误')
    result=[]
    for row in rows:
        if row['method']!='AEGIS_HOCBF_V4':
            continue
        attempts=[attempt for attempt in state['attempts'] if attempt['state']=='VALID' and attempt['label'].startswith(row['trial_id']+'_'+row['method']+'_attempt')]
        if len(attempts)!=1 or not row['infrastructure_valid']:
            raise ValueError('V4 有效轨迹归属不唯一')
        summary=Path(attempts[0]['summary'])
        if json.loads(summary.read_text())['trials']!=[row]:
            raise ValueError('原始摘要变化')
        trajectory=summary.parent/row['trajectory']
        if hashlib.sha256(trajectory.read_bytes()).hexdigest()!=row['trajectory_sha256']:
            raise ValueError('轨迹哈希变化')
        result.append(dict(trial_id=row['trial_id'],seed=row['seed'],trajectory=str(trajectory.resolve()),
            trajectory_sha256=row['trajectory_sha256'],source_status=state['state']))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--calibration',type=Path,required=True)
    parser.add_argument('--c1',type=Path,required=True)
    parser.add_argument('--ood',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if not Path('/Volumes/Expansion').is_mount() or not args.out.resolve().is_relative_to(Path('/Volumes/Expansion').resolve()):
        raise ValueError('数据视图必须位于已挂载外置盘')
    groups={'calibration':selected_traces(args.calibration),'c1':selected_traces(args.c1)}
    if len(groups['calibration'])!=5:
        raise ValueError('原定校准需要五条独立 V4 轨迹')
    ood_state=json.loads((args.ood/'status.json').read_text())
    if ood_state['state'] not in {'COMPLETED','PARTIAL_SCENARIO_STOP'}:
        raise ValueError('OOD 尚未结束')
    for scenario in ood_state['scenarios']:
        groups[scenario['scenario']]=selected_traces(args.ood/scenario['scenario'],allow_stopped=True)
    args.out.mkdir(parents=True,exist_ok=False)
    for name,entries in groups.items():
        destination=args.out/name;destination.mkdir()
        for entry in entries:
            folder=destination/(entry['trial_id']+'_AEGIS_HOCBF_V4');folder.mkdir()
            copy_verified_trace(entry,folder/'trajectory.jsonl')
    with (args.out/'input_index.json').open('x') as stream:
        json.dump(dict(groups=groups,note='仅包含各修正版有效 V4 轨迹。ExFAT 不支持符号链接，使用逐份 SHA-256 复核的字节一致副本供只读审计；不改原始记录，也不声称文件系统强制只读。提前停止场景按实际数量报告，不声称完成未运行 seeds。旧表达式、固定 D=0.8 和 10% 校准膨胀不改，预测状态比较修正另列。'),stream,ensure_ascii=False,indent=2)
    print(json.dumps({name:len(entries) for name,entries in groups.items()}))


if __name__=='__main__':
    main()
