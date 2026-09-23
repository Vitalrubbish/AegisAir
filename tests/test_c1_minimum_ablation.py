from __future__ import annotations

import unittest
import json
from pathlib import Path

from marllib.run_c1_minimum_ablation import (
    ABLATIONS,
    SCENARIOS,
    make_controller,
    params_for,
    scenario_spec,
)
from marllib.phase5_runner import OBSERVATION_LOCAL_FRESH_SELF

REPO = Path(__file__).resolve().parents[1]
PX4_MANIFEST = REPO / "configs" / "c1_px4_telemetry_delay_validation_v1.json"
PX4_V2_MANIFEST = REPO / "configs" / "c1_px4_telemetry_delay_validation_v2.json"


class C1MinimumAblationTest(unittest.TestCase):
    def test_all_required_ablations_are_frozen(self) -> None:
        self.assertEqual(ABLATIONS, ("fixed_distance", "full_envelope", "no_perception_margin", "no_aoi_margin"))

    def test_ablation_changes_only_its_expected_margin_terms(self) -> None:
        fixed = params_for("fixed_distance")
        self.assertEqual(fixed.beta, 0.0)
        self.assertEqual(fixed.v_max, 0.0)
        self.assertEqual(params_for("no_perception_margin").beta, 0.0)
        self.assertEqual(params_for("no_aoi_margin").v_max, 0.0)

    def test_all_scenarios_are_four_uav(self) -> None:
        self.assertEqual(set(SCENARIOS), {"randomized_start_goal", "dense_intersection", "perception_dropout", "telemetry_delay"})
        for name in SCENARIOS:
            self.assertEqual(scenario_spec(name)["scenario"].num_agents, 4)

    def test_telemetry_delay_uses_stale_estimator_state(self) -> None:
        self.assertEqual(
            SCENARIOS["telemetry_delay"]["fault"],
            {"estimator_delay_ms": 300},
        )

    def test_make_controller_has_zero_default_perception_sigma(self) -> None:
        ra = make_controller("full_envelope", qp_max_iters=10, speed_limit=1.5)
        self.assertEqual(ra.perception_sigma, 0.0)

    def test_local_fresh_self_mode_is_available_for_v5(self) -> None:
        self.assertEqual(
            OBSERVATION_LOCAL_FRESH_SELF,
            "local_fresh_self_stale_peers",
        )

    def test_px4_core_manifest_is_seeded_and_latin_square(self) -> None:
        payload = json.loads(PX4_MANIFEST.read_text(encoding="utf-8"))
        trials = payload["trials"]
        self.assertEqual(payload["observation_mode"], OBSERVATION_LOCAL_FRESH_SELF)
        self.assertEqual(len(trials), 20)
        self.assertEqual([t["seed"] for t in trials], list(range(5101, 5121)))
        self.assertEqual(sum(t["condition_order"][0] == "full_envelope" for t in trials), 10)

    def test_px4_v2_manifest_freezes_independent_seeds_and_tau_roles(self) -> None:
        payload = json.loads(PX4_V2_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual([t["seed"] for t in payload["trials"]], list(range(6101, 6121)))
        self.assertEqual(
            payload["tau"],
            {
                "barrier_tau_px4_s": 0.2,
                "command_feedforward_tau_s": 0.7,
                "admission_execution_tau_s": 0.7,
            },
        )


if __name__ == "__main__":
    unittest.main()
