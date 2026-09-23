#!/usr/bin/env python3
"""从完整 trajectory 重建 post-processing crash 的 recoverability summary。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from marllib.phase5_runner import _latency_summary_ms
from marllib.run_c_recoverability_admission_gazebo import _trajectory_audit


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--condition-dir", type=Path, required=True)
    parser.add_argument("--trial-id", required=True)
    parser.add_argument("--condition", required=True)
    args = parser.parse_args()
    if (args.condition_dir / "summary.json").exists():
        parser.error("summary 已存在，拒绝覆盖")
    trajectory = args.condition_dir / "trajectory.jsonl"
    records = [
        json.loads(line)
        for line in trajectory.read_text(encoding="utf-8").splitlines()
    ]
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if len(records) != int(manifest["max_steps"]):
        parser.error("trajectory 不完整，不能重建")
    trial = next(
        item for item in manifest["trials"] if item["trial_id"] == args.trial_id
    )
    geometry = manifest["geometries"][trial["geometry_id"]]
    failed = int(manifest["failed_drone"])
    healthy = next(int(value) for value in manifest["drone_ids"] if int(value) != failed)
    audit = _trajectory_audit(
        trajectory,
        failed_drone=failed,
        healthy_drone=healthy,
        change_step=int(manifest["change_step"]),
        critical_goal=tuple(geometry["critical_goal"]),
        goal_epsilon=float(manifest["goal_epsilon"]),
    )
    path_length = 0.0
    previous: dict[str, np.ndarray] = {}
    for record in records:
        for drone, data in record["drones"].items():
            position = np.asarray(data["pos"], dtype=np.float64)
            if drone in previous:
                path_length += float(np.linalg.norm(position - previous[drone]))
            previous[drone] = position
    latencies = [float(record["ra_solve_latency_ms"]) for record in records]
    final_admission = records[-1].get("recoverability_admission")
    recovery_step = next(
        (
            int(record["step"])
            for record in records
            if (record.get("recoverability_admission") or {}).get("plans_committed", 0) > 0
        ),
        None,
    )
    row = {
        "trial_id": trial["trial_id"],
        "geometry_id": trial["geometry_id"],
        "seed": trial["seed"],
        "condition": args.condition,
        "expected_admission": geometry["expected_admission"],
        "collision": any(float(record["min_distance"]) < 0.25 for record in records),
        "min_rho": min(float(record["min_rho"]) for record in records),
        "min_distance_m": min(float(record["min_distance"]) for record in records),
        "critical_reached": audit["post_failure_critical_reached_by_healthy"],
        "post_failure_critical_reached": audit["post_failure_critical_reached_by_healthy"],
        "recovery_step": recovery_step,
        "path_length_m": round(path_length, 6),
        "counters": None,
        "recoverability_admission": final_admission,
        "safety_bypass_count": audit["ra_bypass_count"],
        "ra_solve_latency_summary_ms": _latency_summary_ms(latencies, deadline_ms=50.0),
        "trajectory_audit": audit,
        "trajectory": trajectory.name,
        "trajectory_sha256": _sha256(trajectory),
        "postprocessing_recovered": True,
    }
    payload = {
        "protocol_id": manifest["protocol_id"],
        "phase": manifest["phase"],
        "manifest_sha256": _sha256(args.manifest),
        "trial": trial,
        "geometry": geometry,
        "trials": [row],
    }
    (args.condition_dir / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.condition_dir / "manifest.json").write_bytes(args.manifest.read_bytes())
    (args.condition_dir / "integrity.sha256").write_text(
        "".join(
            f"{_sha256(args.condition_dir / name)}  {name}\n"
            for name in ("manifest.json", "trajectory.jsonl", "summary.json")
        ),
        encoding="utf-8",
    )
    (args.condition_dir / "COMPLETE").touch()
    print(json.dumps(row, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
