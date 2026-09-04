#!/usr/bin/env python3
"""Tests for scripts/scoring.py - the single scoring implementation.

These assert the properties the leaderboard depends on, in the order the bugs
of 2026-09-02..04 were found: the qualified set must not depend on which
models are on top, coverage must be visible, non-benchmarks must not score,
and the numbers must be reproducible.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from scoring import (MIN_COHORT_PARTICIPATION, MIN_QUALIFIED_FLOOR, drop_sparse_benchmarks,
                     score_cohort)


class E:
    def __init__(self, name, country, price_in="$1.00", price_out="$2.00", **cells):
        self.name, self.country, self.url = name, country, ""
        self.columns = {"Input$/M": price_in, "Output$/M": price_out, **{k: v for k, v in cells.items()}}


def pct(v):
    return f"{v:.1f}%"


def cohort(n=10, benches=("A", "B", "C", "D"), base=50.0, step=2.0):
    """n models; model i scores base + i*step on every benchmark (higher i = better)."""
    return [E(f"m{i}", "US" if i % 2 else "CN", **{b: pct(base + i * step) for b in benches}) for i in range(n)]


class SparseDropTests(unittest.TestCase):
    def test_benchmark_below_floor_is_dropped_and_cells_removed(self):
        ents = cohort()
        for e in ents[:MIN_COHORT_PARTICIPATION - 1]:
            e.columns["Rare"] = "99.0%"
        headers, dropped = drop_sparse_benchmarks(ents, ["A", "B", "C", "D", "Rare"], log=lambda *a: None)
        self.assertEqual(dropped, ["Rare"])
        self.assertNotIn("Rare", headers)
        self.assertTrue(all("Rare" not in e.columns for e in ents))

    def test_benchmark_at_floor_is_kept(self):
        ents = cohort()
        for e in ents[:MIN_COHORT_PARTICIPATION]:
            e.columns["Edge"] = "99.0%"
        headers, dropped = drop_sparse_benchmarks(ents, ["A", "Edge"], log=lambda *a: None)
        self.assertEqual(dropped, [])
        self.assertIn("Edge", headers)

    def test_drop_sparse_false_leaves_cells_alone(self):
        ents = cohort()
        ents[0].columns["Rare"] = "99.0%"
        score_cohort(ents, ["A", "Rare"], drop_sparse=False, log=lambda *a: None)
        self.assertIn("Rare", ents[0].columns)


class QualifiedSetTests(unittest.TestCase):
    def test_qualified_means_reported_by_half_the_cohort(self):
        ents = cohort(10)
        for e in ents[:5]:
            e.columns["Half"] = "60.0%"       # 5/10 -> qualifies
        for e in ents[:4]:
            e.columns["Less"] = "60.0%"       # 4/10 -> does not
        r = score_cohort(ents, ["A", "B", "C", "D", "Half", "Less"], drop_sparse=False, log=lambda *a: None)
        self.assertIn("Half", r.qualified_benchmarks)
        self.assertNotIn("Less", r.qualified_benchmarks)

    def test_qualified_set_does_not_depend_on_who_is_on_top(self):
        """The 2026-09-03 bug: removing two duplicate models switched HLE off
        because the set was derived from the top 10. Derived from the whole
        cohort, adding or removing a top model must not change it."""
        ents = cohort(12)
        for e in ents:
            e.columns["HLE"] = "55.0%"
        r_all = score_cohort(ents, ["A", "B", "C", "D", "HLE"], drop_sparse=False, log=lambda *a: None)
        without_best = ents[:-1]
        r_less = score_cohort(without_best, ["A", "B", "C", "D", "HLE"], drop_sparse=False, log=lambda *a: None)
        self.assertEqual(r_all.qualified_benchmarks, r_less.qualified_benchmarks)

    def test_pass1_fallback_when_too_few_qualify(self):
        ents = cohort(10, benches=("A", "B"))   # only 2 can ever qualify (< MIN_QUALIFIED_FLOOR)
        r = score_cohort(ents, ["A", "B"], drop_sparse=False, log=lambda *a: None)
        self.assertIsNone(r.qualified_benchmarks)
        self.assertEqual(r.coverage(ents[0]), (0, 0))
        self.assertGreater(r.scores_for(ents[-1])["unified"], r.scores_for(ents[0])["unified"])
        self.assertGreaterEqual(MIN_QUALIFIED_FLOOR, 3)


class ScoreShapeTests(unittest.TestCase):
    def test_avgiq_is_the_raw_benchmark_mean_and_unified_is_a_1000_point_scale(self):
        """avgIq / value come back raw; only unified is normalised (x10)."""
        ents = cohort(10)                       # model i averages 50 + 2i on every benchmark
        r = score_cohort(ents, ["A", "B", "C", "D"], drop_sparse=False, log=lambda *a: None)
        best, worst = r.scores_for(ents[-1]), r.scores_for(ents[0])
        self.assertAlmostEqual(best["avgIq"], 68.0)
        self.assertAlmostEqual(worst["avgIq"], 50.0)
        self.assertGreater(best["unified"], worst["unified"])
        self.assertAlmostEqual(best["unified"], 1000.0, delta=1.0)     # best on capability AND value
        self.assertEqual(max(r.scores_for(e)["unified"] for e in ents), best["unified"])

    def test_unified_is_90_capability_10_value_on_normalised_scales_times_ten(self):
        ents = cohort(10)
        r = score_cohort(ents, ["A", "B", "C", "D"], drop_sparse=False, log=lambda *a: None)
        for e in ents:
            s = r.scores_for(e)
            norm_iq = (s["avgIq"] - r.min_avg_iq) / (r.max_avg_iq - r.min_avg_iq) * 100
            norm_val = max(0.0, (s["value"] - r.min_value) / (r.max_value - r.min_value) * 100)
            self.assertAlmostEqual(s["unified"], (0.9 * norm_iq + 0.1 * norm_val) * 10, delta=0.5)

    def test_unpriced_model_gets_zero_value_never_negative(self):
        ents = cohort(10)
        ents[3].columns["Input$/M"] = "-"; ents[3].columns["Output$/M"] = "-"
        r = score_cohort(ents, ["A", "B", "C", "D"], drop_sparse=False, log=lambda *a: None)
        self.assertEqual(r.scores_for(ents[3])["value"], 0.0)
        for e in ents:
            self.assertGreaterEqual(r.scores_for(e)["value"], 0.0)

    def test_cheaper_model_with_equal_scores_has_higher_value(self):
        ents = cohort(10)
        cheap, dear = ents[4], ents[5]
        dear.columns.update({k: cheap.columns[k] for k in ("A", "B", "C", "D")})   # equal capability
        cheap.columns["Input$/M"], dear.columns["Input$/M"] = "$0.10", "$10.00"
        r = score_cohort(ents, ["A", "B", "C", "D"], drop_sparse=False, log=lambda *a: None)
        self.assertGreater(r.scores_for(cheap)["value"], r.scores_for(dear)["value"])

    def test_coverage_counts_only_qualified_benchmarks(self):
        ents = cohort(10)
        del ents[0].columns["A"]
        ents[0].columns["Nobody"] = "1.0%"
        r = score_cohort(ents, ["A", "B", "C", "D", "Nobody"], drop_sparse=False, log=lambda *a: None)
        self.assertEqual(r.coverage(ents[0]), (3, 4))
        self.assertEqual(r.coverage(ents[1]), (4, 4))

    def test_missing_cells_are_skipped_not_zeroed(self):
        ents = cohort(10)
        twin = E("twin", "US", **{k: ents[-1].columns[k] for k in ("A", "B", "C")})   # no D at all
        r = score_cohort(ents + [twin], ["A", "B", "C", "D"], drop_sparse=False, log=lambda *a: None)
        self.assertAlmostEqual(r.scores_for(twin)["avgIq"], r.scores_for(ents[-1])["avgIq"])

    def test_scoring_is_deterministic(self):
        a = score_cohort(cohort(), ["A", "B", "C", "D"], drop_sparse=False, log=lambda *a: None)
        b = score_cohort(cohort(), ["A", "B", "C", "D"], drop_sparse=False, log=lambda *a: None)
        for e1, e2 in zip(cohort(), cohort()):
            self.assertEqual(a.scores_for(e1), b.scores_for(e2))


if __name__ == "__main__":
    unittest.main(verbosity=2)
