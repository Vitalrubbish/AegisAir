#!/usr/bin/env bash
# Drive the frozen 30-trial C3 validation. Broker, heartbeat, and adapter must
# already be healthy. Each physical trial gets a fresh seed-controlled SITL.
set -euo pipefail

REPO="/Users/lijiajun/Documents/drone/AegisAir"
OUT="/Volumes/Expansion/Aegis/c3_closed_loop_validation_ff_v1"
MANIFEST="$REPO/configs/c3_closed_loop_validation_v1.json"
GATE0="/Users/lijiajun/Documents/ChatGPT/无人机论文尝试/safety_margin_scheduler_gate0"
mkdir -p "$OUT"
if [[ -e "$OUT/COMPLETE" ]]; then
  echo "refusing completed validation output: $OUT" >&2
  exit 2
fi
if [[ -e "$OUT/STARTED" ]]; then
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

wait_px4_gone() {
  for _ in $(seq 1 30); do
    pgrep -x px4 >/dev/null 2>&1 || return 0
    sleep 1
  done
  return 1
}

run_trial() {
  local trial="$1" seed="$2"
  if [[ -f "$OUT/$trial/summary.json" ]]; then
    python - "$OUT/$trial/summary.json" "$trial" "$seed" <<'PY'
import json, sys
summary, trial, seed = sys.argv[1:]
payload = json.load(open(summary, encoding="utf-8"))
rows = payload.get("trials", [])
if (payload.get("manifest_sha256") != open("/Volumes/Expansion/Aegis/c3_closed_loop_validation_ff_v1/manifest.sha256").read().split()[0]
        or len(rows) != 2
        or {r.get("trial_id") for r in rows} != {trial}
        or {str(r.get("seed")) for r in rows} != {seed}
        or {r.get("condition") for r in rows} != {"R0", "R1"}):
    raise SystemExit("existing summary audit failed")
PY
    echo "SKIP completed $trial"
    return 0
  fi
  local launch_log="$OUT/${trial}_launch.log"
  echo "===== TRIAL $trial seed=$seed ====="
  (
    cd "$REPO"
    POSES='2=0,-3,0.5;3=0,3,0.5' C3_GAZEBO_SEED="$seed" \
      bash scripts/launch_c3_seeded_sitl.sh "$seed" >"$launch_log" 2>&1
  ) &
  local state_dir=""
  for _ in $(seq 1 40); do
    [[ -f "$launch_log" ]] || { sleep 1; continue; }
    state_dir=$(sed -n 's/.*state_dir=\([^ ]*\).*/\1/p' "$launch_log" | head -1)
    [[ -n "$state_dir" ]] && break
    sleep 1
  done
  [[ -n "$state_dir" ]] || { echo "LAUNCH FAILED $trial"; return 1; }
  printf 'trial=%s\nseed=%s\nstate_dir=%s\n' "$trial" "$seed" "$state_dir" > "$OUT/${trial}_launch_meta.txt"
  sleep 14
  (
    cd "$REPO"
    conda run -n eai-swarm python marllib/run_c3_gazebo.py \
      --manifest "$MANIFEST" --out-dir "$OUT/$trial" --trial-id "$trial" \
      --velocity-command-mode feedforward_tau --tau-command-s 0.7
  )
  (cd "$GATE0" && bash scripts/stop_multi_sitl.sh "$state_dir") 2>&1 | tail -1
  pkill -x px4 2>/dev/null || true
  pkill -f 'gz sim -r' 2>/dev/null || true
  wait_px4_gone || { echo "px4 linger after $trial"; return 1; }
  sleep 2
}

while IFS=$'\t' read -r trial seed; do
  run_trial "$trial" "$seed"
done < <(conda run -n eai-swarm python -c 'import json; m=json.load(open("configs/c3_closed_loop_validation_v1.json")); [print(t["trial_id"], t["seed"], sep="\t") for t in m["trials"]]')

touch "$OUT/COMPLETE"
echo "ALL DONE"
