#!/usr/bin/env bash
set -euo pipefail

REPO="/Users/lijiajun/Documents/drone/AegisAir"
GATE0="/Users/lijiajun/Documents/ChatGPT/无人机论文尝试/safety_margin_scheduler_gate0"
OUT="/Volumes/Expansion/Aegis/c2_prime_validation_v2_current_head"
MANIFEST="$REPO/configs/c2_prime_validation_v2_current_head.json"
CAL="/Volumes/Expansion/Aegis/c2_prime_calibration_live_20260821/frozen_thresholds.json"
mkdir -p "$OUT"
if [[ -e "$OUT/COMPLETE" ]]; then exit 2; fi
if [[ -e "$OUT/STARTED" ]]; then
  cmp -s "$MANIFEST" "$OUT/manifest.json" || exit 2
else
  touch "$OUT/STARTED"; cp "$MANIFEST" "$OUT/manifest.json"
  shasum -a 256 "$MANIFEST" > "$OUT/manifest.sha256"
fi
state_dir=""
cleanup() {
  if [[ -n "$state_dir" && -d "$state_dir" ]]; then
    (cd "$GATE0" && bash scripts/stop_multi_sitl.sh "$state_dir") >/dev/null 2>&1 || true
  fi
  pkill -x px4 2>/dev/null || true
  pkill -f 'gz sim -r' 2>/dev/null || true
  state_dir=""
}
trap cleanup EXIT INT TERM

run_trial() {
  local trial="$1" seed="$2" log="$OUT/${trial}_launch.log"
  if [[ -f "$OUT/$trial/summary.json" ]]; then echo "SKIP $trial"; return; fi
  echo "===== C2-V2 $trial seed=$seed ====="
  state_dir=""
  : > "$log"
  (cd "$REPO"; POSES='2=0,-3,0.5;3=0,3,0.5' bash scripts/launch_c3_seeded_sitl.sh "$seed" >"$log" 2>&1) &
  for _ in $(seq 1 40); do
    state_dir=$(sed -n 's/.*state_dir=\([^ ]*\).*/\1/p' "$log" | head -1 || true)
    [[ -n "$state_dir" ]] && break; sleep 1
  done
  [[ -n "$state_dir" ]] || return 1
  sleep 14
  (cd "$REPO"; conda run -n eai-swarm python marllib/run_c2_prime_gazebo.py \
    --manifest "$MANIFEST" --calibration "$CAL" --out-dir "$OUT/$trial" --trial-id "$trial")
  cleanup; sleep 2
}

while IFS=$'\t' read -r trial seed; do
  [[ -n "$trial" && -n "$seed" ]] || continue
  run_trial "$trial" "$seed"
done < <(conda run -n eai-swarm python -c 'import json; m=json.load(open("configs/c2_prime_validation_v2_current_head.json")); [print(t["trial_id"],t["seed"],sep="\t") for t in m["trials"]]')
touch "$OUT/COMPLETE"
echo "C2-V2 ALL DONE"
