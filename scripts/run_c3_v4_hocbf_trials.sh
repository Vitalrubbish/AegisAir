#!/usr/bin/env bash
# 运行冻结的 C3 HOCBF-v4 closed-loop trial；每个配对 trial 使用新的 PX4/Gazebo。
set -euo pipefail

REPO="/Users/lijiajun/Documents/drone/AegisAir"
GATE0="/Users/lijiajun/Documents/ChatGPT/无人机论文尝试/safety_margin_scheduler_gate0"
MANIFEST="${1:?usage: $0 MANIFEST OUTDIR}"
OUT="${2:?usage: $0 MANIFEST OUTDIR}"
HEARTBEAT="$GATE0/scripts/gcs_heartbeat.py"
HB2=""
HB3=""
mkdir -p "$OUT"
if [[ -e "$OUT/COMPLETE" ]]; then exit 2; fi
if [[ -e "$OUT/STARTED" ]]; then
  cmp -s "$MANIFEST" "$OUT/manifest.json" || exit 2
else
  touch "$OUT/STARTED"
  cp "$MANIFEST" "$OUT/manifest.json"
  shasum -a 256 "$MANIFEST" > "$OUT/manifest.sha256"
fi

state_dir=""
stop_trial_sitl() {
  if [[ -n "$state_dir" && -d "$state_dir" ]]; then
    (cd "$GATE0" && bash scripts/stop_multi_sitl.sh "$state_dir") >/dev/null 2>&1 || true
  fi
  pkill -x px4 2>/dev/null || true
  pkill -f 'gz sim -r' 2>/dev/null || true
  for _ in $(seq 1 40); do
    pgrep -f 'px4.*-i (2|3)' >/dev/null 2>&1 || break
    sleep .25
  done
  pkill -KILL -f 'px4.*-i (2|3)' 2>/dev/null || true
  state_dir=""
}

cleanup() {
  stop_trial_sitl
  [[ -z "$HB2" ]] || kill "$HB2" 2>/dev/null || true
  [[ -z "$HB3" ]] || kill "$HB3" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

/opt/anaconda3/envs/eai-swarm/bin/python "$HEARTBEAT" --port 18572 --duration-s 14400 >"$OUT/gcs18572.log" 2>&1 &
HB2=$!
/opt/anaconda3/envs/eai-swarm/bin/python "$HEARTBEAT" --port 18573 --duration-s 14400 >"$OUT/gcs18573.log" 2>&1 &
HB3=$!

run_trial() {
  local trial="$1" seed="$2" log="$OUT/${trial}_launch.log"
  [[ -f "$OUT/$trial/summary.json" ]] && { echo "SKIP $trial"; return; }
  echo "===== C3-V4 $trial seed=$seed ====="
  state_dir=""
  (cd "$REPO" && POSES='2=0,-3,0.5;3=0,3,0.5' bash scripts/launch_c3_seeded_sitl.sh "$seed" >"$log" 2>&1) &
  for _ in $(seq 1 40); do
    state_dir=$(sed -n 's/.*state_dir=\([^ ]*\).*/\1/p' "$log" | head -1 || true)
    [[ -n "$state_dir" ]] && break
    sleep 1
  done
  [[ -n "$state_dir" ]] || return 1
  # PX4 EKF/offboard readiness is checked by the runner; 30 s is a fixed
  # infrastructure warm-up, not a controller parameter.
  sleep 30
  (cd "$REPO" && conda run -n eai-swarm python marllib/run_c3_gazebo.py \
    --manifest "$MANIFEST" --out-dir "$OUT/$trial" --trial-id "$trial" \
    --velocity-command-mode feedforward_tau --tau-command-s .7)
  python - "$OUT/$trial/summary.json" <<'PY'
import json, sys
rows = json.load(open(sys.argv[1]))["trials"]
r0 = next(r for r in rows if r["condition"] == "R0")
r1 = next(r for r in rows if r["condition"] == "R1")
if r0["critical_reached"] or not r1["critical_reached"]:
    raise SystemExit("C3 closure gate failed")
if any(r["collision"] or r["min_rho"] <= 0 for r in rows):
    raise SystemExit("C3 safety gate failed")
if (r1.get("counters") or {}).get("mission_changes") != 1:
    raise SystemExit("C3 mission-change audit failed")
PY
  # Keep persistent GCS heartbeat alive between fresh physical trials.
  stop_trial_sitl
  sleep 2
}

while IFS=$'\t' read -r trial seed; do
  [[ -n "$trial" && -n "$seed" ]] || continue
  run_trial "$trial" "$seed"
done < <(cd "$REPO" && conda run -n eai-swarm python -c 'import json,sys; m=json.load(open(sys.argv[1])); [print(t["trial_id"],t["seed"],sep="\t") for t in m["trials"]]' "$MANIFEST")
touch "$OUT/COMPLETE"
echo "C3-V4 ALL DONE"
