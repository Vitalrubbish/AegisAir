"""触发对照保留原开发门，不套用不存在的完整 V4 主方法。"""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from run_corrected_trigger_comparison import settings_for, trigger_decision


class TriggerComparisonTests(unittest.TestCase):
    def test_original_numeric_grid_preserved(self):
        for grid in (1, 2, 3):
            old = json.loads((ROOT / 'configs' / f'trigger_comparison_development_grid{grid}_v1.json').read_text())
            new = settings_for(grid)
            for key in ('methods', 'trials', 'scenarios', 'rate_hz', 'max_steps', 'analysis', 'safety_gate'):
                self.assertEqual(new[key], old[key])

    def test_negative_margin_and_incompletion_remain_outcomes(self):
        methods = list(settings_for(1)['methods'])
        rows = [dict(method=method, infrastructure_valid=True, collision=False,
                     min_rho=-1, mission_complete=False) for method in methods]
        self.assertEqual(trigger_decision(rows, methods), 'CONTINUE')
        rows[0]['collision'] = True
        self.assertEqual(trigger_decision(rows, methods), 'STOP_SCENARIO_COLLISION')
        rows[0]['safety_bypass_count'] = 1
        self.assertEqual(trigger_decision(rows, methods), 'STOP_SAFETY_CHAIN')


if __name__ == '__main__':
    unittest.main()
