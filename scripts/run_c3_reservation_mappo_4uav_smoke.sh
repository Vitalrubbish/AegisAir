#!/usr/bin/env bash
# 每个条件使用全新四机 PX4/Gazebo 栈运行配对 calibration。
set -euo pipefail

REPO="/Users/lijiajun/Documents/drone/AegisAir"
MANIFEST="${1:?usage: $0 MANIFEST OUTROOT}"
OUT="${2:?usage: $0 MANIFEST OUTROOT}"
PY="/opt/anaconda3/envs/eai-swarm/bin/python"

if [[ -e "$OUT" ]]; then
  echo "拒绝覆盖已有输出目录：$OUT" >&2
  exit 2
fi
mkdir -p "$OUT/conditions"
cp "$MANIFEST" "$OUT/manifest.json"
shasum -a 256 "$MANIFEST" >"$OUT/manifest.sha256"
touch "$OUT/STARTED"

index=0
while IFS= read -r condition; do
  # The PX4 launcher rejects overlap by command-line identity.  Require a
  # stable process-free interval after the previous condition's cleanup so a
  # fresh trial cannot race a still-exiting PX4 process.
  stable_clear=0
  for _ in $(seq 1 120); do
    if pgrep -f 'px4.*-i (2|3|4|5)' >/dev/null 2>&1; then
      stable_clear=0
    else
      stable_clear=$((stable_clear + 1))
      (( stable_clear >= 6 )) && break
    fi
    sleep 0.5
  done
  if (( stable_clear < 6 )); then
    echo "PX4 条件隔离失败：旧实例未在 60 秒内退出" >&2
    touch "$OUT/invalid_condition_isolation"
    exit 1
  fi
  condition_out=$(printf '%s/conditions/%02d_%s' "$OUT" "$index" "$condition")
  C3_RUNNER="marllib/run_c3_reservation_mappo_gazebo.py" \
  C3_CONDITION="$condition" \
    "$REPO/scripts/run_c3_reservation_4uav_smoke.sh" "$MANIFEST" "$condition_out"
  index=$((index + 1))
done < <("$PY" -c "import json,sys; print('\\n'.join(json.load(open(sys.argv[1]))['condition_order']))" "$MANIFEST")

(
  cd "$REPO"
  conda run -n eai-swarm python marllib/aggregate_c3_reservation_mappo.py \
    --manifest "$MANIFEST" --conditions-root "$OUT/conditions" --output "$OUT/summary.json"
) | tee "$OUT/aggregate.log"
shasum -a 256 "$OUT/summary.json" >"$OUT/integrity.sha256"
touch "$OUT/COMPLETE"
