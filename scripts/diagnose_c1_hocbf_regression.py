"""同输入诊断 C1 HOCBF：解析可行性、历史求解器与时延分解；不改控制参数。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from swarm.ra.hocbf import _pair_constraint, solve_acceleration_qp
from swarm.ra.margins import RuntimeAssuranceParams, communication_margin


def diagnose(path, legacy_solver):
    data = [json.loads(line) for line in path.read_text().splitlines()]
    report = dict(trajectory=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  steps=len(data), exact_infeasible=0, false_infeasible=0,
                  legacy_feasibility_disagreements=0, action_difference_steps=0,
                  max_action_difference=0.0, current_replay_mismatch=0,
                  negative_rho_steps=0, first_infeasible=None, first_negative=None,
                  negative_with_zero_communication_margin=0)
    ages = []
    events = []
    for row in data:
        drones = {int(i):d for i,d in row['drones'].items()}
        ids = sorted(drones)
        if len(ids)!=2 or any(d.get('control_authority') is False for d in drones.values()):
            raise ValueError('诊断仅适用于本次双机无权限撤销的 V3')
        velocities = {i:np.asarray(d['v_actual'][:2]) for i,d in drones.items()}
        age = {i:d.get('solver_input_age_s',d['age_s']) for i,d in drones.items()}
        positions = {i:np.asarray(d['pos'][:2])+velocities[i]*age[i] for i,d in drones.items()}
        safe = float(drones[ids[0]]['d_safe'])
        args = dict(a_nom={i:np.asarray(d['a_nom']) for i,d in drones.items()},
                    positions=positions, velocities=velocities, d_safe={tuple(ids):safe},
                    k1=4.0,k2=4.0,a_max=2.0,infeasible_fallback='max_brake')
        c,b = _pair_constraint(i=0,j=1,n_agents=2,p_i=positions[ids[0]],p_j=positions[ids[1]],
                               v_i=velocities[ids[0]],v_j=velocities[ids[1]],s=safe,k1=4.0,k2=4.0)
        # 双机单半空间与盒的交集非空，当且仅当盒上的支持函数不小于 b。
        maximum_slack = 2.0*np.abs(c).sum()-b
        exact = maximum_slack >= -1e-9
        current, feasible, _ = solve_acceleration_qp(**args)
        legacy, old_feasible, _ = legacy_solver(**args)
        diff = max(float(np.max(np.abs(current[i]-legacy[i]))) for i in ids)
        mismatch = max(float(np.max(np.abs(current[i]-drones[i]['a_safe']))) for i in ids)
        report['exact_infeasible'] += int(not exact)
        report['false_infeasible'] += int(exact and not feasible)
        report['legacy_feasibility_disagreements'] += int(feasible!=old_feasible)
        report['action_difference_steps'] += int(diff>1e-6)
        report['max_action_difference'] = max(report['max_action_difference'],diff)
        report['current_replay_mismatch'] += int(mismatch>1e-6)
        if not exact and report['first_infeasible'] is None:
            report['first_infeasible'] = row['step']
        negative = row['min_rho']<0
        if negative:
            report['negative_rho_steps'] += 1
            if report['first_negative'] is None:
                report['first_negative'] = row['step']
        ages.append(max(age.values()))
        # 仅分解当前状态的评价边界，不能当作零时延闭环反事实。
        p3 = {i:np.asarray(d['pos'])+np.asarray(d['v_actual'])*age[i] for i,d in drones.items()}
        distance = float(np.linalg.norm(positions[ids[0]]-positions[ids[1]]))
        from swarm.ra.margins import closing_speed, dynamic_safety_boundary
        params = RuntimeAssuranceParams(degradation_dt=0.05,v_max=1.5,a_max=2.0)
        closing = closing_speed(tuple(p3[ids[0]]),tuple(p3[ids[1]]),
                                tuple(drones[ids[0]]['v_actual']),tuple(drones[ids[1]]['v_actual']))
        # runner 默认 sigma=0.1；先核验 rho 一致才允许边界分解。
        boundary = dynamic_safety_boundary(closing_speed=closing,perception_sigma_i=0.1,
            perception_sigma_j=0.1,aoi=max(age.values()),params=params)
        rho = (distance-boundary)/boundary
        if abs(rho-row['min_rho'])>2e-6:
            raise ValueError(f"无法重建 rho: {path.name} step={row['step']} {rho} != {row['min_rho']}")
        no_comm = boundary-communication_margin(max(age.values()),params)
        report['negative_with_zero_communication_margin'] += int(negative and distance<no_comm)
        if negative or not exact or diff>1e-6:
            events.append(dict(step=row['step'],rho=row['min_rho'],maximum_constraint_slack=float(maximum_slack),
                               current_feasible=bool(feasible),legacy_feasible=bool(old_feasible),
                               action_difference=diff,replay_error=mismatch,aoi=max(age.values()),
                               evaluation_boundary=boundary,distance=distance,
                               rho_without_communication_margin=(distance-no_comm)/no_comm))
    report['aoi_p50_s'],report['aoi_p95_s'] = np.percentile(ages,[50,95]).tolist()
    report['events']=events
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    legacy_ref='7b6376c'
    source=subprocess.check_output(['git','show',f'{legacy_ref}:swarm/ra/hocbf.py'],cwd=ROOT,text=True)
    namespace={}
    exec(compile(source,f'{legacy_ref}:swarm/ra/hocbf.py','exec'),namespace)
    reports=[]
    rows=json.loads((args.root/'results.json').read_text())
    for row in rows:
        if row['method']!='AEGIS_HOCBF_V3':
            continue
        paths=list(args.root.glob(f"{row['trial_id']}_AEGIS_HOCBF_V3_attempt*/*/{row['trajectory']}"))
        matches=[p for p in paths if hashlib.sha256(p.read_bytes()).hexdigest()==row['trajectory_sha256']]
        if len(matches)!=1:
            raise ValueError('有效轨迹归属不唯一')
        report=diagnose(matches[0],namespace['solve_acceleration_qp'])
        report['trial_id']=row['trial_id']
        reports.append(report)
        print(row['trial_id'],{k:v for k,v in report.items() if k not in ('events','trajectory','sha256')},flush=True)
    payload=dict(legacy_ref=legacy_ref,legacy_source_sha256=hashlib.sha256(source.encode()).hexdigest(),
                 limitation='公开历史源码是参考实现，不是已证实的每条历史实验运行快照；同输入回放不是闭环反事实。',
                 reports=reports)
    with args.out.open('x') as stream:
        json.dump(payload,stream,ensure_ascii=False,indent=2)


if __name__=='__main__':
    main()
