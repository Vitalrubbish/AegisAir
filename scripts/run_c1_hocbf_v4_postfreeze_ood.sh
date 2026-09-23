#!/usr/bin/env bash
# 独立运行冻结的 C1-v4 OOD 包络；不复用或覆盖主实验目录。
set -euo pipefail

REPO="/Users/lijiajun/Documents/drone/AegisAir"
GATE0="/Users/lijiajun/Documents/ChatGPT/无人机论文尝试/safety_margin_scheduler_gate0"
MANIFEST="${OOD_MANIFEST:-$REPO/configs/c1_hocbf_v4_px4_postfreeze_ood_v1.json}"
OUT="${OOD_OUT:-/Volumes/Expansion/Aegis/c1_hocbf_v4_px4_postfreeze_ood_v1}"
PY="/opt/anaconda3/envs/eai-swarm/bin/python"
mkdir -p "$OUT"
if [[ -e "$OUT/STARTED" ]]; then
  cmp -s "$MANIFEST" "$OUT/manifest.json" || {
    echo "refusing resume: frozen manifest differs from recorded copy" >&2; exit 2;
  }
  echo "RESUME: retaining integrity-checked completed conditions"
else
  touch "$OUT/STARTED"
  cp "$MANIFEST" "$OUT/manifest.json"
  shasum -a 256 "$MANIFEST" > "$OUT/manifest.sha256"
fi

HB2=""
HB3=""
STATE_DIR=""
TRIAL_PIDS=""

stop_tree() {
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do
    stop_tree "$child"
  done
  kill -TERM "$pid" 2>/dev/null || true
}

stop_trial() {
  local pid
  for pid in $TRIAL_PIDS; do stop_tree "$pid"; done
  for _ in $(seq 1 40); do
    local alive=0
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

"$PY" "$GATE0/scripts/gcs_heartbeat.py" --port 18572 --duration-s 14400 >"$OUT/gcs18572.log" 2>&1 & HB2=$!
"$PY" "$GATE0/scripts/gcs_heartbeat.py" --port 18573 --duration-s 14400 >"$OUT/gcs18573.log" 2>&1 & HB3=$!

run_condition() {
  local trial="$1" seed="$2" method="$3" condition_out="$OUT/${trial}_${method}"
  if [[ -f "$condition_out/summary.json" ]]; then
    "$PY" - "$condition_out/summary.json" "$trial" "$method" <<'PY'
import json, sys
row = json.load(open(sys.argv[1], encoding="utf-8"))["trials"]
if len(row) != 1 or row[0]["trial_id"] != sys.argv[2] or row[0]["method"] != sys.argv[3]:
    raise SystemExit("existing OOD condition summary failed integrity check")
PY
    echo "SKIP completed $trial $method"
    return 0
  fi
  [[ ! -e "$condition_out" ]] || { echo "partial condition output: $condition_out" >&2; exit 2; }
  local launch_log="$OUT/${trial}_${method}_launch.log"
  STATE_DIR=""
  (cd "$GATE0" && C3_GAZEBO_SEED="$seed" POSES='2=0,-3,0.5;3=0,3,0.5' bash scripts/launch_multi_sitl_pose.sh S1 2,3 >"$launch_log" 2>&1) &
  # Rootfs is copied to the external drive for every fresh physical trial.
  # On this workstation that can take about two minutes; do not mistake it for
  # a failed PX4 launch and kill the child processes mid-initialisation.
  for _ in $(seq 1 300); do
    STATE_DIR=$(sed -n 's/.*state_dir=\([^ ]*\).*/\1/p' "$launch_log" | head -1)
    [[ -z "$STATE_DIR" ]] || break
    sleep 1
  done
  [[ -n "$STATE_DIR" ]] || { echo "launch failed after 300 s: $trial $method" >&2; exit 2; }
  # STATE contains only wrapper PIDs started for this physical condition.
  # Capture them before teardown so no unrelated PX4 process can be affected.
  # shellcheck disable=SC1090
  source "$STATE_DIR/STATE"
  TRIAL_PIDS="$px4_pids $gazebo_pid"
  sleep 12
  (cd "$REPO" && conda run -n eai-swarm python marllib/run_c1_sota_cbf_gazebo.py --manifest "$MANIFEST" --out-dir "$condition_out" --trial-id "$trial" --method "$method")
  stop_trial
  STATE_DIR=""
}

while IFS=$'\t' read -r trial scenario seed methods; do
  IFS=',' read -r -a method_list <<< "$methods"
  for method in "${method_list[@]}"; do run_condition "$trial" "$seed" "$method"; done
  "$PY" - "$OUT" "$trial" <<'PY'
import json, pathlib, sys
root, trial = map(pathlib.Path, sys.argv[1:])
summary = json.load(open(root / f"{trial}_AEGIS_HOCBF_V4" / "summary.json"))["trials"][0]
if summary["collision"] or not summary["mission_complete"] or summary["min_rho"] <= 0.0:
    raise SystemExit("OOD V4 stop rule reached after paired trial: " + trial)
PY
done < <(
  "$PY" - "$MANIFEST" <<'PY'
import json, sys
for trial in json.load(open(sys.argv[1]))["trials"]:
    print(trial["trial_id"], trial["scenario_id"], trial["seed"], ",".join(trial["condition_order"]), sep="\t")
PY
)

conda run -n eai-swarm python "$REPO/marllib/analyze_c1_hocbf_v4_ood.py" --manifest "$MANIFEST" --root "$OUT" --out "$OUT/audit.json"
touch "$OUT/COMPLETE"
echo "ALL DONE"
