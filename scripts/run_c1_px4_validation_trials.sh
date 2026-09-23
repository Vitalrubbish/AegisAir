#!/usr/bin/env bash
# Run the frozen C1 PX4 telemetry-delay core validation with fresh SITL per seed.
set -euo pipefail

REPO="/Users/lijiajun/Documents/drone/AegisAir"
GATE0="/Users/lijiajun/Documents/ChatGPT/无人机论文尝试/safety_margin_scheduler_gate0"
OUT="/Volumes/Expansion/Aegis/c1_px4_telemetry_delay_validation_v1"
MANIFEST="$REPO/configs/c1_px4_telemetry_delay_validation_v1.json"
mkdir -p "$OUT"
[[ ! -e "$OUT/STARTED" ]] || { echo "refusing to reuse output: $OUT" >&2; exit 2; }
touch "$OUT/STARTED"
cp "$MANIFEST" "$OUT/manifest.json"
shasum -a 256 "$MANIFEST" > "$OUT/manifest.sha256"

wait_px4_gone() {
  for _ in $(seq 1 30); do pgrep -x px4 >/dev/null 2>&1 || return 0; sleep 1; done
  return 1
}

run_trial() {
  local trial="$1" seed="$2" launch_log="$OUT/${trial}_launch.log" state_dir=""
  echo "===== TRIAL $trial seed=$seed ====="
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
    conda run -n eai-swarm python marllib/run_c1_px4_gazebo.py \
      --manifest "$MANIFEST" --out-dir "$OUT/$trial" --trial-id "$trial"
  )
  python - "$OUT/$trial/summary.json" <<'PY'
import json, sys
rows=json.load(open(sys.argv[1]))["trials"]
full=next(r for r in rows if r["condition"] == "full_envelope")
if full["collision"] or full["min_rho"] <= 0:
    raise SystemExit("C1 full_envelope safety gate failed")
PY
  (cd "$GATE0" && bash scripts/stop_multi_sitl.sh "$state_dir") 2>&1 | tail -1
  pkill -x px4 2>/dev/null || true
  pkill -f 'gz sim -r' 2>/dev/null || true
  wait_px4_gone || { echo "px4 linger after $trial" >&2; return 1; }
  sleep 2
}

while IFS=$'\t' read -r trial seed; do run_trial "$trial" "$seed"; done < <(
  conda run -n eai-swarm python -c 'import json; m=json.load(open("configs/c1_px4_telemetry_delay_validation_v1.json")); [print(t["trial_id"],t["seed"],sep="\t") for t in m["trials"]]'
)
touch "$OUT/COMPLETE"
echo "ALL DONE"
