#!/usr/bin/env bash
# C3-STR 单 seed 独立 calibration smoke；复用已验证的四机 fresh-SITL 启动路径。
set -euo pipefail

REPO="/Users/lijiajun/Documents/drone/AegisAir"
MANIFEST="${1:-$REPO/configs/c3_str_4uav_calibration_smoke_v1.json}"
OUT="${2:-/Volumes/Expansion/Aegis/c3_str_4uav_calibration_smoke_v1}"

export C3_RUNNER="marllib/run_c3_space_time_reservation_gazebo.py"
export C3_GAZEBO_SEED_OVERRIDE="9701"
exec bash "$REPO/scripts/run_c3_reservation_4uav_smoke.sh" "$MANIFEST" "$OUT"
