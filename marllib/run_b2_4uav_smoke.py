#!/usr/bin/env python3
"""运行单次 4-UAV B2 基础设施 smoke；不产生论文统计主张。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from marllib.phase5_runner import run_mqtt_loop
from marllib.run_c1_sota_cbf_gazebo import _method_kwargs, _trajectory_metrics


PROTOCOL_ID = "aegisair-b2-4uav-px4-infrastructure-smoke-v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    trajectory = args.output / "trajectory.jsonl"
    drone_ids = [int(value) for value in manifest["drone_ids"]]
    starts = {int(k): tuple(v) for k, v in manifest["reset_starts"].items()}
    goals = {int(k): tuple(v) for k, v in manifest["base_goals"].items()}
    method = manifest["method"]
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
        sequential_pass=bool(manifest["coordination"]["sequential_pass"]),
        urgent_drone=int(manifest["coordination"]["urgent_drone"]),
        land_at_end=True,
        **_method_kwargs(
            method,
            manifest["method_config"],
            float(manifest["execution_tau_s"]),
        ),
    )
    effort, infeasible = _trajectory_metrics(trajectory)
    complete = all(
        np.linalg.norm(
            np.asarray(run["final_positions"][drone][:2])
            - np.asarray(goals[drone][:2])
        )
        < float(manifest["goal_epsilon"])
        for drone in drone_ids
    )
    latency = run["ra_solve_latency_summary_ms"]
    passed = bool(
        complete
        and not run["collision"]
        and run["min_rho"] is not None
        and run["min_rho"] > 0.0
        and infeasible == 0
        and latency is not None
        and latency["p99"] < 50.0
        and latency["deadline_misses"] == 0
    )
    summary = {
        "protocol_id": PROTOCOL_ID,
        "decision": "GO" if passed else "NO_GO",
        "manifest_sha256": _sha256(args.manifest),
        "gazebo_seed": manifest["gazebo_seed"],
        "scenario_id": manifest["scenario_id"],
        "method": method,
        "mission_complete": complete,
        "collision": run["collision"],
        "min_rho": run["min_rho"],
        "min_distance_m": run["min_distance_m"],
        "steps": run["steps"],
        "cbf_events": run["cbf_events"],
        "selected_qp_infeasible_steps": infeasible,
        "hocbf_primary_infeasible_steps": run["hocbf_primary_infeasible_steps"],
        "hocbf_predictive_infeasible_steps": run[
            "hocbf_predictive_infeasible_steps"
        ],
        "hocbf_recovery_infeasible_steps": run[
            "hocbf_recovery_infeasible_steps"
        ],
        "mean_control_effort": effort,
        "path_length_m": run["path_length_m"],
        "ra_solve_latency_summary_ms": latency,
        "reset_elapsed_s": run["reset_elapsed_s"],
        "final_positions": run["final_positions"],
        "trajectory": trajectory.name,
        "trajectory_sha256": _sha256(trajectory),
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output / "manifest.json").write_bytes(args.manifest.read_bytes())
    (args.output / "integrity.sha256").write_text(
        f"{_sha256(args.output / 'manifest.json')}  manifest.json\n"
        f"{_sha256(trajectory)}  trajectory.jsonl\n"
        f"{_sha256(args.output / 'summary.json')}  summary.json\n",
        encoding="utf-8",
    )
    (args.output / "COMPLETE").touch()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
