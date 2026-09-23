#!/usr/bin/env bash
# 冻结 C2-v4 execution bridge：每个 condition 使用 fresh SITL。
set -euo pipefail

REPO="/Users/lijiajun/Documents/drone/AegisAir"
GATE0="/Users/lijiajun/Documents/ChatGPT/无人机论文尝试/safety_margin_scheduler_gate0"
MANIFEST="$REPO/configs/c2_v4_execution_bridge_v1.json"
OUT="/Volumes/Expansion/Aegis/c2_v4_execution_bridge_v1"
HEARTBEAT="$GATE0/scripts/gcs_heartbeat.py"
HB2=""
HB3=""
CURRENT_STATE_DIR=""

mkdir -p "$OUT"

stop_px4() {
  local state_dir="${1:-}"
  if [[ -n "$state_dir" ]]; then
    bash "$GATE0/scripts/stop_multi_sitl.sh" "$state_dir" >/dev/null 2>&1 || true
  fi
  pkill -x px4 2>/dev/null || true
  pkill -f "gz sim -r" 2>/dev/null || true
}

cleanup_all() {
  stop_px4 "$CURRENT_STATE_DIR"
  [[ -z "$HB2" ]] || kill "$HB2" 2>/dev/null || true
  [[ -z "$HB3" ]] || kill "$HB3" 2>/dev/null || true
}

/opt/anaconda3/envs/eai-swarm/bin/python "$HEARTBEAT" --port 18572 --duration-s 14400 >"$OUT/gcs18572.log" 2>&1 &
HB2=$!
/opt/anaconda3/envs/eai-swarm/bin/python "$HEARTBEAT" --port 18573 --duration-s 14400 >"$OUT/gcs18573.log" 2>&1 &
HB3=$!
trap cleanup_all EXIT INT TERM

while read -r trial seed method; do
  condition_out="$OUT/${trial}_${method}"
  [[ -f "$condition_out/summary.json" ]] && { echo "SKIP completed $trial $method"; continue; }
  echo "START $trial seed=$seed method=$method"
  launch_log="$OUT/${trial}_${method}_launch.log"
  (
    cd "$GATE0"
    C3_GAZEBO_SEED="$seed" POSES='2=0,-3,0.5;3=0,3,0.5' bash scripts/launch_multi_sitl_pose.sh S1 2,3 >"$launch_log" 2>&1
  ) &
  state_dir=""
  for _ in $(seq 1 45); do
    state_dir=$(sed -n 's/.*state_dir=\([^ ]*\).*/\1/p' "$launch_log" | head -1)
    [[ -n "$state_dir" ]] && break
    sleep 1
  done
  [[ -n "$state_dir" ]] || exit 2
  CURRENT_STATE_DIR="$state_dir"
  sleep 12
  cd "$REPO"
  conda run -n eai-swarm python marllib/run_c1_sota_cbf_gazebo.py --manifest "$MANIFEST" --out-dir "$condition_out" --trial-id "$trial" --method "$method"
  /opt/anaconda3/envs/eai-swarm/bin/python - "$condition_out/summary.json" <<'PY'
import json, sys
row = json.load(open(sys.argv[1]))["trials"][0]
if row["collision"]:
    raise SystemExit("STOP_RULE collision")
PY
  stop_px4 "$state_dir"
  CURRENT_STATE_DIR=""
done < <(/opt/anaconda3/envs/eai-swarm/bin/python - "$MANIFEST" <<'PY'
import json, sys
for trial in json.load(open(sys.argv[1]))["trials"]:
    for method in trial["condition_order"]:
        print(trial["trial_id"], trial["seed"], method)
PY
)

kill "$HB2" "$HB3" 2>/dev/null || true
trap - EXIT INT TERM
echo "ALL DONE"
