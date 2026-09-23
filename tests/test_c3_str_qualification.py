from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from marllib.aggregate_c3_str_qualification import collect
from marllib.run_c3_str_qualification_gazebo import CONDITIONS, validate_manifest


ROOT = Path(__file__).resolve().parents[1]


class C3StrQualificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.path = ROOT / "configs/c3_str_4uav_qualification_v1.json"
        self.manifest = json.loads(self.path.read_text(encoding="utf-8"))

    def test_manifest_is_five_new_seed_paired_gate(self) -> None:
        validate_manifest(self.manifest)
        self.assertEqual(self.manifest["qualification_seeds"], [9801, 9802, 9803, 9804, 9805])
        first = [
            self.manifest["condition_order_by_seed"][str(seed)][0]
            for seed in self.manifest["qualification_seeds"]
        ]
        self.assertEqual(first.count(CONDITIONS[0]), 3)
        self.assertEqual(first.count(CONDITIONS[1]), 2)

    def test_aggregate_empty_root_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = collect(self.path, Path(directory))
        self.assertEqual(result["decision"], "INCOMPLETE")
        self.assertEqual(result["found_valid_conditions"], 0)
        self.assertEqual(result["r4_passed_trials"], 0)


if __name__ == "__main__":
    unittest.main()
