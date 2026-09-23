#!/usr/bin/env bash
# PCBF Huang et al. ECC 2025 adaptation: frozen five-seed PX4/Gazebo Gate 1.
set -euo pipefail

REPO="/Users/lijiajun/Documents/drone/AegisAir"
GATE0="/Users/lijiajun/Documents/ChatGPT/无人机论文尝试/safety_margin_scheduler_gate0"
MANIFEST="${PCBF_MANIFEST:-$REPO/configs/c1_pcbf_huang_ecc2025_calibration_v1.json}"
OUT="${PCBF_OUT:-/Volumes/Expansion/Aegis/c1_pcbf_huang_ecc2025_calibration_v1}"
PY="/opt/anaconda3/envs/eai-swarm/bin/python"
DOCKER="/Applications/Docker.app/Contents/Resources/bin/docker"
WAIT="$REPO/scripts/wait_for_px4_telemetry.py"

mkdir -p "$OUT"
if [[ -e "$OUT/STARTED" ]]; then
  cmp -s "$MANIFEST" "$OUT/manifest.json" || { echo "frozen manifest mismatch" >&2; exit 2; }
else
  touch "$OUT/STARTED"
  cp "$MANIFEST" "$OUT/manifest.json"
  shasum -a 256 "$MANIFEST" > "$OUT/manifest.sha256"
fi

HB2=""; HB3=""; TRIAL_PIDS=""; ADAPTER=""
stop_tree() { local pid="$1" child; for child in $(pgrep -P "$pid" 2>/dev/null || true); do stop_tree "$child"; done; kill -TERM "$pid" 2>/dev/null || true; }
stop_trial() {
  local pid
  if [[ -n "$ADAPTER" ]]; then "$DOCKER" stop "$ADAPTER" >/dev/null 2>&1 || true; "$DOCKER" rm "$ADAPTER" >/dev/null 2>&1 || true; ADAPTER=""; fi
  for pid in $TRIAL_PIDS; do stop_tree "$pid"; done
  for _ in $(seq 1 40); do local alive=0; for pid in $TRIAL_PIDS; do kill -0 "$pid" 2>/dev/null && alive=1; done; [[ "$alive" == 0 ]] && break; sleep 0.25; done
  for pid in $TRIAL_PIDS; do kill -KILL "$pid" 2>/dev/null || true; done
  TRIAL_PIDS=""
}
cleanup() { stop_trial; [[ -z "$HB2" ]] || kill "$HB2" 2>/dev/null || true; [[ -z "$HB3" ]] || kill "$HB3" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

"$PY" "$GATE0/scripts/gcs_heartbeat.py" --port 18572 --duration-s 43200 > "$OUT/gcs18572.log" 2>&1 & HB2=$!
"$PY" "$GATE0/scripts/gcs_heartbeat.py" --port 18573 --duration-s 43200 > "$OUT/gcs18573.log" 2>&1 & HB3=$!

while IFS=$'\t' read -r trial seed method; do
  condition="$OUT/${trial}_${method}"
  if [[ -f "$condition/summary.json" ]]; then
    "$PY" - "$condition/summary.json" "$trial" "$method" <<'PY'
import json, sys
rows=json.load(open(sys.argv[1], encoding="utf-8"))["trials"]
if len(rows) != 1 or rows[0]["trial_id"] != sys.argv[2] or rows[0]["method"] != sys.argv[3]: raise SystemExit("completed-condition integrity failure")
PY
    echo "SKIP completed $trial $method"; continue
  fi
  [[ ! -e "$condition" ]] || { echo "partial output: $condition" >&2; exit 2; }
  launch_log="$OUT/${trial}_${method}_launch.log"
  (cd "$GATE0" && C3_GAZEBO_SEED="$seed" POSES='2=0,-3,0.5;3=0,3,0.5' bash scripts/launch_multi_sitl_pose.sh S1 2,3 > "$launch_log" 2>&1) &
  launcher=$!; state_dir=""
  for _ in $(seq 1 300); do state_dir=$(sed -n 's/.*state_dir=\([^ ]*\).*/\1/p' "$launch_log" | head -1); [[ -n "$state_dir" ]] && break; sleep 1; done
  [[ -n "$state_dir" ]] || { echo "launch failed: $trial" >&2; exit 2; }
  source "$state_dir/STATE"; TRIAL_PIDS="$launcher $px4_pids $gazebo_pid"
  ADAPTER="aegisair-pcbf-${trial}"
  "$DOCKER" run -d --name "$ADAPTER" -p 127.0.0.1:8889:8889/udp \
    -e XRCE_UDP_PORT=8889 -e ADAPTER_INSTANCES='2 3' \
    -e ADAPTER_ARGS='--no-read-only --mqtt-host host.docker.internal --mqtt-port 1883 --control-rate-hz 20 --telemetry-rate-hz 20' \
    -e ORIGIN_OFFSET_2='-3,0,0' -e ORIGIN_OFFSET_3='3,0,0' \
    aegisair-px4-bridge:humble > "$OUT/${trial}_${method}_adapter_id.txt"
  "$PY" "$WAIT" --drone-ids 2 3 --timeout-s 90 > "$OUT/${trial}_${method}_telemetry.log" 2>&1 || { stop_trial; echo "telemetry readiness failed: $trial" >&2; exit 2; }
  (cd "$REPO" && conda run -n eai-swarm python marllib/run_c1_sota_cbf_gazebo.py --manifest "$MANIFEST" --out-dir "$condition" --trial-id "$trial" --method "$method") > "$OUT/${trial}_${method}_runner.log" 2>&1 || { stop_trial; echo "runner failed: $trial" >&2; exit 2; }
  stop_trial
  "$PY" - "$condition/summary.json" <<'PY'
import json, sys
row=json.load(open(sys.argv[1], encoding="utf-8"))["trials"][0]
lat=row["ra_solve_latency_summary_ms"]
if row["collision"] or not row["mission_complete"] or row["min_rho"] < 0 or lat["p99"] >= 50 or row["safety_bypass_count"] != 0:
    raise SystemExit("PCBF Gate 1 No-Go: " + json.dumps(row, ensure_ascii=False))
PY
done < <("$PY" - "$MANIFEST" <<'PY'
import json, sys
for trial in json.load(open(sys.argv[1], encoding="utf-8"))["trials"]:
    print(trial["trial_id"], trial["seed"], trial["condition_order"][0], sep="\t")
PY
)

"$PY" - "$OUT" <<'PY'
import json, pathlib, sys
root=pathlib.Path(sys.argv[1]); rows=[]
for p in sorted(root.glob("*_PCBF_HUANG_ECC2025/summary.json")):
    rows.extend(json.load(open(p, encoding="utf-8"))["trials"])
manifest=json.load(open(root/"manifest.json", encoding="utf-8"))
if len(rows) != len(manifest["trials"]): raise SystemExit("incomplete PCBF run")
json.dump({"protocol":"pcbf_huang_ecc2025_gate1","trials":rows}, open(root/"audit.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
PY
touch "$OUT/COMPLETE"
echo "PCBF Gate 1 COMPLETE"
