#!/usr/bin/env python3
"""Pick each country's published top 10 solely by Unified Score.

Benchmark coverage is descriptive and never restricts selection or breaks ties.
"""
from preconditions import preconditions
from typing import Callable, List, TypeVar

T = TypeVar('T')
TEAM_SIZE = 10


@preconditions(entries='sequence', unified='callable', team_size='positive_int')
def select_team(entries: List[T], unified: Callable[[T], float],
                team_size: int = TEAM_SIZE) -> List[T]:
    """Return the highest scores, preserving input order for tied scores."""
    return sorted(entries, key=unified, reverse=True)[:team_size]
