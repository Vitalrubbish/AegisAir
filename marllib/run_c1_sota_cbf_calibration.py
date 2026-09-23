#!/usr/bin/env python3
"""运行 C1 近期 CBF 基线的独立参数校准。"""

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


def _controller(method: str, parameters: dict, common: dict) -> RuntimeAssurance:
    kwargs = dict(
        params=RuntimeAssuranceParams(degradation_dt=0.05),
        perception_sigma=0.0,
        v_max=float(common["v_max_mps"]),
        a_max=float(common["a_max_mps2"]),
        kv=float(common["kv"]),
        sampled_data=True,
        tau_px4=float(common["barrier_model_tau_s"]),
        tau_px4_min=float(common["barrier_model_tau_s"]),
        tau_px4_max=float(common["barrier_model_tau_s"]),
        command_feedforward_tau_s=float(common["command_feedforward_tau_s"]),
        constraint_boundary="static",
        qp_max_iters=int(common["qp_max_iters"]),
        sampled_data_boundary_buffer_m=float(common.get("sampled_data_boundary_buffer_m", 0.0)),
        sampled_data_infeasible_fallback=str(common.get("sampled_data_infeasible_fallback", "velocity_cancel")),
    )
    if method == "ZOCBF":
        kwargs.update(
            sampled_data_method="zocbf",
            gamma=float(parameters["gamma"]),
            zocbf_delta=float(parameters["delta_m"]),
        )
    elif method == "PB_CBF":
        kwargs.update(
            sampled_data_method="pb_cbf",
            pb_alpha=float(parameters["alpha"]),
            pb_braking_accel=float(parameters["braking_accel_mps2"]),
        )
    elif method == "AEGIS_HOCBF":
        kwargs.update(
            sampled_data=False,
            use_hocbf=True,
            hocbf_k1=float(parameters["k1"]),
            hocbf_k2=float(parameters["k2"]),
            constraint_boundary="full",
        )
    elif method == "AEGIS_HOCBF_V2":
        kwargs.update(
            sampled_data=False,
            use_hocbf=True,
            hocbf_k1=float(parameters["k1"]),
            hocbf_k2=float(parameters["k2"]),
            hocbf_boundary_guard=float(parameters["boundary_guard"]),
            hocbf_boundary_buffer_m=float(parameters["boundary_buffer_m"]),
            constraint_boundary="full",
        )
    elif method == "AEGIS_HOCBF_V3":
        kwargs.update(
            sampled_data=False,
            use_hocbf=True,
            hocbf_k1=float(parameters["k1"]),
            hocbf_k2=float(parameters["k2"]),
            hocbf_boundary_guard=float(parameters["boundary_guard"]),
            hocbf_boundary_buffer_m=float(parameters["boundary_buffer_m"]),
            hocbf_infeasible_fallback="max_brake",
            constraint_boundary="full",
        )
    else:
        raise ValueError(f"不支持的校准方法：{method}")
    return RuntimeAssurance(**kwargs)


def _candidates(manifest: dict) -> list[tuple[str, dict]]:
    output = []
    for gamma in manifest.get("zocbf_grid", {}).get("gamma", []):
        for delta in manifest.get("zocbf_grid", {}).get("delta_m", []):
            output.append(("ZOCBF", {"gamma": gamma, "delta_m": delta}))
    for alpha in manifest.get("pb_cbf_grid", {}).get("alpha", []):
        for braking in manifest.get("pb_cbf_grid", {}).get("braking_accel_mps2", []):
            output.append(
                (
                    "PB_CBF",
                    {"alpha": alpha, "braking_accel_mps2": braking},
                )
            )
    for k1 in manifest.get("hocbf_grid", {}).get("k1", []):
        for k2 in manifest.get("hocbf_grid", {}).get("k2", []):
            output.append(("AEGIS_HOCBF", {"k1": k1, "k2": k2}))
    v2_grid = manifest.get("hocbf_v2_grid", {})
    for guard in v2_grid.get("boundary_guard", []):
        for buffer_m in v2_grid.get("boundary_buffer_m", []):
            output.append(
                (
                    "AEGIS_HOCBF_V2",
                    {
                        "k1": v2_grid["k1"],
                        "k2": v2_grid["k2"],
                        "boundary_guard": guard,
                        "boundary_buffer_m": buffer_m,
                    },
                )
            )
    v3_grid = manifest.get("hocbf_v3_grid", {})
    for k1 in v3_grid.get("k1", []):
        for k2 in v3_grid.get("k2", []):
            output.append(
                (
                    "AEGIS_HOCBF_V3",
                    {
                        "k1": k1,
                        "k2": k2,
                        "boundary_guard": v3_grid["boundary_guard"],
                        "boundary_buffer_m": v3_grid["boundary_buffer_m"],
                    },
                )
            )
    return output


