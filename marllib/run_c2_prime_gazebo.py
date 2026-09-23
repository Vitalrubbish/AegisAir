#!/usr/bin/env python3
"""Run frozen C2-prime calibration or validation trials on PX4/Gazebo.

The full PX4/Gazebo/MQTT stack must already be running.  This runner never
derives thresholds from validation data.  Supervised conditions require a
separate frozen calibration artifact produced before validation starts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from marllib.phase5_runner import run_mqtt_loop
from swarm.ra.execution_supervisor import ExecutionSupervisorConfig


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _supervisor_config(
    condition: str,
    calibration: dict | None,
    predictive_contract: dict | None = None,
) -> ExecutionSupervisorConfig | None:
    if condition == "E2_FIXED":
        return None
    if condition == "E2_OBSERVE":
        # Observation-only calibration: all switch gates are placed outside
        # the operating range, while residuals remain logged every cycle.
        return ExecutionSupervisorConfig(
            tau_s=0.2,
            velocity_residual_limit_mps=1e6,
            position_residual_limit_m=1e6,
            max_telemetry_age_s=1e6,
            solve_deadline_s=1e6,
            trip_samples=1_000_000,
            enable_qp_gate=False,
        )
    if calibration is None:
        raise ValueError(f"{condition} requires --calibration")
    frozen = calibration["frozen_thresholds"]
    if condition == "E2_QP_GATE":
        return ExecutionSupervisorConfig(
            tau_s=float(frozen["tau_s"]),
            velocity_residual_limit_mps=float(frozen["velocity_residual_limit_mps"]),
            position_residual_limit_m=float(frozen["position_residual_limit_m"]),
            max_telemetry_age_s=float(frozen["max_telemetry_age_s"]),
            solve_deadline_s=float(frozen["solve_deadline_s"]),
            trip_samples=int(frozen["trip_samples"]),
            release_samples=int(frozen["release_samples"]),
            backup_speed_mps=float(frozen["backup_speed_mps"]),
            enable_residual_gate=False,
        )
    if condition == "C2_PRIME":
        return ExecutionSupervisorConfig(**frozen)
    if condition == "PREDICTIVE_GATE":
        if predictive_contract is None:
            raise ValueError("PREDICTIVE_GATE requires a frozen predictive_contract")
        required = {
            "safe_distance_m",
            "response_delay_s",
            "braking_deceleration_mps2",
            "recoverability_buffer_m",
        }
        missing = sorted(required.difference(predictive_contract))
        if missing:
            raise ValueError(f"predictive_contract missing {missing}")
        return ExecutionSupervisorConfig(
            **frozen,
            enable_predictive_gate=True,
            **{name: float(predictive_contract[name]) for name in required},
        )
    raise ValueError(f"unknown C2-prime condition: {condition}")


def main() -> int:
    parser = argparse.ArgumentParser(description="C2-prime PX4/Gazebo runner")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--trial-id",
        action="append",
        help="Run only named physical trial(s); use fresh SITL per invocation.",
    )
    args = parser.parse_args()

    manifest = _load_json(args.manifest)
    calibration = _load_json(args.calibration) if args.calibration else None
    valid_protocols = {
        "aegisair-c2-prime-v1",
        "aegisair-c2-prime-v2-current-head",
        "aegisair-c2-predictive-v1",
    }
    if manifest.get("protocol_id") not in valid_protocols:
        parser.error(f"manifest protocol_id must be one of {sorted(valid_protocols)}")
    predictive_contract = manifest.get("predictive_contract")
    if manifest.get("phase") in {"validation", "pilot"} and calibration is None:
        parser.error("validation/pilot requires a frozen --calibration artifact")
    if any(
        "PREDICTIVE_GATE" in trial["condition_order"]
        for trial in manifest["trials"]
    ) and predictive_contract is None:
        parser.error("PREDICTIVE_GATE requires manifest.predictive_contract")
    if args.out_dir.exists():
        parser.error(f"refusing to overwrite existing output directory: {args.out_dir}")
    args.out_dir.mkdir(parents=True)

    all_trials = list(manifest["trials"])
    selected_ids = set(args.trial_id or [])
    selected_trials = (
        [trial for trial in all_trials if str(trial["trial_id"]) in selected_ids]
        if selected_ids
        else all_trials
    )
    missing_ids = selected_ids.difference(str(trial["trial_id"]) for trial in selected_trials)
    if missing_ids:
        parser.error(f"unknown trial_id(s): {sorted(missing_ids)}")

    rows = []
    total_episodes = sum(len(trial["condition_order"]) for trial in selected_trials)
    episode_index = 0
    for trial in selected_trials:
        trial_id = str(trial["trial_id"])
        lateral = float(trial["lateral_m"])
        calibration_phase = manifest["phase"] == "calibration"
        drone_ids = [2] if calibration_phase else [2, 3]
        base_goals = (
            {2: (3.0, lateral, 2.5)}
            if calibration_phase
            else {2: (3.0, lateral, 2.5), 3: (-3.0, -lateral, 2.5)}
        )
        reset_starts = (
            {2: (-3.0, 0.0, 2.5)}
            if calibration_phase
            else {2: (-3.0, 0.0, 2.5), 3: (3.0, 0.0, 2.5)}
        )
        for order_index, condition in enumerate(trial["condition_order"]):
            trajectory = args.out_dir / f"{trial_id}_{order_index:02d}_{condition}.jsonl"
            config = _supervisor_config(condition, calibration, predictive_contract)
            run = run_mqtt_loop(
                drone_ids=drone_ids,
                base_goals=base_goals,
                mode="CBF_ONLY",
                llm_client=None,
                llm_fallback=None,
                host=args.host,
                port=args.port,
                max_steps=int(manifest["max_steps"]),
                trajectory=trajectory,
                reset_starts=reset_starts,
                rate_hz=float(manifest["rate_hz"]),
                tau_ctrl=0.2,
                tau_px4=0.2,
                execution_model="exact_zoh",
                sampled_data=True,
                gamma=0.1,
                execution_supervisor_config=config,
                # Keep all paired trials in the same velocity-offboard regime;
                # a LAND between conditions creates a re-arm/EKF race and is
                # not a valid execution-model comparison.
                land_at_end=(episode_index == total_episodes - 1),
            )
            rows.append(
                {
                    "trial_id": trial_id,
                    "lateral_m": lateral,
                    "condition": condition,
                    "order_index": order_index,
                    "min_rho": run["min_rho"],
                    "min_distance_m": run["min_distance_m"],
                    "cbf_events": run["cbf_events"],
                    "reset_elapsed_s": run["reset_elapsed_s"],
                    "execution_supervisor": run["execution_supervisor"],
                    "trajectory": trajectory.name,
                    "trajectory_sha256": _sha256(trajectory),
                }
            )
            episode_index += 1
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)

    payload = {
        "protocol_id": manifest["protocol_id"],
        "phase": manifest["phase"],
        "selected_trial_ids": [str(trial["trial_id"]) for trial in selected_trials],
        "manifest": str(args.manifest),
        "manifest_sha256": _sha256(args.manifest),
        "calibration": str(args.calibration) if args.calibration else None,
        "calibration_sha256": _sha256(args.calibration) if args.calibration else None,
        "predictive_contract": predictive_contract,
        "trials": rows,
    }
    (args.out_dir / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
