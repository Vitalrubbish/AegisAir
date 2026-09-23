#!/usr/bin/env bash
set -uo pipefail

REPO="/Users/lijiajun/Documents/drone/AegisAir"
PY="/opt/anaconda3/envs/eai-swarm/bin/python"
MANIFEST="${1:-$REPO/configs/c3_group_slot_4uav_qualification_v1.json}"
OUT="${2:-/Volumes/Expansion/Aegis/c3_group_slot_4uav_qualification_v2}"

stable_isolation() {
  local stable=0
  for _ in $(seq 1 600); do
    if pgrep -f '[p]x4.*-i (2|3|4|5)' >/dev/null 2>&1; then
      stable=0
    else
      stable=$((stable + 1))
      (( stable >= 6 )) && return 0
    fi
    sleep 0.5
  done
  return 1
}

cleanup_trial_px4_children() {
  pkill -TERM -f '/PX4-Autopilot/.*/bin/px4 -d -i (2|3|4|5)' 2>/dev/null || true
  for _ in $(seq 1 120); do
    pgrep -f '/PX4-Autopilot/.*/bin/px4 -d -i (2|3|4|5)' >/dev/null 2>&1 || return 0
    sleep 0.25
  done
  return 1
}

mkdir -p "$OUT/trials"
if [[ ! -e "$OUT/STARTED" ]]; then
  cp "$MANIFEST" "$OUT/manifest.json"
  shasum -a 256 "$MANIFEST" >"$OUT/manifest.sha256"
  touch "$OUT/STARTED"
fi

for seed in $($PY -c 'import json,sys; print(*json.load(open(sys.argv[1]))["qualification_seeds"])' "$MANIFEST"); do
  seed_root="$OUT/trials/seed_$seed"
  valid=""
  mkdir -p "$seed_root"
  for existing in "$seed_root"/attempt_*/calibration/summary.json; do
    if [[ -f "$existing" && -f "${existing%summary.json}COMPLETE" ]]; then
      valid="$existing"
      break
    fi
  done
  [[ -n "$valid" ]] && continue
  for attempt_index in 1 2 3; do
    attempt=$(printf '%s/attempt_%02d' "$seed_root" "$attempt_index")
    [[ -e "$attempt" ]] && continue
    stable_isolation || { touch "$OUT/BLOCKED_INFRASTRUCTURE"; exit 1; }
    C3_RUNNER="marllib/run_c3_group_slot_gazebo.py" \
    C3_TRIAL_SEED="$seed" C3_GAZEBO_SEED_OVERRIDE="$seed" \
      bash "$REPO/scripts/run_c3_reservation_4uav_smoke.sh" "$MANIFEST" "$attempt"
    status=$?
    cleanup_trial_px4_children || true
    if (( status == 0 )) && [[ -f "$attempt/calibration/summary.json" && -f "$attempt/calibration/COMPLETE" ]]; then
      valid="$attempt/calibration/summary.json"
      break
    fi
    touch "$attempt/INVALID_INFRASTRUCTURE" 2>/dev/null || true
  done
  [[ -n "$valid" ]] || { touch "$OUT/BLOCKED_INFRASTRUCTURE"; exit 1; }
  "$PY" - "$valid" <<'PY'
import json, sys
s=json.load(open(sys.argv[1]))
raise SystemExit(0 if s["m4_go"] else 3)
PY
  if (( $? != 0 )); then
    touch "$OUT/STOP_RULE_NO_GO" "$OUT/COMPLETE"
    exit 0
  fi
done
touch "$OUT/QUALIFICATION_GO" "$OUT/COMPLETE"
