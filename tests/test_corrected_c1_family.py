"""后续比较不得意外改变数值条件或混淆 OOD 场景。"""
import json
import unittest
import tempfile
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from run_corrected_c1_family import CONFIGS,settings_for,existing_group


class FamilyTests(unittest.TestCase):
    def test_resume_does_not_skip_paused_scenario(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'run_settings.json').write_text('{}')
            (root/'status.json').write_text(json.dumps(dict(state='PAUSED_FOR_DIAGNOSIS')))
            with self.assertRaisesRegex(ValueError,'仍需排查'):
                existing_group(root,{}, {'COMPLETED','STOP_PRIMARY_FAILURE'})

    def test_resume_reuses_finished_unchanged_scenario(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'run_settings.json').write_text('{}')
            (root/'status.json').write_text(json.dumps(dict(state='COMPLETED',valid_conditions=15)))
            (root/'source_hashes.json').write_text('{}')
            self.assertEqual(existing_group(root,{}, {'COMPLETED'})['valid_conditions'],15)
            with self.assertRaisesRegex(ValueError,'配置变化'):
                existing_group(root,{'rate_hz':10}, {'COMPLETED'})

    def test_numeric_conditions_preserved(self):
        for name,parent in CONFIGS.items():
            with self.subTest(name=name):
                old=json.loads((ROOT/'configs'/parent).read_text())
                new=settings_for(name)
                for key in ('methods','trials','rate_hz','max_steps','execution_tau_s','base_goals','reset_starts','scenarios','command_hold_jitter'):
                    self.assertEqual(old.get(key),new.get(key),key)
                for trial in new['trials']:
                    self.assertIn('AEGIS_HOCBF_V4',trial['condition_order'])