def _score(rows: list[dict]) -> tuple:
    return (
        sum(row["collision"] for row in rows),
        sum(row["min_rho"] < 0.0 for row in rows),
        sum(row["qp_infeasible_steps"] for row in rows),
        -sum(row["completed"] for row in rows),
        float(np.mean([row["control_effort"] for row in rows])),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("configs/c1_sota_cbf_calibration_v1.json"),
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error(f"拒绝覆盖已有结果：{args.out}")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    rows = []
    for method, parameters in _candidates(manifest):
        candidate_id = method + ":" + ",".join(
            f"{key}={parameters[key]}" for key in sorted(parameters)
        )
        for scenario_name in manifest["scenarios"]:
            base_spec = _scenario(scenario_name)
            scenario = replace(
                base_spec["scenario"],
                dt=float(manifest["dt_s"]),
                start_noise=float(manifest["start_goal_noise_m"]),
                goal_noise=float(manifest["start_goal_noise_m"]),
            )
            spec = {**base_spec, "scenario": scenario}
            for seed in manifest["seeds"]:
                run = run_sim_episode(
                    spec=spec,
                    env=MultiUAVEnv(scenario, max_steps=int(manifest["max_steps"])),
                    seed=int(seed),
                    ra=_controller(method, parameters, manifest["common"]),
                    mode="CBF_ONLY",
                    llm_client=None,
                    llm_fallback=None,
                    max_steps=int(manifest["max_steps"]),
                    real_time=False,
                    nominal_noise=float(manifest["nominal_velocity_noise_mps"]),
                    observation_mode=manifest["common"]["observation_mode"],
                    execution_tau_s=float(manifest["execution_tau_s"]),
                    execution_audit_samples=5,
                )
                rows.append(
                    {
                        "candidate_id": candidate_id,
                        "method": method,
                        "parameters": parameters,
                        "scenario": scenario_name,
                        "seed": seed,
                        **run,
                    }
                )
        print(f"完成 {candidate_id}", flush=True)

    selected = {}
    summaries = []
    methods = sorted({row["method"] for row in rows})
    for method in methods:
        candidate_ids = sorted({row["candidate_id"] for row in rows if row["method"] == method})
        for candidate_id in candidate_ids:
            group = [row for row in rows if row["candidate_id"] == candidate_id]
            summaries.append(
                {
                    "candidate_id": candidate_id,
                    "method": method,
                    "parameters": group[0]["parameters"],
                    "score": list(_score(group)),
                    "episodes": len(group),
                    "cbf_events": sum(row["cbf_events"] for row in group),
                }
            )
        winner = min(
            (item for item in summaries if item["method"] == method),
            key=lambda item: tuple(item["score"]),
        )
        selected[method] = winner

    payload = {
        "protocol_id": manifest["protocol_id"],
        "manifest_sha256": _sha256(args.manifest),
        "selection_rule": manifest["selection_rule"],
        "selected": selected,
        "summaries": summaries,
        "episodes": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(selected, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
