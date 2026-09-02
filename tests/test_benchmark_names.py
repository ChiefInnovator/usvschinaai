#!/usr/bin/env python3
"""Tests for benchmark-name identity (scripts/benchmark_names.py).

Written after a production incident: llm-stats began exposing "MMMU-Pro (with
tools)" on detail pages, the scraper added it as a second column beside
"MMMU-Pro", and validate_models.py halted the daily run to stop the two
double-counting in Pass 2 scoring. The site went a full cycle without fresh
data. The same thing had happened before with "MRCRv2 (8-needle)".
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from benchmark_names import canonicalize_benchmark_name, is_artifact_header


class TrailingParentheticalTests(unittest.TestCase):
    def test_mmmu_pro_with_tools_merges(self):
        """The exact collision that broke the 2026-09-02 scrape."""
        self.assertEqual(
            canonicalize_benchmark_name("MMMU-Pro (with tools)"),
            canonicalize_benchmark_name("MMMU-Pro"),
        )

    def test_mrcrv2_8_needle_merges(self):
        """The earlier instance, previously handled by a hand-written alias."""
        self.assertEqual(
            canonicalize_benchmark_name("MRCRv2 (8-needle)"),
            canonicalize_benchmark_name("MRCRv2"),
        )

    def test_arbitrary_future_variant_merges(self):
        """A qualifier we have never seen must not need a code change."""
        for qualifier in ("(no tools)", "(pass@1)", "(64k context)", "(v2 harness)"):
            self.assertEqual(
                canonicalize_benchmark_name(f"SWE-benchPro {qualifier}"),
                canonicalize_benchmark_name("SWE-benchPro"),
                qualifier,
            )

    def test_only_trailing_parentheticals_are_stripped(self):
        """A leading or embedded parenthetical is part of the name."""
        self.assertNotEqual(
            canonicalize_benchmark_name("GPQA (Diamond) Extended"),
            canonicalize_benchmark_name("GPQA"),
        )

    def test_distinct_benchmarks_stay_distinct(self):
        names = ["GPQA", "BrowseComp", "MMMU-Pro", "SWE-benchPro", "Terminal-Bench2.1"]
        keys = [canonicalize_benchmark_name(n) for n in names]
        self.assertEqual(len(set(keys)), len(names))


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


class ScraperValidatorAgreementTests(unittest.TestCase):
    def test_validator_uses_the_same_identity_as_the_scraper(self):
        """Separate copies previously drifted and halted the daily run."""
        from validate_models import alias_base
        for name in ("MMMU-Pro (with tools)", "MRCRv2 (8-needle)", "HLE", "GPQA"):
            self.assertEqual(alias_base(name), canonicalize_benchmark_name(name), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
