#!/usr/bin/env bash
# Frozen four-condition C1 ablation. Each condition gets a fresh PX4/Gazebo stack.
set -euo pipefail

REPO="/Users/lijiajun/Documents/drone/AegisAir"
GATE0="/Users/lijiajun/Documents/ChatGPT/无人机论文尝试/safety_margin_scheduler_gate0"
MANIFEST="${ABLATION_MANIFEST:-$REPO/configs/c1_hocbf_v4_ablation_sealed_v1.json}"
OUT="${ABLATION_OUT:-/Volumes/Expansion/Aegis/c1_hocbf_v4_ablation_sealed_v1}"
PY="/opt/anaconda3/envs/eai-swarm/bin/python"
DOCKER="/Applications/Docker.app/Contents/Resources/bin/docker"
TELEMETRY_WAIT="$REPO/scripts/wait_for_px4_telemetry.py"

mkdir -p "$OUT"
if [[ -e "$OUT/STARTED" ]]; then
  cmp -s "$MANIFEST" "$OUT/manifest.json" || { echo "frozen manifest mismatch" >&2; exit 2; }
else
  touch "$OUT/STARTED"
  cp "$MANIFEST" "$OUT/manifest.json"
  shasum -a 256 "$MANIFEST" > "$OUT/manifest.sha256"
fi

