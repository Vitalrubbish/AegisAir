#!/usr/bin/env bash
set -euo pipefail

REPO="/Users/lijiajun/Documents/drone/AegisAir"
MANIFEST="${1:-$REPO/configs/c3_group_slot_4uav_calibration_smoke_v1.json}"
OUT="${2:-/Volumes/Expansion/Aegis/c3_group_slot_4uav_calibration_smoke_v1}"

export C3_RUNNER="marllib/run_c3_group_slot_gazebo.py"
export C3_GAZEBO_SEED_OVERRIDE="9901"
exec bash "$REPO/scripts/run_c3_reservation_4uav_smoke.sh" "$MANIFEST" "$OUT"
