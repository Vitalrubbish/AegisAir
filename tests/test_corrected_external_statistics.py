"""修正版外部比较：有效配对、补审计与原始结果保护。"""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from analyze_corrected_external import main


class ExternalStatisticsTests(unittest.TestCase):
    def fixture(self, root):
        methods = ['AEGIS_HOCBF_V4', 'AEGIS_HOCBF_V4_REACTIVE',
                   'AEGIS_HOCBF_V3', 'PB_CBF', 'PCBF_HUANG_ECC2025']
        trials, rows = [], []
        for i in range(10):
            trial = f't{i}'
            trials.append(dict(trial_id=trial, seed=i, condition_order=methods))
            for method in methods:
                rho = .2 if method == methods[0] else -.1
                folder = root / f'{trial}_{method}_attempt1' / 'episode'
                folder.mkdir(parents=True)
                path = folder / 'trajectory.jsonl'
                path.write_text(json.dumps(dict(min_rho=rho)) + '\n')
                rows.append(dict(trial_id=trial, seed=i, method=method,
                    infrastructure_valid=True, trajectory=path.name,
                    trajectory_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    min_rho=rho, mission_complete=True, collision=False,
                    mean_control_effort=.1, path_length_m=10, cbf_events=2,
                    qp_infeasible_steps=0, ra_solve_latency_summary_ms=dict(p99=1),
                    published_command_constraint_unknown_count=0,
                    published_command_constraint_failure_count=0))
        rows[4]['published_command_constraint_unknown_count'] = 2
        for row in rows:
            summary = root / f"{row['trial_id']}_{row['method']}_attempt1" / 'episode' / 'summary.json'
            summary.write_text(json.dumps(dict(trials=[row])))
        correction = dict(trial_id='t0', method=methods[-1],
            trajectory_sha256=rows[4]['trajectory_sha256'],
            corrected_unknown=0, corrected_failure=2, proofs=[])
        for name, value in [('status.json', dict(state='COMPLETED')),
                            ('run_settings.json', dict(protocol_id='test', trials=trials,
                                                       methods=dict.fromkeys(methods, {}))),
                            ('results.json', rows),
                            ('pcbf_audit_resume_1.json', dict(corrections=[correction]))]:
            (root / name).write_text(json.dumps(value))

    def test_ten_pairs_and_read_only_correction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            original = (root / 'results.json').read_bytes()
            out = root / 'analysis.json'
            with patch.object(sys, 'argv', ['analysis', '--root', str(root), '--out', str(out)]), contextlib.redirect_stdout(io.StringIO()):
                main()
            report = json.loads(out.read_text())
            self.assertEqual(report['conditions_verified'], 50)
            self.assertEqual(report['paired_trials'], 10)
            for comparison in report['paired']:
                self.assertEqual(comparison['pairs'], 10)
                metric = comparison['metrics']['min_rho']
                self.assertAlmostEqual(metric['mean_aegis_minus_baseline'], .3)
                self.assertAlmostEqual(metric['paired_randomization_p'], 2 / 1024)
            self.assertEqual(report['safety_counts']['PCBF_HUANG_ECC2025']['published_constraint_failures'], 2)
            self.assertEqual(original, (root / 'results.json').read_bytes())

    def test_incomplete_campaign_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'status.json').write_text(json.dumps(dict(state='RUNNING')))
            with patch.object(sys, 'argv', ['analysis', '--root', str(root), '--out', str(root / 'analysis.json')]):
                with self.assertRaisesRegex(ValueError, '未完成'):
                    main()

    def test_summary_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            summary = root / 't0_AEGIS_HOCBF_V4_attempt1' / 'episode' / 'summary.json'
            value = json.loads(summary.read_text())
            value['trials'][0]['min_rho'] = 99
            summary.write_text(json.dumps(value))
            with patch.object(sys, 'argv', ['analysis', '--root', str(root), '--out', str(root / 'analysis.json')]):
                with self.assertRaisesRegex(ValueError, '原摘要不一致'):
                    main()


if __name__ == '__main__':
    unittest.main()
