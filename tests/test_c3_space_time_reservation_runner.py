from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from marllib.run_c3_space_time_reservation_gazebo import (
    PROTOCOL_ID,
    _audit,
    _coordinator,
)


ROOT = Path(__file__).resolve().parents[1]


class C3SpaceTimeReservationRunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.path = ROOT / "configs/c3_str_4uav_calibration_smoke_v1.json"
        self.manifest = json.loads(self.path.read_text(encoding="utf-8"))

    def test_manifest_freezes_independent_sixty_second_smoke(self) -> None:
        self.assertEqual(self.manifest["protocol_id"], PROTOCOL_ID)
        self.assertEqual(self.manifest["drone_ids"], [2, 3, 4, 5])
        self.assertEqual(self.manifest["max_steps"], 1200)
        self.assertEqual(self.manifest["rate_hz"], 20.0)
        schedule = self.manifest["space_time_reservation"]
        derived = (
            schedule["staging_window_s"]
            + 4 * schedule["service_window_s"]
            + 2 * schedule["final_return_window_s"]
        )
        self.assertEqual(derived, 52.0)
        self.assertIn("C3-Reservation qualification No-Go", self.manifest["claim_boundary"])

    def test_coordinator_builds_two_grouped_return_slots(self) -> None:
        ids = [int(value) for value in self.manifest["drone_ids"]]
        starts = {
            int(key): tuple(value) for key, value in self.manifest["reset_starts"].items()
        }
        goals = {
            int(key): tuple(value) for key, value in self.manifest["base_goals"].items()
        }
        coordinator = _coordinator(self.manifest, ids, starts, goals)
        self.assertEqual(coordinator.config.return_compatibility_clearance_m, 1.9)
        self.assertEqual(coordinator.config.veto_delay_steps, 10)

    def test_audit_detects_early_authorization(self) -> None:
        decision = {
            "coordination_mode": "pass",
            "schedule_revision": 0,
            "reservation_windows": [
                {
                    "slot_id": "service-00-uav2",
                    "drone_ids": [2],
                    "planned_open_step": 10,
                    "planned_close_step": 20,
                }
            ],
            "authorized_drone_ids": [2],
            "active_slot_id": "service-00-uav2",
            "step": 9,
        }
        row = {
            "drones": {str(drone): {"feasible": True, "ra_bypass": False} for drone in [2, 3, 4, 5]},
            "coordination_space_time_reservation": decision,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trajectory.jsonl"
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            audit = _audit(path, [2, 3, 4, 5])
        self.assertEqual(len(audit["early_authorizations"]), 1)
        self.assertFalse(audit["all_drones_ever_authorized"])


if __name__ == "__main__":
    unittest.main()
