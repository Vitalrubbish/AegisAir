#!/usr/bin/env bash
# 五 seed 四机 R2/R3 qualification；每个条件使用全新 PX4/Gazebo/SITL。
set -uo pipefail

REPO="/Users/lijiajun/Documents/drone/AegisAir"
PY="/opt/anaconda3/envs/eai-swarm/bin/python"
MANIFEST="${1:-$REPO/configs/c3_reservation_4uav_qualification_v1.json}"
OUT="${2:-/Volumes/Expansion/Aegis/c3_reservation_4uav_qualification_v1}"
RUNNER="marllib/run_c3_reservation_qualification_gazebo.py"

if [[ -e "$OUT/COMPLETE" ]]; then
  echo "qualification 已关闭：$OUT" >&2
  exit 2
fi
if [[ -e "$OUT/STARTED" ]]; then
  cmp -s "$MANIFEST" "$OUT/manifest.json" || {
    echo "现有输出与 manifest 不一致" >&2
    exit 2
  }
else
  mkdir -p "$OUT"
  cp "$MANIFEST" "$OUT/manifest.json"
  shasum -a 256 "$MANIFEST" >"$OUT/manifest.sha256"
  touch "$OUT/STARTED"
fi

stable_isolation() {
  local stable=0
  for _ in $(seq 1 180); do
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

force_trial_cleanup() {
  local attempt="$1" state_dir=""
  state_dir=$(sed -n 's/.*state_dir=\([^ ]*\).*/\1/p' "$attempt/launch.log" 2>/dev/null | head -1 || true)
  if [[ -n "$state_dir" && -d "$state_dir" ]]; then
    bash "/Users/lijiajun/Documents/ChatGPT/无人机论文尝试/safety_margin_scheduler_gate0/scripts/stop_multi_sitl.sh" \
      "$state_dir" >/dev/null 2>&1 || true
  fi
  # Bracketed patterns do not match the cleanup commands themselves.
  pkill -f '[p]x4.*-i (2|3|4|5)' 2>/dev/null || true
  pkill -f '[l]aunch_multi_sitl_pose.sh S1 2,3,4,5' 2>/dev/null || true
  for _ in $(seq 1 120); do
    pgrep -f '[p]x4.*-i (2|3|4|5)' >/dev/null 2>&1 || return 0
    sleep 0.25
  done
  pkill -KILL -f '[p]x4.*-i (2|3|4|5)' 2>/dev/null || true
}

write_aggregate() {
  local name="$1"
  if [[ -e "$OUT/$name" ]]; then
    echo "保留已有汇总，不覆盖：$OUT/$name" >&2
    return 0
  fi
  (
    cd "$REPO"
    conda run -n eai-swarm python marllib/aggregate_c3_reservation_qualification.py \
      --manifest "$MANIFEST" --root "$OUT/trials" --output "$OUT/$name"
  )
}

write_root_integrity() {
  local integrity="$OUT/qualification_integrity.sha256"
  [[ ! -e "$integrity" ]] || return 0
  (
    cd "$OUT"
    files=(manifest.json qualification_summary.json)
    if [[ -d figures_and_statistics ]]; then
      while IFS= read -r file; do files+=("$file"); done < <(
        find figures_and_statistics -type f ! -name '._*' | sort
      )
    fi
    shasum -a 256 "${files[@]}" >qualification_integrity.sha256
  )
}

condition_valid_summary() {
  local condition_root="$1"
  "$PY" - "$condition_root" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
for attempt in sorted(root.glob("attempt_*")):
    summary = attempt / "calibration" / "summary.json"
    complete = attempt / "calibration" / "COMPLETE"
    integrity = attempt / "calibration" / "integrity.sha256"
    if summary.is_file() and complete.is_file() and integrity.is_file():
        print(summary)
        break
PY
}

while IFS=$'\t' read -r seed_index seed condition; do
  [[ -n "$seed" && -n "$condition" ]] || continue
  condition_root=$(printf '%s/trials/q%02d_seed%s/%s' "$OUT" "$seed_index" "$seed" "$condition")
  mkdir -p "$condition_root"
  valid_summary=$(condition_valid_summary "$condition_root")
  if [[ -z "$valid_summary" ]]; then
    max_attempts=$(
      "$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["max_invalid_attempts_per_condition"])' "$MANIFEST"
    )
    for attempt_index in $(seq 1 "$max_attempts"); do
      attempt=$(printf '%s/attempt_%02d' "$condition_root" "$attempt_index")
      [[ -e "$attempt" ]] && continue
      if ! stable_isolation; then
        echo "旧 PX4 实例未清理，qualification 基础设施阻塞" >&2
        touch "$OUT/BLOCKED_INFRASTRUCTURE"
        exit 1
      fi
      echo "START seed=$seed condition=$condition attempt=$attempt_index"
      C3_RUNNER="$RUNNER" \
      C3_CONDITION="$condition" \
      C3_TRIAL_SEED="$seed" \
      C3_GAZEBO_SEED_OVERRIDE="$seed" \
        "$REPO/scripts/run_c3_reservation_4uav_smoke.sh" "$MANIFEST" "$attempt"
      status=$?
      force_trial_cleanup "$attempt"
      if (( status != 0 )); then
        touch "$attempt/INVALID_INFRASTRUCTURE" 2>/dev/null || true
        echo "INVALID seed=$seed condition=$condition attempt=$attempt_index"
        continue
      fi
      valid_summary=$(condition_valid_summary "$condition_root")
      [[ -n "$valid_summary" ]] && break
    done
  fi
  if [[ -z "$valid_summary" ]]; then
    echo "三次基础设施尝试后仍无有效 trial：seed=$seed condition=$condition" >&2
    touch "$OUT/BLOCKED_INFRASTRUCTURE"
    write_aggregate "qualification_partial.json" || true
    exit 1
  fi

  if [[ "$condition" == "R3_C3_RESERVATION" ]]; then
    if ! "$PY" - "$valid_summary" <<'PY'
import json, sys
row = json.load(open(sys.argv[1]))["trial"]
raise SystemExit(0 if row["r3_qualification_go"] else 3)
PY
    then
      echo "R3 QUALIFICATION NO_GO seed=${seed}；停止后续算法 trial"
      touch "$OUT/STOP_RULE_NO_GO"
      if ! write_aggregate "qualification_summary.json"; then
        touch "$OUT/PACKAGING_ERROR"
        exit 1
      fi
      write_root_integrity
      touch "$OUT/COMPLETE"
      exit 0
    fi
  fi
  echo "DONE seed=$seed condition=$condition"
done < <(
  "$PY" - "$MANIFEST" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
for index, seed in enumerate(m["qualification_seeds"], 1):
    for condition in m["condition_order_by_seed"][str(seed)]:
        print(index, seed, condition, sep="\t")
PY
)

write_aggregate "qualification_summary.json"
decision=$(
  "$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["decision"])' "$OUT/qualification_summary.json"
)
[[ "$decision" == "GO" ]] || {
  echo "qualification 汇总未达到 GO：$decision" >&2
  exit 1
}
(
  cd "$REPO"
  conda run -n eai-swarm python marllib/analyze_c3_reservation_4uav.py \
    --summary "$OUT/qualification_summary.json" --manifest "$MANIFEST" \
    --output "$OUT/figures_and_statistics"
)
write_root_integrity
touch "$OUT/COMPLETE"
echo "C3-Reservation 4-UAV qualification GO"
