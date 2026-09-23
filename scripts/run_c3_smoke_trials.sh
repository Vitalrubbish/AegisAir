#!/usr/bin/env bash
# Drive the C3 closed-loop smoke (6 trials) with the feedforward execution model.
#
# Caller must already run: MQTT broker, GCS heartbeat (18572/18573), and the
# `aegisair-adapters` bridge.  Each physical trial gets a fresh PX4/Gazebo SITL.
set -euo pipefail

GATE0="/Users/lijiajun/Documents/ChatGPT/无人机论文尝试/safety_margin_scheduler_gate0"
REPO="/Users/lijiajun/Documents/drone/AegisAir"
OUT="/Volumes/Expansion/Aegis/c3_closed_loop_smoke_ff_v4"
MANIFEST="$REPO/configs/c3_closed_loop_smoke_v1.json"
mkdir -p "$OUT"

wait_px4_gone() {
  for _ in $(seq 1 30); do
    if ! pgrep -x px4 >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

run_trial() {
  local trial="$1"
  echo "===== TRIAL $trial ====="
  local launch_log="$OUT/${trial}_launch.log"
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
    echo "LAUNCH FAILED for $trial"
    cat "$launch_log"
    return 1
  fi
  echo "state_dir=$sd"
  sleep 14
  (
    cd "$REPO"
    conda run -n eai-swarm python marllib/run_c3_gazebo.py \
      --manifest "$MANIFEST" \
      --out-dir "$OUT/$trial" \
      --trial-id "$trial" \
      --velocity-command-mode feedforward_tau \
      --tau-command-s 0.7
  )
  (
    cd "$GATE0"
    bash scripts/stop_multi_sitl.sh "$sd"
  ) 2>&1 | tail -1
  pkill -x px4 2>/dev/null || true
  pkill -f "gz sim -r" 2>/dev/null || true
  wait_px4_gone || { echo "px4 linger after $trial"; return 1; }
  sleep 2
}

for t in smoke01 smoke02 smoke03 smoke04 smoke05 smoke06; do
  run_trial "$t"
done
echo "ALL DONE"
