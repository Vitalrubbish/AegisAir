"""接纳重跑保留数值、部分结果和基线负结局。"""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from run_admission_corrected_v2 import CONFIGS,settings_for,paired_decision,run,validate_prerequisite,chain_integrity,pre_episode_reset_failure


class AdmissionCampaignTests(unittest.TestCase):
    def test_original_settings_preserved(self):
        for stage,name in CONFIGS.items():
            original=json.loads((ROOT/'configs'/name).read_text())
            settings=settings_for(stage)
            for key,value in original.items():
                self.assertEqual(settings[key],value,(stage,key))

    def test_no_historical_or_missing_prerequisite(self):
        with self.assertRaises(ValueError):
            validate_prerequisite('qualification',None)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'audit.json'
            path.write_text(json.dumps(dict(decision='GO',protocol_id='old-v1')))
            with self.assertRaises(ValueError):
                validate_prerequisite('qualification',path)

    def test_v5_settings_are_new_and_preserve_original_trials(self):
        old=settings_for('calibration')
        new=settings_for('calibration_v5')
        self.assertEqual(new['trials'],old['trials'])
        self.assertEqual(new['geometries'],old['geometries'])
        self.assertEqual(new['ra_config'],old['ra_config'])
        self.assertEqual(new['recoverability_admission']['healthy_velocity_limit_mps'],1.5)
        self.assertEqual(new['recoverability_admission']['stabilization_wait_s'],2.0)
        self.assertEqual(new['recoverability_admission']['stabilization_consecutive_samples'],3)
        self.assertNotEqual(new['protocol_id'],old['protocol_id'])
        with self.assertRaises(ValueError):
            validate_prerequisite('qualification_v5',None)

    def test_baseline_outcome_not_main_failure(self):
        rows=[dict(condition='IMMEDIATE_COMMIT_RA',infrastructure_valid=True,collision=True,min_rho=-1),
              dict(condition='RECOVERABILITY_ADMISSION_RA',infrastructure_valid=True,collision=False,min_rho=1)]
        report=dict(admission_checks=[dict(passed=True)],hold_checks=[dict(passed=True)])
        with patch('run_admission_corrected_v2.chain_integrity',return_value=True), patch('run_admission_corrected_v2.analyze',return_value=report):
            self.assertEqual(paired_decision({},rows),'CONTINUE')
            report['admission_checks'][0]['passed']=False
            self.assertEqual(paired_decision({},rows),'STOP_ADMISSION_DIAGNOSIS')

    def test_baseline_latency_and_constraint_failure_are_not_authority_bypass(self):
        row=dict(infrastructure_valid=True,safety_bypass_count=0,published_command_mismatch_count=0,
            published_command_constraint_unknown_count=0,published_command_constraint_failure_count=100,
            ra_solve_latency_summary_ms=dict(p99=70,deadline_misses=20),
            trajectory_audit=dict(ra_bypass_count=0,failed_authority_revoked_all_steps=True,
                failed_horizontal_command_zero_all_steps=True))
        self.assertTrue(chain_integrity(row))
        row['trajectory_audit']['failed_authority_revoked_all_steps']=False
        self.assertFalse(chain_integrity(row))

    def test_pre_episode_reset_timeout_is_infrastructure_only_without_trajectory(self):
        label='radm4_onpath_dev_RA_ONLY_HOLD_attempt1'
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)
            logs=out/'radm4_onpath_dev_RA_ONLY_HOLD_logs'
            logs.mkdir()
            (logs/'runner.log').write_text('PX4 velocity reset failed to settle within 45s')
            self.assertTrue(pre_episode_reset_failure(out,label))
            episode=out/'radm4_onpath_dev_RA_ONLY_HOLD'
            episode.mkdir()
            (episode/'trajectory.jsonl').write_text('{}\n')
            self.assertFalse(pre_episode_reset_failure(out,label))

    def test_retry_same_condition_without_repeating_valid(self):
        settings=dict(trials=[dict(trial_id='t1',seed=3,condition_order=['A','B'])])
        commands=[]
        def fake_run(command,**kwargs):
            commands.append(command)
            out=Path(command[command.index('--out')+1]);folder=out/'episode';folder.mkdir(parents=True)
            condition=command[-1]
            valid=len(commands)!=2
            row=dict(trial_id='t1',seed=3,condition=condition,infrastructure_valid=valid)
            (folder/'summary.json').write_text(json.dumps(dict(trials=[row])))
            if not valid:
                (out/'BLOCKED.txt').write_text('infrastructure_invalid')
            return SimpleNamespace(returncode=0 if valid else 1)
        with tempfile.TemporaryDirectory() as tmp, patch('run_admission_corrected_v2.subprocess.run',side_effect=fake_run), patch('run_admission_corrected_v2.verify_trace'), patch('run_admission_corrected_v2.paired_decision',return_value='CONTINUE'), patch('run_admission_corrected_v2.final_audit',return_value=dict(decision='GO')):
            run(Path(tmp),settings,[],[],None)
            self.assertEqual([command[-1] for command in commands],['A','B','B'])
            self.assertEqual(json.loads((Path(tmp)/'status.json').read_text())['state'],'COMPLETED')


if __name__=='__main__':
    unittest.main()
