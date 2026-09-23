from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from marllib.run_c3_reservation_gazebo import _audit, _coordinators


ROOT = Path(__file__).resolve().parents[1]


class C3ReservationRunnerTest(unittest.TestCase):
    def test_manifest_is_new_four_uav_protocol(self) -> None:
        manifest = json.loads(
            (ROOT / "configs/c3_reservation_4uav_calibration_smoke_v1.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["drone_ids"], [2, 3, 4, 5])
        self.assertEqual(
            manifest["condition_order"],
            ["R2_C3_ADMISSION", "R3_C3_RESERVATION"],
        )
        self.assertIn("new_falsifiable_protocol", manifest["phase"])
        self.assertIn("不调整RA", manifest["stopping_rule"])

    def test_conditions_create_mutually_exclusive_coordinators(self) -> None:
        manifest = json.loads(
            (ROOT / "configs/c3_reservation_4uav_calibration_smoke_v1.json").read_text(encoding="utf-8")
        )
        drones = manifest["drone_ids"]
        starts = {int(key): tuple(value) for key, value in manifest["reset_starts"].items()}
        goals = {int(key): tuple(value) for key, value in manifest["base_goals"].items()}
        admission, reservation = _coordinators(
            "R2_C3_ADMISSION", manifest, drones, starts, goals
        )
        self.assertIsNotNone(admission)
        self.assertIsNone(reservation)
        admission, reservation = _coordinators(
            "R3_C3_RESERVATION", manifest, drones, starts, goals
        )
        self.assertIsNone(admission)
        self.assertIsNotNone(reservation)

    def test_audit_requires_complete_lifecycle_and_stable_clearance(self) -> None:
        modes = [
            "admission_pending",
            "staging",
            "pass",
            "clear",
            "release",
            "final_return",
            "complete",
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trajectory.jsonl"
            rows = []
            for step, mode in enumerate(modes):
                active = 2 if mode in {"pass", "clear", "final_return"} else None
                rows.append(
                    {
                        "step": step,
                        "min_rho": 0.5,
                        "drones": {
                            str(drone): {"feasible": True, "ra_bypass": False}
                            for drone in [2, 3, 4, 5]
                        },
                        "coordination_reservation": {
                            "step": step,
                            "coordination_mode": mode,
                            "authorized_drone_ids": [active] if active else [],
                            "clearance_drone_id": 2 if mode == "clear" else None,
                            "clearance_goal": [3.0, -3.0, 2.5] if mode == "clear" else None,
                            "ra_vetoed": False,
                        },
                    }
                )
            # Add the remaining three stable clearance identities without changing modes.
            for drone in [3, 4, 5]:
                row = json.loads(json.dumps(rows[3]))
                row["step"] = len(rows)
                row["coordination_reservation"]["step"] = len(rows)
                row["coordination_reservation"]["clearance_drone_id"] = drone
                row["coordination_reservation"]["clearance_goal"] = [float(drone), 3.0, 2.5]
                rows.append(row)
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            audit = _audit(path, "R3_C3_RESERVATION")
        self.assertTrue(audit["required_modes_seen"])
        self.assertTrue(audit["clearance_goals_stable"])
        self.assertFalse(audit["revoke_hold_seen"])


if __name__ == "__main__":
    unittest.main()
