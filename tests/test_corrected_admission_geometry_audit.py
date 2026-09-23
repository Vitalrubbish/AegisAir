"""离线审计须使用现行生产接口，不伪造已移除的采样维度。"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from run_corrected_admission_geometry_audit import cases, decide, variants
from swarm.recovery.recoverability_admission import RecoverabilityAdmissionConfig


class GeometryAuditTests(unittest.TestCase):
    def test_fixed_states_and_supported_variants(self):
        self.assertEqual(len(list(cases())), 61)
        self.assertEqual(len(variants()), 15)
        self.assertFalse(any('obstacle_samples' in name for name, _ in variants()))

    def test_occupied_goal_is_not_admitted(self):
        result = decide(dict(start=[-4., 3.], goal=[0., 0.], failed=[0., 0.],
                             velocity=[0., 0.]), RecoverabilityAdmissionConfig())
        self.assertEqual(result['state'], 'rejected_hold')
        self.assertIsNone(result['route_length_m'])


if __name__ == '__main__':
    unittest.main()
