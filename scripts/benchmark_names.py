#!/usr/bin/env python3
"""Benchmark-name identity: which column headers mean the same benchmark.

llm-stats exposes some benchmarks under one name on the leaderboard table and a
qualified variant on the model detail pages — "MRCRv2" vs "MRCRv2 (8-needle)",
"MMMU-Pro" vs "MMMU-Pro (with tools)". If both land in a snapshot they become
two columns measuring one thing, which double-counts in Pass 2 scoring.

This module is the single definition of that identity, shared by the scraper
(which merges the variants) and validate_models.py (which fails the run if two
columns still collapse to the same benchmark). They previously carried separate
copies and could disagree: the scraper needed a hand-written alias for each new
variant, and until someone added one the validator would halt the daily run.
Stripping a trailing parenthetical generically retires that whole class.

Deliberately free of third-party imports so the test suite and the CI validator
can use it without installing Playwright.
"""
import re
from typing import Dict

# Naming variants are collapsed only where they are named explicitly below.
# Nothing is merged generically: two columns that look like the same benchmark
# are left alone for validate_models.py to flag, so a human decides whether
# they really measure the same thing rather than the scraper assuming it.
BENCHMARK_NAME_ALIASES: Dict[str, str] = {
    # canonicalized form -> shared canonical token
    "humanityslastexam": "hle",
    "hle": "hle",
    # MRCRv2 appears as "MRCRv2" on the leaderboard table and
    # "MRCRv2 (8-needle)" on detail pages — same benchmark, and without this
    # alias both columns land in the snapshot and can double-count in Pass 2.
    "mrcrv2": "mrcrv2",
    "mrcrv28needle": "mrcrv2",
}

# Detail pages occasionally leak non-benchmark artifacts (e.g. a "GDP.pdf"
# link label) into the flight payload. Reject anything that looks like a
# filename before it becomes a benchmark column.
_ARTIFACT_HEADER_RE = re.compile(r"\.(pdf|html?|docx?|xlsx?|csv|json)$", re.IGNORECASE)


def is_artifact_header(name: str) -> bool:
    """Whether a detail-page benchmark name is a scraped file artifact."""
    return bool(_ARTIFACT_HEADER_RE.search(name.strip()))


def canonicalize_benchmark_name(name: str) -> str:
    """Lowercased, alphanumeric-only form for fuzzy benchmark-name matching.

    Known abbreviation variants (e.g. "Humanity's Last Exam" / "HLE") are
    collapsed through BENCHMARK_NAME_ALIASES so both forms resolve to the same
    key. Unlisted variants are deliberately NOT merged.
    """
    canon = re.sub(r"[^a-z0-9]", "", name.strip().lower())
    return BENCHMARK_NAME_ALIASES.get(canon, canon)
