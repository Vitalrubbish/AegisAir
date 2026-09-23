#!/usr/bin/env python3
"""Run the frozen C1 PX4 v2 admission-control validation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from marllib.phase5_runner import OBSERVATION_LOCAL_FRESH_SELF, run_mqtt_loop
from swarm.estimation import SharedStateEstimatorConfig
from swarm.ra.c1_px4_supervisor import C1Px4SupervisorConfig
from swarm.ra.margins import RuntimeAssuranceParams

PROTOCOL_ID = "aegisair-c1-px4-telemetry-delay-v2"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="C1 PX4 v2 validation runner")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--trial-id", action="append")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1883)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("protocol_id") != PROTOCOL_ID:
        parser.error(f"manifest protocol_id must be {PROTOCOL_ID}")
    if manifest.get("observation_mode") != OBSERVATION_LOCAL_FRESH_SELF:
        parser.error("C1 PX4 v2 requires local_fresh_self_stale_peers")
    if args.out_dir.exists():
        parser.error(f"refusing to overwrite existing output directory: {args.out_dir}")
    args.out_dir.mkdir(parents=True)

    wanted = set(args.trial_id or [])
    trials = [t for t in manifest["trials"] if not wanted or t["trial_id"] in wanted]
    if wanted.difference(t["trial_id"] for t in trials):
        parser.error("unknown trial id")
    estimator = SharedStateEstimatorConfig(**manifest["estimator"])
    tau = manifest["tau"]
    supervisor = C1Px4SupervisorConfig(
        estimator_delay_s=estimator.delay_ms / 1000.0,
        barrier_tau_px4_s=float(tau["barrier_tau_px4_s"]),
        command_feedforward_tau_s=float(tau["command_feedforward_tau_s"]),
        admission_execution_tau_s=float(tau["admission_execution_tau_s"]),
        **manifest["supervisor"],
    )
    drone_ids = [int(i) for i in manifest["drone_ids"]]
    base_goals = {int(i): tuple(v) for i, v in manifest["base_goals"].items()}
    reset_starts = {int(i): tuple(v) for i, v in manifest["reset_starts"].items()}
    rows = []
    for index, trial in enumerate(trials):
        trajectory = args.out_dir / f"{trial['trial_id']}.jsonl"
        run = run_mqtt_loop(
            drone_ids=drone_ids,
            base_goals=base_goals,
            mode="CBF_ONLY",
            llm_client=None,
            llm_fallback=None,
            host=args.host,
            port=args.port,
            max_steps=int(manifest["max_steps"]),
            trajectory=trajectory,
            reset_starts=reset_starts,
            rate_hz=float(manifest["rate_hz"]),
            tau_ctrl=0.2,
            tau_px4=float(tau["barrier_tau_px4_s"]),
            execution_model="exact_zoh",
            sampled_data=True,
            gamma=0.1,
            estimator_config=estimator,
            estimator_seed=int(trial["seed"]),
            velocity_command_mode="feedforward_tau",
            tau_command_s=float(tau["command_feedforward_tau_s"]),
            observation_mode=OBSERVATION_LOCAL_FRESH_SELF,
            ra_params=RuntimeAssuranceParams(tau_ctrl=0.2),
            c1_px4_supervisor_config=supervisor,
            goal_epsilon=float(manifest["goal_epsilon"]),
            land_at_end=index == len(trials) - 1,
        )
        supervision = run["c1_px4_supervisor"]
        row = {
            "trial_id": trial["trial_id"],
            "seed": trial["seed"],
            "min_rho": run["min_rho"],
            "min_distance_m": run["min_distance_m"],
            "collision": run["collision"],
            "mission_complete": supervision["complete"],
            "final_phase": supervision["phase"],
            "latch_trip_count": supervision["latch_trip_count"],
            "latch_release_count": supervision["latch_release_count"],
            "cbf_events": run["cbf_events"],
            "path_length_m": run["path_length_m"],
            "tau": tau,
            "trajectory": trajectory.name,
            "trajectory_sha256": _sha256(trajectory),
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    (args.out_dir / "summary.json").write_text(
        json.dumps(
            {
                "protocol_id": PROTOCOL_ID,
                "manifest": str(args.manifest),
                "manifest_sha256": _sha256(args.manifest),
                "trials": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
