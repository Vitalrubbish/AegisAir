"""与恢复器解耦的平面距离/TTC 触发指标。"""
from __future__ import annotations

import math
import numpy as np


def constant_velocity_ttc(relative_position, relative_velocity, radius: float) -> float:
    """冻结当前圆形边界，求恒速首次接触时间；不接触返回 inf。"""
    r = np.asarray(relative_position, dtype=float)
    v = np.asarray(relative_velocity, dtype=float)
    if not np.isfinite(radius) or radius <= 0 or not np.all(np.isfinite(r)) or not np.all(np.isfinite(v)):
        raise ValueError("TTC 输入必须有限且半径为正")
    c = float(r @ r) - radius * radius
    if c <= 0:
        return 0.0
    a, b = float(v @ v), float(r @ v)
    if a <= 1e-12 or b >= 0:
        return math.inf
    discriminant = b * b - a * c
    if discriminant < 0:
        return math.inf
    # 等价于 (-b-sqrt(discriminant))/a，避免远处近切线的相消。
    return c / (-b + math.sqrt(discriminant))


def proximity_trigger(positions, velocities, boundaries, *, distance_m=None, ttc_s=None):
    """只读取当前 RA 配对状态；不修改约束、恢复动作或滞回。"""
    for (i, j), radius in boundaries.items():
        r = np.asarray(positions[i]) - np.asarray(positions[j])
        if distance_m is not None and float(np.linalg.norm(r)) <= distance_m:
            return "distance_threshold"
        if ttc_s is not None:
            v = np.asarray(velocities[i]) - np.asarray(velocities[j])
            if constant_velocity_ttc(r, v, radius) <= ttc_s:
                return "ttc_threshold"
    return None
