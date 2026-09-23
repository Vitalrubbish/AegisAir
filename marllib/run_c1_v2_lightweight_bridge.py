#!/usr/bin/env python3
"""Run the frozen lightweight mirror of the C1 PX4 v2 supervisor."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from marllib.config import ScenarioConfig
from marllib.envs.multi_uav import MultiUAVEnv
from marllib.phase5_runner import OBSERVATION_LOCAL_FRESH_SELF, run_sim_episode
from swarm.ra.c1_px4_supervisor import C1Px4SupervisorConfig
from swarm.ra.margins import RuntimeAssuranceParams
from swarm.ra.runtime_assurance import RuntimeAssurance

PROTOCOL_ID = "aegisair-c1-v2-lightweight-bridge-v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="C1 v2 lightweight bridge")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error(f"refusing to overwrite {args.out}")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("protocol_id") != PROTOCOL_ID:
        parser.error(f"manifest protocol_id must be {PROTOCOL_ID}")
    scenario = ScenarioConfig(
        name="c1_v2_lightweight_bridge",
        num_agents=2,
        starts=((-4.0, 0.0), (4.0, 0.0)),
        goals=((4.0, 0.0), (-4.0, 0.0)),
        dt=float(manifest["dt_s"]),
        speed_limit=1.5,
        start_noise=float(manifest["start_goal_noise_m"]),
        goal_noise=float(manifest["start_goal_noise_m"]),
    )
    spec = {
        "name": scenario.name,
        "scenario": scenario,
        "mission_change": None,
        "change_step": None,
        "failed_drone": None,
        "blocked_zone": None,
        "critical_goal": None,
        "high_drone": None,
    }
    supervisor = C1Px4SupervisorConfig(
        estimator_delay_s=float(manifest["estimator_delay_ms"]) / 1000.0,
        right_of_way_drone=0,
        barrier_tau_px4_s=float(manifest["barrier_tau_px4_s"]),
        command_feedforward_tau_s=float(manifest["command_feedforward_tau_s"]),
        admission_execution_tau_s=float(manifest["admission_execution_tau_s"]),
    )
    rows = []
    for seed in manifest["seeds"]:
        ra = RuntimeAssurance(
            params=RuntimeAssuranceParams(tau_ctrl=0.2),
            v_max=1.5,
            a_max=2.0,
            kv=2.0,
            sampled_data=True,
            gamma=0.1,
            tau_px4=float(manifest["barrier_tau_px4_s"]),
            execution_model="exact_zoh",
        )
        run = run_sim_episode(
            spec=spec,
            env=MultiUAVEnv(scenario),
            seed=int(seed),
            ra=ra,
            mode="CBF_ONLY",
            llm_client=None,
            llm_fallback=None,
            max_steps=int(manifest["max_steps"]),
            real_time=False,
            fault={"estimator_delay_ms": int(manifest["estimator_delay_ms"])},
            observation_mode=OBSERVATION_LOCAL_FRESH_SELF,
            execution_tau_s=float(manifest["execution_tau_s"]),
            c1_px4_supervisor_config=supervisor,
        )
        rows.append({
            "seed": seed,
            "min_rho": run["min_rho"],
            "min_distance_m": run["min_pairwise_distance_m"],
            "collision": run["collision"],
            "completed": run["completed"],
            "completion_steps": run["completion_steps"],
            "cbf_events": run["cbf_events"],
            "qp_infeasible_steps": run["qp_infeasible_steps"],
            "path_length_m": run["path_length_m"],
            "supervisor": run["c1_px4_supervisor"],
        })
    payload = {
        "protocol_id": PROTOCOL_ID,
        "manifest_sha256": _sha256(args.manifest),
        "decision": "GO" if all(
            not r["collision"] and r["completed"] and r["min_rho"] > 0
            for r in rows
        ) else "NO_GO",
        "trials": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
