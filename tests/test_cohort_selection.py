"""Selection must never exclude or demote a model based on benchmark count."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from cohort_selection import select_team


def model(name, score, coverage):
    return SimpleNamespace(name=name, score=score, coverage=coverage)


class SelectTeamTests(unittest.TestCase):
    def test_sparse_high_scorer_is_selected_first(self):
        pool=[model('sparse',999,1)]+[model(str(i),100-i,12) for i in range(12)]
        chosen=select_team(pool,lambda m:m.score)
        self.assertEqual(len(chosen),10)
        self.assertEqual(chosen[0].name,'sparse')

    def test_zero_coverage_is_not_a_filter(self):
        pool=[model(str(i),i,0) for i in range(12)]
        self.assertEqual([m.score for m in select_team(pool,lambda m:m.score)],list(range(11,1,-1)))

    def test_coverage_does_not_break_ties(self):
        pool=[model('first',50,0),model('second',50,12)]
        self.assertEqual(select_team(pool,lambda m:m.score,1)[0].name,'first')

    def test_short_or_empty_pool(self):
        pool=[model('low',1,12),model('high',2,0)]
        self.assertEqual([m.name for m in select_team(pool,lambda m:m.score)],['high','low'])
        self.assertEqual(select_team([],lambda m:m.score),[])


if __name__=='__main__': unittest.main()
