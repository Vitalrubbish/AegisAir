#!/usr/bin/env bash
# Failure-aware recoverability admission development/calibration；每个条件 fresh PX4/Gazebo。
set -euo pipefail

REPO="/Users/lijiajun/Documents/drone/AegisAir"
GATE0="/Users/lijiajun/Documents/ChatGPT/无人机论文尝试/safety_margin_scheduler_gate0"
MANIFEST="${RADM_MANIFEST:-$REPO/configs/c_recoverability_admission_calibration_v1.json}"
OUT="${RADM_OUT:-/Volumes/Expansion/Aegis/c_recoverability_admission_calibration_v1}"
PY="/opt/anaconda3/envs/eai-swarm/bin/python"
DOCKER="/Applications/Docker.app/Contents/Resources/bin/docker"
WAIT="$REPO/scripts/wait_for_px4_telemetry.py"

mkdir -p "$OUT"
if [[ -e "$OUT/STARTED" ]]; then
  cmp -s "$MANIFEST" "$OUT/manifest.json" || {
    echo "frozen manifest mismatch: $OUT" >&2
    exit 2
  }
else
  touch "$OUT/STARTED"
  cp "$MANIFEST" "$OUT/manifest.json"
  shasum -a 256 "$MANIFEST" >"$OUT/manifest.sha256"
fi

HB2=""
HB3=""
TRIAL_PIDS=""
ADAPTER=""

stop_tree() {
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do stop_tree "$child"; done
  kill -TERM "$pid" 2>/dev/null || true
}

stop_trial() {
  local pid alive
  if [[ -n "$ADAPTER" ]]; then
    "$DOCKER" stop "$ADAPTER" >/dev/null 2>&1 || true
    "$DOCKER" rm "$ADAPTER" >/dev/null 2>&1 || true
    ADAPTER=""
  fi
  for pid in $TRIAL_PIDS; do stop_tree "$pid"; done
  for _ in $(seq 1 80); do
    alive=0
    for pid in $TRIAL_PIDS; do kill -0 "$pid" 2>/dev/null && alive=1; done
    [[ "$alive" == 0 ]] && break
    sleep 0.25
  done
  for pid in $TRIAL_PIDS; do kill -KILL "$pid" 2>/dev/null || true; done
  TRIAL_PIDS=""
}

cleanup() {
  stop_trial
  [[ -z "$HB2" ]] || kill "$HB2" 2>/dev/null || true
  [[ -z "$HB3" ]] || kill "$HB3" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

"$PY" "$GATE0/scripts/gcs_heartbeat.py" --port 18572 --duration-s 43200 >"$OUT/gcs18572.log" 2>&1 &
HB2=$!
"$PY" "$GATE0/scripts/gcs_heartbeat.py" --port 18573 --duration-s 43200 >"$OUT/gcs18573.log" 2>&1 &
HB3=$!

while IFS=$'\t' read -r trial seed geometry condition world poses origin2 origin3; do
  condition_out="$OUT/${trial}_${condition}"
  if [[ -f "$condition_out/summary.json" ]]; then
    echo "SKIP completed $trial $condition"
    continue
  fi
  [[ ! -e "$condition_out" ]] || {
    echo "partial condition output requires audit: $condition_out" >&2
    exit 2
  }
  echo "===== RADM $trial geometry=$geometry condition=$condition seed=$seed ====="
  launch_log="$OUT/${trial}_${condition}_launch.log"
  (
    cd "$GATE0"
    C3_GAZEBO_SEED="$seed" POSES="$poses" \
      bash scripts/launch_multi_sitl_pose.sh "$world" 2,3 >"$launch_log" 2>&1
  ) &
  launcher=$!
  state_dir=""
  for _ in $(seq 1 300); do
    state_dir=$(sed -n 's/.*state_dir=\([^ ]*\).*/\1/p' "$launch_log" | head -1 || true)
    [[ -n "$state_dir" ]] && break
    kill -0 "$launcher" 2>/dev/null || break
    sleep 1
  done
  [[ -n "$state_dir" ]] || {
    touch "$OUT/${trial}_${condition}.invalid_launch"
    stop_trial
    continue
  }
  source "$state_dir/STATE"
  TRIAL_PIDS="$launcher $px4_pids $gazebo_pid"
  safe_name=$(echo "${trial}_${condition}" | tr '[:upper:]_' '[:lower:]-')
  ADAPTER="aegisair-radm-${safe_name}"
  "$DOCKER" run -d --name "$ADAPTER" -p 127.0.0.1:8889:8889/udp \
    -e XRCE_UDP_PORT=8889 -e ADAPTER_INSTANCES='2 3' \
    -e ADAPTER_ARGS='--no-read-only --mqtt-host host.docker.internal --mqtt-port 1883 --control-rate-hz 20 --telemetry-rate-hz 20' \
    -e ORIGIN_OFFSET_2="$origin2" -e ORIGIN_OFFSET_3="$origin3" \
    aegisair-px4-bridge:humble >"$OUT/${trial}_${condition}_adapter_id.txt"
  if ! "$PY" "$WAIT" --drone-ids 2 3 --timeout-s 90 >"$OUT/${trial}_${condition}_telemetry.log" 2>&1; then
    touch "$OUT/${trial}_${condition}.invalid_telemetry"
    stop_trial
    continue
  fi
  if ! (
    cd "$REPO"
    conda run --no-capture-output -n eai-swarm python \
      marllib/run_c_recoverability_admission_gazebo.py \
      --manifest "$MANIFEST" --out-dir "$condition_out" \
      --trial-id "$trial" --condition "$condition"
  ) >"$OUT/${trial}_${condition}_runner.log" 2>&1; then
    touch "$OUT/${trial}_${condition}.invalid_runner"
    stop_trial
    continue
  fi
  stop_trial
  sleep 2
done < <("$PY" "$REPO/scripts/c_recoverability_admission_launch_table.py" "$MANIFEST")

cd "$REPO"
conda run --no-capture-output -n eai-swarm python \
  marllib/analyze_c_recoverability_admission_calibration.py \
  --manifest "$MANIFEST" --root "$OUT"
