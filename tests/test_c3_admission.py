from __future__ import annotations

from types import SimpleNamespace
import unittest

import numpy as np

from swarm.recovery.admission import AdmissionConfig, C3AdmissionCoordinator
from swarm.safety import DroneSnapshot


def _snapshots(offset: float = 0.0) -> dict[int, DroneSnapshot]:
    starts = {
        2: (-3.0 - offset, 0.8, 2.5),
        3: (3.0 + offset, -0.8, 2.5),
        4: (-3.0 - offset, -0.8, 2.5),
        5: (3.0 + offset, 0.8, 2.5),
    }
    goals = {
        2: (3.0, -0.8, 2.5),
        3: (-3.0, 0.8, 2.5),
        4: (3.0, 0.8, 2.5),
        5: (-3.0, -0.8, 2.5),
    }
    return {
        drone: DroneSnapshot(drone, position, target=goals[drone], velocity=(0.0, 0.0, 0.0))
        for drone, position in starts.items()
    }


def _nominal() -> dict[int, np.ndarray]:
    return {
        2: np.asarray((1.5, -0.4)),
        3: np.asarray((-1.5, 0.4)),
        4: np.asarray((1.5, 0.4)),
        5: np.asarray((-1.5, -0.4)),
    }


class C3AdmissionCoordinatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = AdmissionConfig(
            conflict_zone_id="crossing_center",
            conflict_zone_center=(0.0, 0.0),
            conflict_zone_radius_m=1.25,
            admission_horizon_s=2.5,
            reserve_threshold=1.0,
            predicted_rho_warning=0.2,
            fallback_d_safe_m=1.6,
        )
        self.coordinator = C3AdmissionCoordinator(self.config, [2, 3, 4, 5])

    def test_requires_conflict_zone_and_risk_gate(self) -> None:
        safe_nominal = {drone: np.zeros(2) for drone in [2, 3, 4, 5]}
        result = self.coordinator.directives(
            step=0,
            timestamp_ms=1,
            snapshots=_snapshots(),
            nominal=safe_nominal,
            previous_results=None,
        )
        self.assertEqual(result.decision.coordination_mode, "normal")
        self.assertEqual(result.decision.admission_triggers, [])

    def test_state_machine_and_holds_are_frozen_once(self) -> None:
        first = self.coordinator.directives(
            step=10,
            timestamp_ms=1,
            snapshots=_snapshots(),
            nominal=_nominal(),
            previous_results=None,
        )
        self.assertEqual(first.decision.coordination_mode, "admission_pending")
        self.assertEqual(set(first.decision.held_drone_ids), {2, 3, 4, 5})
        self.assertIn("conflict_zone", first.decision.admission_triggers)
        self.assertIn("predicted_rho_low", first.decision.admission_triggers)
        frozen = dict(first.decision.frozen_hold_goals)

        second = self.coordinator.directives(
            step=11,
            timestamp_ms=2,
            snapshots=_snapshots(offset=0.2),
            nominal=_nominal(),
            previous_results=None,
        )
        self.assertEqual(second.decision.coordination_mode, "hold")
        self.assertEqual(second.decision.frozen_hold_goals, frozen)
        self.assertTrue(all(step == 10 for step in second.decision.hold_enter_steps.values()))

        third = self.coordinator.directives(
            step=12,
            timestamp_ms=3,
            snapshots=_snapshots(offset=0.2),
            nominal=_nominal(),
            previous_results=None,
        )
        self.assertEqual(third.decision.coordination_mode, "pass")
        self.assertEqual(len(third.decision.authorized_drone_ids), 1)
        self.assertEqual(len(third.decision.held_drone_ids), 3)

    def test_ra_veto_is_observed_without_direct_command(self) -> None:
        self.coordinator.directives(
            step=0,
            timestamp_ms=1,
            snapshots=_snapshots(),
            nominal=_nominal(),
            previous_results=None,
        )
        self.coordinator.directives(
            step=1,
            timestamp_ms=2,
            snapshots=_snapshots(),
            nominal=_nominal(),
            previous_results=None,
        )
        passed = self.coordinator.directives(
            step=2,
            timestamp_ms=3,
            snapshots=_snapshots(),
            nominal=_nominal(),
            previous_results=None,
        )
        authorized = passed.decision.authorized_drone_ids[0]
        results = {
            drone: SimpleNamespace(
                feasible=(False if drone == authorized else True),
                safe_action=(0.0, 0.0),
                d_safe=1.6,
                feasibility_reserve=2.0,
            )
            for drone in [2, 3, 4, 5]
        }
        decision = self.coordinator.observe_ra(results)
        self.assertIsNotNone(decision)
        self.assertTrue(decision.ra_vetoed)
        self.assertEqual(self.coordinator.summary()["ra_veto_count"], 1)

    def test_horizon_outside_preregistered_range_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            AdmissionConfig(
                conflict_zone_id="x",
                conflict_zone_center=(0.0, 0.0),
                conflict_zone_radius_m=1.0,
                admission_horizon_s=3.5,
                reserve_threshold=1.0,
                predicted_rho_warning=0.2,
                fallback_d_safe_m=1.6,
            )


if __name__ == "__main__":
    unittest.main()
