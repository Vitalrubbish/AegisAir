"""现行动态接纳器的 61 状态离线敏感性审计，不冒充闭环证据。"""
import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ras_admission_geometry_audit import cases
from swarm.recovery.recoverability_admission import (
    RecoverabilityAdmissionConfig, RecoverabilityAdmissionCoordinator,
)
from swarm.safety import DroneSnapshot


def variants():
    base = RecoverabilityAdmissionConfig()
    output = [('nominal', base)]
    for field, values in {
        'clearance_m': (2.0, 2.2, 2.6, 2.8),
        'max_route_length_m': (8.0, 10.0, 14.0, 22.0),
        'ring_samples': (8, 16, 64),
        'braking_accel_mps2': (1.0, 1.5, 2.5),
    }.items():
        output.extend((f'{field}={value}', replace(base, **{field: value})) for value in values)
    return output


def decide(case, config):
    coordinator = RecoverabilityAdmissionCoordinator(config)
    failed = DroneSnapshot(drone_id=2, position=(*case['failed'], 2.5),
                           velocity=(*case['velocity'], 0.0))
    coordinator._admit(start=np.asarray(case['start'], dtype=float),
        initial_velocity=np.zeros(2), goal=np.asarray(case['goal'], dtype=float),
        failed_trajectory=coordinator._failed_trajectory(failed), altitude=2.5)
    summary = coordinator.summary()
    summary['route_length_m'] = (coordinator._route_length(
        [np.asarray(case['start'], dtype=float)] +
        [np.asarray(point[:2], dtype=float) for point in coordinator.route])
        if coordinator.route else None)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    mount = Path('/Volumes/Expansion')
    if not mount.is_mount() or not args.out.resolve().is_relative_to(mount.resolve()):
        parser.error('结果必须写入已挂载的 /Volumes/Expansion')
    args.out.mkdir(parents=True, exist_ok=False)
    configurations = variants()
    states = list(cases())
    sources = ['swarm/recovery/recoverability_admission.py',
               'scripts/ras_admission_geometry_audit.py',
               'scripts/run_corrected_admission_geometry_audit.py']
    settings = dict(cases=states, healthy_initial_velocity_mps=[0.0, 0.0],
        variants={name: asdict(config) for name, config in configurations},
        source_hashes={name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources},
        note='历史 61 个确定性状态及仍存在的参数值原样保留；velocity 是失效机初速度。现行实现采用连续扫掠线段，不存在 obstacle_samples，故不伪造该维度。健康机初速度固定为零，并调用生产动态 rollout。64 点候选族仅是离散化敏感性参照，不是完备可达性真值，也不用于调参。')
    (args.out / 'run_settings.json').write_text(json.dumps(settings, ensure_ascii=False, indent=2))
    counts = {name: dict(states=0, admitted=0, differs_from_dense=0) for name, _ in configurations}
    with (args.out / 'results.jsonl').open('x') as stream:
        for index, case in enumerate(states):
            reference = decide(case, replace(configurations[0][1], ring_samples=64))
            for name, config in configurations:
                result = reference if name == 'ring_samples=64' else decide(case, config)
                stream.write(json.dumps(dict(case_id=index, case=case, variant=name,
                    result=result, dense_reference=reference), ensure_ascii=False) + '\n')
                counts[name]['states'] += 1
                counts[name]['admitted'] += result['state'] == 'admitted'
                counts[name]['differs_from_dense'] += result['state'] != reference['state']
            stream.flush()
            print(f'完成状态 {index + 1}/{len(states)}', flush=True)
    result = dict(state='COMPLETED', cases=len(states), rows=len(states) * len(configurations),
                  evidence_level='离线确定性判定；不是闭环成功率或真实可达性准确率', variants=counts)
    (args.out / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
