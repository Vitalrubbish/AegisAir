"""串行队列的检查不能把部分输出或有效负裕度误当基础设施错误。"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from run_corrected_trigger_chain import verify_completed


class ChainTests(unittest.TestCase):
    def fixture(self, root):
        trial = dict(trial_id='t1', scenario_id='s1', seed=1, condition_order=['M'])
        settings = dict(trials=[trial])
        folder = root / 's1'
        episode = folder / 't1_M_attempt1' / 'episode'
        episode.mkdir(parents=True)
        trace = b'{"min_rho": -0.1}\n'
        (episode / 'trajectory.jsonl').write_bytes(trace)
        row = dict(trial_id='t1', method='M', seed=1, min_rho=-.1,
                   infrastructure_valid=True, collision=False,
                   trajectory='trajectory.jsonl', trajectory_sha256=hashlib.sha256(trace).hexdigest())
        summary = episode / 'summary.json'
        summary.write_text(json.dumps(dict(trials=[row])))
        for base in (root, folder):
            (base / 'run_settings.json').write_text(json.dumps(settings))
            (base / 'status.json').write_text(json.dumps(dict(state='COMPLETED', attempts=[
                dict(state='VALID', label='t1_M_attempt1', summary=str(summary))])))
        (folder / 'results.json').write_text(json.dumps([row]))
        return episode

    def test_preserves_valid_negative_margin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            self.assertEqual(verify_completed(root)['conditions_verified'], 1)

    def test_rejects_modified_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            episode = self.fixture(root)
            (episode / 'trajectory.jsonl').write_text('{"min_rho": 1}\n')
            with self.assertRaisesRegex(ValueError, '哈希'):
                verify_completed(root)

    def test_rejects_partial_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            (root / 'status.json').write_text('{"state": "RUNNING"}')
            with self.assertRaisesRegex(ValueError, '未完整完成'):
                verify_completed(root)


if __name__ == '__main__':
    unittest.main()
