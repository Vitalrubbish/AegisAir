"""正式队列的范围与前置门：测试不得启动模拟器。"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from scripts.run_drones_formal_queue import JOBS

ROOT = Path(__file__).resolve().parents[1]


class FormalQueueTests(unittest.TestCase):
    def test_group_uses_own_chain_not_b2(self):
        by_name = {row[0]: row for row in JOBS}
        self.assertIsNone(by_name['09a_group_calibration'][3])
        self.assertEqual(by_name['09b_group_qualification'][3], '09a_group_calibration/RUN_COMPLETE.json')
        self.assertEqual(by_name['09c_group_sealed'][3], '09b_group_qualification/RUN_COMPLETE.json')
        self.assertFalse(any('b2_' in row[1] for row in JOBS))
        for _, name, _, _ in JOBS:
            self.assertTrue((ROOT/'configs'/name).is_file())

    def test_qualification_cannot_use_historical_go_implicitly(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)/'must_not_exist'
            result = subprocess.run([
                sys.executable,str(ROOT/'scripts/run_paper_c1_rerun.py'),
                '--family','group','--manifest',str(ROOT/'configs/c3_group_slot_4uav_qualification_v1.json'),
                '--out',str(out),
            ],capture_output=True,text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('本次前置门未通过',result.stderr)
            self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
