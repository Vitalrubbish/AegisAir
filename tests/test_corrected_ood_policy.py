"""故意注入的保持不等于未知改写，但不能用注入标签掩盖任意速度。"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from corrected_ood_policy import audit_holds, decision_for


class HoldAuditTests(unittest.TestCase):
    def records(self):
        return [dict(step=step, drones={str(drone): dict(telemetry_fresh=True,
            control_authority=True, command_hold_jitter_applied=True,
            published_velocity=[0., 0.], solver_selected_velocity=[1., 0.],
            published_command_matches_selected=False, published_action='velocity',
            fallback_reason='COMMAND_HOLD_JITTER') for drone in (2, 3)}) for step in range(2)]

    def test_verified_hold_is_expected_mismatch(self):
        result = audit_holds(self.records(), seed=1, probability=1, drone_ids=[2, 3])
        self.assertEqual(result, dict(hold_count=4, raw_mismatch_count=4,
            expected_hold_mismatch_count=4, unexpected_count=0))

    def test_wrong_held_value_not_excused(self):
        records = self.records()
        records[0]['drones']['2']['published_velocity'] = [.5, 0.]
        result = audit_holds(records, seed=1, probability=1, drone_ids=[2, 3])
        self.assertGreater(result['unexpected_count'], 0)

    def test_sequence_not_merely_self_reported_flag(self):
        records = self.records()
        records[0]['drones']['2']['command_hold_jitter_applied'] = False
        with self.assertRaisesRegex(ValueError, '序列'):
            audit_holds(records, seed=1, probability=1, drone_ids=[2, 3])

    def test_identical_hold_is_not_a_mismatch(self):
        records = copy.deepcopy(self.records())
        for record in records:
            for row in record['drones'].values():
                row['solver_selected_velocity'] = [0., 0.]
                row['published_command_matches_selected'] = True
        result = audit_holds(records, seed=1, probability=1, drone_ids=[2, 3])
        self.assertEqual(result['hold_count'], 4)
        self.assertEqual(result['raw_mismatch_count'], 0)
        self.assertEqual(result['unexpected_count'], 0)

    def test_injected_hold_does_not_bypass_primary_or_unknown_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            method = 'AEGIS_HOCBF_V4'
            folder = root / f't1_{method}_attempt1' / 'episode'
            folder.mkdir(parents=True)
            path = folder / 'trajectory.jsonl'
            path.write_text(''.join(json.dumps(record)+'\n' for record in self.records()))
            row = dict(trial_id='t1', method=method, seed=1, scenario_id='jitter',
                trajectory=path.name, trajectory_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                command_hold_jitter_count=4, published_command_mismatch_count=4,
                infrastructure_valid=True, mission_complete=True, min_rho=.1, collision=False,
                published_command_constraint_unknown_count=0)
            decide = decision_for(root, dict(drone_ids=[2, 3], command_hold_jitter={
                'jitter': dict(probability=1)}))
            self.assertEqual(decide([row], [method]), 'CONTINUE')
            self.assertEqual(row['published_command_mismatch_count'], 4)
            self.assertEqual(decide([dict(row, min_rho=-.1)], [method]), 'STOP_PRIMARY_FAILURE')
            self.assertEqual(decide([dict(row, published_command_constraint_unknown_count=1)], [method]), 'STOP_SAFETY_CHAIN')


if __name__ == '__main__':
    unittest.main()
