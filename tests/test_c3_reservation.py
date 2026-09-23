from __future__ import annotations

from types import SimpleNamespace
import unittest

import numpy as np

from swarm.recovery import C3ReservationCoordinator, ReservationConfig
from swarm.safety import DroneSnapshot


DRONES = [2, 3, 4, 5]
STARTS = {
    2: (-3.0, 0.8, 2.5),
    3: (3.0, -0.8, 2.5),
    4: (-3.0, -0.8, 2.5),
    5: (3.0, 0.8, 2.5),
}
GOALS = {
    2: (3.0, -0.8, 2.5),
    3: (-3.0, 0.8, 2.5),
    4: (3.0, 0.8, 2.5),
    5: (-3.0, -0.8, 2.5),
}
NOMINAL = {
    2: np.asarray((1.5, -1.5)),
    3: np.asarray((-1.5, 1.5)),
    4: np.asarray((1.5, 1.5)),
    5: np.asarray((-1.5, -1.5)),
}


def snapshots(positions=None, velocities=None):
    positions = positions or STARTS
    velocities = velocities or {drone: (0.0, 0.0, 0.0) for drone in DRONES}
    return {
        drone: DroneSnapshot(
            drone_id=drone,
            position=positions[drone],
            target=GOALS[drone],
            velocity=velocities[drone],
        )
        for drone in DRONES
    }


class C3ReservationCoordinatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.coordinator = C3ReservationCoordinator(
            ReservationConfig(
                conflict_zone_id="crossing_center",
                conflict_zone_center=(0.0, 0.0),
                settle_steps=2,
                ra_veto_streak_limit=3,
            ),
            DRONES,
            STARTS,
            GOALS,
        )
        self.step = 0

    def call(self, current, nominal=NOMINAL):
        result = self.coordinator.directives(
            step=self.step,
            timestamp_ms=self.step + 1,
            snapshots=current,
            nominal=nominal,
            previous_results=None,
        )
        self.step += 1
        return result

    def enter_pass(self):
        first = self.call(snapshots())
        self.assertEqual(first.decision.coordination_mode, "admission_pending")
        second = self.call(snapshots())
        self.assertEqual(second.decision.coordination_mode, "staging")
        staged = snapshots(self.coordinator.hold_goals)
        self.call(staged)
        passed = self.call(staged)
        self.assertEqual(passed.decision.coordination_mode, "pass")
        return staged, passed

    def test_staging_waits_until_all_holds_are_settled(self) -> None:
        self.call(snapshots())
        self.call(snapshots())
        still_moving = snapshots(
            self.coordinator.hold_goals,
            {drone: (0.3, 0.0, 0.0) for drone in DRONES},
        )
        for _ in range(4):
            result = self.call(still_moving)
        self.assertEqual(result.decision.coordination_mode, "staging")

    def test_service_clear_release_and_final_return_complete(self) -> None:
        staged, result = self.enter_pass()
        order = list(self.coordinator.order)
        current_positions = dict(self.coordinator.hold_goals)
        for index, drone in enumerate(order):
            current_positions[drone] = GOALS[drone]
            result = self.call(snapshots(current_positions))
            self.assertEqual(result.decision.coordination_mode, "clear")
            current_positions[drone] = self.coordinator.clearance_goals[drone]
            self.call(snapshots(current_positions))
            result = self.call(snapshots(current_positions))
            self.assertEqual(result.decision.coordination_mode, "release")
            result = self.call(snapshots(current_positions))
            expected = "final_return" if index == len(order) - 1 else "pass"
            self.assertEqual(result.decision.coordination_mode, expected)

        for drone in self.coordinator.final_order:
            current_positions[drone] = GOALS[drone]
            self.call(snapshots(current_positions))
            result = self.call(snapshots(current_positions))
        self.assertEqual(result.decision.coordination_mode, "complete")
        self.assertEqual(set(result.decision.final_returned_drone_ids), set(DRONES))

    def test_clearance_points_are_distinct_from_stage_holds(self) -> None:
        self.call(snapshots())
        for drone in DRONES:
            clearance = np.asarray(self.coordinator.clearance_goals[drone][:2])
            hold = np.asarray(self.coordinator.hold_goals[drone][:2])
            self.assertGreater(float(np.linalg.norm(clearance - hold)), 1.0)
        self.assertEqual(len(set(self.coordinator.clearance_goals.values())), 4)

    def test_consecutive_ra_veto_revokes_pass(self) -> None:
        staged, passed = self.enter_pass()
        active = passed.decision.authorized_drone_ids[0]
        self.coordinator.record_nominal(NOMINAL)
        results = {
            drone: SimpleNamespace(
                feasible=(False if drone == active else True),
                safe_action=(0.0, 0.0),
            )
            for drone in DRONES
        }
        for _ in range(3):
            self.coordinator.observe_ra(results)
        revoked = self.call(staged)
        self.assertEqual(revoked.decision.coordination_mode, "revoke_hold")
        self.assertEqual(revoked.decision.authority_source, "fallback")
        self.assertEqual(self.coordinator.summary()["revoke_count"], 1)

    def test_feasible_braking_opposite_nominal_is_not_explicit_veto(self) -> None:
        _, passed = self.enter_pass()
        active = passed.decision.authorized_drone_ids[0]
        self.coordinator.record_nominal(NOMINAL)
        results = {
            drone: SimpleNamespace(
                feasible=True,
                safe_action=(1.0, 1.0) if drone == active else (0.0, 0.0),
            )
            for drone in DRONES
        }
        decision = self.coordinator.observe_ra(results)
        self.assertIsNotNone(decision)
        self.assertFalse(decision.ra_vetoed)
        self.assertEqual(decision.ra_veto_streak, 0)


if __name__ == "__main__":
    unittest.main()
