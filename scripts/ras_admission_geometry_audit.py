"""RAS 准入几何参数审计；只产生离线判定，不代表 PX4 闭环结果。"""
from __future__ import annotations

import argparse
import itertools
import json
from dataclasses import replace
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from swarm.recovery.recoverability_admission import (
    RecoverabilityAdmissionConfig, RecoverabilityAdmissionCoordinator,
)


def cases():
    """确定性边界扫描；无事后标签、无旧 sealed seed。"""
    for y, speed, angle in itertools.product(
        (-2.8, -2.4, -2.0, 0.0, 2.0, 2.4, 2.8),
        (0.0, 0.5, 1.0, 2.0), (0.0, np.pi / 2),
    ):
        yield dict(start=[-4.0, y], goal=[4.0, y], failed=[0.0, 0.0],
                   velocity=[speed * float(np.cos(angle)), speed * float(np.sin(angle))])
    for offset in (2.2, 2.35, 2.4, 2.45, 2.6):
        yield dict(start=[-4.0, 3.0], goal=[offset, 0.0],
                   failed=[0.0, 0.0], velocity=[0.0, 0.0])


def decide(case, config):
    from swarm.safety import DroneSnapshot
    coordinator = RecoverabilityAdmissionCoordinator(config)
    # 使用生产实现的制动包络与候选路由，而非另写准入规则。
    snapshot = DroneSnapshot(drone_id=2, position=(*case['failed'], 2.5),
                             velocity=(*case['velocity'], 0.0))
    centers = coordinator._obstacle_centers(snapshot)
    coordinator._admit(start=np.array(case['start']), goal=np.array(case['goal']),
                       obstacle_centers=centers, altitude=2.5)
    result = coordinator.summary()
    result['route_length_m'] = (
        coordinator._route_length([np.array(case['start'])] +
                                  [np.array(p[:2]) for p in coordinator.route])
        if coordinator.route else None)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    mount = Path('/Volumes/Expansion')
    if not mount.is_mount():
        parser.error('移动硬盘未挂载；不在仓库或系统盘写入实验 metrics')
    destination = args.output.resolve()
    if not destination.is_relative_to(mount.resolve()):
        parser.error('输出必须位于 /Volumes/Expansion')
    base = RecoverabilityAdmissionConfig()
    variants = [('nominal', base)]
    for field, values in {
        'clearance_m': (2.0, 2.2, 2.6, 2.8),
        'max_route_length_m': (8.0, 10.0, 14.0, 22.0),
        'ring_samples': (8, 16, 64),
        'obstacle_samples': (3, 5, 17, 33),
        'braking_accel_mps2': (1.0, 1.5, 2.5),
    }.items():
        variants.extend((f'{field}={v}', replace(base, **{field: v})) for v in values)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('x') as stream:
        for index, case in enumerate(cases()):
            # 高密度候选族只对每个几何计算一次；它是“生产候选是否过疏”的
            # 参考，而不是完整可达性判定或新的调参依据。
            reference = decide(
                case, replace(base, ring_samples=64, obstacle_samples=17)
            )
            for name, config in variants:
                result = decide(case, config)
                stream.write(json.dumps(dict(case_id=index, geometry=case, variant=name,
                                             result=result, dense_reference=reference)) + '\n')
            stream.flush()


if __name__ == '__main__':
    main()
