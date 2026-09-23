#!/usr/bin/env python3
"""运行四机 C3-Admission 的 R0/R1/R2 独立 calibration smoke。"""

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
from swarm.recovery import AdmissionConfig, C3AdmissionCoordinator


PROTOCOL_IDS = {
    "aegisair-c3-admission-4uav-calibration-smoke-v1",
    "aegisair-c3-admission-4uav-calibration-smoke-v2",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _admission_config(payload: dict[str, Any]) -> AdmissionConfig:
    return AdmissionConfig(
        conflict_zone_id=str(payload["conflict_zone_id"]),
        conflict_zone_center=tuple(float(v) for v in payload["conflict_zone_center"]),
        conflict_zone_radius_m=float(payload["conflict_zone_radius_m"]),
        admission_horizon_s=float(payload["admission_horizon_s"]),
        reserve_threshold=float(payload["reserve_threshold"]),
        predicted_rho_warning=float(payload["predicted_rho_warning"]),
        fallback_d_safe_m=float(payload["fallback_d_safe_m"]),
        release_margin_m=float(payload["release_margin_m"]),
        hold_offset_m=float(payload["hold_offset_m"]),
        hold_goal_epsilon_m=float(payload["hold_goal_epsilon_m"]),
    )


def _audit(path: Path, condition: str) -> dict[str, Any]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    infeasible = sum(
        any(drone.get("feasible") is False for drone in row["drones"].values())
        for row in rows
    )
    bypass = sum(
        int(drone.get("ra_bypass", True))
        for row in rows
        for drone in row["drones"].values()
    )
    audit: dict[str, Any] = {
        "steps": len(rows),
        "selected_qp_infeasible_steps": infeasible,
        "ra_bypass_count": bypass,
    }
    if condition != "R2_C3_ADMISSION":
        audit["coordination_admission_absent"] = all(
            row.get("coordination_admission") is None for row in rows
        )
        return audit
    decisions = [row["coordination_admission"] for row in rows]
    active = [
        (row, decision)
        for row, decision in zip(rows, decisions)
        if decision and decision["coordination_mode"] != "normal"
    ]
    frozen_by_drone: dict[str, set[tuple[float, float, float]]] = {}
    for decision in decisions:
        if not decision:
            continue
        for drone, goal in decision["frozen_hold_goals"].items():
            frozen_by_drone.setdefault(str(drone), set()).add(tuple(goal))
    modes = sorted({decision["coordination_mode"] for decision in decisions if decision})
    first_row, first_decision = active[0] if active else (None, None)
    audit.update(
        {
            "triggered": bool(active),
            "first_trigger_step": first_decision["step"] if first_decision else None,
            "first_trigger_current_min_rho": first_row["min_rho"] if first_row else None,
            "triggered_while_current_rho_positive": bool(first_row)
            and float(first_row["min_rho"]) > 0.0,
            "modes_seen": modes,
            "required_modes_seen": all(
                mode in modes for mode in ["admission_pending", "hold", "pass", "release"]
            ),
            "frozen_hold_goals_stable": bool(frozen_by_drone)
            and all(len(values) == 1 for values in frozen_by_drone.values()),
            "frozen_goal_versions": {
                drone: len(values) for drone, values in frozen_by_drone.items()
            },
            "authorized_cardinality_valid": all(
                len(decision["authorized_drone_ids"]) <= 1 for decision in decisions if decision
            ),
            "ra_vetoed_steps": sum(
                int(decision["ra_vetoed"]) for decision in decisions if decision
            ),
        }
    )
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("protocol_id") not in PROTOCOL_IDS:
        parser.error(f"protocol_id 必须属于 {sorted(PROTOCOL_IDS)}")
    if args.output.exists():
        parser.error(f"拒绝覆盖已有输出目录：{args.output}")
    args.output.mkdir(parents=True)
    drone_ids = [int(value) for value in manifest["drone_ids"]]
    starts = {int(key): tuple(value) for key, value in manifest["reset_starts"].items()}
    goals = {int(key): tuple(value) for key, value in manifest["base_goals"].items()}
    rows: list[dict[str, Any]] = []
    for order_index, condition in enumerate(manifest["condition_order"]):
        trajectory = args.output / f"{order_index:02d}_{condition}.jsonl"
        coordinator = (
            C3AdmissionCoordinator(_admission_config(manifest["c3_admission"]), drone_ids)
            if condition == "R2_C3_ADMISSION"
            else None
        )
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
            sequential_pass=condition == "R1_SEQUENTIAL_PASS",
            urgent_drone=2,
            admission_coordinator=coordinator,
            land_at_end=order_index == len(manifest["condition_order"]) - 1,
            **_method_kwargs(
                manifest["method"],
                manifest["method_config"],
                float(manifest["execution_tau_s"]),
            ),
        )
        effort, _ = _trajectory_metrics(trajectory)
        complete = all(
            np.linalg.norm(
                np.asarray(run["final_positions"][drone][:2])
                - np.asarray(goals[drone][:2])
            ) < float(manifest["goal_epsilon"])
            for drone in drone_ids
        )
        row = {
            "condition": condition,
            "order_index": order_index,
            "mission_complete": complete,
            "collision": run["collision"],
            "min_rho": run["min_rho"],
            "min_distance_m": run["min_distance_m"],
            "path_length_m": run["path_length_m"],
            "mean_control_effort": effort,
            "ra_solve_latency_summary_ms": run["ra_solve_latency_summary_ms"],
            "safety_bypass_count": run["safety_bypass_count"],
            "c3_admission_summary": run["c3_admission"],
            "audit": _audit(trajectory, condition),
            "trajectory": trajectory.name,
            "trajectory_sha256": _sha256(trajectory),
            "final_positions": run["final_positions"],
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    r2 = next(row for row in rows if row["condition"] == "R2_C3_ADMISSION")
    infrastructure_valid = all(
        not row["collision"]
        and row["safety_bypass_count"] == 0
        and row["audit"]["ra_bypass_count"] == 0
        and row["ra_solve_latency_summary_ms"]["p99"] < 50.0
        and row["ra_solve_latency_summary_ms"]["deadline_misses"] == 0
        for row in rows
    )
    r2_go = bool(
        r2["mission_complete"]
        and r2["min_rho"] is not None
        and r2["min_rho"] > 0.0
        and r2["audit"]["selected_qp_infeasible_steps"] == 0
        and r2["audit"]["triggered_while_current_rho_positive"]
        and r2["audit"]["required_modes_seen"]
        and r2["audit"]["frozen_hold_goals_stable"]
        and r2["audit"]["authorized_cardinality_valid"]
    )
    summary = {
        "protocol_id": manifest["protocol_id"],
        "phase": manifest["phase"],
        "decision": "GO" if infrastructure_valid and r2_go else "NO_GO",
        "manifest_sha256": _sha256(args.manifest),
        "gazebo_seed": manifest["gazebo_seed"],
        "infrastructure_valid": infrastructure_valid,
        "r2_go": r2_go,
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
