#!/usr/bin/env bash
# Run frozen C1 PX4 v2 with fresh SITL and a hard safety gate per seed.
set -euo pipefail

REPO="/Users/lijiajun/Documents/drone/AegisAir"
GATE0="/Users/lijiajun/Documents/ChatGPT/无人机论文尝试/safety_margin_scheduler_gate0"
OUT="/Volumes/Expansion/Aegis/c1_px4_telemetry_delay_validation_v2"
MANIFEST="$REPO/configs/c1_px4_telemetry_delay_validation_v2.json"
mkdir -p "$OUT"
if [[ -e "$OUT/COMPLETE" ]]; then
  echo "refusing completed validation output: $OUT" >&2
  exit 2
elif [[ -e "$OUT/STARTED" ]]; then
  cmp -s "$MANIFEST" "$OUT/manifest.json" || {
    echo "refusing resume: frozen manifest differs from recorded copy" >&2
    exit 2
  }
  echo "RESUME: retaining completed trials and continuing missing trials"
else
  touch "$OUT/STARTED"
  cp "$MANIFEST" "$OUT/manifest.json"
  shasum -a 256 "$MANIFEST" > "$OUT/manifest.sha256"
fi

state_dir=""
cleanup_trial() {
  if [[ -n "$state_dir" && -d "$state_dir" ]]; then
    (cd "$GATE0" && bash scripts/stop_multi_sitl.sh "$state_dir") >/dev/null 2>&1 || true
  fi
  pkill -x px4 2>/dev/null || true
  pkill -f 'gz sim -r' 2>/dev/null || true
  state_dir=""
}
trap cleanup_trial EXIT INT TERM

wait_px4_gone() {
  for _ in $(seq 1 30); do
    pgrep -x px4 >/dev/null 2>&1 || return 0
    sleep 1
  done
  return 1
}

run_trial() {
  local trial="$1" seed="$2" launch_log="$OUT/${trial}_launch.log"
  if [[ -f "$OUT/$trial/summary.json" ]]; then
    python - "$OUT/$trial/summary.json" "$trial" "$seed" <<'PY'
import json, sys
summary, trial, seed = sys.argv[1:]
rows = json.load(open(summary, encoding="utf-8")).get("trials", [])
if len(rows) != 1 or rows[0].get("trial_id") != trial or str(rows[0].get("seed")) != seed:
    raise SystemExit("existing C1 v2 summary audit failed")
row = rows[0]
if row.get("collision") or row.get("min_rho", 0) <= 0 or not row.get("mission_complete"):
    raise SystemExit("existing C1 v2 result fails frozen gate")
PY
    echo "SKIP completed $trial"
    return 0
  fi
  echo "===== TRIAL $trial seed=$seed ====="
  state_dir=""
  (
    cd "$REPO"
    POSES='2=0,-3,0.5;3=0,3,0.5' C3_GAZEBO_SEED="$seed" \
      bash scripts/launch_c3_seeded_sitl.sh "$seed" >"$launch_log" 2>&1
  ) &
  for _ in $(seq 1 40); do
    [[ -f "$launch_log" ]] || { sleep 1; continue; }
    state_dir=$(sed -n 's/.*state_dir=\([^ ]*\).*/\1/p' "$launch_log" | head -1)
    [[ -n "$state_dir" ]] && break
    sleep 1
  done
  [[ -n "$state_dir" ]] || { echo "LAUNCH FAILED $trial" >&2; return 1; }
  printf 'trial=%s\nseed=%s\nstate_dir=%s\n' "$trial" "$seed" "$state_dir" > "$OUT/${trial}_launch_meta.txt"
  sleep 14
  (
    cd "$REPO"
    conda run -n eai-swarm python marllib/run_c1_px4_gazebo_v2.py \
      --manifest "$MANIFEST" --out-dir "$OUT/$trial" --trial-id "$trial"
  )
  python - "$OUT/$trial/summary.json" <<'PY'
import json, sys
row = json.load(open(sys.argv[1]))["trials"][0]
failures = []
if row["collision"]:
    failures.append("collision")
if row["min_rho"] <= 0:
    failures.append(f"min_rho={row['min_rho']}")
if not row["mission_complete"]:
    failures.append(f"final_phase={row['final_phase']}")
if row["tau"] != {
    "barrier_tau_px4_s": 0.2,
    "command_feedforward_tau_s": 0.7,
    "admission_execution_tau_s": 0.7,
}:
    failures.append(f"tau={row['tau']}")
if failures:
    raise SystemExit("C1 PX4 v2 gate failed: " + ", ".join(failures))
PY
  cleanup_trial
  wait_px4_gone || { echo "px4 linger after $trial" >&2; return 1; }
  sleep 2
}

while IFS=$'\t' read -r trial seed; do
  [[ -n "$trial" && -n "$seed" ]] || continue
  run_trial "$trial" "$seed"
done < <(
  conda run -n eai-swarm python -c 'import json; m=json.load(open("configs/c1_px4_telemetry_delay_validation_v2.json")); [print(t["trial_id"],t["seed"],sep="\t") for t in m["trials"]]'
)
conda run -n eai-swarm python marllib/analyze_c1_px4_v2.py \
  --manifest "$MANIFEST" --data-dir "$OUT" --output "$OUT/summary.json"
touch "$OUT/COMPLETE"
echo "ALL DONE"
