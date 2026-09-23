#!/usr/bin/env python3
"""运行冻结的 C1 HOCBF 强基线 sealed validation。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from marllib.envs.multi_uav import MultiUAVEnv
from marllib.phase5_runner import _scenario, run_sim_episode
from swarm.ra.margins import RuntimeAssuranceParams
from swarm.ra.runtime_assurance import RuntimeAssurance


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _controller(method: str, manifest: dict, speed_limit: float) -> RuntimeAssurance:
    common = manifest["common"]
    config = manifest["methods"][method]
    kwargs = dict(
        params=RuntimeAssuranceParams(degradation_dt=float(manifest["dt_s"])),
        perception_sigma=0.0,
        v_max=speed_limit,
        a_max=float(common["a_max_mps2"]),
        kv=float(common["kv"]),
        qp_max_iters=int(common["qp_max_iters"]),
        constraint_boundary=config["constraint_boundary"],
        sampled_data_boundary_buffer_m=float(config.get("boundary_buffer_m", 0.0)),
        sampled_data_infeasible_fallback=str(config.get("infeasible_fallback", "velocity_cancel")),
    )
    if method == "VELOCITY_CBF":
        kwargs["params"] = RuntimeAssuranceParams(
            degradation_dt=float(manifest["dt_s"]), alpha=float(config["alpha"])
        )
    elif method == "ZOCBF":
        kwargs.update(
            sampled_data=True,
            sampled_data_method="zocbf",
            tau_px4=float(config["barrier_model_tau_s"]),
            tau_px4_min=float(config["barrier_model_tau_s"]),
            tau_px4_max=float(config["barrier_model_tau_s"]),
            gamma=float(config["gamma"]),
            zocbf_delta=float(config["delta_m"]),
            command_feedforward_tau_s=float(common["command_feedforward_tau_s"]),
        )
    elif method == "PB_CBF":
        kwargs.update(
            sampled_data=True,
            sampled_data_method="pb_cbf",
            tau_px4=float(manifest["execution_tau_s"]),
            tau_px4_min=float(manifest["execution_tau_s"]),
            tau_px4_max=float(manifest["execution_tau_s"]),
            pb_alpha=float(config["alpha"]),
            pb_braking_accel=float(config["braking_accel_mps2"]),
            command_feedforward_tau_s=float(common["command_feedforward_tau_s"]),
        )
    elif method == "AEGIS_HOCBF":
        kwargs.update(
            use_hocbf=True,
            hocbf_k1=float(config["k1"]),
            hocbf_k2=float(config["k2"]),
            command_feedforward_tau_s=float(common["command_feedforward_tau_s"]),
        )
    elif method == "AEGIS_HOCBF_V2":
        kwargs.update(
            use_hocbf=True,
            hocbf_k1=float(config["k1"]),
            hocbf_k2=float(config["k2"]),
            hocbf_boundary_guard=float(config["boundary_guard"]),
            hocbf_boundary_buffer_m=float(config["boundary_buffer_m"]),
            tau_px4=float(config["barrier_model_tau_s"]),
            command_feedforward_tau_s=float(common["command_feedforward_tau_s"]),
        )
    elif method == "AEGIS_HOCBF_V3":
        kwargs.update(
            use_hocbf=True,
            hocbf_k1=float(config["k1"]),
            hocbf_k2=float(config["k2"]),
            hocbf_boundary_guard=float(config["boundary_guard"]),
            hocbf_boundary_buffer_m=float(config["boundary_buffer_m"]),
            hocbf_infeasible_fallback="max_brake",
            tau_px4=float(config["barrier_model_tau_s"]),
            command_feedforward_tau_s=float(common["command_feedforward_tau_s"]),
        )
    elif method.startswith("AEGIS_HOCBF_V4"):
        kwargs.update(
            use_hocbf=True,
            hocbf_k1=float(config["k1"]),
            hocbf_k2=float(config["k2"]),
            hocbf_boundary_guard=float(config["boundary_guard"]),
            hocbf_boundary_buffer_m=float(config["boundary_buffer_m"]),
            hocbf_infeasible_fallback="max_brake",
            hocbf_pb_recovery=True,
            hocbf_predictive_recovery=bool(
                config.get("predictive_recovery", True)
            ),
            hocbf_prediction_execution_fraction=float(
                config.get("prediction_execution_fraction", 1.0)
            ),
            hocbf_prediction_steps=int(config.get("prediction_steps", 1)),
            hocbf_recovery_reserve_threshold=(
                float(config["recovery_reserve_threshold"])
                if config.get("recovery_reserve_threshold") is not None
                else None
            ),
            hocbf_recovery_alpha=float(config["recovery_alpha"]),
            hocbf_recovery_braking_accel=float(
                config["recovery_braking_accel_mps2"]
            ),
            hocbf_recovery_boundary_buffer_m=float(
                config["recovery_boundary_buffer_m"]
            ),
            hocbf_recovery_clear_steps=int(config["recovery_clear_steps"]),
            tau_px4=float(config["barrier_model_tau_s"]),
            command_feedforward_tau_s=float(common["command_feedforward_tau_s"]),
        )
    else:
        raise ValueError(f"未知方法：{method}")
    return RuntimeAssurance(**kwargs)


def _summary(rows: list[dict]) -> list[dict]:
    output = []
    for method in sorted({row["method"] for row in rows}):
        group = [row for row in rows if row["method"] == method]
        output.append(
            {
                "method": method,
                "episodes": len(group),
                "collisions": sum(row["collision"] for row in group),
                "boundary_violations": sum(row["min_rho"] < 0.0 for row in group),
                "completed": sum(row["completed"] for row in group),
                "minimum_rho": min(row["min_rho"] for row in group),
                "mean_min_rho": float(np.mean([row["min_rho"] for row in group])),
                "cbf_events": sum(row["cbf_events"] for row in group),
                "qp_infeasible_steps": sum(row["qp_infeasible_steps"] for row in group),
                "hocbf_primary_infeasible_steps": sum(
                    row.get("hocbf_primary_infeasible_steps", 0) for row in group
                ),
                "hocbf_predictive_infeasible_steps": sum(
                    row.get("hocbf_predictive_infeasible_steps", 0) for row in group
                ),
                "hocbf_recovery_infeasible_steps": sum(
                    row.get("hocbf_recovery_infeasible_steps", 0) for row in group
                ),
                "hocbf_recovery_steps": sum(
                    row.get("hocbf_recovery_steps", 0) for row in group
                ),
                "hocbf_recovery_entries": sum(
                    row.get("hocbf_recovery_entries", 0) for row in group
                ),
                "mean_control_effort": float(np.mean([row["control_effort"] for row in group])),
            }
        )
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest", type=Path, default=Path("configs/c1_sota_cbf_validation_v1.json")
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error(f"拒绝覆盖已有结果：{args.out}")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    rows = []
    for trial in manifest["trials"]:
        for method in trial["condition_order"]:
            for scenario_name in manifest["scenarios"]:
                base = _scenario(scenario_name)
                scenario = replace(
                    base["scenario"],
                    dt=float(manifest["dt_s"]),
                    start_noise=float(manifest["start_goal_noise_m"]),
                    goal_noise=float(manifest["start_goal_noise_m"]),
                )
                run = run_sim_episode(
                    spec={**base, "scenario": scenario},
                    env=MultiUAVEnv(scenario, max_steps=int(manifest["max_steps"])),
                    seed=int(trial["seed"]),
                    ra=_controller(method, manifest, scenario.speed_limit),
                    mode="CBF_ONLY",
                    llm_client=None,
                    llm_fallback=None,
                    max_steps=int(manifest["max_steps"]),
                    real_time=False,
                    nominal_noise=float(manifest["nominal_velocity_noise_mps"]),
                    observation_mode=common_mode(manifest),
                    execution_tau_s=float(manifest["execution_tau_s"]),
                    execution_audit_samples=5,
                )
                rows.append(
                    {
                        "trial_id": trial["trial_id"],
                        "seed": trial["seed"],
                        "method": method,
                        "scenario": scenario_name,
                        **run,
                    }
                )
        print(f"完成 {trial['trial_id']}", flush=True)
    payload = {
        "protocol_id": manifest["protocol_id"],
        "manifest_sha256": _sha256(args.manifest),
        "summary": _summary(rows),
        "episodes": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0


def common_mode(manifest: dict) -> str:
    return str(manifest["common"]["observation_mode"])


if __name__ == "__main__":
    raise SystemExit(main())
