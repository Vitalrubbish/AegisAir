#!/usr/bin/env python3
"""四机 C3-Admission 与 C3-Reservation 的独立 calibration smoke。"""

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
from marllib.run_c1_sota_cbf_gazebo import _method_kwargs, _trajectory_metrics
from swarm.recovery import (
    AdmissionConfig,
    C3AdmissionCoordinator,
    C3ReservationCoordinator,
    ReservationConfig,
)


PROTOCOL_ID = "aegisair-c3-reservation-4uav-calibration-smoke-v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _coordinators(
    condition: str,
    manifest: dict[str, Any],
    drone_ids: list[int],
    starts: dict[int, tuple[float, float, float]],
    goals: dict[int, tuple[float, float, float]],
):
    shared = manifest["shared_admission"]
    if condition == "R2_C3_ADMISSION":
        return C3AdmissionCoordinator(
            AdmissionConfig(
                conflict_zone_id=shared["conflict_zone_id"],
                conflict_zone_center=tuple(shared["conflict_zone_center"]),
                conflict_zone_radius_m=float(shared["conflict_zone_radius_m"]),
                admission_horizon_s=float(shared["admission_horizon_s"]),
                reserve_threshold=float(shared["reserve_threshold"]),
                predicted_rho_warning=float(shared["predicted_rho_warning"]),
                fallback_d_safe_m=float(shared["fallback_d_safe_m"]),
                hold_offset_m=float(shared["hold_offset_m"]),
                hold_goal_epsilon_m=float(shared["position_epsilon_m"]),
            ),
            drone_ids,
        ), None
    if condition == "R3_C3_RESERVATION":
        reservation = manifest["reservation"]
        return None, C3ReservationCoordinator(
            ReservationConfig(
                conflict_zone_id=shared["conflict_zone_id"],
                conflict_zone_center=tuple(shared["conflict_zone_center"]),
                conflict_zone_radius_m=float(shared["conflict_zone_radius_m"]),
                admission_horizon_s=float(shared["admission_horizon_s"]),
                reserve_threshold=float(shared["reserve_threshold"]),
                predicted_rho_warning=float(shared["predicted_rho_warning"]),
                fallback_d_safe_m=float(shared["fallback_d_safe_m"]),
                hold_offset_m=float(shared["hold_offset_m"]),
                clearance_offset_m=float(reservation["clearance_offset_m"]),
                position_epsilon_m=float(shared["position_epsilon_m"]),
                speed_epsilon_mps=float(reservation["speed_epsilon_mps"]),
                settle_steps=int(reservation["settle_steps"]),
                ra_veto_streak_limit=int(reservation["ra_veto_streak_limit"]),
                transit_scale=float(reservation["transit_scale"]),
            ),
            drone_ids,
            starts,
            goals,
        )
    raise ValueError(f"未知条件：{condition}")


