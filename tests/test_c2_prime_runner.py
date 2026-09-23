"""Offline tests for the C2-prime experiment harness."""

from __future__ import annotations

import unittest

from marllib.run_c2_prime_gazebo import _supervisor_config


class C2PrimeRunnerTest(unittest.TestCase):
    def test_fixed_condition_has_no_supervisor(self) -> None:
        self.assertIsNone(_supervisor_config("E2_FIXED", None))

    def test_validation_requires_calibration(self) -> None:
        with self.assertRaises(ValueError):
            _supervisor_config("C2_PRIME", None)

    def test_qp_ablation_disables_only_residual_gate(self) -> None:
        calibration = {
            "frozen_thresholds": {
                "tau_s": 0.2,
                "velocity_residual_limit_mps": 0.3,
                "position_residual_limit_m": 0.05,
                "max_telemetry_age_s": 0.15,
                "solve_deadline_s": 0.05,
                "trip_samples": 2,
                "release_samples": 10,
                "backup_speed_mps": 0.6,
                "enable_residual_gate": True,
                "enable_qp_gate": True,
            }
        }
        config = _supervisor_config("E2_QP_GATE", calibration)
        self.assertFalse(config.enable_residual_gate)
        self.assertTrue(config.enable_qp_gate)
        full = _supervisor_config("C2_PRIME", calibration)
        self.assertTrue(full.enable_residual_gate)
        self.assertTrue(full.enable_qp_gate)

    def test_predictive_gate_requires_and_freezes_contract(self) -> None:
        calibration = {
            "frozen_thresholds": {
                "tau_s": 0.2,
                "velocity_residual_limit_mps": 0.3,
                "position_residual_limit_m": 0.05,
                "max_telemetry_age_s": 0.15,
                "solve_deadline_s": 0.05,
                "trip_samples": 2,
                "release_samples": 10,
                "backup_speed_mps": 0.6,
                "enable_residual_gate": True,
                "enable_qp_gate": True,
            }
        }
        with self.assertRaises(ValueError):
            _supervisor_config("PREDICTIVE_GATE", calibration)
        config = _supervisor_config(
            "PREDICTIVE_GATE",
            calibration,
            {
                "safe_distance_m": 1.6,
                "response_delay_s": 0.3,
                "braking_deceleration_mps2": 2.0,
                "recoverability_buffer_m": 0.2,
            },
        )
        self.assertTrue(config.enable_predictive_gate)
        self.assertEqual(config.response_delay_s, 0.3)


if __name__ == "__main__":
    unittest.main()
