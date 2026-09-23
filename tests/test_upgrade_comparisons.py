"""论文新增对照不改变默认生产行为。"""
import math
import unittest
from unittest.mock import patch
import numpy as np
from swarm.ra.trigger_baselines import constant_velocity_ttc, proximity_trigger
from swarm.ra.runtime_assurance import RuntimeAssurance
from swarm.recovery.recoverability_admission import RecoverabilityAdmissionCoordinator
from swarm.safety import DroneSnapshot


class TriggerTests(unittest.TestCase):
    def test_ttc_cases(self):
        self.assertAlmostEqual(constant_velocity_ttc([5, 0], [-1, 0], 2), 3)
        self.assertEqual(constant_velocity_ttc([1, 0], [1, 0], 2), 0)
        for v in ([1, 0], [0, 0], [0, 1], [-1, 1]):
            self.assertTrue(math.isinf(constant_velocity_ttc([5, 0], v, 2)))
        self.assertAlmostEqual(constant_velocity_ttc([5, 2], [-1, 0], 2), 5)

    def test_disabled_and_thresholds(self):
        p, v, b = {2: [0, 0], 3: [5, 0]}, {2: [1, 0], 3: [-1, 0]}, {(2, 3): 2}
        self.assertIsNone(proximity_trigger(p, v, b))
        self.assertEqual(proximity_trigger(p, v, b, distance_m=5), "distance_threshold")
        self.assertEqual(proximity_trigger(p, v, b, ttc_s=1.5), "ttc_threshold")
        self.assertIsNone(proximity_trigger(p, v, b, ttc_s=1))

    def test_parameter_validation(self):
        for value in (0, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                RuntimeAssurance(hocbf_recovery_ttc_threshold_s=value)
        with self.assertRaises(ValueError):
            RuntimeAssurance(hocbf_recovery_distance_threshold_m=3, hocbf_recovery_reserve_threshold=0)
        self.assertIsNone(RuntimeAssurance().hocbf_recovery_distance_threshold_m)

    def test_distance_latch_and_revoked_authority(self):
        c = RuntimeAssurance(use_hocbf=True, hocbf_pb_recovery=True,
                             hocbf_predictive_recovery=False,
                             hocbf_recovery_distance_threshold_m=10)
        snapshots = {2: DroneSnapshot(2, (-3., 0., 2.5), velocity=(0., 0., 0.)),
                     3: DroneSnapshot(3, (3., 0., 2.5), velocity=(0., 0., 0.))}
        nominal = {2: np.zeros(2), 3: np.zeros(2)}
        result = c.filter(snapshots, nominal, t=0, fixed_actions={2: np.zeros(2)})
        self.assertEqual(result[3].recovery_reason, 'distance_threshold')
        np.testing.assert_array_equal(result[2].safe_action, np.zeros(2))
        snapshots[3] = DroneSnapshot(3, (30., 0., 2.5), velocity=(0., 0., 0.))
        for step in range(1, 5):
            result = c.filter(snapshots, nominal, t=step*.05)
            self.assertEqual(result[3].recovery_reason, 'distance_threshold')
        result = c.filter(snapshots, nominal, t=.25)
        self.assertIsNone(result[3].recovery_reason)

    def test_ttc_full_filter_branch(self):
        c = RuntimeAssurance(use_hocbf=True, hocbf_pb_recovery=True,
                             hocbf_predictive_recovery=False,
                             hocbf_recovery_ttc_threshold_s=20)
        snapshots = {2: DroneSnapshot(2, (-5., 0., 2.5), velocity=(.1, 0., 0.)),
                     3: DroneSnapshot(3, (5., 0., 2.5), velocity=(-.1, 0., 0.))}
        nominal = {2: np.zeros(2), 3: np.zeros(2)}
        self.assertIsNone(c.filter(snapshots, nominal, t=0)[3].recovery_reason)
        c.hocbf_recovery_ttc_threshold_s = 100
        self.assertEqual(c.filter(snapshots, nominal, t=.05)[3].recovery_reason, 'ttc_threshold')


class AdmissionTests(unittest.TestCase):
    def test_geometry_removes_rollout_only(self):
        c = RecoverabilityAdmissionCoordinator(geometry_only=True)
        start, goal = np.array([-4., 4.]), np.array([4., 4.])
        with patch.object(c, '_candidate_routes', return_value=[[start, goal]]), patch.object(c, '_rollout_route', side_effect=AssertionError('几何对照不应 rollout')):
            c._admit(start=start, initial_velocity=np.zeros(2), goal=goal,
                     failed_trajectory=[np.zeros(2), np.zeros(2)], altitude=2)
        self.assertEqual(c.state, 'admitted')
        self.assertEqual(c.plans_committed, 1)
        self.assertEqual(c.rollout_candidate_count, 0)
        self.assertIsNone(c.predicted_min_clearance_m)
        self.assertFalse(RecoverabilityAdmissionCoordinator().geometry_only)

    def test_geometry_rejects_occupied_goal(self):
        c = RecoverabilityAdmissionCoordinator(geometry_only=True)
        c._admit(start=np.array([-4., 4.]), initial_velocity=np.zeros(2), goal=np.zeros(2),
                 failed_trajectory=[np.zeros(2), np.zeros(2)], altitude=2)
        self.assertEqual(c.state, 'rejected_hold')
        self.assertEqual(c.plans_committed, 0)

    def test_both_modes_retain_velocity_guard(self):
        for geometry_only in (False, True):
            c = RecoverabilityAdmissionCoordinator(geometry_only=geometry_only)
            c._admit(start=np.array([-4., 4.]), initial_velocity=np.array([2., 0.]),
                     goal=np.array([4., 4.]), failed_trajectory=[np.zeros(2), np.zeros(2)], altitude=2)
            self.assertEqual(c.rejection_reason, 'initial_velocity_limit_violation')
            self.assertEqual(c.plans_committed, 0)


if __name__ == '__main__':
    unittest.main()
