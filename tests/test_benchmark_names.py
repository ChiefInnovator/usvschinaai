#!/usr/bin/env python3
"""Tests for benchmark-name identity (scripts/benchmark_names.py).

Two names are merged only when BENCHMARK_NAME_ALIASES says so. Anything else
that looks like a duplicate is left as two columns for validate_models.py to
flag, which halts the run so a human decides whether they really measure the
same thing. That split is deliberate — the scraper does not get to assume.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from benchmark_names import canonicalize_benchmark_name, is_artifact_header


class ExplicitAliasOnlyTests(unittest.TestCase):
    def test_listed_variant_merges(self):
        """MRCRv2 (8-needle) is named in the alias table, so it merges."""
        self.assertEqual(
            canonicalize_benchmark_name("MRCRv2 (8-needle)"),
            canonicalize_benchmark_name("MRCRv2"),
        )

    def test_unlisted_variant_is_NOT_merged(self):
        """MMMU-Pro (with tools) is not in the table, so it stays separate.

        The scraper must not silently fold an unrecognised variant into another
        column; validate_models.py flags the pair instead.
        """
        self.assertNotEqual(
            canonicalize_benchmark_name("MMMU-Pro (with tools)"),
            canonicalize_benchmark_name("MMMU-Pro"),
        )

    def test_arbitrary_future_variant_is_NOT_merged(self):
        for qualifier in ("(no tools)", "(pass@1)", "(64k context)"):
            self.assertNotEqual(
                canonicalize_benchmark_name(f"SWE-benchPro {qualifier}"),
                canonicalize_benchmark_name("SWE-benchPro"),
                qualifier,
            )

    def test_distinct_benchmarks_stay_distinct(self):
        names = ["GPQA", "BrowseComp", "MMMU-Pro", "SWE-benchPro", "Terminal-Bench2.1"]
        keys = [canonicalize_benchmark_name(n) for n in names]
        self.assertEqual(len(set(keys)), len(names))

    def test_version_variants_stay_separate(self):
        """Terminal-Bench 4.0 runs ~60 points below 2.1 — different benchmarks."""
        self.assertNotEqual(
            canonicalize_benchmark_name("Terminal-Bench2.1"),
            canonicalize_benchmark_name("Terminal-Bench4.0"),
        )
        self.assertNotEqual(
            canonicalize_benchmark_name("DeepSWE"),
            canonicalize_benchmark_name("DeepSWE1.1"),
        )


class AbbreviationAliasTests(unittest.TestCase):
    def test_hle_expansion_merges(self):
        self.assertEqual(
            canonicalize_benchmark_name("Humanity's Last Exam"),
            canonicalize_benchmark_name("HLE"),
        )


class NormalizationTests(unittest.TestCase):
    def test_punctuation_and_case_are_ignored(self):
        self.assertEqual(
            canonicalize_benchmark_name("Terminal-Bench 2.1"),
            canonicalize_benchmark_name("terminalbench2.1"),
        )

    def test_surrounding_whitespace_is_ignored(self):
        self.assertEqual(canonicalize_benchmark_name("  GPQA  "), canonicalize_benchmark_name("GPQA"))


class ArtifactHeaderTests(unittest.TestCase):
    def test_file_artifacts_are_rejected(self):
        for name in ("GDP.pdf", "results.CSV", "notes.docx", "data.json"):
            self.assertTrue(is_artifact_header(name), name)

    def test_real_benchmarks_are_not_rejected(self):
        for name in ("GPQA", "MMMU-Pro", "Terminal-Bench2.1", "SWE-benchPro"):
            self.assertFalse(is_artifact_header(name), name)


class ValidatorCollisionTests(unittest.TestCase):
    def test_qualified_variant_is_a_separate_benchmark_not_a_collision(self):
        """MMMU-Pro (with tools) measures something else — both columns stand.

        The validator must not halt the run over this pair.
        """
        from validate_models import alias_base
        self.assertNotEqual(alias_base("MMMU-Pro (with tools)"), alias_base("MMMU-Pro"))

    def test_true_spelling_collision_is_still_flagged(self):
        from validate_models import alias_base
        self.assertEqual(alias_base("MMMU Pro"), alias_base("mmmu-pro"))

    def test_validator_does_not_flag_genuinely_different_benchmarks(self):
        from validate_models import alias_base
        self.assertNotEqual(alias_base("Terminal-Bench2.1"), alias_base("Terminal-Bench4.0"))
        self.assertNotEqual(alias_base("GPQA"), alias_base("BrowseComp"))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class VersionSiblingTests(unittest.TestCase):
    """Versions stay separate columns, but we must be able to spot they are kin.

    Gap-fill filled `DeepSWE` for five models with a value exactly equal to
    their existing `DeepSWE1.1`, while every genuinely scraped pair differed.
    It was copying the sibling rather than researching the benchmark, and since
    both columns score, that double-weighted the benchmark.
    """

    def test_versions_share_a_base(self):
        from benchmark_names import benchmark_version_base
        self.assertEqual(
            benchmark_version_base("DeepSWE"), benchmark_version_base("DeepSWE1.1")
        )
        self.assertEqual(
            benchmark_version_base("Terminal-Bench2.1"),
            benchmark_version_base("Terminal-Bench4.0"),
        )

    def test_different_benchmarks_do_not_share_a_base(self):
        from benchmark_names import benchmark_version_base
        bases = [
            benchmark_version_base(n)
            for n in ("DeepSWE1.1", "SWE-benchPro", "Terminal-Bench2.1", "HLE", "OSWorld2.0")
        ]
        self.assertEqual(len(set(bases)), len(bases))

    def test_sharing_a_base_does_not_merge_the_columns(self):
        """Scoring must still treat them as two separate benchmarks."""
        self.assertNotEqual(
            canonicalize_benchmark_name("DeepSWE"),
            canonicalize_benchmark_name("DeepSWE1.1"),
        )


class SiblingVersionLockTests(unittest.TestCase):
    def test_gap_fill_skips_a_benchmark_whose_sibling_is_already_reported(self):
        try:
            from gap_fill_benchmarks import has_sibling_version_value
        except ImportError:
            self.skipTest("gap_fill_benchmarks needs requests")

        class Entry:
            def __init__(self, columns):
                self.columns = columns

        headers = ["DeepSWE", "DeepSWE1.1", "HLE"]
        has_sibling = Entry({"DeepSWE1.1": "75.4%", "HLE": "60.0%"})
        self.assertTrue(has_sibling_version_value(has_sibling, "DeepSWE", headers))
        # No sibling reported -> researching it is legitimate.
        no_sibling = Entry({"HLE": "60.0%"})
        self.assertFalse(has_sibling_version_value(no_sibling, "DeepSWE", headers))
        # An unrelated benchmark is never blocked.
        self.assertFalse(has_sibling_version_value(has_sibling, "HLE", headers))
