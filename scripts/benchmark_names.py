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

# A trailing parenthetical qualifies a benchmark rather than naming a new one:
# "MMMU-Pro (with tools)" is MMMU-Pro under a particular harness setting.
_TRAILING_PARENTHETICAL_RE = re.compile(r"\s*\([^)]*\)\s*$")

# Variants that are not distinguished by a parenthetical still need an explicit
# alias — canonicalization cannot fuzzy-match an abbreviation to its expansion.
BENCHMARK_NAME_ALIASES: Dict[str, str] = {
    # canonicalized form -> shared canonical token
    "humanityslastexam": "hle",
    "hle": "hle",
}

# Detail pages occasionally leak non-benchmark artifacts (e.g. a "GDP.pdf"
# link label) into the flight payload. Reject anything that looks like a
# filename before it becomes a benchmark column.
_ARTIFACT_HEADER_RE = re.compile(r"\.(pdf|html?|docx?|xlsx?|csv|json)$", re.IGNORECASE)


def is_artifact_header(name: str) -> bool:
    """Whether a detail-page benchmark name is a scraped file artifact."""
    return bool(_ARTIFACT_HEADER_RE.search(name.strip()))


def canonicalize_benchmark_name(name: str) -> str:
    """Lowercased, alphanumeric-only key that collapses naming variants.

    A trailing parenthetical is dropped first, so a new qualified variant on
    llm-stats merges into its base column automatically instead of halting the
    daily run until someone hand-writes an alias. Remaining abbreviation pairs
    (e.g. "Humanity's Last Exam" / "HLE") resolve through
    BENCHMARK_NAME_ALIASES.
    """
    base = _TRAILING_PARENTHETICAL_RE.sub("", name.strip())
    canon = re.sub(r"[^a-z0-9]", "", base.lower())
    return BENCHMARK_NAME_ALIASES.get(canon, canon)
