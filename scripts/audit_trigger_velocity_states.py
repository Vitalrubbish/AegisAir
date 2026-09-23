"""固定位置改变速度，复用真实触发分支；只读单步机制审计。"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from marllib.run_c1_sota_cbf_gazebo import _method_kwargs
from swarm.ra.runtime_assurance import RuntimeAssurance
from swarm.ra.trigger_baselines import constant_velocity_ttc
from swarm.safety import DroneSnapshot


def controller(method,config):
    kwargs=_method_kwargs(method,config,.7)
    kwargs['params']=kwargs.pop('ra_params')
    kwargs['command_feedforward_tau_s']=kwargs.pop('ra_command_feedforward_tau_s')
    for key in ('velocity_command_mode','tau_command_s','observation_mode'):
        kwargs.pop(key)
    return RuntimeAssurance(v_max=1.5,**kwargs)


def state_grid(protocol,scenarios):
    for scenario in protocol['scenarios']:
        geometry=scenarios[scenario]
        starts={int(key):np.asarray(value,float) for key,value in geometry['reset_starts'].items()}
        goals={int(key):np.asarray(value,float) for key,value in geometry['base_goals'].items()}
        for fraction in protocol['route_fractions']:
            positions={drone:start+fraction*(goals[drone]-start) for drone,start in starts.items()}
            nominal={drone:np.clip(1.5*(goals[drone][:2]-position[:2]),-1.5,1.5) for drone,position in positions.items()}
            for speed in protocol['signed_speed_mps']:
                for angle in protocol['heading_rotation_deg']:
                    theta=math.radians(angle)
                    rotation=np.array([[math.cos(theta),-math.sin(theta)],[math.sin(theta),math.cos(theta)]])
                    velocities={drone:np.r_[speed*(rotation@((goals[drone][:2]-starts[drone][:2])/np.linalg.norm(goals[drone][:2]-starts[drone][:2]))),0.] for drone in starts}
                    snapshots={drone:DroneSnapshot(drone,tuple(positions[drone]),velocity=tuple(velocities[drone])) for drone in starts}
                    yield dict(scenario=scenario,route_fraction=fraction,speed_mps=speed,heading_deg=angle),snapshots,nominal


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    source=ROOT/'configs/trigger_velocity_state_audit_v1.json'
    protocol=json.loads(source.read_text())
    grids=[json.loads((ROOT/'configs'/name).read_text()) for name in protocol['parent_grids']]
    if any(grid['scenarios']!=grids[0]['scenarios'] for grid in grids):
        raise ValueError('三个开发网格的几何不一致')
    configurations={}
    for grid in grids:
        for method,config in grid['methods'].items():
            threshold=config.get('recovery_distance_threshold_m',config.get('recovery_ttc_threshold_s'))
            key=method+(f'_{threshold:g}' if threshold is not None else '')
            if key in configurations and configurations[key]!=(method,config):
                raise ValueError('重复参照的配置不同，不能去重')
            configurations[key]=(method,config)
    if len(configurations)!=8:
        raise ValueError('必须是八个不同触发设置')
    args.out.mkdir(parents=True,exist_ok=False)
    (args.out/'run_settings.json').write_bytes(source.read_bytes())
    (args.out/'input_hashes.json').write_text(json.dumps({str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()
        for path in [source,*[ROOT/'configs'/name for name in protocol['parent_grids']],ROOT/'scripts/audit_trigger_velocity_states.py',
                     ROOT/'marllib/run_c1_sota_cbf_gazebo.py',ROOT/'swarm/ra/runtime_assurance.py',ROOT/'swarm/ra/hocbf.py',ROOT/'swarm/ra/trigger_baselines.py']},indent=2))
    rows=[]
    for index,(identity,snapshots,nominal) in enumerate(state_grid(protocol,grids[0]['scenarios'])):
        r=np.asarray(snapshots[2].position[:2])-np.asarray(snapshots[3].position[:2])
        v=np.asarray(snapshots[2].velocity[:2])-np.asarray(snapshots[3].velocity[:2])
        invariants=[]
        for name,(method,config) in configurations.items():
            result=controller(method,config).filter(snapshots,nominal,t=0,aoi={(2,3):protocol['aoi_s']})[2]
            ttc=constant_velocity_ttc(r,v,result.d_safe)
            invariants.append((result.d_safe,result.feasibility_reserve,result.primary_feasible))
            rows.append(dict(state_index=index,**identity,configuration=name,
                positions={str(drone):list(snapshot.position) for drone,snapshot in snapshots.items()},
                velocities={str(drone):list(snapshot.velocity) for drone,snapshot in snapshots.items()},
                nominal={str(drone):value.tolist() for drone,value in nominal.items()},
                distance_m=float(np.linalg.norm(r)),primary_boundary_m=result.d_safe,
                constant_velocity_ttc_s=None if math.isinf(ttc) else ttc,ttc_infinite=math.isinf(ttc),
                primary_reserve=result.feasibility_reserve,primary_feasible=result.primary_feasible,
                raw_distance_trigger=bool(np.linalg.norm(r)<=config['recovery_distance_threshold_m']) if 'recovery_distance_threshold_m' in config else None,
                raw_ttc_trigger=bool(ttc<=config['recovery_ttc_threshold_s']) if 'recovery_ttc_threshold_s' in config else None,
                recovery_active=result.recovery_active,recovery_reason=result.recovery_reason,
                selected_filter=result.selected_filter,selected_feasible=result.feasible))
        if any(value!=invariants[0] for value in invariants):
            raise ValueError('同一状态的主约束随触发方法变化')
    if len(rows)!=720 or len({row['state_index'] for row in rows})!=90:
        raise ValueError('状态矩阵不完整')
    (args.out/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2,allow_nan=False))
    summary={name:dict(states=90,triggered=sum(row['recovery_active'] for row in rows if row['configuration']==name),
        primary_infeasible=sum(not row['primary_feasible'] for row in rows if row['configuration']==name)) for name in configurations}
    (args.out/'summary.json').write_text(json.dumps(dict(state='COMPLETED',state_count=90,evaluations=len(rows),configurations=summary,
        note=protocol['claim_boundary']),ensure_ascii=False,indent=2))
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':
    main()