HB2=""; HB3=""; STATE_DIR=""; TRIAL_PIDS=""; ADAPTER_NAME=""
stop_tree() { local pid="$1" child; for child in $(pgrep -P "$pid" 2>/dev/null || true); do stop_tree "$child"; done; kill -TERM "$pid" 2>/dev/null || true; }
stop_trial() {
  local pid
  if [[ -n "$ADAPTER_NAME" ]]; then
    "$DOCKER" stop "$ADAPTER_NAME" >/dev/null 2>&1 || true
    "$DOCKER" rm "$ADAPTER_NAME" >/dev/null 2>&1 || true
    ADAPTER_NAME=""
  fi
  for pid in $TRIAL_PIDS; do stop_tree "$pid"; done
  for _ in $(seq 1 40); do
    local alive=0; for pid in $TRIAL_PIDS; do kill -0 "$pid" 2>/dev/null && alive=1; done
    [[ "$alive" == 0 ]] && break; sleep 0.25
  done
  for pid in $TRIAL_PIDS; do kill -KILL "$pid" 2>/dev/null || true; done
  TRIAL_PIDS=""
}
cleanup() { stop_trial; [[ -z "$HB2" ]] || kill "$HB2" 2>/dev/null || true; [[ -z "$HB3" ]] || kill "$HB3" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

"$PY" "$GATE0/scripts/gcs_heartbeat.py" --port 18572 --duration-s 43200 >"$OUT/gcs18572.log" 2>&1 & HB2=$!
"$PY" "$GATE0/scripts/gcs_heartbeat.py" --port 18573 --duration-s 43200 >"$OUT/gcs18573.log" 2>&1 & HB3=$!

run_condition() {
  local trial="$1" seed="$2" method="$3" condition_out="$OUT/${trial}_${method}" launch_log
  if [[ -f "$condition_out/summary.json" ]]; then
    "$PY" - "$condition_out/summary.json" "$trial" "$method" <<'PY'
import json, sys
rows=json.load(open(sys.argv[1], encoding="utf-8"))["trials"]
if len(rows) != 1 or rows[0]["trial_id"] != sys.argv[2] or rows[0]["method"] != sys.argv[3]: raise SystemExit("completed-condition integrity failure")
PY
    echo "SKIP completed $trial $method"; return
  fi
  [[ ! -e "$condition_out" ]] || { echo "partial output: $condition_out" >&2; exit 2; }
  launch_log="$OUT/${trial}_${method}_launch.log"; STATE_DIR=""
  (cd "$GATE0" && C3_GAZEBO_SEED="$seed" POSES='2=0,-3,0.5;3=0,3,0.5' bash scripts/launch_multi_sitl_pose.sh S1 2,3 >"$launch_log" 2>&1) &
  for _ in $(seq 1 300); do
    if [[ -f "$launch_log" ]]; then
      STATE_DIR=$(sed -n 's/.*state_dir=\([^ ]*\).*/\1/p' "$launch_log" | head -1)
    fi
    [[ -z "$STATE_DIR" ]] || break
    sleep 1
  done
  [[ -n "$STATE_DIR" ]] || { echo "launch failed: $trial $method" >&2; exit 2; }
  source "$STATE_DIR/STATE"; TRIAL_PIDS="$px4_pids $gazebo_pid"
  ADAPTER_NAME="aegisair-ablation-${trial}-$(printf '%s' "$method" | tr '[:upper:]' '[:lower:]')"
  "$DOCKER" run -d --name "$ADAPTER_NAME" \
    -p 127.0.0.1:8889:8889/udp \
    -e XRCE_UDP_PORT=8889 \
    -e ADAPTER_INSTANCES='2 3' \
    -e ADAPTER_ARGS='--no-read-only --mqtt-host host.docker.internal --mqtt-port 1883 --control-rate-hz 20 --telemetry-rate-hz 20' \
    -e ORIGIN_OFFSET_2='-3,0,0' \
    -e ORIGIN_OFFSET_3='3,0,0' \
    aegisair-px4-bridge:humble >"$OUT/${trial}_${method}_adapter_id.txt"
  if ! "$PY" "$TELEMETRY_WAIT" --drone-ids 2 3 --timeout-s 90 >"$OUT/${trial}_${method}_telemetry.log" 2>&1; then
    stop_trial; STATE_DIR=""
    echo "telemetry readiness failed; see $OUT/${trial}_${method}_telemetry.log" >&2
    exit 2
  fi
  if ! (cd "$REPO" && conda run -n eai-swarm python marllib/run_c1_sota_cbf_gazebo.py --manifest "$MANIFEST" --out-dir "$condition_out" --trial-id "$trial" --method "$method") >"$OUT/${trial}_${method}_runner.log" 2>&1; then
    stop_trial; STATE_DIR=""
    echo "runner failed; see $OUT/${trial}_${method}_runner.log" >&2
    exit 2
  fi
  stop_trial; STATE_DIR=""
}

while IFS=$'\t' read -r trial seed methods; do
  IFS=',' read -r -a method_list <<< "$methods"
  for method in "${method_list[@]}"; do run_condition "$trial" "$seed" "$method"; done
  "$PY" - "$OUT" "$trial" "$MANIFEST" <<'PY'
import json, pathlib, sys
root=pathlib.Path(sys.argv[1]); trial=sys.argv[2]
manifest=json.load(open(sys.argv[3], encoding="utf-8"))
rows=[]
for path in root.glob(f"{trial}_*/summary.json"): rows.extend(json.load(open(path, encoding="utf-8"))["trials"])
if len(rows) != len(manifest["methods"]): raise SystemExit("paired trial incomplete")
if any(r["collision"] or not r["mission_complete"] or r["min_rho"] <= 0 for r in rows): raise SystemExit("sealed ablation safety stop rule reached after paired trial " + str(trial))
PY
done < <("$PY" - "$MANIFEST" <<'PY'
import json, sys
for t in json.load(open(sys.argv[1], encoding="utf-8"))["trials"]: print(t["trial_id"], t["seed"], ",".join(t["condition_order"]), sep="\t")
PY
)

if [[ "$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["protocol_id"])' "$MANIFEST")" == "aegisair-c1-hocbf-v4-ablation-sealed-v1" ]]; then
  conda run -n eai-swarm python "$REPO/marllib/analyze_c1_hocbf_v4_ablation.py" --manifest "$MANIFEST" --root "$OUT" --out "$OUT/audit.json"
else
  "$PY" - "$OUT" "$MANIFEST" <<'PY'
import json, pathlib, sys
root=pathlib.Path(sys.argv[1]); manifest=json.load(open(sys.argv[2], encoding="utf-8")); rows=[]
for path in root.glob("ext*_*/summary.json"): rows.extend(json.load(open(path, encoding="utf-8"))["trials"])
expected=len(manifest["trials"])*len(manifest["methods"])
if len(rows) != expected: raise SystemExit(f"sealed audit incomplete: {len(rows)}/{expected}")
go=all(not r["collision"] and r["mission_complete"] and r["min_rho"]>0 and r.get("safety_bypass_count",0)==0 for r in rows)
payload={"protocol_id":manifest["protocol_id"],"expected":expected,"found":len(rows),"go":go,"trials":rows}
json.dump(payload,open(root/"audit.json","w",encoding="utf-8"),ensure_ascii=False,indent=2)
if not go: raise SystemExit("sealed external baseline safety gate failed")
PY
fi
touch "$OUT/COMPLETE"
echo "C1 sealed batch COMPLETE"
