from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from marllib.run_c3_reservation_mappo_gazebo import (
    RULE_CONDITION,
    ReservationPassOnlyPilot,
    _condition_go,
    _pilot_for_condition,
    _validate_manifest,
)
from marllib.aggregate_c3_reservation_mappo import aggregate


ROOT = Path(__file__).resolve().parents[1]


class C3ReservationMappoRunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = json.loads(
            (ROOT / "configs/c3_reservation_mappo_4uav_calibration_v1.json").read_text(encoding="utf-8")
        )

    def test_manifest_freezes_four_uav_and_all_five_training_seeds(self) -> None:
        _validate_manifest(self.manifest)
        self.assertEqual(self.manifest["drone_ids"], [2, 3, 4, 5])
        self.assertEqual(self.manifest["condition_order"][0], RULE_CONDITION)
        self.assertEqual(len(self.manifest["mappo_pilots"]), 5)
        self.assertEqual(
            {spec["training_seed"] for spec in self.manifest["mappo_pilots"].values()},
            {1, 2, 3, 4, 5},
        )

    def test_all_three_role_manifests_are_independently_frozen(self) -> None:
        expected = {
            "c3_reservation_mappo_4uav_calibration_v1.json": "full_lifecycle",
            "c3_reservation_mappo_pass_only_4uav_calibration_v2.json": "pass_only",
            "c3_reservation_mappo_intent_only_4uav_calibration_v3.json": "intent_only",
        }
        protocol_ids = set()
        for name, application in expected.items():
            manifest = json.loads((ROOT / "configs" / name).read_text(encoding="utf-8"))
            _validate_manifest(manifest)
            self.assertEqual(manifest["pilot_application"], application)
            protocol_ids.add(manifest["protocol_id"])
        self.assertEqual(len(protocol_ids), 3)

    def test_rule_condition_does_not_construct_checkpoint_pilot(self) -> None:
        pilot, metadata = _pilot_for_condition(RULE_CONDITION, self.manifest)
        self.assertIsNone(pilot)
        self.assertEqual(metadata["kind"], "go_to_goal")
        self.assertTrue(metadata["untrusted"])

    def test_checkpoint_hash_is_verified_before_pilot_construction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "final.pt"
            checkpoint.write_bytes(b"frozen checkpoint")
            condition = "G1_MAPPO_TEST_C3_RESERVATION"
            manifest = json.loads(json.dumps(self.manifest))
            manifest["mappo_pilots"] = {
                condition: {
                    "training_seed": 9,
                    "training_scenario": "randomized_4",
                    "checkpoint": str(checkpoint),
                    "sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                }
            }
            manifest["condition_order"] = [RULE_CONDITION, condition]
            sentinel = object()
            with patch(
                "marllib.run_c3_reservation_mappo_gazebo.MappoPilot",
                return_value=sentinel,
            ) as constructor:
                pilot, metadata = _pilot_for_condition(condition, manifest)
            self.assertIs(pilot, sentinel)
            self.assertEqual(metadata["checkpoint_sha256"], manifest["mappo_pilots"][condition]["sha256"])
            constructor.assert_called_once()

            manifest["mappo_pilots"][condition]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "哈希不匹配"):
                _pilot_for_condition(condition, manifest)

    def test_pass_only_routes_mappo_only_to_authorized_pass_drone(self) -> None:
        class Learned:
            def actions(self, **kwargs):
                return {drone: [9.0, 9.0] for drone in kwargs["positions"]}

        class Decision:
            authorized_drone_ids = [2]

        class Coordinator:
            mode = "pass"
            last_decision = Decision()

        pilot = ReservationPassOnlyPilot(Learned(), Coordinator(), speed_limit=1.5)
        actions = pilot.actions(
            positions={2: [0.0, 0.0], 3: [0.0, 0.0]},
            velocities={2: [0.0, 0.0], 3: [0.0, 0.0]},
            goals={2: [1.0, 0.0], 3: [0.0, 1.0]},
        )
        self.assertEqual(actions[2], [9.0, 9.0])
        self.assertEqual(actions[3].tolist(), [0.0, 0.8])

        Coordinator.mode = "staging"
        actions = pilot.actions(
            positions={2: [0.0, 0.0], 3: [0.0, 0.0]},
            velocities={2: [0.0, 0.0], 3: [0.0, 0.0]},
            goals={2: [1.0, 0.0], 3: [0.0, 1.0]},
        )
        self.assertEqual(actions[2].tolist(), [0.8, 0.0])

    def test_condition_gate_requires_complete_safe_lifecycle(self) -> None:
        row = {
            "mission_complete": True,
            "collision": False,
            "min_rho": 0.1,
            "safety_bypass_count": 0,
            "ra_solve_latency_summary_ms": {"p99": 10.0, "deadline_misses": 0},
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
        self.assertTrue(_condition_go(row, 1200))
        row["min_rho"] = -0.01
        self.assertFalse(_condition_go(row, 1200))

    def test_aggregate_requires_all_fresh_single_condition_results(self) -> None:
        manifest_path = ROOT / "configs/c3_reservation_mappo_4uav_calibration_v1.json"
        manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            conditions_root = Path(directory)
            for index, condition in enumerate(self.manifest["condition_order"]):
                output = conditions_root / f"{index:02d}_{condition}" / "calibration"
                output.mkdir(parents=True)
                (output / "COMPLETE").touch()
                row = {
                    "condition": condition,
                    "condition_go": True,
                    "mission_complete": True,
                    "min_rho": 0.2,
                    "path_length_m": 10.0,
                    "mean_control_effort": 0.1,
                    "ra_solve_latency_summary_ms": {"p99": 5.0},
                }
                (output / "summary.json").write_text(
                    json.dumps(
                        {
                            "protocol_id": self.manifest["protocol_id"],
                            "manifest_sha256": manifest_hash,
                            "single_condition_run": True,
                            "conditions": [row],
                        }
                    )
                )
            summary = aggregate(manifest_path, conditions_root)
        self.assertTrue(summary["fresh_sitl_per_condition"])
        self.assertEqual(summary["decision"], "GO")
        self.assertEqual(summary["mappo_conditions_total"], 5)


if __name__ == "__main__":
    unittest.main()
