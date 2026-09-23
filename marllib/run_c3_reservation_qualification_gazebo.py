#!/usr/bin/env python3
"""运行一个全新 SITL 的四机 R2/R3 qualification 条件。"""

from __future__ import annotations

import argparse
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
from marllib.run_c3_reservation_gazebo import _audit, _coordinators, _sha256


PROTOCOL_ID = "aegisair-c3-reservation-4uav-qualification-v1"
CONDITIONS = ("R2_C3_ADMISSION", "R3_C3_RESERVATION")


def validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("protocol_id") != PROTOCOL_ID:
        raise ValueError(f"protocol_id 必须为 {PROTOCOL_ID}")
    if manifest.get("drone_ids") != [2, 3, 4, 5]:
        raise ValueError("qualification 必须固定为 UAV 2/3/4/5")
    if float(manifest.get("rate_hz", 0.0)) != 20.0 or int(
        manifest.get("max_steps", 0)
    ) != 1200:
        raise ValueError("qualification 必须固定为 20 Hz、1200 步（60 s）")
    seeds = manifest.get("qualification_seeds", [])
    if len(seeds) != 5 or len(set(seeds)) != 5:
        raise ValueError("qualification 必须包含五个不同的新 seed")
    schedule = manifest.get("condition_order_by_seed", {})
    if set(schedule) != {str(seed) for seed in seeds}:
        raise ValueError("每个 qualification seed 必须有冻结条件顺序")
    orders = []
    for seed in seeds:
        order = schedule[str(seed)]
        if sorted(order) != sorted(CONDITIONS):
            raise ValueError(f"seed {seed} 必须且只能各运行一次 R2/R3")
        orders.append(tuple(order))
    first_counts = {condition: sum(order[0] == condition for order in orders) for condition in CONDITIONS}
    if abs(first_counts[CONDITIONS[0]] - first_counts[CONDITIONS[1]]) > 1:
        raise ValueError("五 seed 条件首位必须按 3:2 平衡")
    if int(manifest.get("max_invalid_attempts_per_condition", 0)) < 1:
        raise ValueError("必须冻结无效启动的最大重试次数")


def _completion_step(
    trajectory: Path,
    condition: str,
    goals: dict[int, tuple[float, float, float]],
    epsilon: float,
) -> int | None:
    for line in trajectory.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if condition == "R3_C3_RESERVATION":
            decision = row.get("coordination_reservation")
            if decision and decision.get("coordination_mode") == "complete":
                return int(row["step"])
        elif all(
            np.linalg.norm(
                np.asarray(row["drones"][str(drone)]["pos"][:2])
                - np.asarray(goals[drone][:2])
            )
            < epsilon
            for drone in goals
        ):
            return int(row["step"])
    return None


def _r3_go(row: dict[str, Any], max_steps: int) -> bool:
    state = row["c3_reservation_summary"] or {}
    audit = row["audit"]
    latency = row["ra_solve_latency_summary_ms"]
    return bool(
        row["mission_complete"]
        and not row["collision"]
        and row["min_rho"] is not None
        and row["min_rho"] > 0.0
        and audit["selected_qp_infeasible_steps"] == 0
        and row["safety_bypass_count"] == 0
        and audit["ra_bypass_count"] == 0
        and audit["required_modes_seen"]
        and audit["clearance_goals_stable"]
        and not audit["revoke_hold_seen"]
        and state.get("complete") is True
        and len(state.get("service_latched", [])) == 4
        and len(state.get("cleared", [])) == 4
        and len(state.get("final_returned", [])) == 4
        and state.get("revoke_count") == 0
        and latency["p99"] < 50.0
        and latency["deadline_misses"] / max_steps < 0.01
    )


def _joint_success(row: dict[str, Any]) -> bool:
    return bool(
        row["mission_complete"]
        and not row["collision"]
        and row["min_rho"] is not None
        and row["min_rho"] > 0.0
        and row["audit"]["selected_qp_infeasible_steps"] == 0
        and row["safety_bypass_count"] == 0
        and row["audit"]["ra_bypass_count"] == 0
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--condition", choices=CONDITIONS, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    try:
        validate_manifest(manifest)
    except ValueError as exc:
        parser.error(str(exc))
    if args.seed not in manifest["qualification_seeds"]:
        parser.error(f"seed 未冻结在 qualification 中：{args.seed}")
    if args.output.exists():
        parser.error(f"拒绝覆盖已有输出目录：{args.output}")
    args.output.mkdir(parents=True)

    drone_ids = [int(value) for value in manifest["drone_ids"]]
    starts = {int(key): tuple(value) for key, value in manifest["reset_starts"].items()}
    goals = {int(key): tuple(value) for key, value in manifest["base_goals"].items()}
    admission, reservation = _coordinators(
        args.condition, manifest, drone_ids, starts, goals
    )
    trajectory = args.output / f"seed_{args.seed}_{args.condition}.jsonl"
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
        land_at_end=True,
        **_method_kwargs(
            manifest["method"],
            manifest["method_config"],
            float(manifest["execution_tau_s"]),
        ),
    )
    effort, _ = _trajectory_metrics(trajectory)
    mission_complete = all(
        np.linalg.norm(
            np.asarray(run["final_positions"][drone][:2])
            - np.asarray(goals[drone][:2])
        )
        < float(manifest["goal_epsilon"])
        for drone in drone_ids
    )
    audit = _audit(trajectory, args.condition)
    row = {
        "seed": args.seed,
        "condition": args.condition,
        "valid_trial": True,
        "mission_complete": mission_complete,
        "collision": run["collision"],
        "min_rho": run["min_rho"],
        "min_distance_m": run["min_distance_m"],
        "path_length_m": run["path_length_m"],
        "mean_control_effort": effort,
        "completion_step": _completion_step(
            trajectory, args.condition, goals, float(manifest["goal_epsilon"])
        ),
        "horizon_steps": int(manifest["max_steps"]),
        "rate_hz": float(manifest["rate_hz"]),
        "ra_solve_latency_summary_ms": run["ra_solve_latency_summary_ms"],
        "safety_bypass_count": run["safety_bypass_count"],
        "c3_admission_summary": run["c3_admission"],
        "c3_reservation_summary": run["c3_reservation"],
        "audit": audit,
        "trajectory": trajectory.name,
        "trajectory_sha256": _sha256(trajectory),
        "final_positions": run["final_positions"],
    }
    row["joint_success"] = _joint_success(row)
    row["r3_qualification_go"] = (
        _r3_go(row, int(manifest["max_steps"]))
        if args.condition == "R3_C3_RESERVATION"
        else None
    )
    summary = {
        "protocol_id": PROTOCOL_ID,
        "phase": manifest["phase"],
        "manifest_sha256": _sha256(args.manifest),
        "seed": args.seed,
        "condition": args.condition,
        "trial": row,
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
    print(json.dumps(row, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
