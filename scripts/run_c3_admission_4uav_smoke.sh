#!/usr/bin/env bash
# 四机 C3-Admission R0/R1/R2 calibration；仅运行一个 fresh PX4/Gazebo 栈。
set -uo pipefail

REPO="/Users/lijiajun/Documents/drone/AegisAir"
GATE0="/Users/lijiajun/Documents/ChatGPT/无人机论文尝试/safety_margin_scheduler_gate0"
PY="/opt/anaconda3/envs/eai-swarm/bin/python"
DOCKER="/Applications/Docker.app/Contents/Resources/bin/docker"
MANIFEST="${1:?usage: $0 MANIFEST OUTROOT}"
OUT="${2:?usage: $0 MANIFEST OUTROOT}"
HEARTBEAT="$GATE0/scripts/gcs_heartbeat.py"
state_dir=""
launch_pid=""
adapter_name="aegisair-c3-admission-adapters"
heartbeat_pids=()

if [[ -e "$OUT" ]]; then
  echo "拒绝覆盖已有输出目录：$OUT" >&2
  exit 2
fi
mkdir -p "$OUT"
cp "$MANIFEST" "$OUT/manifest.json"
shasum -a 256 "$MANIFEST" >"$OUT/manifest.sha256"
touch "$OUT/STARTED"

stop_stack() {
  "$DOCKER" logs "$adapter_name" >"$OUT/adapter.log" 2>&1 || true
  "$DOCKER" stop "$adapter_name" >/dev/null 2>&1 || true
  "$DOCKER" rm "$adapter_name" >/dev/null 2>&1 || true
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
    for _ in $(seq 1 120); do
      pgrep -x px4 >/dev/null 2>&1 || break
      sleep .25
    done
  fi
  [[ -z "$launch_pid" ]] || wait "$launch_pid" 2>/dev/null || true
}

cleanup() {
  stop_stack
  for pid in "${heartbeat_pids[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

for port in 18572 18573 18574 18575; do
  "$PY" "$HEARTBEAT" --port "$port" --duration-s 14400 \
    >"$OUT/gcs${port}.log" 2>&1 &
  heartbeat_pids+=("$!")
done

(
  cd "$GATE0"
  POSES='2=-0.8,-3,0.5;3=0.8,3,0.5;4=0.8,-3,0.5;5=-0.8,3,0.5' \
  C3_GAZEBO_SEED=9511 \
    bash scripts/launch_multi_sitl_pose.sh S1 2,3,4,5 >"$OUT/launch.log" 2>&1
) &
launch_pid=$!
for _ in $(seq 1 300); do
  state_dir=$(sed -n 's/.*state_dir=\([^ ]*\).*/\1/p' "$OUT/launch.log" | head -1 || true)
  [[ -n "$state_dir" ]] && break
  kill -0 "$launch_pid" 2>/dev/null || break
  sleep 1
done
if [[ -z "$state_dir" ]]; then
  touch "$OUT/invalid_launch"
  exit 1
fi

"$DOCKER" run -d --name "$adapter_name" \
  -p 127.0.0.1:8889:8889/udp \
  -e XRCE_UDP_PORT=8889 \
  -e ADAPTER_INSTANCES='2 3 4 5' \
  -e ADAPTER_ARGS='--no-read-only --mqtt-host host.docker.internal --mqtt-port 1883 --control-rate-hz 20 --telemetry-rate-hz 20' \
  -e ORIGIN_OFFSET_2='-3,-0.8,0' \
  -e ORIGIN_OFFSET_3='3,0.8,0' \
  -e ORIGIN_OFFSET_4='-3,0.8,0' \
  -e ORIGIN_OFFSET_5='3,-0.8,0' \
  aegisair-px4-bridge:humble >"$OUT/adapter_id.txt"
sleep 30

(
  cd "$REPO"
  conda run -n eai-swarm python marllib/run_c3_admission_gazebo.py \
    --manifest "$MANIFEST" --output "$OUT/calibration"
) | tee "$OUT/runner.log"
runner_status=${PIPESTATUS[0]}
if (( runner_status != 0 )); then
  touch "$OUT/invalid_runner"
  exit "$runner_status"
fi
touch "$OUT/COMPLETE"
