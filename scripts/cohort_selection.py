#!/usr/bin/env python3
"""Pick each country's published top 10 from a larger scored pool.

The cohort used to be cut to 10 per country at scrape time, so anything
removed later — a model under the minimum benchmark coverage — left a hole.
On 2026-09-04 five US models were dropped at scoring time and Team USA
published with five. The pool is now larger than ten and the cut happens
here, after enrichment, gap-filling and scoring, with complete data.

Dependency-free so the test suite can import it without Playwright.
"""
from typing import Callable, List, Tuple, TypeVar

T = TypeVar("T")

TEAM_SIZE = 10

# Share of the qualified benchmark set a model must report to be ranked,
# rounded UP. A third: on 2026-09-04 the pool's highest-scoring model (Muse
# Spark 1.3, unified 948) was excluded at 3/8 under a 50% floor. A third still
# keeps out the cases the rule exists for - 2 of 7 (the Gemini 3.8 Flash #1
# artifact), 2 of 8, 1 of 8 - because rounding up never lets 2 through until
# the set is 6 or smaller.
MIN_QUALIFIED_COVERAGE = 1 / 3


def min_coverage_for(qualified_count: int) -> int:
    """Minimum reported benchmarks to rank, for a qualified set of this size."""
    import math
    return max(1, math.ceil(qualified_count * MIN_QUALIFIED_COVERAGE))


def select_team(
    entries: List[T],
    unified: Callable[[T], float],
    coverage: Callable[[T], int],
    min_coverage: int,
    team_size: int = TEAM_SIZE,
) -> Tuple[List[T], List[T]]:
    """Return (chosen, provisional).

    `chosen` is always min(team_size, len(entries)) long. Models meeting
    min_coverage are ranked by unified score and taken first. If that yields
    fewer than team_size, the remaining slots are filled from the
    under-coverage models — best coverage first, then unified — and those
    fillers are also returned as `provisional` so the caller can flag them.
    A team never publishes short just because coverage was thin that day.
    """
    ranked = sorted(
        (e for e in entries if coverage(e) >= min_coverage),
        key=unified, reverse=True,
    )
    under = sorted(
        (e for e in entries if coverage(e) < min_coverage),
        key=lambda e: (-coverage(e), -unified(e)),
    )
    chosen = ranked[:team_size]
    provisional: List[T] = []
    if len(chosen) < team_size:
        provisional = under[: team_size - len(chosen)]
        chosen = chosen + provisional
    return chosen, provisional
