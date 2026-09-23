"""无额外依赖的精确配对检验回归测试。"""
import itertools
import unittest
from scripts.analyze_corrected_ablation import signed_rank_p, mcnemar_p, holm


class StatisticsTests(unittest.TestCase):
    def test_zero_and_one_sided(self):
        self.assertEqual(signed_rank_p([0,0]),1)
        self.assertEqual(signed_rank_p([1,2,3]),.25)
        self.assertEqual(signed_rank_p([-1,-1,-1]),.25)
        self.assertEqual(signed_rank_p([1,-1]),1)

    def test_against_enumerated_ranks(self):
        for signs in itertools.product((-1,1),repeat=4):
            delta=[s*v for s,v in zip(signs,[1,2,2,4])]
            ranks=[1,2.5,2.5,4]
            observed=abs(sum(s*r for s,r in zip(signs,ranks)))
            p=sum(abs(sum(s*r for s,r in zip(sample,ranks)))>=observed
                  for sample in itertools.product((-1,1),repeat=4))/16
            self.assertEqual(signed_rank_p(delta),p)

    def test_binary_and_holm(self):
        self.assertEqual(mcnemar_p(0,0),1)
        self.assertEqual(mcnemar_p(8,0),.0078125)
        self.assertEqual(holm([.01,.04,.03]),[.03,.06,.06])
