"""消融的数值条件不随停止规则修订而改变。"""
import json
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from run_ablation_corrected_v2 import revised_settings
from c1_revision_policy import paired_decision
from run_c1_corrected_v2 import run_remaining, has_episode_trajectory


class CorrectedAblationTests(unittest.TestCase):
    def test_observer_jsonl_is_not_an_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)
            logs=out/'ext23_AEGIS_HOCBF_V3_logs';logs.mkdir()
            (logs/'telemetry_arrivals.jsonl').write_text('{}\n')
            self.assertFalse(has_episode_trajectory(out))
            episode=out/'ext23_AEGIS_HOCBF_V3';episode.mkdir()
            (episode/'ext23_00_AEGIS_HOCBF_V3.jsonl').write_text('{}\n')
            self.assertTrue(has_episode_trajectory(out))

    def test_resume_skips_valid_condition_and_uses_new_attempt_number(self):
        settings={'trials':[dict(trial_id='abl08',condition_order=['AEGIS_HOCBF_V4','AEGIS_HOCBF_V3'])]}
        rows=[dict(trial_id='abl08',method='AEGIS_HOCBF_V4')]
        attempts=[dict(label=f'abl08_AEGIS_HOCBF_V3_attempt{i}',state='INFRASTRUCTURE_INVALID') for i in (1,2,3)]
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)
            with patch('run_c1_corrected_v2.subprocess.run',side_effect=RuntimeError('测试中止')) as run:
                with self.assertRaisesRegex(RuntimeError,'测试中止'):
                    run_remaining(out,settings,rows,attempts,0)
            command=run.call_args.args[0]
            self.assertEqual(command[-1],'AEGIS_HOCBF_V3')
            self.assertIn('abl08_AEGIS_HOCBF_V3_attempt4',command[command.index('--out')+1])
            self.assertEqual(len(rows),1)
            self.assertEqual(json.loads((out/'status.json').read_text())['valid_conditions'],1)

    def test_only_execution_policy_changes(self):
        parent = ROOT/'configs/c1_hocbf_v4_ablation_sealed_v1.json'
        old = json.loads(parent.read_text())
        new = revised_settings(parent)
        for key in ('methods','trials','rate_hz','max_steps','execution_tau_s',
                    'base_goals','reset_starts','comparisons','primary_endpoints','analysis'):
            self.assertEqual(old[key], new[key], key)
        self.assertNotIn('safety_gate', new)
        self.assertEqual(sum(len(t['condition_order']) for t in new['trials']),80)

    def test_reserve_only_failure_does_not_stop_complete_pair(self):
        methods = ['AEGIS_HOCBF_V3','AEGIS_HOCBF_V4_REACTIVE',
                   'AEGIS_HOCBF_V4_RESERVE_ONLY','AEGIS_HOCBF_V4']
        rows = [dict(method=m,infrastructure_valid=True,collision=False,
                     mission_complete=True,min_rho=.1) for m in methods]
        rows[2].update(min_rho=-.1,mission_complete=False)
        self.assertEqual(paired_decision(rows,methods),'CONTINUE')
