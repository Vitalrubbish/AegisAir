#!/usr/bin/env python3
"""Audit and aggregate the frozen C1 PX4 v2 validation outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
from typing import Any


EXPECTED_TAU = {
    "barrier_tau_px4_s": 0.2,
    "command_feedforward_tau_s": 0.7,
    "admission_execution_tau_s": 0.7,
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def aggregate(manifest: dict[str, Any], data_dir: Path) -> dict[str, Any]:
    rows = []
    errors = []
    for trial in manifest["trials"]:
        path = data_dir / trial["trial_id"] / "summary.json"
        if not path.is_file():
            errors.append(f"missing {trial['trial_id']}")
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        trial_rows = payload.get("trials", [])
        if len(trial_rows) != 1:
            errors.append(f"{trial['trial_id']}: expected one row")
            continue
        row = trial_rows[0]
        trajectory = data_dir / trial["trial_id"] / row["trajectory"]
        checks = {
            "trial_id": row.get("trial_id") == trial["trial_id"],
            "seed": row.get("seed") == trial["seed"],
            "manifest_hash": payload.get("manifest_sha256")
            == _sha256(data_dir / "manifest.json"),
            "trajectory_hash": trajectory.is_file()
            and row.get("trajectory_sha256") == _sha256(trajectory),
            "tau": row.get("tau") == EXPECTED_TAU,
        }
        if not all(checks.values()):
            errors.append(f"{trial['trial_id']}: audit failed {checks}")
            continue
        rows.append(row)
    if errors:
        raise ValueError("; ".join(errors))

    min_rhos = [float(row["min_rho"]) for row in rows]
    min_distances = [float(row["min_distance_m"]) for row in rows]
    paths = [float(row["path_length_m"]) for row in rows]
    gate = {
        "all_twenty_present": len(rows) == 20,
        "collision_free": all(not row["collision"] for row in rows),
        "positive_margin": all(value > 0.0 for value in min_rhos),
        "mission_complete": all(row["mission_complete"] for row in rows),
        "tau_roles_frozen": all(row["tau"] == EXPECTED_TAU for row in rows),
    }
    return {
        "protocol_id": manifest["protocol_id"],
        "decision": "GO" if all(gate.values()) else "NO_GO",
        "gate": gate,
        "n_trials": len(rows),
        "metrics": {
            "min_rho_min": min(min_rhos),
            "min_rho_mean": statistics.fmean(min_rhos),
            "min_rho_max": max(min_rhos),
            "min_distance_m_min": min(min_distances),
            "min_distance_m_mean": statistics.fmean(min_distances),
            "path_length_m_mean": statistics.fmean(paths),
            "path_length_m_range": [min(paths), max(paths)],
            "collision_count": sum(bool(row["collision"]) for row in rows),
            "completion_count": sum(bool(row["mission_complete"]) for row in rows),
            "latch_trip_count": sum(int(row["latch_trip_count"]) for row in rows),
            "cbf_event_count": sum(int(row["cbf_events"]) for row in rows),
        },
        "tau": EXPECTED_TAU,
        "manifest_sha256": _sha256(data_dir / "manifest.json"),
        "trials": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate C1 PX4 v2")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    summary = aggregate(manifest, args.data_dir)
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({k: summary[k] for k in ("decision", "n_trials", "metrics")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