def _audit(path: Path, condition: str) -> dict[str, Any]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    audit: dict[str, Any] = {
        "steps": len(rows),
        "selected_qp_infeasible_steps": sum(
            any(drone.get("feasible") is False for drone in row["drones"].values())
            for row in rows
        ),
        "ra_bypass_count": sum(
            int(drone.get("ra_bypass", True))
            for row in rows
            for drone in row["drones"].values()
        ),
    }
    if condition == "R2_C3_ADMISSION":
        audit["reservation_absent"] = all(
            row.get("coordination_reservation") is None for row in rows
        )
        return audit
    decisions = [row["coordination_reservation"] for row in rows]
    modes = [decision["coordination_mode"] for decision in decisions if decision]
    active = [
        (row, decision)
        for row, decision in zip(rows, decisions)
        if decision and decision["coordination_mode"] != "normal"
    ]
    clearance_versions: dict[str, set[tuple[float, float, float]]] = {}
    for decision in decisions:
        if decision and decision["clearance_drone_id"] is not None:
            clearance_versions.setdefault(str(decision["clearance_drone_id"]), set()).add(
                tuple(decision["clearance_goal"])
            )
    transitions = []
    previous = None
    for decision in decisions:
        if not decision:
            continue
        key = (decision["coordination_mode"], tuple(decision["authorized_drone_ids"]))
        if key != previous:
            transitions.append([decision["step"], key[0], list(key[1])])
            previous = key
    first_row, first_decision = active[0] if active else (None, None)
    required = ["staging", "pass", "clear", "release", "final_return", "complete"]
    audit.update(
        {
            "triggered": bool(active),
            "first_trigger_step": first_decision["step"] if first_decision else None,
            "first_trigger_current_min_rho": first_row["min_rho"] if first_row else None,
            "triggered_while_current_rho_positive": bool(first_row) and first_row["min_rho"] > 0.0,
            "modes_seen": sorted(set(modes)),
            "required_modes_seen": all(mode in modes for mode in required),
            "clearance_goals_stable": len(clearance_versions) == 4
            and all(len(values) == 1 for values in clearance_versions.values()),
            "clearance_goal_versions": {
                drone: len(values) for drone, values in clearance_versions.items()
            },
            "ra_vetoed_steps": sum(
                int(decision["ra_vetoed"]) for decision in decisions if decision
            ),
            "revoke_hold_seen": "revoke_hold" in modes,
            "transitions": transitions,
        }
    )
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("protocol_id") != PROTOCOL_ID:
        parser.error(f"protocol_id 必须为 {PROTOCOL_ID}")
    if args.output.exists():
        parser.error(f"拒绝覆盖已有输出目录：{args.output}")
    args.output.mkdir(parents=True)
    drone_ids = [int(value) for value in manifest["drone_ids"]]
    starts = {int(key): tuple(value) for key, value in manifest["reset_starts"].items()}
    goals = {int(key): tuple(value) for key, value in manifest["base_goals"].items()}
    rows = []
    for order_index, condition in enumerate(manifest["condition_order"]):
        admission, reservation = _coordinators(condition, manifest, drone_ids, starts, goals)
        trajectory = args.output / f"{order_index:02d}_{condition}.jsonl"
        run = run_mqtt_loop(
            drone_ids=drone_ids,
            base_goals=goals,
            reset_starts=starts,
            mode="CBF_ONLY",
            llm_client=None,
            llm_fallback=None,
            host="127.0.0.1",
            port=1883,
            max_steps=int(manifest["max_steps"]),
            rate_hz=float(manifest["rate_hz"]),
            goal_epsilon=float(manifest["goal_epsilon"]),
            trajectory=trajectory,
            admission_coordinator=admission,
            reservation_coordinator=reservation,
            land_at_end=order_index == len(manifest["condition_order"]) - 1,
            **_method_kwargs(
                manifest["method"], manifest["method_config"], float(manifest["execution_tau_s"])
            ),
        )
        effort, _ = _trajectory_metrics(trajectory)
        complete = all(
            np.linalg.norm(
                np.asarray(run["final_positions"][drone][:2]) - np.asarray(goals[drone][:2])
            ) < float(manifest["goal_epsilon"])
            for drone in drone_ids
        )
        row = {
            "condition": condition,
            "mission_complete": complete,
            "collision": run["collision"],
            "min_rho": run["min_rho"],
            "min_distance_m": run["min_distance_m"],
            "path_length_m": run["path_length_m"],
            "mean_control_effort": effort,
            "ra_solve_latency_summary_ms": run["ra_solve_latency_summary_ms"],
            "safety_bypass_count": run["safety_bypass_count"],
            "c3_admission_summary": run["c3_admission"],
            "c3_reservation_summary": run["c3_reservation"],
            "audit": _audit(trajectory, condition),
            "trajectory": trajectory.name,
            "trajectory_sha256": _sha256(trajectory),
            "final_positions": run["final_positions"],
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    r3 = next(row for row in rows if row["condition"] == "R3_C3_RESERVATION")
    latency = r3["ra_solve_latency_summary_ms"]
    summary_state = r3["c3_reservation_summary"] or {}
    r3_go = bool(
        r3["mission_complete"]
        and not r3["collision"]
        and r3["min_rho"] is not None
        and r3["min_rho"] > 0.0
        and r3["audit"]["selected_qp_infeasible_steps"] == 0
        and r3["safety_bypass_count"] == 0
        and r3["audit"]["ra_bypass_count"] == 0
        and r3["audit"]["required_modes_seen"]
        and r3["audit"]["clearance_goals_stable"]
        and not r3["audit"]["revoke_hold_seen"]
        and summary_state.get("complete") is True
        and len(summary_state.get("service_latched", [])) == 4
        and len(summary_state.get("cleared", [])) == 4
        and len(summary_state.get("final_returned", [])) == 4
        and summary_state.get("revoke_count") == 0
        and latency["p99"] < 50.0
        and latency["deadline_misses"] / int(manifest["max_steps"]) < 0.01
    )
    summary = {
        "protocol_id": PROTOCOL_ID,
        "phase": manifest["phase"],
        "decision": "GO" if r3_go else "NO_GO",
        "manifest_sha256": _sha256(args.manifest),
        "gazebo_seed": manifest["gazebo_seed"],
        "r3_go": r3_go,
        "conditions": rows,
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output / "manifest.json").write_bytes(args.manifest.read_bytes())
    names = ["manifest.json", *(row["trajectory"] for row in rows), "summary.json"]
    (args.output / "integrity.sha256").write_text(
        "".join(f"{_sha256(args.output / name)}  {name}\n" for name in names),
        encoding="utf-8",
    )
    (args.output / "COMPLETE").touch()
    print(json.dumps({"decision": summary["decision"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
