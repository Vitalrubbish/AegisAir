"""Offline tests for the C3 closed-loop fail-closed recovery harness."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from marllib.run_c3_gazebo import _recovery_clients
from swarm.recovery import RuleMissionPlanner
from swarm.recovery.llm import RecoveryContext
from swarm.safety import DroneSnapshot


REPO = Path(__file__).resolve().parents[1]
SMOKE_MANIFEST = REPO / "configs" / "c3_closed_loop_smoke_v1.json"
VALIDATION_MANIFEST = REPO / "configs" / "c3_closed_loop_validation_v1.json"


def _px4_context(mission_change: dict) -> RecoveryContext:
    """Recovery context keyed by PX4 instance ids (2, 3), not logical 0, 1."""
    snapshots = {
        2: DroneSnapshot(2, (-2.0, 0.0, 2.5), (0.0, 0.0, 0.0)),
        3: DroneSnapshot(3, (-2.0, -2.0, 2.5), (0.0, 0.0, 0.0)),
    }
    return RecoveryContext(
        event="MISSION_PLAN_INVALIDATED",
        agent_i=2,
        agent_j=2,
        current_margin=1.0,
        predicted_min_margin=None,
        margin_degradation=None,
        intervention_count=0,
        cause="MISSION_CHANGE",
        severity="MEDIUM",
        snapshots=snapshots,
        current_goals={2: (4.0, 0.0, 2.5), 3: (4.0, -2.0, 2.5)},
        base_goals={2: (4.0, 0.0, 2.5), 3: (4.0, -2.0, 2.5)},
        priorities={2: "normal", 3: "normal"},
        timestamp_ms=1000,
        mission_change=mission_change,
    )


class C3ClosedLoopTest(unittest.TestCase):
    def test_fail_drone_reassigns_using_px4_instance_ids(self) -> None:
        plan = RuleMissionPlanner().generate(
            _px4_context({"kind": "fail_drone", "drone": 2})
        ).plan
        actions = {c.drone: c.action for c in plan.commands}
        self.assertEqual(actions[2], "ABORT")
        self.assertEqual(actions[3], "REASSIGN")
        reassign = next(c for c in plan.commands if c.action == "REASSIGN")
        self.assertEqual(reassign.waypoint, (4.0, 0.0, 2.5))

    def test_recovery_clients_map_r0_r1(self) -> None:
        mode, client, fallback = _recovery_clients("R0", "", 0)
        self.assertEqual(mode, "CBF_ONLY")
        self.assertIsNone(client)
        self.assertIsNone(fallback)

        mode, client, fallback = _recovery_clients("R1", "", 0)
        self.assertEqual(mode, "ASYNC")
        self.assertIsInstance(client, RuleMissionPlanner)
        self.assertIsNone(fallback)

    def test_smoke_manifest_is_frozen_and_well_formed(self) -> None:
        manifest = json.loads(SMOKE_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["protocol_id"], "aegisair-c3-closed-loop-v1")
        self.assertEqual(manifest["scenario"], "drone_failure")
        self.assertEqual(manifest["drone_ids"], [2, 3])
        self.assertEqual(manifest["mission_change"], {"kind": "fail_drone", "drone": 2})
        self.assertEqual(manifest["failed_drone"], 2)
        self.assertEqual(manifest["critical_goal"], [4.0, 0.0])
        for trial in manifest["trials"]:
            self.assertEqual(sorted(trial["condition_order"]), ["R0", "R1"])

    def test_validation_manifest_has_independent_seeded_latin_square(self) -> None:
        manifest = json.loads(VALIDATION_MANIFEST.read_text(encoding="utf-8"))
        trials = manifest["trials"]
        self.assertEqual(manifest["phase"], "validation")
        self.assertEqual(len(trials), 30)
        self.assertEqual([trial["seed"] for trial in trials], list(range(4101, 4131)))
        self.assertEqual(sum(t["condition_order"] == ["R0", "R1"] for t in trials), 15)
        self.assertEqual(sum(t["condition_order"] == ["R1", "R0"] for t in trials), 15)


if __name__ == "__main__":
    unittest.main()
