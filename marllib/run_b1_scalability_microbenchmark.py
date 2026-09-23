#!/usr/bin/env python3
"""运行冻结的 B1 单进程 Runtime Assurance 规模微基准。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import resource
import subprocess
import sys
import time
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from swarm.ra.margins import RuntimeAssuranceParams
from swarm.ra.runtime_assurance import RuntimeAssurance
from swarm.safety import DroneSnapshot


PROTOCOL_ID = "aegisair-b1-scalability-microbenchmark-v1"
METHODS = ("AEGIS_HOCBF_V4", "AEGIS_HOCBF_V3", "PB_CBF")
GEOMETRIES = ("symmetric_crossing", "merge", "random_conflict")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_revision() -> dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.run(
            args, cwd=ROOT, check=False, text=True, capture_output=True
        ).stdout.strip()

    return {
        "head": run("git", "rev-parse", "HEAD"),
        "dirty": bool(run("git", "status", "--porcelain")),
    }


def _environment() -> dict[str, Any]:
    try:
        import scipy

        scipy_version = scipy.__version__
    except ModuleNotFoundError:
        scipy_version = None
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy_version,
        "pid": os.getpid(),
        "single_process": True,
        "power_mode_note": "操作系统当前电源模式；脚本不主动修改系统设置",
    }


def _unit(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.maximum(norms, 1e-12)


def generate_flow(
    *,
    n_agents: int,
    geometry: str,
    flow_index: int,
    steps: int,
    seed: int,
    domain: dict[str, float],
) -> list[dict[str, Any]]:
    """预生成一条不依赖被测方法的状态流。"""
    if geometry not in GEOMETRIES:
        raise ValueError(f"unknown geometry: {geometry}")
    rng = np.random.default_rng(seed)
    angles = 2.0 * np.pi * np.arange(n_agents) / n_agents
    angles += rng.uniform(-0.08, 0.08, n_agents)
    if geometry == "symmetric_crossing":
        directions = np.stack([np.cos(angles), np.sin(angles)], axis=1)
        starts = float(domain["flow_start_radius_m"]) * directions
        ends = float(domain["flow_end_radius_m"]) * directions
        velocity_dirs = -directions
    elif geometry == "merge":
        lane = np.where(np.arange(n_agents) % 2 == 0, -1.0, 1.0)
        rank = np.arange(n_agents) // 2
        starts = np.stack(
            [-4.5 - 0.55 * rank, lane * (1.25 + 0.10 * rank)], axis=1
        )
        ends = np.stack(
            [-0.20 + 0.18 * rank, lane * (0.22 + 0.04 * rank)], axis=1
        )
        velocity_dirs = _unit(np.array([3.5, 0.0]) - starts)
    else:
        shuffled = rng.permutation(angles)
        radii = rng.uniform(3.5, 5.0, n_agents)
        starts = radii[:, None] * np.stack(
            [np.cos(shuffled), np.sin(shuffled)], axis=1
        )
        targets = rng.normal(0.0, 0.45, size=(n_agents, 2))
        ends = targets + 1.25 * _unit(starts - targets)
        velocity_dirs = _unit(targets - starts)

    position_jitter = rng.normal(
        0.0, float(domain["position_jitter_m"]), size=(n_agents, 2)
    )
    velocity_jitter = rng.normal(
        0.0, float(domain["velocity_jitter_mps"]), size=(n_agents, 2)
    )
    speed = rng.uniform(0.85, 1.35, n_agents)[:, None]
    flow = []
    for step in range(steps):
        fraction = step / max(1, steps - 1)
        # smoothstep 保留冲突前、冲突附近和恢复前输入，同时避免状态跳变支配计时。
        blend = fraction * fraction * (3.0 - 2.0 * fraction)
        positions = (1.0 - blend) * starts + blend * ends + position_jitter
        velocities = speed * velocity_dirs + velocity_jitter
        nominal = np.clip(1.5 * velocity_dirs, -1.5, 1.5)
        flow.append(
            {
                "flow_index": flow_index,
                "step": step,
                "positions": positions.tolist(),
                "velocities": velocities.tolist(),
                "nominal_actions": nominal.tolist(),
            }
        )
    return flow


def _make_ra(method: str, config: dict[str, Any]) -> RuntimeAssurance:
    c = config["controller"]
    common = dict(
        params=RuntimeAssuranceParams(
            tau_ctrl=float(c["tau_ctrl_s"]), degradation_dt=1.0 / config["rate_hz"]
        ),
        v_max=float(c["v_max_mps"]),
        perception_sigma=float(config["input_domain"]["perception_sigma_m"]),
        use_hocbf=method != "PB_CBF",
        hocbf_k1=float(c["k1"]),
        hocbf_k2=float(c["k2"]),
        a_max=float(c["a_max_mps2"]),
        kv=float(c["kv"]),
        tau_px4=float(c["execution_tau_s"]),
        command_feedforward_tau_s=float(c["execution_tau_s"]),
        qp_max_iters=int(c["qp_max_iters"]),
    )
    if method == "AEGIS_HOCBF_V4":
        return RuntimeAssurance(
            **common,
            constraint_boundary="full",
            hocbf_boundary_guard=float(c["boundary_guard"]),
            hocbf_boundary_buffer_m=float(c["boundary_buffer_m"]),
            hocbf_infeasible_fallback="max_brake",
            hocbf_pb_recovery=True,
            hocbf_predictive_recovery=True,
            hocbf_prediction_execution_fraction=float(
                c["prediction_execution_fraction"]
            ),
            hocbf_prediction_steps=int(c["prediction_steps"]),
            hocbf_recovery_reserve_threshold=float(
                c["recovery_reserve_threshold"]
            ),
            hocbf_recovery_alpha=float(c["recovery_alpha"]),
            hocbf_recovery_braking_accel=float(
                c["recovery_braking_accel_mps2"]
            ),
            hocbf_recovery_boundary_buffer_m=float(
                c["recovery_boundary_buffer_m"]
            ),
            hocbf_recovery_clear_steps=int(c["recovery_clear_steps"]),
        )
    if method == "AEGIS_HOCBF_V3":
        return RuntimeAssurance(
            **common,
            constraint_boundary="full",
            hocbf_boundary_guard=float(c["boundary_guard"]),
            hocbf_boundary_buffer_m=float(c["boundary_buffer_m"]),
            hocbf_infeasible_fallback="max_brake",
        )
    if method == "PB_CBF":
        common["use_hocbf"] = False
        return RuntimeAssurance(
            **common,
            sampled_data=True,
            sampled_data_method="pb_cbf",
            constraint_boundary="static",
            pb_alpha=float(c["recovery_alpha"]),
            pb_braking_accel=float(c["recovery_braking_accel_mps2"]),
            sampled_data_boundary_buffer_m=float(
                c["recovery_boundary_buffer_m"]
            ),
            sampled_data_infeasible_fallback="max_brake",
        )
    raise ValueError(f"unknown method: {method}")


def _state_to_inputs(
    state: dict[str, Any], *, altitude_m: float, timestamp_ms: int
) -> tuple[dict[int, DroneSnapshot], dict[int, np.ndarray]]:
    snapshots = {}
    nominal = {}
    for index, (position, velocity, action) in enumerate(
        zip(
            state["positions"],
            state["velocities"],
            state["nominal_actions"],
            strict=True,
        ),
        start=1,
    ):
        snapshots[index] = DroneSnapshot(
            drone_id=index,
            position=(float(position[0]), float(position[1]), altitude_m),
            velocity=(float(velocity[0]), float(velocity[1]), 0.0),
            timestamp_ms=timestamp_ms,
        )
        nominal[index] = np.asarray(action, dtype=np.float64)
    return snapshots, nominal


def _peak_rss_mib() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    # macOS reports bytes; Linux reports KiB.
    return value / (1024.0 * 1024.0) if sys.platform == "darwin" else value / 1024.0


def _percentile(values: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))


def summarize(
    rows: list[dict[str, Any]], *, config: dict[str, Any]
) -> dict[str, Any]:
    cells = []
    deadline = float(config["deadline_ms"])
    for n_agents in config["scales"]:
        for geometry in config["geometries"]:
            for method in config["method_order"]:
                selected = [
                    row
                    for row in rows
                    if row["n_agents"] == n_agents
                    and row["geometry"] == geometry
                    and row["method"] == method
                ]
                latency = [row["latency_ms"] for row in selected]
                misses = sum(value > deadline for value in latency)
                cells.append(
                    {
                        "n_agents": n_agents,
                        "geometry": geometry,
                        "method": method,
                        "constraints": n_agents * (n_agents - 1) // 2,
                        "samples": len(selected),
                        "latency_ms": {
                            "p50": _percentile(latency, 50),
                            "p95": _percentile(latency, 95),
                            "p99": _percentile(latency, 99),
                            "max": max(latency),
                        },
                        "deadline_misses": misses,
                        "deadline_miss_fraction": misses / len(selected),
                        "qp_infeasible": sum(not row["feasible"] for row in selected),
                        "intervention_fraction": sum(
                            row["intervened_agents"] > 0 for row in selected
                        )
                        / len(selected),
                        "mean_control_effort": float(
                            np.mean([row["control_effort"] for row in selected])
                        ),
                        "peak_process_rss_mib": max(
                            row["peak_process_rss_mib"] for row in selected
                        ),
                    }
                )
    criteria = config["go_criteria"]
    gated = [
        cell
        for cell in cells
        if cell["n_agents"] <= int(criteria["primary_max_scale"])
    ]
    failures = [
        cell
        for cell in gated
        if cell["latency_ms"]["p99"] >= float(criteria["p99_latency_ms_lt"])
        or cell["deadline_miss_fraction"]
        >= float(criteria["deadline_miss_fraction_lt"])
    ]
    supported_scales = []
    for scale in config["scales"]:
        scale_cells = [cell for cell in cells if cell["n_agents"] == scale]
        if scale_cells and all(
            cell["latency_ms"]["p99"] < float(criteria["p99_latency_ms_lt"])
            and cell["deadline_miss_fraction"]
            < float(criteria["deadline_miss_fraction_lt"])
            for cell in scale_cells
        ):
            supported_scales.append(scale)
    return {
        "protocol_id": PROTOCOL_ID,
        "decision": "GO" if not failures else "NO_GO",
        "maximum_supported_scale_in_tested_set": max(supported_scales, default=None),
        "failed_gate_cells": failures,
        "cells": cells,
    }


def run(config: dict[str, Any], output: Path, manifest_path: Path) -> dict[str, Any]:
    if config.get("protocol_id") != PROTOCOL_ID:
        raise ValueError(f"manifest protocol_id must be {PROTOCOL_ID}")
    if tuple(config.get("method_order", [])) != METHODS:
        raise ValueError(f"method_order must be {METHODS}")
    if tuple(config.get("geometries", [])) != GEOMETRIES:
        raise ValueError(f"geometries must be {GEOMETRIES}")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite output directory: {output}")
    output.mkdir(parents=True)
    (output / "STARTED").touch()
    (output / "manifest.json").write_bytes(manifest_path.read_bytes())
    (output / "manifest.sha256").write_text(
        f"{_sha256(manifest_path)}  manifest.json\n", encoding="utf-8"
    )
    metadata = {
        "protocol_id": PROTOCOL_ID,
        "manifest_sha256": _sha256(manifest_path),
        "environment": _environment(),
        "git": _git_revision(),
        "started_unix_s": time.time(),
    }
    (output / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    all_flows: dict[tuple[int, str], list[list[dict[str, Any]]]] = {}
    with (output / "inputs.jsonl").open("w", encoding="utf-8") as handle:
        for n_agents in config["scales"]:
            for geometry_index, geometry in enumerate(config["geometries"]):
                flows = []
                for flow_index in range(int(config["flows_per_cell"])):
                    seed = (
                        int(config["base_seed"])
                        + 100_000 * int(n_agents)
                        + 1_000 * geometry_index
                        + flow_index
                    )
                    flow = generate_flow(
                        n_agents=int(n_agents),
                        geometry=geometry,
                        flow_index=flow_index,
                        steps=int(config["steps_per_flow"]),
                        seed=seed,
                        domain=config["input_domain"],
                    )
                    flows.append(flow)
                    handle.write(
                        json.dumps(
                            {
                                "n_agents": n_agents,
                                "geometry": geometry,
                                "seed": seed,
                                "flow": flow,
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        + "\n"
                    )
                all_flows[(n_agents, geometry)] = flows

    # 预热不写入结果；每个规模使用同一份预生成输入。
    warmup_count = int(config["warmup_steps_per_method_and_scale"])
    for n_agents in config["scales"]:
        warmup_flow = all_flows[(n_agents, config["geometries"][0])][0]
        for method in config["method_order"]:
            ra = _make_ra(method, config)
            for index in range(warmup_count):
                state = warmup_flow[index % len(warmup_flow)]
                snapshots, nominal = _state_to_inputs(
                    state,
                    altitude_m=float(config["input_domain"]["altitude_m"]),
                    timestamp_ms=index * int(1000.0 / config["rate_hz"]),
                )
                ra.filter(snapshots, nominal, t=index / config["rate_hz"], aoi={})

    rows = []
    raw_path = output / "timing.jsonl"
    global_step = 0
    with raw_path.open("w", encoding="utf-8") as handle:
        for n_agents in config["scales"]:
            for geometry in config["geometries"]:
                for flow_index, flow in enumerate(all_flows[(n_agents, geometry)]):
                    # 平衡方法顺序；每条流的每种方法均从全新 RA 状态开始。
                    base_order = list(config["method_order"])
                    shift = flow_index % len(base_order)
                    method_order = base_order[shift:] + base_order[:shift]
                    for order_index, method in enumerate(method_order):
                        ra = _make_ra(method, config)
                        for state in flow:
                            snapshots, nominal = _state_to_inputs(
                                state,
                                altitude_m=float(
                                    config["input_domain"]["altitude_m"]
                                ),
                                timestamp_ms=global_step
                                * int(1000.0 / config["rate_hz"]),
                            )
                            started = time.perf_counter_ns()
                            result = ra.filter(
                                snapshots,
                                nominal,
                                t=state["step"] / config["rate_hz"],
                                aoi={},
                            )
                            elapsed_ms = (time.perf_counter_ns() - started) / 1e6
                            row = {
                                "n_agents": n_agents,
                                "geometry": geometry,
                                "flow_index": flow_index,
                                "step": state["step"],
                                "method": method,
                                "order_index": order_index,
                                "constraints": n_agents * (n_agents - 1) // 2,
                                "latency_ms": elapsed_ms,
                                "feasible": bool(ra.last_qp_feasible),
                                "selected_filter": next(iter(result.values())).selected_filter,
                                "intervened_agents": sum(
                                    item.intervened for item in result.values()
                                ),
                                "control_effort": float(
                                    np.mean(
                                        [
                                            np.linalg.norm(
                                                np.asarray(item.safe_action)
                                                - nominal[drone]
                                            )
                                            for drone, item in result.items()
                                        ]
                                    )
                                ),
                                "peak_process_rss_mib": _peak_rss_mib(),
                            }
                            rows.append(row)
                            handle.write(
                                json.dumps(
                                    row, ensure_ascii=False, separators=(",", ":")
                                )
                                + "\n"
                            )
                            global_step += 1

    summary = summarize(rows, config=config)
    summary.update(
        {
            "manifest_sha256": _sha256(manifest_path),
            "inputs_sha256": _sha256(output / "inputs.jsonl"),
            "timing_sha256": _sha256(raw_path),
            "environment": metadata["environment"],
            "git": metadata["git"],
            "raw_samples": len(rows),
        }
    )
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "integrity.sha256").write_text(
        "".join(
            f"{_sha256(output / name)}  {name}\n"
            for name in ("inputs.jsonl", "timing.jsonl", "summary.json", "metadata.json")
        ),
        encoding="utf-8",
    )
    (output / "COMPLETE").touch()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.manifest.read_text(encoding="utf-8"))
    summary = run(config, args.output, args.manifest)
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "maximum_supported_scale_in_tested_set": summary[
                    "maximum_supported_scale_in_tested_set"
                ],
                "raw_samples": summary["raw_samples"],
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
