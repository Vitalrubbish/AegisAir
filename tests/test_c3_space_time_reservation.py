from __future__ import annotations

from types import SimpleNamespace
import unittest

import numpy as np

from swarm.recovery import (
    C3SpaceTimeReservationCoordinator,
    SpaceTimeReservationConfig,
)
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


class C3SpaceTimeReservationCoordinatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.coordinator = C3SpaceTimeReservationCoordinator(
            SpaceTimeReservationConfig(
                conflict_zone_id="crossing_center",
                conflict_zone_center=(0.0, 0.0),
                settle_steps=2,
                rate_hz=1.0,
                staging_window_s=1.0,
                service_window_s=1.0,
                final_return_window_s=1.0,
                veto_delay_steps=3,
                return_compatibility_clearance_m=1.6,
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
        self.assertEqual(len(first.decision.reservation_windows), 4 + len(self.coordinator.final_groups))
        self.call(snapshots())
        staged = snapshots(self.coordinator.hold_goals)
        self.call(staged)
        passed = self.call(staged)
        self.assertEqual(passed.decision.coordination_mode, "pass")
        return staged, passed

    def test_schedule_is_frozen_and_has_compatible_return_groups(self) -> None:
        self.call(snapshots())
        windows = list(self.coordinator.slots)
        self.assertEqual(len(windows), 4 + len(self.coordinator.final_groups))
        self.assertTrue(self.coordinator.final_groups)
        for group in self.coordinator.final_groups:
            for index, left in enumerate(group):
                for right in group[index + 1 :]:
                    self.assertTrue(self.coordinator._compatible_return(left, right))
        self.call(snapshots())
        self.assertEqual(
            [(slot.slot_id, slot.planned_open_step, slot.planned_close_step) for slot in windows],
            [
                (slot.slot_id, slot.planned_open_step, slot.planned_close_step)
                for slot in self.coordinator.slots
            ],
        )

    def test_transition_cycle_cannot_authorize_before_slot_open(self) -> None:
        coordinator = C3SpaceTimeReservationCoordinator(
            SpaceTimeReservationConfig(
                conflict_zone_id="crossing_center",
                conflict_zone_center=(0.0, 0.0),
                settle_steps=2,
                rate_hz=20.0,
                staging_window_s=6.0,
                service_window_s=8.0,
                final_return_window_s=7.0,
            ),
            DRONES,
            STARTS,
            GOALS,
        )
        coordinator.directives(
            step=0,
            timestamp_ms=1,
            snapshots=snapshots(),
            nominal=NOMINAL,
            previous_results=None,
        )
        coordinator.directives(
            step=1,
            timestamp_ms=2,
            snapshots=snapshots(),
            nominal=NOMINAL,
            previous_results=None,
        )
        staged = snapshots(coordinator.hold_goals)
        coordinator.directives(
            step=2,
            timestamp_ms=3,
            snapshots=staged,
            nominal=NOMINAL,
            previous_results=None,
        )
        transition = coordinator.directives(
            step=3,
            timestamp_ms=4,
            snapshots=staged,
            nominal=NOMINAL,
            previous_results=None,
        )
        self.assertEqual(transition.decision.coordination_mode, "slot_wait")
        self.assertEqual(transition.decision.authorized_drone_ids, [])
        self.assertEqual(transition.decision.active_slot_id, "service-00-uav2")

    def test_ra_veto_delays_schedule_and_holds_all_agents(self) -> None:
        staged, passed = self.enter_pass()
        active = passed.decision.authorized_drone_ids[0]
        before = [slot.planned_close_step for slot in self.coordinator.slots]
        before_revision = self.coordinator.schedule_revision
        before_delay = self.coordinator.total_delay_steps
        results = {
            drone: SimpleNamespace(feasible=(drone != active)) for drone in DRONES
        }
        observed = self.coordinator.observe_ra(results)
        self.assertTrue(observed.ra_vetoed)
        delayed = self.call(staged)
        self.assertEqual(delayed.decision.coordination_mode, "slot_delay")
        self.assertEqual(delayed.decision.authorized_drone_ids, [])
        self.assertEqual(set(delayed.decision.held_drone_ids), set(DRONES))
        self.assertEqual(delayed.decision.schedule_revision, before_revision + 1)
        self.assertEqual(delayed.decision.total_delay_steps, before_delay + 3)
        self.assertTrue(
            all(after >= prior for prior, after in zip(before, [slot.planned_close_step for slot in self.coordinator.slots]))
        )
        for _ in range(2):
            self.call(staged)
        resumed = self.call(staged)
        self.assertEqual(resumed.decision.coordination_mode, "pass")

    def test_grouped_final_return_reaches_complete(self) -> None:
        self.enter_pass()
        positions = dict(self.coordinator.hold_goals)
        for drone in list(self.coordinator.order):
            positions[drone] = GOALS[drone]
            self.call(snapshots(positions))
            positions[drone] = self.coordinator.clearance_goals[drone]
            self.call(snapshots(positions))
            self.call(snapshots(positions))
            self.call(snapshots(positions))
        self.assertEqual(self.coordinator.mode, "final_return")
        for group in self.coordinator.final_groups:
            for drone in group:
                positions[drone] = GOALS[drone]
            self.call(snapshots(positions))
            result = self.call(snapshots(positions))
        self.assertEqual(result.decision.coordination_mode, "complete")
        self.assertEqual(set(result.decision.final_returned_drone_ids), set(DRONES))


if __name__ == "__main__":
    unittest.main()
