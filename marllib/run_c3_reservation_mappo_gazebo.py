#!/usr/bin/env python3
"""四机规则/MAPPO 名义策略接入 C3-Reservation 的配对 calibration。"""

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
from marllib.policies.mappo import MappoPilot
from marllib.run_c1_sota_cbf_gazebo import _method_kwargs, _trajectory_metrics
from marllib.run_c3_reservation_gazebo import _audit, _coordinators, _sha256


PROTOCOL_ID = "aegisair-c3-reservation-mappo-4uav-calibration-v1"
PASS_ONLY_PROTOCOL_ID = "aegisair-c3-reservation-mappo-pass-only-4uav-calibration-v2"
INTENT_ONLY_PROTOCOL_ID = "aegisair-c3-reservation-mappo-intent-only-4uav-calibration-v3"
PROTOCOL_IDS = {PROTOCOL_ID, PASS_ONLY_PROTOCOL_ID, INTENT_ONLY_PROTOCOL_ID}
RULE_CONDITION = "G0_RULE_C3_RESERVATION"


class ReservationPassOnlyPilot:
    """只在 C3 明确授权 PASS 时使用 MAPPO，其余状态确定性跟踪 C3 目标。"""

    def __init__(
        self,
        pilot: MappoPilot,
        coordinator,
        *,
        speed_limit: float,
        nominal_gain: float = 0.8,
    ) -> None:
        self.pilot = pilot
        self.coordinator = coordinator
        self.speed_limit = speed_limit
        self.nominal_gain = nominal_gain

    def actions(self, *, positions, velocities, goals):
        learned = self.pilot.actions(
            positions=positions, velocities=velocities, goals=goals
        )
        direct = {
            drone: np.clip(
                self.nominal_gain
                * (np.asarray(goals[drone][:2]) - np.asarray(positions[drone][:2])),
                -self.speed_limit,
                self.speed_limit,
            )
            for drone in positions
        }
        # Before the trigger, MAPPO remains the nominal intent used by C3 to
        # predict shared-zone entry.  Once C3 owns the lifecycle, only the
        # explicitly authorized PASS drone may retain learned nominal control.
        if self.coordinator.mode == "normal":
            return learned
        authorized = set(
            self.coordinator.last_decision.authorized_drone_ids
            if self.coordinator.last_decision is not None
            else []
        )
        if self.coordinator.mode == "pass":
            return {
                drone: learned[drone] if drone in authorized else direct[drone]
                for drone in positions
            }
        return direct


def _validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("protocol_id") not in PROTOCOL_IDS:
        raise ValueError(f"protocol_id 必须属于 {sorted(PROTOCOL_IDS)}")
    drone_ids = manifest.get("drone_ids", [])
    if len(drone_ids) != 4 or len(set(drone_ids)) != 4:
        raise ValueError("本协议必须且只能使用四架 UAV")
    order = manifest.get("condition_order", [])
    if not order or order[0] != RULE_CONDITION:
        raise ValueError(f"首个条件必须为 {RULE_CONDITION}")
    pilots = manifest.get("mappo_pilots", {})
    if set(order[1:]) != set(pilots):
        raise ValueError("condition_order 中的 MAPPO 条件必须与 mappo_pilots 一一对应")
    if len(pilots) < 1:
        raise ValueError("至少需要一个冻结 MAPPO checkpoint")
    application = manifest.get("pilot_application")
    expected_application = {
        PROTOCOL_ID: "full_lifecycle",
        PASS_ONLY_PROTOCOL_ID: "pass_only",
        INTENT_ONLY_PROTOCOL_ID: "intent_only",
    }[manifest["protocol_id"]]
    if application != expected_application:
        raise ValueError(f"pilot_application 必须为 {expected_application}")
    expected = manifest.get("pilot_interface", {})
    required = {
        "num_agents": 4,
        "obs_dim": 44,
        "action_dim": 2,
        "max_neighbors": 8,
        "speed_limit_mps": 1.5,
    }
    if any(expected.get(key) != value for key, value in required.items()):
        raise ValueError(f"pilot_interface 必须冻结为 {required}")
    for condition, spec in pilots.items():
        if spec.get("training_scenario") != "randomized_4":
            raise ValueError(f"{condition} 不是 randomized_4 checkpoint")
        digest = spec.get("sha256", "")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError(f"{condition} 的 sha256 无效")


