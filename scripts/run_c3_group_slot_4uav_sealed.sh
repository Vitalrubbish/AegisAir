#!/usr/bin/env bash
set -uo pipefail

REPO="/Users/lijiajun/Documents/drone/AegisAir"
PY="/opt/anaconda3/envs/eai-swarm/bin/python"
MANIFEST="${1:-$REPO/configs/c3_group_slot_4uav_sealed_v1.json}"
OUT="${2:-/Volumes/Expansion/Aegis/c3_group_slot_4uav_sealed_v1}"

stable_isolation() {
  local stable=0
  for _ in $(seq 1 600); do
    if pgrep -f '[p]x4.*-i (2|3|4|5)' >/dev/null 2>&1; then stable=0; else stable=$((stable+1)); (( stable >= 6 )) && return 0; fi
    sleep 0.5
  done
  return 1
}

cleanup_px4() {
  local pids
  pids=$(pgrep -f '/PX4-Autopilot/.*/bin/px4 -d -i (2|3|4|5)' || true)
  while IFS= read -r pid; do [[ -z "$pid" ]] || kill -TERM "$pid" 2>/dev/null || true; done <<<"$pids"
  for _ in $(seq 1 120); do pgrep -f '/PX4-Autopilot/.*/bin/px4 -d -i (2|3|4|5)' >/dev/null || return 0; sleep 0.25; done
  pids=$(pgrep -f '/PX4-Autopilot/.*/bin/px4 -d -i (2|3|4|5)' || true)
  while IFS= read -r pid; do [[ -z "$pid" ]] || kill -KILL "$pid" 2>/dev/null || true; done <<<"$pids"
  return 0
}

mkdir -p "$OUT/trials"
if [[ ! -e "$OUT/STARTED" ]]; then
  cp "$MANIFEST" "$OUT/manifest.json"
  shasum -a 256 "$MANIFEST" >"$OUT/manifest.sha256"
  touch "$OUT/STARTED"
else
  cmp -s "$MANIFEST" "$OUT/manifest.json" || { echo "manifest mismatch" >&2; exit 2; }
fi

for seed in $($PY -c 'import json,sys; print(*json.load(open(sys.argv[1]))["sealed_seeds"])' "$MANIFEST"); do
  seed_root="$OUT/trials/seed_$seed"; mkdir -p "$seed_root"; valid=""
  for existing in "$seed_root"/attempt_*/calibration/summary.json; do
    [[ -f "$existing" && -f "${existing%summary.json}COMPLETE" ]] && { valid="$existing"; break; }
  done
  if [[ -z "$valid" ]]; then
    for attempt_index in 1 2 3; do
      attempt=$(printf '%s/attempt_%02d' "$seed_root" "$attempt_index"); [[ -e "$attempt" ]] && continue
      stable_isolation || { touch "$OUT/BLOCKED_INFRASTRUCTURE"; exit 1; }
      C3_RUNNER="marllib/run_c3_group_slot_gazebo.py" C3_TRIAL_SEED="$seed" C3_GAZEBO_SEED_OVERRIDE="$seed" \
        bash "$REPO/scripts/run_c3_reservation_4uav_smoke.sh" "$MANIFEST" "$attempt"
      status=$?; cleanup_px4 || true
      if (( status == 0 )) && [[ -f "$attempt/calibration/summary.json" && -f "$attempt/calibration/COMPLETE" ]]; then valid="$attempt/calibration/summary.json"; break; fi
      touch "$attempt/INVALID_INFRASTRUCTURE" 2>/dev/null || true
    done
  fi
  [[ -n "$valid" ]] || { touch "$OUT/BLOCKED_INFRASTRUCTURE"; exit 1; }
  if ! "$PY" -c 'import json,sys; raise SystemExit(0 if json.load(open(sys.argv[1]))["m4_go"] else 3)' "$valid"; then
    touch "$OUT/STOP_RULE_NO_GO"
    "$PY" "$REPO/marllib/aggregate_c3_group_slot_sealed.py" --manifest "$MANIFEST" --root "$OUT/trials" --output "$OUT/sealed_summary.json"
    touch "$OUT/COMPLETE"; exit 0
  fi
done

"$PY" "$REPO/marllib/aggregate_c3_group_slot_sealed.py" --manifest "$MANIFEST" --root "$OUT/trials" --output "$OUT/sealed_summary.json"
(cd "$OUT" && shasum -a 256 manifest.json sealed_summary.json >sealed_integrity.sha256)
touch "$OUT/SEALED_GO" "$OUT/COMPLETE"
