#!/usr/bin/env bash
# Frozen C1 active-CBF PX4 validation. Every method-condition gets fresh SITL.
set -euo pipefail

REPO="/Users/lijiajun/Documents/drone/AegisAir"
GATE0="/Users/lijiajun/Documents/ChatGPT/无人机论文尝试/safety_margin_scheduler_gate0"
MANIFEST="${C1_CBF_MANIFEST:-$REPO/configs/c1_sota_cbf_px4_validation_v1.json}"
OUT="${C1_CBF_OUT:-/Volumes/Expansion/Aegis/c1_sota_cbf_px4_validation_v1}"
mkdir -p "$OUT"
HEARTBEAT="$GATE0/scripts/gcs_heartbeat.py"
HB2=""
HB3=""
CURRENT_STATE_DIR=""

stop_px4() {
  local state_dir="${1:-}"
  if [[ -n "$state_dir" ]]; then
    bash "$GATE0/scripts/stop_multi_sitl.sh" "$state_dir" >/dev/null 2>&1 || true
  fi
  pkill -x px4 2>/dev/null || true
  pkill -f "gz sim -r" 2>/dev/null || true
  for _ in $(seq 1 30); do
    pgrep -x px4 >/dev/null || return 0
    sleep 1
  done
  return 1
}

cleanup_all() {
  stop_px4 "$CURRENT_STATE_DIR" || true
  [[ -z "$HB2" ]] || kill "$HB2" 2>/dev/null || true
  [[ -z "$HB3" ]] || kill "$HB3" 2>/dev/null || true
}

/opt/anaconda3/envs/eai-swarm/bin/python "$HEARTBEAT" \
  --port 18572 --duration-s 14400 >"$OUT/gcs18572.log" 2>&1 &
HB2=$!
/opt/anaconda3/envs/eai-swarm/bin/python "$HEARTBEAT" \
  --port 18573 --duration-s 14400 >"$OUT/gcs18573.log" 2>&1 &
HB3=$!
trap cleanup_all EXIT INT TERM

mapfile_cmd() {
  /opt/anaconda3/envs/eai-swarm/bin/python - "$MANIFEST" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
for trial in m["trials"]:
    for method in trial["condition_order"]:
        print(trial["trial_id"], trial["seed"], method)
PY
}

while read -r trial seed method; do
  condition_out="$OUT/${trial}_${method}"
  if [[ -f "$condition_out/summary.json" ]]; then
    echo "SKIP completed $trial $method"
    continue
  fi
  launch_log="$OUT/${trial}_${method}_launch.log"
  state_dir=""
  echo "START $trial seed=$seed method=$method"
  (
    cd "$GATE0"
    C3_GAZEBO_SEED="$seed" POSES='2=0,-3,0.5;3=0,3,0.5' \
      bash scripts/launch_multi_sitl_pose.sh S1 2,3 >"$launch_log" 2>&1
  ) &
  for _ in $(seq 1 45); do
    state_dir=$(sed -n 's/.*state_dir=\([^ ]*\).*/\1/p' "$launch_log" | head -1)
    [[ -n "$state_dir" ]] && break
    sleep 1
  done
  [[ -n "$state_dir" ]] || { echo "launch failed: $trial $method"; exit 2; }
  CURRENT_STATE_DIR="$state_dir"
  sleep 12
  (
    cd "$REPO"
    conda run -n eai-swarm python marllib/run_c1_sota_cbf_gazebo.py \
      --manifest "$MANIFEST" --out-dir "$condition_out" \
      --trial-id "$trial" --method "$method"
  )
  if [[ "${C1_CBF_STOP_ALL:-0}" == 1 || "$method" == AEGIS_HOCBF_V2 || "$method" == AEGIS_HOCBF_V3 ]]; then
    /opt/anaconda3/envs/eai-swarm/bin/python - "$condition_out/summary.json" <<'PY'
import json, sys
row = json.load(open(sys.argv[1]))["trials"][0]
if row["collision"] or not row["mission_complete"] or row["min_rho"] <= 0.0:
    raise SystemExit(
        "STOP_RULE collision=%s complete=%s min_rho=%s"
        % (row["collision"], row["mission_complete"], row["min_rho"])
    )
PY
  fi
  stop_px4 "$state_dir"
  CURRENT_STATE_DIR=""
  state_dir=""
  echo "DONE $trial $method"
done < <(mapfile_cmd)

kill "$HB2" "$HB3" 2>/dev/null || true
HB2=""
HB3=""
trap - EXIT INT TERM
echo "ALL DONE"
