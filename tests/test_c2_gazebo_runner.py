"""Offline checks for the original C2 PX4/Gazebo comparison harness."""

from __future__ import annotations

import unittest

from marllib.run_c2_gazebo import _balanced_model_orders


class C2GazeboRunnerTest(unittest.TestCase):
    def test_complete_three_model_block_uses_each_order_once(self) -> None:
        models = ["E0", "E1", "E2"]
        orders = _balanced_model_orders(models, trials=6, order_seed=7)
        self.assertEqual(len(orders), 6)
        self.assertEqual({tuple(order) for order in orders}, {
            ("E0", "E1", "E2"),
            ("E0", "E2", "E1"),
            ("E1", "E0", "E2"),
            ("E1", "E2", "E0"),
            ("E2", "E0", "E1"),
            ("E2", "E1", "E0"),
        })

    def test_orders_are_reproducible_and_do_not_claim_disturbance_seeds(self) -> None:
        first = _balanced_model_orders(["E0", "E1", "E2"], trials=12, order_seed=42)
        second = _balanced_model_orders(["E0", "E1", "E2"], trials=12, order_seed=42)
        self.assertEqual(first, second)
        self.assertNotEqual(first[0], first[1])


if __name__ == "__main__":
    unittest.main()
