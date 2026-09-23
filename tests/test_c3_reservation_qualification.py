from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from marllib.aggregate_c3_reservation_qualification import collect
from marllib.analyze_c3_reservation_4uav import statistics
from marllib.run_c3_reservation_qualification_gazebo import (
    PROTOCOL_ID,
    _r3_go,
    validate_manifest,
)


ROOT = Path(__file__).resolve().parents[1]


class C3ReservationQualificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.path = ROOT / "configs/c3_reservation_4uav_qualification_v1.json"
        self.manifest = json.loads(self.path.read_text(encoding="utf-8"))

    def test_manifest_freezes_five_new_balanced_seeds(self) -> None:
        validate_manifest(self.manifest)
        self.assertEqual(self.manifest["qualification_seeds"], [9601, 9602, 9603, 9604, 9605])
        first = [
            self.manifest["condition_order_by_seed"][str(seed)][0]
            for seed in self.manifest["qualification_seeds"]
        ]
        self.assertEqual(first.count("R2_C3_ADMISSION"), 3)
        self.assertEqual(first.count("R3_C3_RESERVATION"), 2)

    def test_qualification_parameters_equal_calibration(self) -> None:
        calibration = json.loads(
            (ROOT / "configs/c3_reservation_4uav_calibration_smoke_v1.json").read_text(encoding="utf-8")
        )
        keys = [
            "rate_hz",
            "max_steps",
            "goal_epsilon",
            "execution_tau_s",
            "drone_ids",
            "reset_starts",
            "base_goals",
            "shared_admission",
            "reservation",
            "method",
            "method_config",
        ]
        for key in keys:
            self.assertEqual(self.manifest[key], calibration[key], key)

    def test_r3_gate_is_joint_and_strict(self) -> None:
        row = {
            "mission_complete": True,
            "collision": False,
            "min_rho": 0.1,
            "safety_bypass_count": 0,
            "ra_solve_latency_summary_ms": {"p99": 9.0, "deadline_misses": 0},
            "audit": {
                "selected_qp_infeasible_steps": 0,
                "ra_bypass_count": 0,
                "required_modes_seen": True,
                "clearance_goals_stable": True,
                "revoke_hold_seen": False,
            },
            "c3_reservation_summary": {
                "complete": True,
                "service_latched": [2, 3, 4, 5],
                "cleared": [2, 3, 4, 5],
                "final_returned": [2, 3, 4, 5],
                "revoke_count": 0,
            },
        }
        self.assertTrue(_r3_go(row, 1200))
        row["audit"]["selected_qp_infeasible_steps"] = 1
        self.assertFalse(_r3_go(row, 1200))

    def _fake_row(self, seed: int, condition: str) -> dict:
        return {
            "seed": seed,
            "condition": condition,
            "valid_trial": True,
            "mission_complete": condition == "R3_C3_RESERVATION",
            "collision": False,
            "min_rho": 0.2 if condition == "R3_C3_RESERVATION" else -0.2,
            "path_length_m": 60.0,
            "mean_control_effort": 0.1,
            "completion_step": 1100 if condition == "R3_C3_RESERVATION" else None,
            "horizon_steps": 1200,
            "rate_hz": 20.0,
            "joint_success": condition == "R3_C3_RESERVATION",
            "r3_qualification_go": True if condition == "R3_C3_RESERVATION" else None,
            "audit": {
                "selected_qp_infeasible_steps": 0,
                "ra_bypass_count": 0,
            },
            "safety_bypass_count": 0,
            "trajectory": "trajectory.jsonl",
        }

    def test_aggregate_accepts_one_integrity_checked_attempt_per_condition(self) -> None:
        manifest_hash = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, seed in enumerate(self.manifest["qualification_seeds"], 1):
                for condition in self.manifest["condition_order_by_seed"][str(seed)]:
                    calibration = (
                        root
                        / f"q{index:02d}_seed{seed}"
                        / condition
                        / "attempt_01"
                        / "calibration"
                    )
                    calibration.mkdir(parents=True)
                    payload = {
                        "protocol_id": PROTOCOL_ID,
                        "manifest_sha256": manifest_hash,
                        "seed": seed,
                        "condition": condition,
                        "trial": self._fake_row(seed, condition),
                    }
                    summary = calibration / "summary.json"
                    summary.write_text(json.dumps(payload))
                    digest = hashlib.sha256(summary.read_bytes()).hexdigest()
                    (calibration / "integrity.sha256").write_text(f"{digest}  summary.json\n")
                    (calibration / "COMPLETE").touch()
            result = collect(self.path, root)
        self.assertEqual(result["decision"], "GO")
        self.assertEqual(result["r3_passed_trials"], 5)
        self.assertEqual(result["invalid_startups"], 0)

    def test_statistics_retains_incomplete_trials_as_60s_rmst(self) -> None:
        trials = []
        for seed in self.manifest["qualification_seeds"]:
            trials.extend(
                [
                    self._fake_row(seed, "R2_C3_ADMISSION"),
                    self._fake_row(seed, "R3_C3_RESERVATION"),
                ]
            )
        payload = {"phase": self.manifest["phase"], "trials": trials}
        result = statistics(payload)
        self.assertEqual(result["pairs"], 5)
        self.assertEqual(result["joint_success"]["r2"], 0)
        self.assertEqual(result["joint_success"]["r3"], 5)
        self.assertLess(result["paired_metrics_r3_minus_r2"]["rmst_60s"]["mean"], 0.0)
        self.assertEqual(result["inference_scope"], "qualification_descriptive_only")


if __name__ == "__main__":
    unittest.main()
