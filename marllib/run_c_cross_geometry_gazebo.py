#!/usr/bin/env python3
"""运行 C 工作包三种失效几何的 PX4/Gazebo calibration smoke。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from marllib.phase5_runner import run_mqtt_loop
from marllib.run_c3_gazebo import _recovery_clients


PROTOCOL_ID = "aegisair-c-cross-geometry-calibration-smoke-v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ra_kwargs(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "use_hocbf": True,
        "hocbf_k1": float(config["k1"]),
        "hocbf_k2": float(config["k2"]),
        "tau_ctrl": float(config["tau_ctrl_s"]),
        "tau_px4": float(config["execution_tau_s"]),
        "tau_px4_min": float(config["execution_tau_s"]),
        "tau_px4_max": float(config["execution_tau_s"]),
        "execution_model": "exact_zoh",
        "sampled_data": False,
        "hocbf_boundary_guard": float(config["boundary_guard"]),
        "hocbf_boundary_buffer_m": float(config["boundary_buffer_m"]),
        "hocbf_infeasible_fallback": "max_brake",
        "hocbf_pb_recovery": True,
        "hocbf_predictive_recovery": True,
        "hocbf_prediction_execution_fraction": float(
            config["prediction_execution_fraction"]
        ),
        "hocbf_prediction_steps": int(config["prediction_steps"]),
        "hocbf_recovery_reserve_threshold": float(
            config["recovery_reserve_threshold"]
        ),
        "hocbf_recovery_alpha": float(config["recovery_alpha"]),
        "hocbf_recovery_braking_accel": float(
            config["recovery_braking_accel_mps2"]
        ),
        "hocbf_recovery_boundary_buffer_m": float(
            config["recovery_boundary_buffer_m"]
        ),
        "hocbf_recovery_clear_steps": int(config["recovery_clear_steps"]),
        "ra_command_feedforward_tau_s": float(config["execution_tau_s"]),
    }


def _audit_trajectory(
    path: Path, *, failed_drone: int, change_step: int
) -> dict[str, Any]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    after = [row for row in rows if int(row["step"]) >= change_step]
    failed_rows = [row["drones"][str(failed_drone)] for row in after]
    return {
        "steps": len(rows),
        "post_failure_steps": len(after),
        "ra_bypass_count": sum(
            int(drone.get("ra_bypass", True))
            for row in rows
            for drone in row["drones"].values()
        ),
        "failed_authority_revoked_all_steps": bool(failed_rows)
        and all(row.get("command_authority") == "failed_zero" for row in failed_rows),
        "failed_horizontal_command_zero_all_steps": bool(failed_rows)
        and all(
            np.linalg.norm(np.asarray(row["v_safe"][:2], dtype=np.float64))
            <= 1e-9
            for row in failed_rows
        ),
        "selected_qp_infeasible_steps": sum(
            any(drone.get("feasible") is False for drone in row["drones"].values())
            for row in rows
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--trial-id", required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("protocol_id") != PROTOCOL_ID:
        parser.error(f"protocol_id 必须为 {PROTOCOL_ID}")
    if args.out_dir.exists():
        parser.error(f"拒绝覆盖输出目录：{args.out_dir}")
    trial = next(
        (item for item in manifest["trials"] if item["trial_id"] == args.trial_id),
        None,
    )
    if trial is None:
        parser.error(f"未知 trial_id：{args.trial_id}")
    geometry = manifest["geometries"][trial["geometry_id"]]
    args.out_dir.mkdir(parents=True)
    starts = {int(k): tuple(v) for k, v in geometry["reset_starts"].items()}
    goals = {int(k): tuple(v) for k, v in geometry["base_goals"].items()}
    drone_ids = [int(value) for value in manifest["drone_ids"]]
    rows = []
    for order_index, condition in enumerate(trial["condition_order"]):
        mode, client, fallback = _recovery_clients(condition, "", 0)
        trajectory = args.out_dir / f"{order_index:02d}_{condition}.jsonl"
        run = run_mqtt_loop(
            drone_ids=drone_ids,
            base_goals=goals,
            reset_starts=starts,
            mode=mode,
            llm_client=client,
            llm_fallback=fallback,
            host="127.0.0.1",
            port=1883,
            max_steps=int(manifest["max_steps"]),
            rate_hz=float(manifest["rate_hz"]),
            trajectory=trajectory,
            mission_change=manifest["mission_change"],
            change_step=int(manifest["change_step"]),
            failed_drone=int(manifest["failed_drone"]),
            critical_goal=tuple(geometry["critical_goal"]),
            goal_epsilon=float(manifest["goal_epsilon"]),
            velocity_command_mode=manifest["velocity_command_mode"],
            tau_command_s=float(manifest["tau_command_s"]),
            land_at_end=order_index == len(trial["condition_order"]) - 1,
            **_ra_kwargs(manifest["ra_config"]),
        )
        audit = _audit_trajectory(
            trajectory,
            failed_drone=int(manifest["failed_drone"]),
            change_step=int(manifest["change_step"]),
        )
        rows.append(
            {
                "trial_id": trial["trial_id"],
                "geometry_id": trial["geometry_id"],
                "seed": trial["seed"],
                "condition": condition,
                "order_index": order_index,
                "collision": run["collision"],
                "min_rho": run["min_rho"],
                "min_distance_m": run["min_distance_m"],
                "critical_reached": run["critical_reached"],
                "recovery_step": run["recovery_step"],
                "path_length_m": run["path_length_m"],
                "counters": run.get("counters"),
                "safety_bypass_count": run["safety_bypass_count"],
                "ra_solve_latency_summary_ms": run[
                    "ra_solve_latency_summary_ms"
                ],
                "trajectory_audit": audit,
                "trajectory": trajectory.name,
                "trajectory_sha256": _sha256(trajectory),
            }
        )
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    r0 = next(row for row in rows if row["condition"] == "R0")
    r1 = next(row for row in rows if row["condition"] == "R1")
    all_rows_safe = all(
        not row["collision"]
        and row["min_rho"] is not None
        and row["min_rho"] > 0.0
        and row["safety_bypass_count"] == 0
        and row["trajectory_audit"]["ra_bypass_count"] == 0
        and row["trajectory_audit"]["failed_authority_revoked_all_steps"]
        and row["trajectory_audit"]["failed_horizontal_command_zero_all_steps"]
        and row["trajectory_audit"]["selected_qp_infeasible_steps"] == 0
        and row["ra_solve_latency_summary_ms"]["p99"] < 50.0
        and row["ra_solve_latency_summary_ms"]["deadline_misses"] == 0
        for row in rows
    )
    decision = "GO" if (
        all_rows_safe
        and not r0["critical_reached"]
        and r1["critical_reached"]
        and (r1.get("counters") or {}).get("mission_changes") == 1
    ) else "NO_GO"
    payload = {
        "protocol_id": PROTOCOL_ID,
        "phase": manifest["phase"],
        "decision": decision,
        "manifest_sha256": _sha256(args.manifest),
        "trial": trial,
        "geometry": geometry,
        "trials": rows,
    }
    (args.out_dir / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.out_dir / "manifest.json").write_bytes(args.manifest.read_bytes())
    (args.out_dir / "integrity.sha256").write_text(
        "".join(
            f"{_sha256(args.out_dir / name)}  {name}\n"
            for name in [
                "manifest.json",
                *(row["trajectory"] for row in rows),
                "summary.json",
            ]
        ),
        encoding="utf-8",
    )
    (args.out_dir / "COMPLETE").touch()
    print(json.dumps({"decision": decision, "trial_id": trial["trial_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
