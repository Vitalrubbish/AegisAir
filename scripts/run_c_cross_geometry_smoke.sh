#!/usr/bin/env bash
# 三种失效几何 calibration smoke；每个 paired trial 使用 fresh PX4/Gazebo。
set -uo pipefail

REPO="/Users/lijiajun/Documents/drone/AegisAir"
GATE0="/Users/lijiajun/Documents/ChatGPT/无人机论文尝试/safety_margin_scheduler_gate0"
PY="/opt/anaconda3/envs/eai-swarm/bin/python"
DOCKER="/Applications/Docker.app/Contents/Resources/bin/docker"
MANIFEST="${1:?usage: $0 MANIFEST OUTDIR}"
OUT="${2:?usage: $0 MANIFEST OUTDIR}"
HEARTBEAT="$GATE0/scripts/gcs_heartbeat.py"
HB2=""
HB3=""
state_dir=""
launch_pid=""

mkdir -p "$OUT"
if [[ -e "$OUT/STARTED" ]]; then
  cmp -s "$MANIFEST" "$OUT/manifest.json" || {
    echo "resume manifest mismatch: $OUT" >&2
    exit 2
  }
  if [[ -e "$OUT/COMPLETE" ]]; then
    mv "$OUT/COMPLETE" "$OUT/PREMATURE_COMPLETE_BEFORE_RESUME"
  fi
else
  touch "$OUT/STARTED"
  cp "$MANIFEST" "$OUT/manifest.json"
  shasum -a 256 "$MANIFEST" >"$OUT/manifest.sha256"
fi

stop_trial() {
  "$DOCKER" stop aegisair-cgeo-adapters >/dev/null 2>&1 || true
  "$DOCKER" rm aegisair-cgeo-adapters >/dev/null 2>&1 || true
  if [[ -n "$state_dir" && -d "$state_dir" ]]; then
    px4_pids=$(sed -n 's/^px4_pids="\(.*\)"/\1/p' "$state_dir/STATE" || true)
    gazebo_pid=$(sed -n 's/^gazebo_pid=//p' "$state_dir/STATE" || true)
    (cd "$GATE0" && bash scripts/stop_multi_sitl.sh "$state_dir") >/dev/null 2>&1 || true
    for _ in $(seq 1 120); do
      alive=0
      for pid in $px4_pids $gazebo_pid; do
        kill -0 "$pid" 2>/dev/null && alive=1
      done
      (( alive == 0 )) && break
      sleep .25
    done
    for pid in $px4_pids $gazebo_pid; do
      kill -KILL "$pid" 2>/dev/null || true
    done
    # PX4 may briefly outlive its launcher PID while macOS reaps the process.
    # Wait by exact executable name; never kill unrelated command-line matches.
    for _ in $(seq 1 120); do
      pgrep -x px4 >/dev/null 2>&1 || break
      sleep .25
    done
    if pgrep -x px4 >/dev/null 2>&1; then
      echo "PX4 cleanup did not quiesce after recorded trial PIDs" >&2
      return 1
    fi
  fi
  if [[ -n "$launch_pid" ]]; then
    wait "$launch_pid" 2>/dev/null || true
  fi
  state_dir=""
  launch_pid=""
}

cleanup() {
  stop_trial
  [[ -z "$HB2" ]] || kill "$HB2" 2>/dev/null || true
  [[ -z "$HB3" ]] || kill "$HB3" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

"$PY" "$HEARTBEAT" --port 18572 --duration-s 14400 >"$OUT/gcs18572.log" 2>&1 &
HB2=$!
"$PY" "$HEARTBEAT" --port 18573 --duration-s 14400 >"$OUT/gcs18573.log" 2>&1 &
HB3=$!

while IFS=$'\t' read -r trial seed geometry world poses origin2 origin3; do
  if [[ -f "$OUT/$trial/summary.json" ]]; then
    echo "SKIP completed $trial"
    continue
  fi
  echo "===== C-GEO $trial geometry=$geometry seed=$seed ====="
  launch_log="$OUT/${trial}_launch.log"
  state_dir=""
  (
    cd "$GATE0"
    POSES="$poses" C3_GAZEBO_SEED="$seed" \
      bash scripts/launch_multi_sitl_pose.sh "$world" 2,3 >"$launch_log" 2>&1
  ) &
  launch_pid=$!
  for _ in $(seq 1 300); do
    state_dir=$(sed -n 's/.*state_dir=\([^ ]*\).*/\1/p' "$launch_log" | head -1 || true)
    [[ -n "$state_dir" ]] && break
    kill -0 "$launch_pid" 2>/dev/null || break
    sleep 1
  done
  if [[ -z "$state_dir" ]]; then
    touch "$OUT/${trial}.invalid_launch"
    stop_trial
    continue
  fi

  "$DOCKER" run -d --name aegisair-cgeo-adapters \
    -p 127.0.0.1:8889:8889/udp \
    -e XRCE_UDP_PORT=8889 \
    -e ADAPTER_INSTANCES='2 3' \
    -e ADAPTER_ARGS='--no-read-only --mqtt-host host.docker.internal --mqtt-port 1883 --control-rate-hz 20 --telemetry-rate-hz 20' \
    -e ORIGIN_OFFSET_2="$origin2" \
    -e ORIGIN_OFFSET_3="$origin3" \
    aegisair-px4-bridge:humble >"$OUT/${trial}_adapter_id.txt"
  sleep 15

  trial_out="$OUT/$trial"
  if ! (
    cd "$REPO"
    conda run -n eai-swarm python marllib/run_c_cross_geometry_gazebo.py \
      --manifest "$MANIFEST" --out-dir "$trial_out" --trial-id "$trial"
  ); then
    touch "$OUT/${trial}.invalid_runner"
  fi
  stop_trial
  sleep 2
done < <(
  cd "$REPO"
  "$PY" scripts/c_cross_geometry_launch_table.py "$MANIFEST"
)

expected=$("$PY" -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["trials"]))' "$MANIFEST")
found=$(find "$OUT" -mindepth 2 -maxdepth 2 -name summary.json | wc -l | tr -d ' ')
if [[ "$found" == "$expected" ]]; then
  touch "$OUT/COMPLETE"
  echo "C cross-geometry calibration smoke COMPLETE"
else
  echo "C cross-geometry calibration smoke INCOMPLETE: $found/$expected" >&2
  exit 1
fi
