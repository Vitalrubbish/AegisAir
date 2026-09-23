"""离线状态矩阵保持位置配对，复用闭环触发配置而不混入历史状态。"""
import json
from pathlib import Path
import sys
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from audit_trigger_velocity_states import controller,state_grid


class VelocityAuditTests(unittest.TestCase):
    def test_same_positions_different_velocities(self):
        protocol=json.loads((ROOT/'configs/trigger_velocity_state_audit_v1.json').read_text())
        grid=json.loads((ROOT/'configs/trigger_comparison_development_grid1_v1.json').read_text())
        states=list(state_grid(protocol,grid['scenarios']))
        self.assertEqual(len(states),90)
        for offset in range(0,90,10):
            positions={drone:snapshot.position for drone,snapshot in states[offset][1].items()}
            for _,snapshots,_ in states[offset:offset+10]:
                self.assertEqual({drone:snapshot.position for drone,snapshot in snapshots.items()},positions)
                self.assertTrue(all(np.max(np.abs(snapshot.velocity[:2]))<=1.5+1e-12 for snapshot in snapshots.values()))

    def test_actual_controller_mapping(self):
        grid=json.loads((ROOT/'configs/trigger_comparison_development_grid1_v1.json').read_text())
        c=controller('AEGIS_HOCBF_V4_DISTANCE',grid['methods']['AEGIS_HOCBF_V4_DISTANCE'])
        self.assertEqual(c.v_max,1.5)
        self.assertEqual(c.command_feedforward_tau_s,.7)
        self.assertEqual(c.params.degradation_dt,.05)
        self.assertEqual(c.hocbf_recovery_distance_threshold_m,3)
        self.assertIsNone(c.hocbf_recovery_reserve_threshold)
        self.assertFalse(c.hocbf_predictive_recovery)


if __name__=='__main__':
    unittest.main()
