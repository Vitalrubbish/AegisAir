import json
import tempfile
import unittest
from pathlib import Path

from marllib.run_c_cross_geometry_gazebo import _audit_trajectory


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "configs" / "c_cross_geometry_calibration_smoke_v1.json"


class CrossGeometryProtocolTests(unittest.TestCase):
    def test_manifest_freezes_three_distinct_geometries_and_seeds(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(
            set(manifest["geometries"]),
            {"on_path_failure", "lateral_failure", "bottleneck_merge_failure"},
        )
        self.assertEqual(
            len({trial["seed"] for trial in manifest["trials"]}), 3
        )
        for trial in manifest["trials"]:
            self.assertEqual(sorted(trial["condition_order"]), ["R0", "R1"])

    def test_trajectory_audit_detects_revocation_and_bypass(self):
        rows = []
        for step in range(3):
            failed = step >= 1
            rows.append(
                {
                    "step": step,
                    "drones": {
                        "2": {
                            "command_authority": "failed_zero" if failed else "ra_filtered",
                            "ra_bypass": False,
                            "v_safe": [0.0, 0.0, 0.0],
                            "feasible": True,
                        },
                        "3": {
                            "command_authority": "ra_filtered",
                            "ra_bypass": step == 2,
                            "v_safe": [1.0, 0.0, 0.0],
                            "feasible": True,
                        },
                    },
                }
            )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trajectory.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            audit = _audit_trajectory(path, failed_drone=2, change_step=1)
        self.assertTrue(audit["failed_authority_revoked_all_steps"])
        self.assertTrue(audit["failed_horizontal_command_zero_all_steps"])
        self.assertEqual(audit["ra_bypass_count"], 1)


if __name__ == "__main__":
    unittest.main()
