"""核验修正版外部比较的有效配对，保留补审计记录与阴性结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from marllib.analyze_c1_external_pcbf_sealed import _paired, _summaries


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    state=json.loads((args.root/'status.json').read_text())
    if state['state']!='COMPLETED':
        raise ValueError('未完成，不能生成全量统计')
    settings=json.loads((args.root/'run_settings.json').read_text())
    rows=json.loads((args.root/'results.json').read_text())
    expected=[(t['trial_id'],m,t['seed']) for t in settings['trials'] for m in t['condition_order']]
    if [(r['trial_id'],r['method'],r['seed']) for r in rows]!=expected:
        raise ValueError('配对条件不完整或不唯一')
    corrections={}
    for p in sorted(args.root.glob('pcbf_audit_resume_*.json')):
        for correction in json.loads(p.read_text())['corrections']:
            key=correction['trial_id'],correction['method']
            if key in corrections and corrections[key]!=correction:
                raise ValueError('补审计记录相互冲突')
            corrections[key]=correction
    for r in rows:
        if not r['infrastructure_valid']:
            raise ValueError('有效结果包含基础设施无效运行')
        paths=[p for p in args.root.glob(f"{r['trial_id']}_{r['method']}_attempt*/*/{r['trajectory']}")
               if hashlib.sha256(p.read_bytes()).hexdigest()==r['trajectory_sha256']]
        if len(paths)!=1:
            raise ValueError('轨迹归属不唯一或哈希错误')
        original=json.loads((paths[0].parent/'summary.json').read_text())['trials']
        if len(original)!=1:
            raise ValueError('原摘要条件归属不唯一')
        source_row=dict(original[0])
        correction=corrections.get((r['trial_id'],r['method']))
        if source_row!=r:
            if correction and correction['trajectory_sha256']==r['trajectory_sha256']:
                source_row['published_command_constraint_unknown_count']=correction['corrected_unknown']
                source_row['published_command_constraint_failure_count']=correction['corrected_failure']
            if source_row!=r:
                raise ValueError('汇总与原摘要不一致，且不是留档的发布审计补判')
        records=[json.loads(line) for line in paths[0].read_text().splitlines()]
        if min(x['min_rho'] for x in records)!=r['min_rho']:
            raise ValueError('轨迹与摘要的最小裕度不一致')
        r['latency_p99_ms']=r['ra_solve_latency_summary_ms']['p99']
    for r in rows:
        correction=corrections.get((r['trial_id'],r['method']))
        if correction:
            if correction['trajectory_sha256']!=r['trajectory_sha256']:
                raise ValueError('补审计轨迹身份不一致')
            r['published_command_constraint_unknown_count']=correction['corrected_unknown']
            r['published_command_constraint_failure_count']=correction['corrected_failure']
        if r.get('published_command_constraint_unknown_count',0):
            raise ValueError('仍有未解决的审计未知')
    paired=_paired(rows)
    for comparison in paired:
        # 历史分析器将 pair 数硬编码为 20；匹配组实际只有 10。
        comparison['pairs']=len(settings['trials'])
    invalid_attempts=[]
    for attempt in state.get('attempts',[]):
        if attempt['state']=='VALID':
            continue
        entry=dict(attempt)
        summaries=list((args.root/attempt['label']).glob('*/summary.json'))
        if len(summaries)==1:
            invalid=json.loads(summaries[0].read_text())['trials'][0]
            entry['observed_outcome']={key:invalid.get(key) for key in (
                'trial_id','method','seed','min_rho','collision','mission_complete',
                'infrastructure_valid','infrastructure_invalid_reasons','freshness_gate')}
        invalid_attempts.append(entry)
    result=dict(protocol_id=settings['protocol_id'],conditions_verified=len(rows),
        paired_trials=len(settings['trials']),method_summary=_summaries(rows),paired=paired,
        excluded_infrastructure_attempts=invalid_attempts,
        audit_corrections=list(corrections.values()),
        safety_counts={m:dict(negative_or_zero_rho=sum(r['min_rho']<=0 for r in rows if r['method']==m),
            published_constraint_failures=sum(r.get('published_command_constraint_failure_count',0) for r in rows if r['method']==m)) for m in settings['methods']},
        note='原结果不覆盖；统计单位为配对 seed。失败基线进入分析，不作为全组否决。逐比较 bootstrap CI 非同时区间；每指标四基线的精确符号翻转检验采用 Holm 校正。')
    with args.out.open('x') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2)
    print(json.dumps(dict(conditions_verified=len(rows),paired_trials=len(settings['trials']),method_summary=result['method_summary']),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
