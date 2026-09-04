#!/usr/bin/env python3
"""Tests for picking each country's published top 10 from the scored pool."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from cohort_selection import min_coverage_for, select_team


class M:
    def __init__(self, name, unified, coverage):
        self.name, self.unified, self.coverage = name, unified, coverage
    def __repr__(self):
        return self.name


U = lambda m: m.unified
C = lambda m: m.coverage


class SelectTeamTests(unittest.TestCase):
    def test_takes_top_ten_ranked_when_enough_meet_coverage(self):
        pool = [M(f"m{i}", 100 - i, 5) for i in range(15)]
        chosen, prov = select_team(pool, U, C, min_coverage=4)
        self.assertEqual([m.name for m in chosen], [f"m{i}" for i in range(10)])
        self.assertEqual(prov, [])

    def test_under_coverage_models_are_not_ranked_ahead_of_measured_ones(self):
        pool = [M("sparse-high", 999, 1)] + [M(f"m{i}", 100 - i, 5) for i in range(10)]
        chosen, prov = select_team(pool, U, C, min_coverage=4)
        self.assertNotIn("sparse-high", [m.name for m in chosen])

    def test_team_is_never_short(self):
        """2026-09-04: five US models cut for coverage, team published with 5."""
        measured = [M(f"ok{i}", 100 - i, 5) for i in range(5)]
        sparse = [M(f"sp{i}", 50 - i, 3 - (i % 3)) for i in range(6)]
        chosen, prov = select_team(measured + sparse, U, C, min_coverage=4)
        self.assertEqual(len(chosen), 10)
        self.assertEqual(len(prov), 5)
        self.assertTrue(all(m in chosen for m in measured))

    def test_fillers_are_best_coverage_first(self):
        sparse = [M("cov1", 90, 1), M("cov3", 10, 3), M("cov2", 50, 2)]
        chosen, prov = select_team(sparse, U, C, min_coverage=4, team_size=2)
        self.assertEqual([m.name for m in prov], ["cov3", "cov2"])

    def test_pool_smaller_than_team_returns_everything(self):
        pool = [M("a", 1, 5), M("b", 2, 0)]
        chosen, prov = select_team(pool, U, C, min_coverage=4)
        self.assertEqual(len(chosen), 2)
        self.assertEqual([m.name for m in prov], ["b"])

    def test_zero_min_coverage_is_plain_top_n(self):
        pool = [M(f"m{i}", i, 0) for i in range(12)]
        chosen, prov = select_team(pool, U, C, min_coverage=0)
        self.assertEqual([m.name for m in chosen], [f"m{i}" for i in range(11, 1, -1)])
        self.assertEqual(prov, [])


class MinCoverageTests(unittest.TestCase):
    def test_a_third_rounded_up(self):
        # 2026-09-04: Muse Spark 1.3 at 3/8 must rank; 2/7 and 2/8 must not.
        self.assertEqual(min_coverage_for(8), 3)
        self.assertEqual(min_coverage_for(7), 3)
        self.assertEqual(min_coverage_for(9), 3)
        self.assertEqual(min_coverage_for(10), 4)
        self.assertEqual(min_coverage_for(12), 4)

    def test_two_of_seven_is_still_excluded(self):
        """The Gemini 3.8 Flash #1-on-two-benchmarks artifact stays out."""
        self.assertGreater(min_coverage_for(7), 2)

    def test_never_below_one(self):
        self.assertEqual(min_coverage_for(0), 1)
        self.assertEqual(min_coverage_for(1), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
