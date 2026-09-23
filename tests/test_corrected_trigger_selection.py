"""阈值只按已声明顺序选择；不完整开发数据不得生成赢家。"""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from freeze_corrected_trigger_test import score,choose,THRESHOLDS
from run_corrected_trigger_comparison import settings_for


class TriggerSelectionTests(unittest.TestCase):
    def row(self,**changes):
        return dict(infrastructure_valid=True,collision=False,mission_complete=True,
                    min_rho=.1,mean_control_effort=.2,**changes)

    def test_collision_precedes_effort(self):
        safe=self.row();unsafe=self.row();unsafe.update(collision=True,mean_control_effort=0)
        self.assertLess(score([safe],5),score([unsafe],1))

    def test_all_candidates_tie_uses_lowest_threshold(self):
        campaigns=[]
        for grid in (1,2,3):
            rows=[dict(self.row(),method=method,seed=21001+i) for method in THRESHOLDS for i in range(6)]
            campaigns.append((settings_for(grid),rows))
        selected=choose(campaigns)
        self.assertEqual(selected['AEGIS_HOCBF_V4_DISTANCE']['best']['threshold'],3)
        self.assertEqual(selected['AEGIS_HOCBF_V4_TTC']['best']['threshold'],.5)
        campaigns[2][1].pop()
        with self.assertRaises(ValueError):
            choose(campaigns)

    def test_invalid_trial_not_scored(self):
        row=self.row();row['infrastructure_valid']=False
        with self.assertRaises(ValueError):
            score([row],1)


if __name__=='__main__':
    unittest.main()
