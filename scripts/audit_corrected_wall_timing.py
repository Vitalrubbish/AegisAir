"""用主机周期起始时间戳区分标称步数时域与实际采集时间跨度。"""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    state=json.loads((args.root/'status.json').read_text())
    if state['state']!='COMPLETED':
        raise ValueError('未完成组不生成全量时间审计')
    rows=json.loads((args.root/'results.json').read_text())
    audit=[]
    for row in rows:
        attempts=[attempt for attempt in state['attempts'] if attempt['state']=='VALID'
                  and attempt['label'].startswith(f"{row['trial_id']}_{row['method']}_attempt")]
        if len(attempts)!=1:
            raise ValueError('轨迹归属不唯一')
        path=Path(attempts[0]['summary']).parent/row['trajectory']
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=row['trajectory_sha256']:
            raise ValueError('轨迹哈希不符')
        records=[json.loads(line) for line in raw.splitlines()]
        times=[]
        for record in records:
            stamps={drone['command_timestamp_ms'] for drone in record['drones'].values()}
            if len(stamps)!=1:
                raise ValueError('同一联合周期时间戳不一致')
            times.append(stamps.pop()/1000)
        delta=np.diff(times)
        if not len(delta) or np.any(delta<=0):
            raise ValueError('周期时间戳不单调，不能解释为可靠时间跨度')
        audit.append(dict(trial_id=row['trial_id'],seed=row['seed'],method=row['method'],
            cycles=len(records),nominal_first_last_span_s=records[-1]['t']-records[0]['t'],
            cycle_start_first_last_span_s=times[-1]-times[0],
            mean_interval_ms=float(np.mean(delta)*1000),p99_interval_ms=float(np.percentile(delta,99)*1000),
            max_interval_ms=float(np.max(delta)*1000),trajectory_sha256=row['trajectory_sha256']))
    methods={}
    for method in sorted({row['method'] for row in audit}):
        group=[row for row in audit if row['method']==method]
        span=[row['cycle_start_first_last_span_s'] for row in group]
        methods[method]=dict(episodes=len(group),mean_span_s=float(np.mean(span)),
            min_span_s=min(span),max_span_s=max(span))
    result=dict(conditions_verified=len(audit),rows=audit,method_summary=methods,
        note='t=step/rate_hz 是标称时间。command_timestamp_ms 在每个控制周期开始读取主机墙钟，不是 adapter 实际发布/执行完成时间。这里报告首末周期起始跨度，排除起飞、reset、最后一步计算及着陆。相同400步预算不等于相同实际墙钟时域；软件调度和求解超期会拉长周期。')
    with args.out.open('x') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2)
    print(json.dumps(methods,ensure_ascii=False))


if __name__=='__main__':
    main()
