import unittest

import numpy as np

from marllib.run_b1_scalability_microbenchmark import generate_flow, summarize


class B1ScalabilityMicrobenchmarkTests(unittest.TestCase):
    def test_flow_is_deterministic_and_has_requested_shape(self):
        domain = {
            "flow_start_radius_m": 4.5,
            "flow_end_radius_m": 1.15,
            "position_jitter_m": 0.08,
            "velocity_jitter_mps": 0.04,
        }
        first = generate_flow(
            n_agents=4,
            geometry="symmetric_crossing",
            flow_index=3,
            steps=12,
            seed=123,
            domain=domain,
        )
        second = generate_flow(
            n_agents=4,
            geometry="symmetric_crossing",
            flow_index=3,
            steps=12,
            seed=123,
            domain=domain,
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first), 12)
        self.assertEqual(np.asarray(first[0]["positions"]).shape, (4, 2))

    def test_summary_uses_strict_predeclared_deadline_gates(self):
        config = {
            "deadline_ms": 50.0,
            "scales": [2, 4],
            "geometries": ["symmetric_crossing"],
            "method_order": ["AEGIS_HOCBF_V4"],
            "go_criteria": {
                "primary_max_scale": 4,
                "p99_latency_ms_lt": 50.0,
                "deadline_miss_fraction_lt": 0.01,
            },
        }
        rows = []
        for scale, latency in ((2, 1.0), (4, 50.0)):
            for _ in range(100):
                rows.append(
                    {
                        "n_agents": scale,
                        "geometry": "symmetric_crossing",
                        "method": "AEGIS_HOCBF_V4",
                        "latency_ms": latency,
                        "feasible": True,
                        "intervened_agents": 0,
                        "control_effort": 0.0,
                        "peak_process_rss_mib": 10.0,
                    }
                )
        summary = summarize(rows, config=config)
        self.assertEqual(summary["decision"], "NO_GO")
        self.assertEqual(summary["maximum_supported_scale_in_tested_set"], 2)


if __name__ == "__main__":
    unittest.main()
