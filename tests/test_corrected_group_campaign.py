"""四机修正版不改变冻结分组、种子或有效失败规则。"""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from run_group_corrected_v2 import CONFIGS,settings_for,seeds_for,decision_for,run


class GroupCampaignTests(unittest.TestCase):
    def test_preserves_all_original_configuration(self):
        for stage,name in CONFIGS.items():
            original=json.loads((ROOT/'configs'/name).read_text())
            settings=settings_for(stage)
            for key,value in original.items():
                self.assertEqual(settings[key],value,(stage,key))
            self.assertEqual(settings['c3_group_slot']['group_order'],[[2,3],[4,5]])
        self.assertEqual(seeds_for(settings_for('calibration')),[9901])
        self.assertEqual(seeds_for(settings_for('qualification')),[9921,9922,9923,9924,9925])
        self.assertEqual(seeds_for(settings_for('sealed')),list(range(10001,10021)))

    def test_valid_failure_does_not_retry(self):
        row=dict(infrastructure_valid=True,published_command_mismatch_count=0,published_command_constraint_unknown_count=0,m4_go=False)
        self.assertEqual(decision_for(row),'STOP_GROUP_DIAGNOSIS')
        row['published_command_constraint_unknown_count']=1
        self.assertEqual(decision_for(row),'STOP_SAFETY_CHAIN')

    def test_infrastructure_retry_keeps_seed(self):
        commands=[]
        def fake_run(command,**kwargs):
            commands.append(command)
            out=Path(command[command.index('--out')+1]);folder=out/'episode';folder.mkdir(parents=True)
            (folder/'summary.json').write_text('{}')
            if len(commands)==1:
                (out/'BLOCKED.txt').write_text('infrastructure_invalid')
            return SimpleNamespace(returncode=1 if len(commands)==1 else 0)
        def verify(*args):
            return dict(seed=1,infrastructure_valid=len(commands)>1,published_command_mismatch_count=0,published_command_constraint_unknown_count=0,m4_go=True)
        with tempfile.TemporaryDirectory() as tmp, patch('run_group_corrected_v2.subprocess.run',side_effect=fake_run), patch('run_group_corrected_v2.verify_summary',side_effect=verify):
            run(Path(tmp),dict(gazebo_seed=1,protocol_id='test'),[],[],None)
            self.assertEqual(len(commands),2)
            self.assertTrue(all(command[-2:]==['--single-group-seed','1'] for command in commands))
            self.assertEqual(json.loads((Path(tmp)/'status.json').read_text())['state'],'COMPLETED')


if __name__=='__main__':
    unittest.main()
