#!/usr/bin/env bash
# Confirm the execution-model-mismatch attribution by comparing three velocity
# command mechanisms on the C3 drone_failure scenario.  Each mode gets a fresh
# PX4/Gazebo SITL instance so EKF/offboard state does not leak between modes.
set -euo pipefail

GATE0="/Users/lijiajun/Documents/ChatGPT/无人机论文尝试/safety_margin_scheduler_gate0"
REPO="/Users/lijiajun/Documents/drone/AegisAir"
OUT="/Volumes/Expansion/Aegis/c3_velocity_command_confirm_v4"
MANIFEST="$REPO/configs/c3_velocity_command_confirm_v1.json"
mkdir -p "$OUT"

wait_px4_gone() {
  for _ in $(seq 1 120); do
    if ! pgrep -x px4 >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

run_mode() {
  local mode="$1"
  echo "===== MODE $mode ====="
  local launch_log="$OUT/${mode}_launch.log"
  (
    cd "$GATE0"
    POSES='2=0,-3,0.5;3=0,3,0.5' \
      bash scripts/launch_multi_sitl_pose.sh S1 2,3 >"$launch_log" 2>&1
  ) &
  local sd=""
  for _ in $(seq 1 40); do
    sd=$(sed -n 's/.*state_dir=\([^ ]*\).*/\1/p' "$launch_log" | head -1)
    [ -n "$sd" ] && break
    sleep 1
  done
  if [ -z "$sd" ]; then
    echo "LAUNCH FAILED for $mode"; cat "$launch_log"; return 1
  fi
  echo "state_dir=$sd"
  sleep 14
  (
    cd "$REPO"
    conda run -n eai-swarm python marllib/run_c3_gazebo.py \
      --manifest "$MANIFEST" \
      --out-dir "$OUT/$mode" \
      --trial-id confirm01 \
      --velocity-command-mode "$mode"
  )
  (
    cd "$GATE0"
    bash scripts/stop_multi_sitl.sh "$sd"
  ) 2>&1 | tail -1
  wait_px4_gone || { echo "px4 did not stop for $mode"; return 1; }
  sleep 1
}

for m in safe_action feedforward_tau nominal; do
  run_mode "$m"
done
echo "ALL DONE"
