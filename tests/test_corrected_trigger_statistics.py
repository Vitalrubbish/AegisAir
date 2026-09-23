"""触发统计以seed配对，重复参考不能扩充样本。"""
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from analyze_corrected_trigger_test import LABELS, REFERENCE, paired_statistics


class TriggerStatisticsTests(unittest.TestCase):
    def rows(self):
        return [dict(seed=s, method=m, min_rho=2 if m == REFERENCE else 1,
                     mean_control_effort=0 if m == REFERENCE else 1)
                for s in range(5) for m in LABELS]

    def test_pair_direction_and_nine_comparisons(self):
        comparisons = paired_statistics({s: self.rows() for s in ('base','wide','diag')})
        self.assertEqual(len(comparisons), 9)
        for row in comparisons:
            self.assertEqual(row['pairs'], 5)
            self.assertEqual(row['metrics']['min_rho']['mean_difference'], 1)
            self.assertEqual(row['metrics']['mean_control_effort']['mean_difference'], -1)
            self.assertEqual(row['metrics']['min_rho']['exact_sign_flip_p'], .0625)
            self.assertEqual(row['metrics']['min_rho']['holm_p'], .5625)

    def test_duplicate_or_missing_rejected(self):
        for rows in (self.rows()[:-1], self.rows() + [self.rows()[0]]):
            with self.assertRaises(ValueError):
                paired_statistics({'base': rows})
