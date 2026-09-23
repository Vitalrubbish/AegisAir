"""基础设施续跑不丢弃部分配对，也不能越过主方法失败。"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from resume_corrected_campaign import load_resume


class ResumeTests(unittest.TestCase):
    def fixture(self, root, *, complete_pair=False, failed_primary=False):
        settings = dict(trials=[dict(trial_id='t1', seed=1,
            condition_order=['AEGIS_HOCBF_V4', 'PB_CBF'])])
        rows, attempts = [], []
        methods = ['AEGIS_HOCBF_V4', 'PB_CBF'] if complete_pair else ['AEGIS_HOCBF_V4']
        for method in methods:
            label = f't1_{method}_attempt1'
            folder = root / label / 'episode'
            folder.mkdir(parents=True)
            (folder / 'trajectory.jsonl').write_text('{}\n')
            row = dict(trial_id='t1', seed=1, method=method, infrastructure_valid=True,
                collision=False, mission_complete=True,
                min_rho=-.1 if failed_primary and method=='AEGIS_HOCBF_V4' else .1,
                trajectory='trajectory.jsonl', trajectory_sha256=hashlib.sha256(b'{}\n').hexdigest())
            (folder / 'summary.json').write_text(json.dumps(dict(trials=[row])))
            rows.append(row)
            attempts.append(dict(label=label, state='VALID', summary=str(folder / 'summary.json')))
        label = 't2_PB_CBF_attempt1' if complete_pair else 't1_PB_CBF_attempt1'
        folder = root / label
        folder.mkdir()
        (folder / 'runtime_hashes.json').write_text('{}')
        attempts.append(dict(label=label, state='INFRASTRUCTURE_INVALID'))
        for attempt in attempts:
            (root / attempt['label'] / 'manifest.json').write_text(json.dumps(settings))
        for name, value in [('run_settings.json', settings), ('results.json', rows),
                            ('status.json', dict(state='PAUSED_FOR_DIAGNOSIS', attempts=attempts)),
                            ('source_hashes.json', {})]:
            (root / name).write_text(json.dumps(value))
        (root / '._infrastructure_resume_999.json').write_bytes(b'AppleDouble')

    def test_preserves_partial_pair_and_ignores_appledouble(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            before = (root / 'results.json').read_bytes()
            with patch('resume_corrected_campaign.ROOT', root):
                _, rows, attempts, completed = load_resume(root, '已排查遥测启动超时')
            self.assertEqual(completed, 0)
            self.assertEqual(len(rows), 1)
            self.assertEqual(len(attempts), 2)
            self.assertEqual(before, (root / 'results.json').read_bytes())

    def test_rejects_failed_completed_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root, complete_pair=True, failed_primary=True)
            with patch('resume_corrected_campaign.ROOT', root):
                with self.assertRaisesRegex(ValueError, '已有完整配对'):
                    load_resume(root, '基础设施已经恢复')

    def test_preflight_arm_failure_requires_no_episode(self):
        for measured in (False, True):
            with self.subTest(measured=measured), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.fixture(root)
                state = json.loads((root / 'status.json').read_text())
                state['attempts'][-1]['state'] = 'NEEDS_DIAGNOSIS'
                (root / 'status.json').write_text(json.dumps(state))
                folder = root / state['attempts'][-1]['label']
                (folder / 'BLOCKED.txt').write_text('worker exit 1')
                logs = folder / 'episode_logs'
                logs.mkdir()
                (logs / 'runner.log').write_text('PX4 did not arm cleanly before live episode\n')
                if measured:
                    episode = folder / 'episode'
                    episode.mkdir()
                    (episode / 'trajectory.jsonl').write_text('{}\n')
                with patch('resume_corrected_campaign.ROOT', root):
                    if measured:
                        with self.assertRaises(ValueError):
                            load_resume(root, '正式测量前解锁失败')
                    else:
                        _, _, attempts, _ = load_resume(root, '正式测量前解锁失败')
                        self.assertEqual(attempts[-1]['state'], 'INFRASTRUCTURE_INVALID')


if __name__ == '__main__':
    unittest.main()
