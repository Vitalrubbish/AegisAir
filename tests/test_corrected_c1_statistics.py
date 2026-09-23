"""机制提前步数不能用未观察事件或首架机状态伪造。"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from analyze_corrected_c1_family import mechanism


class MechanismTests(unittest.TestCase):
    def test_censored_primary_failure(self):
        records = [dict(step=2, drones={'2': dict(recovery_active=True,
            recovery_reason='feasibility_reserve_low', primary_feasible=True)})]
        self.assertIsNone(mechanism(records)['lead_steps'])
        self.assertTrue(mechanism(records)['primary_feasible_at_first_recovery'])

    def test_checks_all_vehicles(self):
        records = [dict(step=2, drones={'2': dict(primary_feasible=True),
            '3': dict(recovery_active=True, recovery_reason='primary_infeasible', primary_feasible=False)})]
        result = mechanism(records)
        self.assertEqual(result['lead_steps'], 0)
        self.assertFalse(result['primary_feasible_at_first_recovery'])


if __name__ == '__main__':
    unittest.main()
