"""PCBF 审计不能将求解可行自动等同于截断后的计划可行。"""
import unittest
from dataclasses import replace
import numpy as np
from swarm.ra.pcbf import PCBFConfig, PCBFResult, published_plan_violation


class PublishedPCBFTests(unittest.TestCase):
    def test_first_action_change_can_break_terminal_stop(self):
        cfg=PCBFConfig(horizon=2,dt=.05,control_scale_s=.05)
        plan=np.zeros((2,2,2))
        result=PCBFResult(accelerations={2:np.zeros(2),3:np.zeros(2)},feasible=True,
            terminal_feasible=True,value=0,slack_sum=0,iterations=0,status='solved_local',
            fail_closed_reason=None,plan=plan,slacks=np.zeros(2))
        args=dict(positions={2:np.array([-4.,0.]),3:np.array([4.,0.])},
                  velocities={2:np.zeros(2),3:np.zeros(2)},safe_distances={(2,3):1.},config=cfg)
        self.assertEqual(published_plan_violation(result,result.accelerations,**args),0)
        changed={2:np.array([.2,0]),3:np.zeros(2)}
        self.assertAlmostEqual(published_plan_violation(result,changed,**args),.01)
        np.testing.assert_array_equal(result.plan,plan)
        self.assertEqual(published_plan_violation(replace(result,feasible=False),changed,**args),float('inf'))
