#!/usr/bin/env bash
# Start fresh two-UAV SITL for one frozen C3 validation trial.
# The Gazebo seed is a real simulator input, not manifest-only metadata.
set -euo pipefail

GATE0="/Users/lijiajun/Documents/ChatGPT/无人机论文尝试/safety_margin_scheduler_gate0"
seed="${1:?usage: launch_c3_seeded_sitl.sh GAZEBO_SEED}"
[[ "$seed" =~ ^[0-9]+$ ]] || { echo "seed must be an unsigned integer" >&2; exit 2; }

export C3_GAZEBO_SEED="$seed"
exec bash "$GATE0/scripts/launch_multi_sitl_pose.sh" S1 2,3
