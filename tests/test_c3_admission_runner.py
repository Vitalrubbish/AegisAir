from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from marllib.run_c3_admission_gazebo import _admission_config, _audit


ROOT = Path(__file__).resolve().parents[1]


class C3AdmissionRunnerTest(unittest.TestCase):
    def test_manifest_freezes_four_uav_and_calibration_only(self) -> None:
        manifest = json.loads(
            (ROOT / "configs/c3_admission_4uav_calibration_smoke_v1.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["drone_ids"], [2, 3, 4, 5])
        self.assertEqual(len(manifest["drone_ids"]), 4)
        self.assertEqual(
            manifest["condition_order"],
            ["R0_RA_ONLY", "R1_SEQUENTIAL_PASS", "R2_C3_ADMISSION"],
        )
        self.assertIn("not_sealed", manifest["phase"])
        config = _admission_config(manifest["c3_admission"])
        self.assertEqual(config.admission_horizon_s, 2.5)

    def test_v2_consumes_only_allowed_zone_horizon_adjustment(self) -> None:
        manifest = json.loads(
            (ROOT / "configs/c3_admission_4uav_calibration_smoke_v2.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["adjustment_count"], 1)
        self.assertEqual(manifest["c3_admission"]["conflict_zone_radius_m"], 2.0)
        self.assertEqual(manifest["c3_admission"]["admission_horizon_s"], 3.0)
        self.assertIn("adjustment_consumed", manifest["c3_admission"]["calibration_status"])

    def test_audit_detects_frozen_hold_and_preconflict_trigger(self) -> None:
        decision = {
            "coordination_mode": "admission_pending",
            "step": 0,
            "authorized_drone_ids": [],
            "frozen_hold_goals": {"2": [-4.0, 1.0, 2.5]},
            "ra_vetoed": False,
        }
        modes = ["admission_pending", "hold", "pass", "release"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trajectory.jsonl"
            rows = []
            for step, mode in enumerate(modes):
                current = dict(decision)
                current["step"] = step
                current["coordination_mode"] = mode
                current["authorized_drone_ids"] = [2] if mode == "pass" else []
                rows.append(
                    {
                        "step": step,
                        "min_rho": 0.5,
                        "drones": {
                            "2": {"feasible": True, "ra_bypass": False},
                            "3": {"feasible": True, "ra_bypass": False},
                        },
                        "coordination_admission": current,
                    }
                )
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            audit = _audit(path, "R2_C3_ADMISSION")
        self.assertTrue(audit["triggered_while_current_rho_positive"])
        self.assertTrue(audit["required_modes_seen"])
        self.assertTrue(audit["frozen_hold_goals_stable"])


if __name__ == "__main__":
    unittest.main()
