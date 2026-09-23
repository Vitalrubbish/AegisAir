#!/usr/bin/env python3
"""四机 C3-STR 独立 PX4/Gazebo calibration smoke。"""

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
    C3SpaceTimeReservationCoordinator,
    SpaceTimeReservationConfig,
)


PROTOCOL_ID = "aegisair-c3-str-4uav-calibration-smoke-v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _coordinator(
    manifest: dict[str, Any],
    drone_ids: list[int],
    starts: dict[int, tuple[float, float, float]],
    goals: dict[int, tuple[float, float, float]],
) -> C3SpaceTimeReservationCoordinator:
    shared = manifest["shared_admission"]
    reservation = manifest["reservation"]
    schedule = manifest["space_time_reservation"]
    return C3SpaceTimeReservationCoordinator(
        SpaceTimeReservationConfig(
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
            rate_hz=float(manifest["rate_hz"]),
            staging_window_s=float(schedule["staging_window_s"]),
            service_window_s=float(schedule["service_window_s"]),
            final_return_window_s=float(schedule["final_return_window_s"]),
            veto_delay_steps=int(schedule["veto_delay_steps"]),
            return_compatibility_clearance_m=float(
                schedule["return_compatibility_clearance_m"]
            ),
        ),
        drone_ids,
        starts,
        goals,
    )


def _audit(path: Path, drone_ids: list[int]) -> dict[str, Any]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    decisions = [row.get("coordination_space_time_reservation") for row in rows]
    decisions = [decision for decision in decisions if decision is not None]
    modes = [decision["coordination_mode"] for decision in decisions]
    required_modes = ["staging", "pass", "clear", "release", "final_return", "complete"]
    window_history: dict[str, list[tuple[int, int]]] = {}
    early_authorizations: list[dict[str, Any]] = []
    invalid_authorizations: list[dict[str, Any]] = []
    previous_revision = -1
    revision_monotonic = True
    for decision in decisions:
        revision = int(decision["schedule_revision"])
        revision_monotonic = revision_monotonic and revision >= previous_revision
        previous_revision = revision
        windows = {window["slot_id"]: window for window in decision["reservation_windows"]}
        for slot_id, window in windows.items():
            window_history.setdefault(slot_id, []).append(
                (int(window["planned_open_step"]), int(window["planned_close_step"]))
            )
        authorized = list(decision["authorized_drone_ids"])
        active_id = decision["active_slot_id"]
        if authorized:
            active = windows.get(active_id)
            if active is None or set(authorized) != set(active["drone_ids"]):
                invalid_authorizations.append(
                    {"step": decision["step"], "active_slot_id": active_id, "authorized": authorized}
                )
            elif int(decision["step"]) < int(active["planned_open_step"]):
                early_authorizations.append(
                    {"step": decision["step"], "slot": active_id, "open": active["planned_open_step"]}
                )
    windows_never_move_earlier = all(
        all(
            current[0] >= previous[0] and current[1] >= previous[1]
            for previous, current in zip(history, history[1:])
        )
        for history in window_history.values()
    )
    veto_fail_closed = all(
        not decision["authorized_drone_ids"]
        for decision in decisions
        if decision["coordination_mode"] in {"slot_wait", "slot_delay"}
    )
    transitions: list[list[Any]] = []
    previous = None
    for decision in decisions:
        key = (
            decision["coordination_mode"],
            decision["active_slot_id"],
            tuple(decision["authorized_drone_ids"]),
        )
        if key != previous:
            transitions.append([decision["step"], key[0], key[1], list(key[2])])
            previous = key
    return {
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
        "modes_seen": sorted(set(modes)),
        "required_modes_seen": all(mode in modes for mode in required_modes),
        "window_count": len(window_history),
        "windows_never_move_earlier": windows_never_move_earlier,
        "schedule_revision_monotonic": revision_monotonic,
        "early_authorizations": early_authorizations,
        "invalid_authorizations": invalid_authorizations,
        "veto_fail_closed": veto_fail_closed,
        "all_drones_ever_authorized": set(drone_ids).issubset(
            {
                drone
                for decision in decisions
                for drone in decision["authorized_drone_ids"]
            }
        ),
        "transitions": transitions,
    }


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
    coordinator = _coordinator(manifest, drone_ids, starts, goals)
    trajectory = args.output / "R4_C3_STR.jsonl"
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
        space_time_reservation_coordinator=coordinator,
        land_at_end=True,
        **_method_kwargs(
            manifest["method"],
            manifest["method_config"],
            float(manifest["execution_tau_s"]),
        ),
    )
    effort, _ = _trajectory_metrics(trajectory)
    complete = all(
        np.linalg.norm(
            np.asarray(run["final_positions"][drone][:2]) - np.asarray(goals[drone][:2])
        ) < float(manifest["goal_epsilon"])
        for drone in drone_ids
    )
    audit = _audit(trajectory, drone_ids)
    state = run["c3_space_time_reservation"] or {}
    latency = run["ra_solve_latency_summary_ms"]
    grouped_return_active = any(
        len(group) > 1 for group in state.get("final_return_groups", [])
    )
    go = bool(
        complete
        and not run["collision"]
        and run["min_rho"] is not None
        and run["min_rho"] > 0.0
        and audit["selected_qp_infeasible_steps"] == 0
        and run["safety_bypass_count"] == 0
        and audit["ra_bypass_count"] == 0
        and audit["required_modes_seen"]
        and audit["windows_never_move_earlier"]
        and audit["schedule_revision_monotonic"]
        and not audit["early_authorizations"]
        and not audit["invalid_authorizations"]
        and audit["veto_fail_closed"]
        and audit["all_drones_ever_authorized"]
        and grouped_return_active
        and state.get("complete") is True
        and len(state.get("service_latched", [])) == len(drone_ids)
        and len(state.get("cleared", [])) == len(drone_ids)
        and len(state.get("final_returned", [])) == len(drone_ids)
        and latency["p99"] < 50.0
        and latency["deadline_misses"] / int(manifest["max_steps"]) < 0.01
    )
    condition = {
        "condition": "R4_C3_STR",
        "mission_complete": complete,
        "collision": run["collision"],
        "min_rho": run["min_rho"],
        "min_distance_m": run["min_distance_m"],
        "path_length_m": run["path_length_m"],
        "mean_control_effort": effort,
        "ra_solve_latency_summary_ms": latency,
        "safety_bypass_count": run["safety_bypass_count"],
        "c3_space_time_reservation_summary": state,
        "audit": audit,
        "trajectory": trajectory.name,
        "trajectory_sha256": _sha256(trajectory),
        "final_positions": run["final_positions"],
    }
    summary = {
        "protocol_id": PROTOCOL_ID,
        "phase": manifest["phase"],
        "decision": "GO" if go else "NO_GO",
        "manifest_sha256": _sha256(args.manifest),
        "gazebo_seed": manifest["gazebo_seed"],
        "r4_go": go,
        "condition": condition,
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output / "manifest.json").write_bytes(args.manifest.read_bytes())
    names = ["manifest.json", trajectory.name, "summary.json"]
    (args.output / "integrity.sha256").write_text(
        "".join(f"{_sha256(args.output / name)}  {name}\n" for name in names),
        encoding="utf-8",
    )
    (args.output / "COMPLETE").touch()
    print(json.dumps({"decision": summary["decision"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
