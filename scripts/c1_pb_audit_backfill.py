"""双机共享当前观测下，离线补齐 PB-CBF 发布后约束审计；不修改轨迹。"""
import hashlib
import json
import math
import numpy as np

from swarm.ra.margins import RuntimeAssuranceParams, dynamics_margin
from swarm.ra.runtime_assurance import _closing_speed_2d
from swarm.ra.sota_cbf import minimum_prediction_based_constraint_slack


def audit_trajectory(path, expected_sha256, config):
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError('原轨迹哈希不一致')
    params = RuntimeAssuranceParams(degradation_dt=0.05, v_max=1.5, a_max=2.0)
    samples = []
    unknown = failures = 0
    for line in path.read_text().splitlines():
        record = json.loads(line)
        drones = {int(i): d for i, d in record['drones'].items()}
        if set(drones) != {2, 3}:
            raise ValueError('补审计仅适用于本次 C1 双机共享当前观测')
        velocities = {i: np.asarray(d['v_actual'][:2]) for i, d in drones.items()}
        ages = {i: max(0.0, (d['command_timestamp_ms'] - d['measurement_timestamp_ms']) / 1000.0)
                for i, d in drones.items()}
        if any(abs(ages[i]-d['solver_input_age_s']) > 1e-10 for i,d in drones.items()):
            raise ValueError('无法精确恢复共享当前观测的前推时长')
        positions = {i: np.asarray(d['pos'][:2]) + velocities[i]*ages[i]
                     for i, d in drones.items()}
        boundaries = [d['d_safe'] for d in drones.values()]
        if not all(math.isfinite(x) for x in boundaries) or abs(boundaries[0]-boundaries[1]) > 1e-10:
            raise ValueError('双机边界缺失或不一致')
        # 日志 d_safe 是完整 s_now，不是 PB 的 static_distance。
        # 相同双机状态下减去动力学项，再加原 PB 配置 buffer。
        closing = _closing_speed_2d(positions[2], positions[3], velocities[2], velocities[3])
        static = boundaries[0] - dynamics_margin(closing, params) + config.get('boundary_buffer_m', 0.0)
        if not math.isfinite(static) or static < params.d0:
            raise ValueError('无法恢复 PB 静态边界')
        slack = minimum_prediction_based_constraint_slack(
            accelerations={i: np.asarray(d['published_effective_acceleration']) for i,d in drones.items()},
            positions=positions, velocities=velocities, static_distance={(2,3):static},
            alpha=config['alpha'], braking_accel=config['braking_accel_mps2'], a_max=2.0,
            box_constrained_drones={i for i,d in drones.items() if d['control_authority']},
        )
        if not math.isfinite(slack):
            raise ValueError('非有限审计结果')
        was_unknown = sum(d['published_command_constraint_ok'] is None for d in drones.values())
        unknown += was_unknown
        failures += len(drones) if slack < -1e-6 else 0
        samples.append(dict(step=record['step'], static_distance=static,
                            minimum_slack=slack, ok=slack >= -1e-6,
                            originally_unknown=was_unknown))
    if not samples:
        raise ValueError('空轨迹')
    return dict(trajectory_sha256=expected_sha256, original_unknown_count=unknown,
                published_command_constraint_unknown_count=0,
                published_command_constraint_failure_count=failures,
                samples=samples)
