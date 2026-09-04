#!/usr/bin/env python3
"""The scraper and the validator must agree on what is not a benchmark.

They kept separate lists and drifted: validate_models.META_KEYS excluded
`LLM Stats`, `Latency` and `CodeArena`, but the scraper's metadata_columns did
not, so all three were scored as benchmarks. `LLM Stats` is llm-stats' own
composite of the benchmarks, so it counted every benchmark twice, and `Latency`
is in seconds where lower is better — normalised as a benchmark it rewarded the
slowest model in the cohort.
"""
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from validate_models import META_KEYS


def scraper_metadata_columns() -> set:
    """Parse metadata_columns out of scrape_country_leaderboard.

    Read from source rather than imported because it is a local inside the
    scrape function, and importing the module needs Playwright.
    """
    src = (REPO_ROOT / "scripts" / "scrape_models.py").read_text()
    block = re.search(r"metadata_columns = \{(.*?)\n    \}", src, re.S).group(1)
    return set(re.findall(r'"([^"]+)"', block))


# Columns that are not benchmark scores and must never reach the flat average.
# Both spellings of every multi-word column. The leaderboard table header is
# spaced ("Code Arena") while the models.json row key is not ("CodeArena"), and
# metadata_columns is matched against the *table header* — excluding only the
# unspaced form let Code Arena into the scored set.
NON_BENCHMARKS = [
    "LLM Stats", "LLMStats",   # llm-stats' own composite — circular
    "Latency",                 # seconds, lower is better
    "Code Arena", "CodeArena", # Elo, different scale
    "Speed", "Multimodal", "Released", "License", "Context",
]


class MetadataColumnTests(unittest.TestCase):
    def test_scraper_excludes_every_non_benchmark(self):
        cols = scraper_metadata_columns()
        missing = [c for c in NON_BENCHMARKS if c not in cols]
        self.assertEqual(
            missing, [],
            f"scraper would score these as benchmarks: {missing}",
        )

    def test_latency_is_excluded(self):
        """Regression: normalised higher-is-better, it rewarded slow models."""
        self.assertIn("Latency", scraper_metadata_columns())

    def test_multi_word_columns_excluded_in_both_spellings(self):
        """The table header is spaced; the row key is not. Both must be listed."""
        cols = scraper_metadata_columns()
        for spaced, tight in (("Code Arena", "CodeArena"), ("LLM Stats", "LLMStats")):
            self.assertIn(spaced, cols, f"{spaced!r} (table header form) not excluded")
            self.assertIn(tight, cols, f"{tight!r} (row key form) not excluded")

    def test_llmstats_is_excluded(self):
        """Regression: it is the composite OF the benchmarks — circular."""
        cols = scraper_metadata_columns()
        self.assertTrue("LLM Stats" in cols and "LLMStats" in cols)

    def test_scraper_and_validator_agree(self):
        """The drift that let all three through in the first place."""
        cols = scraper_metadata_columns()
        collapsed = {c.replace(" ", "") for c in cols}
        drifted = [
            k for k in META_KEYS
            # Row-level fields the scraper generates itself; never table headers.
            if k not in ("model", "organization", "link", "origin", "description",
                         "created", "avgIq", "value", "unified", "coverage", "provisional",
                         "_provenance", "_scoring")
            and k.replace(" ", "") not in collapsed
        ]
        self.assertEqual(
            drifted, [],
            f"validator treats these as metadata but the scraper scores them: {drifted}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
