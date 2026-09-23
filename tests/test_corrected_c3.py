"""C3 部分基础设施失败时保留另一条件，不重跑完整有效配对。"""
import json
import hashlib
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from run_c3_corrected_v2 import settings_for,paired_decision,run,audit_trace
from run_paper_c1_rerun import prepare_worker_manifest


def row(condition,valid=True):
    return dict(trial_id='c3test',seed=1,condition=condition,infrastructure_valid=valid,
        collision=False,min_rho=.1,critical_reached=condition=='R1',
        recovery_step=31 if condition=='R1' else None,
        counters=dict(mission_changes=1,plans_committed=1 if condition=='R1' else 0),
        published_command_mismatch_count=0,published_command_constraint_unknown_count=0)


class C3Tests(unittest.TestCase):
    def test_trace_checks_revoked_vehicle_after_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);path=out/'trajectory.jsonl'
            records=[dict(step=29,min_rho=.2,drones={'2':dict(ra_bypass=False,control_authority=True,published_velocity=[1,0])}),
                     dict(step=30,min_rho=.1,drones={'2':dict(ra_bypass=False,control_authority=False,published_velocity=[0,0])})]
            raw='\n'.join(json.dumps(record) for record in records).encode()
            path.write_bytes(raw)
            record=dict(trajectory=path.name,trajectory_sha256=hashlib.sha256(raw).hexdigest(),min_rho=.1)
            audit=audit_trace(out/'summary.json',record,dict(change_step=30,failed_drone=2))
            self.assertEqual(audit['revoked_authority_failures'],0)
            records[1]['drones']['2']['control_authority']=True
            raw='\n'.join(json.dumps(record) for record in records).encode();path.write_bytes(raw)
            record['trajectory_sha256']=hashlib.sha256(raw).hexdigest()
            self.assertEqual(audit_trace(out/'summary.json',record,dict(change_step=30,failed_drone=2))['revoked_authority_failures'],1)

    def test_worker_reads_selected_condition_without_overwriting_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)
            source=out/'original.json'
            original=dict(trials=[dict(trial_id='c3test',condition_order=['R0','R1'])])
            source.write_text(json.dumps(original))
            selected=dict(trials=[dict(trial_id='c3test',condition_order=['R1'])])
            worker=prepare_worker_manifest(source,out,selected,'c3','R1')
            self.assertEqual(json.loads(worker.read_text()),selected)
            self.assertEqual(json.loads(source.read_text()),original)
            self.assertEqual(prepare_worker_manifest(source,out,original,'c3',None),source.resolve())

    def test_frozen_conditions_preserved(self):
        original=json.loads((ROOT/'configs/c3_closed_loop_v3_hocbf_v4_validation_v1.json').read_text())
        revised=settings_for()
        for key in original:
            if key!='phase':
                self.assertEqual(original[key],revised[key],key)

    def test_original_gate_and_chain_check(self):
        rows=[row('R0'),row('R1')]
        audits=[dict(safety_bypass_count=0,revoked_authority_failures=0)]*2
        self.assertEqual(paired_decision(rows,audits,30),'CONTINUE')
        rows[1]['critical_reached']=False
        self.assertEqual(paired_decision(rows,audits,30),'STOP_C3_MECHANISM_DIAGNOSIS')
        audits=[dict(safety_bypass_count=0,revoked_authority_failures=1)]*2
        self.assertEqual(paired_decision(rows,audits,30),'STOP_SAFETY_CHAIN')

    def test_retry_only_invalid_condition(self):
        settings=dict(trials=[dict(trial_id='c3test',seed=1,condition_order=['R0','R1'])],change_step=30)
        commands=[]
        def fake_run(command,**kwargs):
            commands.append(command)
            out=Path(command[command.index('--out')+1])
            folder=out/'episode';folder.mkdir(parents=True)
            rows=[row('R0'),row('R1',False)] if len(commands)==1 else [row('R1')]
            (folder/'summary.json').write_text(json.dumps(dict(trials=rows)))
            if len(commands)==1:
                (out/'BLOCKED.txt').write_text('infrastructure_invalid')
            return SimpleNamespace(returncode=1 if len(commands)==1 else 0)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('run_c3_corrected_v2.subprocess.run',side_effect=fake_run), patch(
                'run_c3_corrected_v2.audit_trace',return_value=dict(safety_bypass_count=0,revoked_authority_failures=0)):
                run(root,settings,[],[],{}, {})
            self.assertEqual(len(commands),2)
            self.assertNotIn('--single-method',commands[0])
            self.assertEqual(commands[1][-2:],['--single-method','R1'])
            result=json.loads((root/'results.json').read_text())
            self.assertEqual([item['condition'] for item in result],['R0','R1'])
            self.assertEqual(json.loads((root/'status.json').read_text())['state'],'COMPLETED')


if __name__=='__main__':
    unittest.main()
