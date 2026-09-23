"""PB 补审计必须重建前推状态，而不是用原始遥测位置代替。"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from c1_pb_audit_backfill import audit_trajectory
from swarm.ra.runtime_assurance import RuntimeAssurance
from swarm.ra.margins import RuntimeAssuranceParams
from swarm.safety import DroneSnapshot


class BackfillTests(unittest.TestCase):
    def test_backfill_matches_live_audit_with_state_propagation(self):
        config = dict(alpha=0.5, braking_accel_mps2=2.0, boundary_buffer_m=0.3)
        ra = RuntimeAssurance(sampled_data=True, sampled_data_method='pb_cbf',
            params=RuntimeAssuranceParams(degradation_dt=0.05,v_max=1.5,a_max=2.0),
            a_max=2.0, v_max=1.5, pb_alpha=0.5, pb_braking_accel=2.0,
            sampled_data_boundary_buffer_m=0.3, command_feedforward_tau_s=0.7)
        positions = {2: [-2.0,0.5,2.5], 3: [2.0,-0.5,2.5]}
        velocities = {2: [0.9,-0.2,0.0], 3: [-0.9,0.2,0.0]}
        ages = {2:0.04,3:0.07}
        snapshots = {i: DroneSnapshot(i, tuple(np.asarray(positions[i])+np.asarray(velocities[i])*ages[i]),
                                     velocity=tuple(velocities[i])) for i in positions}
        results = ra.filter(snapshots,{2:np.array([1.5,-1.5]),3:np.array([-1.5,1.5])},t=0.0,
                            aoi={(2,3):0.07})
        accelerations = {i:(np.asarray(r.safe_action)-np.asarray(velocities[i][:2]))/0.7
                         for i,r in results.items()}
        record = dict(step=0, drones={i:dict(pos=positions[i],v_actual=velocities[i],
            command_timestamp_ms=1000,measurement_timestamp_ms=1000-round(ages[i]*1000),
            solver_input_age_s=ages[i],d_safe=r.d_safe,control_authority=True,
            published_effective_acceleration=accelerations[i].tolist(),
            published_command_constraint_ok=None) for i,r in results.items()})
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'trajectory.jsonl'
            path.write_text(json.dumps(record)+'\n')
            result=audit_trajectory(path,hashlib.sha256(path.read_bytes()).hexdigest(),config)
            self.assertEqual(result['original_unknown_count'],2)
            self.assertAlmostEqual(result['samples'][0]['minimum_slack'],
                                   ra.audit_published_accelerations(accelerations)[1],places=12)
            self.assertAlmostEqual(result['samples'][0]['static_distance'],
                                   ra._published_audit_context['safe_distance'][(2,3)],places=12)
            with self.assertRaises(ValueError):
                audit_trajectory(path,'wrong-hash',config)
