"""用已有轨迹证明截断后的 PCBF 原计划终端失效，保留原结果并续跑。"""
import hashlib
import json
import math
import time
from pathlib import Path
from c1_revision_policy import paired_decision


def backfill(path,config,tau):
    data=[json.loads(line) for line in path.read_text().splitlines()]
    proofs=[]
    for idx,row in enumerate(data):
        drones=list(row['drones'].values())
        count=sum(d['published_command_constraint_ok'] is None for d in drones)
        if not count:
            continue
        if not all(d['pcbf_terminal_feasible'] and d['solver_feasible'] and
                   d['published_command_matches_selected'] and d['control_authority'] for d in drones):
            raise ValueError('不满足原计划终端约束误差界的前提')
        dt=.05 if idx==0 else max(.001,row['t']-data[idx-1]['t'])
        scale=(1-math.exp(-dt/tau))*tau
        delta=max(abs(a-b) for d in drones for a,b in zip(d['a_safe'],d['published_effective_acceleration']))
        residual=max(d['pcbf_max_constraint_violation'] for d in drones)
        epsilon=config.get('terminal_velocity_tolerance_mps',0.0)
        # v_N' = v_N + scale*(a_published-a_selected)。原计划每分量
        # |v_N|<=epsilon+residual，反三角不等式给出新计划的下界。
        lower=scale*delta-epsilon-residual
        threshold=epsilon+10*config.get('acceptable_tolerance',1e-5)
        if not math.isfinite(lower) or lower<=threshold:
            raise ValueError('现有记录不足以判定，不能将未知直接改为通过/失败')
        proofs.append(dict(step=row['step'],unknown_vehicle_steps=count,
                           terminal_speed_lower_bound=lower,tolerance_threshold=threshold))
    return proofs


def resume(out,root):
    settings=json.loads((out/'run_settings.json').read_text())
    parent=json.loads((root/'configs/c1_external_pcbf_buffer_matched_fresh_v1.json').read_text())
    for key in ('methods','trials','rate_hz','max_steps','execution_tau_s','drone_ids','base_goals','reset_starts','goal_epsilon'):
        if settings[key]!=parent[key]:
            raise ValueError(f'原数值配置变化：{key}')
    state=json.loads((out/'status.json').read_text())
    if state['state'] not in {'STOP_SAFETY_CHAIN','PAUSED_FOR_DIAGNOSIS'}:
        raise ValueError('只恢复已经诊断的审计暂停')
    attempts=[dict(a) for a in state['attempts']]
    if state['state']=='PAUSED_FOR_DIAGNOSIS':
        pending=[a for a in attempts if a['state']=='NEEDS_DIAGNOSIS']
        if not pending:
            raise ValueError('没有明确的启动超时可分类，需另行诊断')
        for attempt in pending:
            folder=out/attempt['label']
            blocked=folder/'BLOCKED.txt'
            from run_c1_corrected_v2 import has_episode_trajectory
            if (not blocked.exists() or not any(marker in blocked.read_text() for marker in ('SITL 超时','wait_for_px4_telemetry.py'))
                    or list(folder.glob('*/summary.json')) or has_episode_trajectory(folder)):
                raise ValueError('不是无正式轨迹的已知启动超时')
            attempt.update(state='INFRASTRUCTURE_INVALID',diagnosis='仿真启动超时，无有效 trial；用户确认环境恢复后同 seed 续跑')
    old=json.loads((out/'source_hashes.json').read_text())
    allowed={'swarm/ra/pcbf.py','swarm/ra/runtime_assurance.py','scripts/run_external_matched_corrected_v2.py',
             'scripts/run_c1_corrected_v2.py','scripts/run_paper_c1_rerun.py','marllib/run_c1_sota_cbf_gazebo.py'}
    changed=[p for p,h in old.items() if hashlib.sha256((root/p).read_bytes()).hexdigest()!=h]
    if set(changed)-allowed:
        raise ValueError(f'审计补丁之外存在源码变化：{changed}')
    rows=json.loads((out/'results.json').read_text())
    expected=[(t['trial_id'],m,t['seed']) for t in settings['trials'] for m in t['condition_order']]
    if [(r['trial_id'],r['method'],r['seed']) for r in rows]!=expected[:len(rows)]:
        raise ValueError('结果不是原定配对前缀')
    evaluated=[]; reports=[]
    for row in rows:
        matches=[a for a in state['attempts'] if a['state']=='VALID' and a['label'].startswith(f"{row['trial_id']}_{row['method']}_attempt")]
        if len(matches)!=1:
            raise ValueError('结果归属不唯一')
        p=Path(matches[0]['summary'])
        if json.loads(p.read_text())['trials'][0]!=row:
            raise ValueError('摘要变化')
        path=p.parent/row['trajectory']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=row['trajectory_sha256']:
            raise ValueError('原轨迹哈希变化')
        checked=dict(row)
        if row.get('published_command_constraint_unknown_count',0):
            if row['method']!='PCBF_HUANG_ECC2025':
                raise ValueError('非 PCBF 未知问题需单独诊断')
            proofs=backfill(path,settings['methods'][row['method']],settings['execution_tau_s'])
            count=sum(p['unknown_vehicle_steps'] for p in proofs)
            if count!=row['published_command_constraint_unknown_count']:
                raise ValueError('未知计数不符')
            checked['published_command_constraint_unknown_count']=0
            checked['published_command_constraint_failure_count']+=count
            reports.append(dict(trial_id=row['trial_id'],method=row['method'],trajectory_sha256=row['trajectory_sha256'],
                                corrected_unknown=0,corrected_failure=checked['published_command_constraint_failure_count'],proofs=proofs))
        evaluated.append(checked)
    offset=completed=0
    for t in settings['trials']:
        if offset==len(rows):break
        n=len(t['condition_order'])
        if paired_decision(evaluated[offset:offset+n],t['condition_order'])!='CONTINUE':
            raise ValueError('完整配对补审计后仍不允许继续')
        offset+=n;completed+=1
    with (out/f'pcbf_audit_resume_{time.time_ns()}.json').open('x') as stream:
        json.dump(dict(previous_status=state,changed_sources=changed,corrections=reports,
            note='原轨迹/摘要/结果行保持不变。补审计判定的是截断输入沿原计划的约束失效，不是重新优化计划不可行或物理碰撞。',
            source_hashes={str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest()
                for base in ('swarm','marllib','scripts') for f in (root/base).rglob('*.py')}),stream,ensure_ascii=False,indent=2)
    return settings,rows,attempts,completed
