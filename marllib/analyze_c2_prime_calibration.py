#!/usr/bin/env python3
"""Freeze C2-prime residual thresholds from calibration trajectories only."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def _finite(values: list[float]) -> list[float]:
    return [value for value in values if math.isfinite(value)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze C2-prime calibration thresholds")
    parser.add_argument("--calibration-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error(f"refusing to overwrite {args.out}")

    summary = json.loads((args.calibration_dir / "summary.json").read_text(encoding="utf-8"))
    if summary.get("phase") != "calibration":
        parser.error("input summary is not calibration data")
    per_trial_velocity: list[float] = []
    per_trial_position: list[float] = []
    for trial in summary["trials"]:
        velocity: list[float] = []
        position: list[float] = []
        path = args.calibration_dir / trial["trajectory"]
        for line in path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)["execution_assurance"]
            if event is None:
                continue
            for residual in event["residuals"].values():
                velocity.append(float(residual["velocity_mps"]))
                position.append(float(residual["position_m"]))
        if velocity:
            per_trial_velocity.append(max(_finite(velocity)))
        if position:
            per_trial_position.append(max(_finite(position)))
    if not per_trial_velocity or not per_trial_position:
        parser.error("calibration trajectories contain no execution residuals")

    # Predeclared calibration rule: 10% guard above the worst calibration-trial
    # maximum.  Validation/final data are never used to revise these values.
    frozen = {
        "tau_s": 0.2,
        "velocity_residual_limit_mps": 1.10 * max(per_trial_velocity),
        "position_residual_limit_m": 1.10 * max(per_trial_position),
        # Engineering contracts, not empirical quantiles: calibration cannot
        # relax the 20 Hz compute deadline or the existing freshness bound.
        "max_telemetry_age_s": 0.15,
        "solve_deadline_s": 0.05,
        "trip_samples": 2,
        "release_samples": 10,
        "backup_speed_mps": 0.6,
        "enable_residual_gate": True,
        "enable_qp_gate": True,
    }
    payload = {
        "protocol_id": "aegisair-c2-prime-calibration-v1",
        "source_summary": str(args.calibration_dir / "summary.json"),
        "calibration_trials": len(per_trial_velocity),
        "threshold_rule": "1.10_times_worst_per_trial_maximum",
        "frozen_thresholds": frozen,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
