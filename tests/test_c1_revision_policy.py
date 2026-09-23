"""比较实验不能因基线失败被整组否决。"""
import unittest
from scripts.c1_revision_policy import paired_decision


def row(method, **overrides):
    return dict(method=method, infrastructure_valid=True, collision=False,
                mission_complete=True, min_rho=.1, **overrides)


class ComparisonPolicyTests(unittest.TestCase):
    def setUp(self):
        self.rows = [row('AEGIS_HOCBF_V4'),row('AEGIS_HOCBF_V3')]
        self.methods = [r['method'] for r in self.rows]

    def test_baseline_negative_margin_continues(self):
        self.rows[1]['min_rho'] = -.012755
        self.assertEqual(paired_decision(self.rows,self.methods),'CONTINUE')

    def test_baseline_collision_and_incompletion_are_outcomes(self):
        self.rows[1].update(collision=True,mission_complete=False,min_rho=-1)
        self.assertEqual(paired_decision(self.rows,self.methods),'CONTINUE')

    def test_primary_failures_stop(self):
        for changes in ({'collision':True},{'min_rho':0},{'mission_complete':False},{'min_rho':float('nan')}):
            rows = [dict(self.rows[0],**changes),self.rows[1]]
            self.assertEqual(paired_decision(rows,self.methods),'STOP_PRIMARY_FAILURE')

    def test_infrastructure_is_not_algorithm_failure(self):
        self.rows[0]['infrastructure_valid'] = False
        self.assertEqual(paired_decision(self.rows,self.methods),'RETRY_INFRASTRUCTURE')

    def test_safety_chain_applies_to_all_methods(self):
        self.rows[1]['safety_bypass_count'] = 1
        self.assertEqual(paired_decision(self.rows,self.methods),'STOP_SAFETY_CHAIN')

    def test_complete_pair_required(self):
        with self.assertRaises(ValueError):
            paired_decision(self.rows[:1],self.methods)

    def test_baseline_constraint_failure_is_not_authority_bypass(self):
        self.rows[1]['published_command_constraint_failure_count'] = 20
        self.assertEqual(paired_decision(self.rows,self.methods),'CONTINUE')

    def test_unknown_audit_pauses_without_claiming_failure(self):
        self.rows[1]['published_command_constraint_unknown_count'] = 1
        self.assertEqual(paired_decision(self.rows,self.methods),'STOP_SAFETY_CHAIN')
