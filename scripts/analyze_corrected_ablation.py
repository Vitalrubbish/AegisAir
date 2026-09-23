"""核验修订版有效轨迹并计算 seed 配对统计；不把基线失败变成全组 No-Go。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import math
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from marllib.analyze_c1_hocbf_v4_ablation import _method_summary, _paired


def signed_rank_p(delta):
    """去掉零差，平均秩处理并列，用精确符号枚举分布而非正态近似。"""
    delta=np.asarray(delta,dtype=float)
    delta=delta[delta!=0]
    if not len(delta):
        return 1.0
    ranks=np.zeros(len(delta),dtype=int)
    order=np.argsort(np.abs(delta))
    start=0
    while start<len(delta):
        end=start+1
        while end<len(delta) and abs(delta[order[end]])==abs(delta[order[start]]):
            end+=1
        ranks[order[start:end]]=start+1+end
        start=end
    total=int(ranks.sum())
    counts=np.zeros(total+1,dtype=np.int64); counts[0]=1
    for rank in ranks:
        counts[rank:]+=counts[:-rank].copy()
    observed=int(ranks[delta>0].sum())
    distance=abs(2*observed-total)
    return float(counts[np.abs(2*np.arange(total+1)-total)>=distance].sum()/2**len(delta))


def mcnemar_p(a,b):
    n=a+b
    return min(1.0,2*sum(math.comb(n,k) for k in range(min(a,b)+1))/2**n) if n else 1.0


def holm(values):
    order=sorted(range(len(values)),key=lambda i:values[i])
    adjusted=[0.0]*len(values)
    running=0.0
    for rank,i in enumerate(order):
        running=max(running,min(1.0,(len(values)-rank)*values[i]))
        adjusted[i]=running
    return adjusted


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    settings=json.loads((args.root/'run_settings.json').read_text())
    rows=json.loads((args.root/'results.json').read_text())
    expected=[(t['trial_id'],m,t['seed']) for t in settings['trials'] for m in t['condition_order']]
    if [(r['trial_id'],r['method'],r['seed']) for r in rows]!=expected:
        raise ValueError('有效配对不完整或顺序/seed 错误')
    timing=[]
    for r in rows:
        paths=[p for p in args.root.glob(f"{r['trial_id']}_{r['method']}_attempt*/*/{r['trajectory']}")
               if hashlib.sha256(p.read_bytes()).hexdigest()==r['trajectory_sha256']]
        if len(paths)!=1 or not r['infrastructure_valid']:
            raise ValueError('有效轨迹哈希或有效性不符')
        data=[json.loads(line) for line in paths[0].read_text().splitlines()]
        if min(x['min_rho'] for x in data)!=r['min_rho']:
            raise ValueError('rho 汇总与轨迹不一致')
        first_bad=next((x['step'] for x in data if any(d.get('primary_feasible') is False for d in x['drones'].values())),None)
        first_pb=next((x['step'] for x in data if any(d.get('recovery_active') for d in x['drones'].values())),None)
        timing.append(dict(trial_id=r['trial_id'],method=r['method'],first_primary_infeasible=first_bad,
            first_takeover=first_pb,lead_steps=None if first_bad is None or first_pb is None else first_bad-first_pb))
    paired=_paired(rows,settings['comparisons'])
    by={(r['trial_id'],r['method']):r for r in rows}
    for metric in ('qp_infeasible_steps','mean_control_effort','min_rho','path_length_m'):
        ps=[]
        for comparison in paired:
            delta=np.array([by[t['trial_id'],comparison['left']][metric]-by[t['trial_id'],comparison['right']][metric] for t in settings['trials']])
            # 额外诊断检验，不冒充旧方案已固定的具体检验实现。
            ps.append(signed_rank_p(delta))
        for comparison,p,adj in zip(paired,ps,holm(ps)):
            comparison['metrics'][metric].update(wilcoxon_p=p,holm_three_comparisons_p=adj)
    binary=[]
    for left,right,label in settings['comparisons']:
        counts=[0,0]
        for t in settings['trials']:
            outcomes=[by[t['trial_id'],m]['min_rho']>0 and not by[t['trial_id'],m]['collision'] and by[t['trial_id'],m]['mission_complete'] for m in (left,right)]
            counts[0]+=int(outcomes==[True,False]); counts[1]+=int(outcomes==[False,True])
        binary.append(dict(label=label,left_only_success=counts[0],right_only_success=counts[1],
            exact_mcnemar_p=mcnemar_p(*counts)))
    payload=dict(conditions_verified=len(rows),method_summary=_method_summary(rows),paired=paired,
        takeover_timing=timing,binary=binary,
        limitations='接管提前步数仅在首次接管与实际主约束不可行均可观察时定义；无不可行事件属于删失，不补零、不推断反事实。尚未对该删失终点作组间检验。精确符号翻转 signed-rank 检验（零差剔除、平均秩、对称差值假设）及 Holm 每指标三比较为本次明确记录的分析实现，不声称此前精确预注册。')
    with args.out.open('x') as stream:
        json.dump(payload,stream,ensure_ascii=False,indent=2)
    print(json.dumps(dict(method_summary=payload['method_summary'],paired=paired),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