def _pilot_for_condition(
    condition: str, manifest: dict[str, Any], reservation_coordinator=None
) -> tuple[MappoPilot | None, dict[str, Any]]:
    if condition == RULE_CONDITION:
        return None, {"kind": "go_to_goal", "untrusted": True}
    spec = manifest["mappo_pilots"].get(condition)
    if spec is None:
        raise ValueError(f"未知条件：{condition}")
    checkpoint = Path(spec["checkpoint"])
    if not checkpoint.is_file():
        raise FileNotFoundError(checkpoint)
    actual_hash = _sha256(checkpoint)
    if actual_hash != spec["sha256"]:
        raise ValueError(
            f"checkpoint 哈希不匹配：{checkpoint}，期望 {spec['sha256']}，实际 {actual_hash}"
        )
    interface = manifest["pilot_interface"]
    pilot: MappoPilot | ReservationPassOnlyPilot = MappoPilot(
        checkpoint,
        obs_dim=int(interface["obs_dim"]),
        num_agents=int(interface["num_agents"]),
        speed_limit=float(interface["speed_limit_mps"]),
        max_neighbors=int(interface["max_neighbors"]),
    )
    if manifest["pilot_application"] == "pass_only":
        if reservation_coordinator is None:
            raise ValueError("pass_only MAPPO 必须绑定 C3-Reservation coordinator")
        pilot = ReservationPassOnlyPilot(
            pilot,
            reservation_coordinator,
            speed_limit=float(interface["speed_limit_mps"]),
        )
    return pilot, {
        "kind": "frozen_mappo",
        "untrusted": True,
        "training_seed": int(spec["training_seed"]),
        "training_scenario": spec["training_scenario"],
        "checkpoint": str(checkpoint),
        "checkpoint_sha256": actual_hash,
        "application": manifest["pilot_application"],
    }


def _condition_go(row: dict[str, Any], max_steps: int) -> bool:
    latency = row["ra_solve_latency_summary_ms"]
    state = row["c3_reservation_summary"] or {}
    audit = row["audit"]
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


def _paired_delta(rule: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "condition": candidate["condition"],
        "mission_complete_equal": candidate["mission_complete"] == rule["mission_complete"],
        "delta_min_rho": candidate["min_rho"] - rule["min_rho"],
        "delta_path_length_m": candidate["path_length_m"] - rule["path_length_m"],
        "delta_mean_control_effort": (
            candidate["mean_control_effort"] - rule["mean_control_effort"]
        ),
        "delta_ra_p99_ms": (
            candidate["ra_solve_latency_summary_ms"]["p99"]
            - rule["ra_solve_latency_summary_ms"]["p99"]
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--condition",
        help="只运行一个冻结条件；用于每条件全新 SITL 的物理试验隔离。",
    )
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    try:
        _validate_manifest(manifest)
    except ValueError as exc:
        parser.error(str(exc))
    if args.output.exists():
        parser.error(f"拒绝覆盖已有输出目录：{args.output}")
    args.output.mkdir(parents=True)

    drone_ids = [int(value) for value in manifest["drone_ids"]]
    starts = {int(key): tuple(value) for key, value in manifest["reset_starts"].items()}
    goals = {int(key): tuple(value) for key, value in manifest["base_goals"].items()}
    conditions = list(manifest["condition_order"])
    if args.condition is not None:
        if args.condition not in conditions:
            parser.error(f"condition 不在冻结顺序中：{args.condition}")
        conditions = [args.condition]
    rows: list[dict[str, Any]] = []
    for order_index, condition in enumerate(conditions):
        _, reservation = _coordinators(
            "R3_C3_RESERVATION", manifest, drone_ids, starts, goals
        )
        pilot, pilot_metadata = _pilot_for_condition(
            condition, manifest, reservation_coordinator=reservation
        )
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
            pilot=(pilot if manifest["pilot_application"] != "intent_only" else None),
            coordination_intent_pilot=(
                pilot if manifest["pilot_application"] == "intent_only" else None
            ),
            reservation_coordinator=reservation,
            land_at_end=args.condition is not None or order_index == len(conditions) - 1,
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
            )
            < float(manifest["goal_epsilon"])
            for drone in drone_ids
        )
        row = {
            "condition": condition,
            "nominal_policy": pilot_metadata,
            "mission_complete": complete,
            "collision": run["collision"],
            "min_rho": run["min_rho"],
            "min_distance_m": run["min_distance_m"],
            "path_length_m": run["path_length_m"],
            "mean_control_effort": effort,
            "ra_solve_latency_summary_ms": run["ra_solve_latency_summary_ms"],
            "safety_bypass_count": run["safety_bypass_count"],
            "c3_reservation_summary": run["c3_reservation"],
            "audit": _audit(trajectory, "R3_C3_RESERVATION"),
            "trajectory": trajectory.name,
            "trajectory_sha256": _sha256(trajectory),
            "final_positions": run["final_positions"],
        }
        row["condition_go"] = _condition_go(row, int(manifest["max_steps"]))
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    all_go = all(row["condition_go"] for row in rows)
    rule = next((row for row in rows if row["condition"] == RULE_CONDITION), None)
    summary = {
        "protocol_id": manifest["protocol_id"],
        "phase": manifest["phase"],
        "decision": "GO" if all_go else "NO_GO",
        "manifest_sha256": _sha256(args.manifest),
        "gazebo_seed": manifest["gazebo_seed"],
        "all_conditions_go": all_go,
        "single_condition_run": args.condition is not None,
        "mappo_conditions_passed": sum(
            row["condition_go"] for row in rows if row["condition"] != RULE_CONDITION
        ),
        "mappo_conditions_total": sum(
            row["condition"] != RULE_CONDITION for row in rows
        ),
        "paired_deltas_vs_rule": (
            [
                _paired_delta(rule, row)
                for row in rows
                if row["condition"] != RULE_CONDITION
            ]
            if rule is not None
            else []
        ),
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
