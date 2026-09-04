#!/usr/bin/env python3
"""Scoring for the leaderboard - the single implementation.

Everything that turns a cohort's raw benchmark cells into avgIq / value /
unified lives here and nowhere else. scrape_models.py imports it for the
daily run; backfill_gap_fill.py imports it to re-score history after filling
cells. It has no third-party dependencies so tests and the backfill can use
it without Playwright.

The helper functions below were moved out of scrape_models.py verbatim on
2026-09-04. score_cohort() wraps the Pass 1 / Pass 2 sequence that used to
be inline in run_scraper():

  1. drop benchmarks reported by fewer than MIN_COHORT_PARTICIPATION models
  2. participation counts and per-benchmark min/max over the cohort
  3. Pass 1: participation-weighted average, and its cohort-wide bounds
  4. qualified set: benchmarks reported by >= QUALIFIED_FRACTION of the
     WHOLE cohort (never derived from the top 10 - see the 2026-09-03 notes
     in scrape_models.py for why)
  5. Pass 2: flat average over the qualified set, with its own bounds; falls
     back to Pass 1 if fewer than MIN_QUALIFIED_FLOOR benchmarks qualify
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

# Placeholders that mean "this cell is missing." llm-stats uses a typographic
# em-dash (U+2014) and occasionally an en-dash (U+2013) for un-reported benchmarks,
# not the ASCII hyphen-minus. Missing that distinction silently poisons averages
# because parse_to_number coerces em-dash to 0.0.
MISSING_VALUE_MARKERS = {"", "-", "\u2013", "\u2014", "n/a", "N/A", "null", "None"}


# Explicit (min, max) ranges for benchmarks whose scale isn't already 0–100. Used
# to normalize non-percentage benchmarks without amplifying cohort-range artifacts.
# Percentage benchmarks (values ending in "%") don't need an entry here — they're
# auto-detected and treated as (0, 100). Only add a benchmark when you actually
# know its documented range.
BENCHMARK_KNOWN_RANGES: Dict[str, Tuple[float, float]] = {
    # CodeArena = Chatbot Arena / LMArena coding Elo. Starting Elo is 1000 per
    # LMSYS methodology; top frontier models sit around 2600-2700 as of
    # Aug 2026 (the old 2000 ceiling was exceeded, which pushed normalized
    # scores past 100 — caught by validate_models.py). Normalized values are
    # additionally clamped to [0, 100] in calculate_derived_scores so future
    # ceiling drift degrades gracefully instead of amplifying.
    "CodeArena": (1000.0, 2800.0),
}


def parse_to_number(value: str) -> float:
    """Convert raw string to number for calculations. Non-numeric → 0."""
    if not value or not isinstance(value, str):
        return 0.0
    
    cleaned = value.replace("%", "").replace(",", "").replace("$", "").strip()

    # Handle common placeholders
    if cleaned in MISSING_VALUE_MARKERS:
        return 0.0
    
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def entry_has_pricing(entry: "LeaderboardEntry") -> bool:
    """Whether a model has public pricing (input + output cost > 0).

    Unpriced models get Value = 0 by construction; including that 0 in the
    Value min/max cohort would make "no public pricing" indistinguishable from
    "worst value for money" and drag the normalization floor down for everyone
    else. They are excluded from the bounds and clamp to 0 instead.
    """
    cost_in = parse_to_number(entry.columns.get("Input$/M") or entry.columns.get("Input $/M", "0"))
    cost_out = parse_to_number(entry.columns.get("Output$/M") or entry.columns.get("Output $/M", "0"))
    return (cost_in + cost_out) > 0


def resolve_benchmark_range(
    benchmark_name: str,
    entries: List["LeaderboardEntry"],
) -> Optional[Tuple[float, float]]:
    """Determine the (min, max) range to normalize a benchmark against.

    Precedence:
      1. An explicit entry in BENCHMARK_KNOWN_RANGES (e.g. CodeArena → 1000-2000).
      2. Auto-detect percentage benchmarks: if every non-missing cell ends in "%",
         the range is (0, 100). No cohort-dependence, no amplification artifact.
      3. Fall back to the cohort's min/max for benchmarks with unknown scale.

    Returns None if no model in ``entries`` has a value for this benchmark.
    """
    if benchmark_name in BENCHMARK_KNOWN_RANGES:
        return BENCHMARK_KNOWN_RANGES[benchmark_name]

    present = [
        str(e.columns.get(benchmark_name, "")).strip()
        for e in entries
        if e.columns.get(benchmark_name, "") not in MISSING_VALUE_MARKERS
    ]
    if not present:
        return None

    if all(v.endswith("%") for v in present):
        return (0.0, 100.0)

    numeric = [parse_to_number(v) for v in present]
    return (min(numeric), max(numeric))


def calculate_derived_scores(
    entry: LeaderboardEntry,
    benchmark_headers: List[str],
    participation: Optional[Dict[str, int]] = None,
    max_participation: Optional[int] = None,
    min_avg_iq: Optional[float] = None,
    max_avg_iq: Optional[float] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    benchmark_min_max: Optional[Dict[str, tuple]] = None,
    qualified_benchmarks: Optional[set] = None,
) -> Dict[str, float]:
    """Calculate total, avgIq, value, unified from raw columns.

    Two-pass semantics:
    - Pass 1 (default, qualified_benchmarks is None): participation-weighted average
      across every benchmark in benchmark_headers, skipping single-participant ones.
    - Pass 2 (qualified_benchmarks is set): flat (unweighted) average, restricted to
      benchmarks in that set. Pass 2 is used after Pass 1 picks the Initial Top 10
      and we know which benchmarks have enough coverage to compare apples-to-apples.
    """
    if participation is None:
        participation = {}
    if not max_participation or max_participation <= 0:
        max_participation = max(participation.values(), default=1)
    if max_participation <= 0:
        max_participation = 1
    if benchmark_min_max is None:
        benchmark_min_max = {}

    pass_two = qualified_benchmarks is not None

    total_weighted = 0.0
    weight_sum = 0.0
    for b in benchmark_headers:
        raw_val = entry.columns.get(b, "")
        # Skip missing/placeholder cells
        if raw_val in MISSING_VALUE_MARKERS:
            continue

        if pass_two:
            # Pass 2: only qualified benchmarks count, and each contributes equally.
            if b not in qualified_benchmarks:
                continue
            weight = 1.0
        else:
            # Pass 1: skip benchmarks with a single participant across the cohort.
            part = participation.get(b, 0) if participation else 0
            if part <= 1:
                continue
            weight = (part / max_participation) if max_participation else 1.0

        score = parse_to_number(raw_val)

        # Normalize benchmark score to 0-100 if min/max available. Clamp so a
        # fixed known range whose ceiling has drifted (e.g. CodeArena Elo
        # passing the old 2000 cap) can't push a score past 100.
        if b in benchmark_min_max:
            min_b, max_b = benchmark_min_max[b]
            if max_b > min_b:
                score = max(0.0, min(100.0, ((score - min_b) / (max_b - min_b)) * 100))

        total_weighted += score * weight
        weight_sum += weight
    
    avg_iq = total_weighted / weight_sum if weight_sum > 0 else 0.0
    
    # Value (avgIq / total cost: input + output)
    # Try both formats for backwards compatibility
    cost_in = parse_to_number(entry.columns.get("Input$/M") or entry.columns.get("Input $/M", "0"))
    cost_out = parse_to_number(entry.columns.get("Output$/M") or entry.columns.get("Output $/M", "0"))
    total_cost = cost_in + cost_out
    value = avg_iq / total_cost if total_cost > 0 else 0.0
    
    # Normalize to 0-100 if bounds provided
    if min_avg_iq is not None and max_avg_iq is not None and max_avg_iq > min_avg_iq:
        # Clamp to [0, 100]: a no-op when the bounds come from this cohort, but
        # a re-score against a snapshot's stored bounds can see a filled cell
        # push avgIq past them.
        norm_avg_iq = min(100.0, max(0.0, ((avg_iq - min_avg_iq) / (max_avg_iq - min_avg_iq)) * 100))
    else:
        norm_avg_iq = avg_iq
    
    if min_value is not None and max_value is not None and max_value > min_value:
        # Clamp at 0: unpriced models (value 0) are excluded from the min/max
        # cohort, so their raw value can sit below min_value. Without the clamp
        # they'd get a negative Value contribution instead of simply zero.
        # Clamp at 100 for the same reason as avgIq above (stored bounds).
        norm_value = min(100.0, max(0.0, ((value - min_value) / (max_value - min_value)) * 100))
    else:
        norm_value = value
    
    # Unified (90% normalized capability, 10% normalized cost efficiency)
    unified = norm_avg_iq * 0.9 + norm_value * 0.1
    # Scale final Unified by 10 as requested
    unified *= 10
    
    return {
        "avgIq": round(avg_iq, 2),
        "value": round(value, 2),
        "unified": round(unified, 2)
    }


def build_benchmark_participation(entries: List[LeaderboardEntry], benchmark_headers: List[str]) -> Tuple[Dict[str, int], int]:
    """Count participation per benchmark and return counts with max participation."""
    counts: Dict[str, int] = {b: 0 for b in benchmark_headers}
    for entry in entries:
        for b in benchmark_headers:
            raw_val = entry.columns.get(b, "")
            if raw_val not in MISSING_VALUE_MARKERS:
                counts[b] += 1
    max_participation = max(counts.values(), default=1)
    if max_participation <= 0:
        max_participation = 1
    return counts, max_participation



MIN_COHORT_PARTICIPATION = 4
QUALIFIED_FRACTION = 0.5
MIN_QUALIFIED_FLOOR = 3


@dataclass
class ScoringResult:
    """Everything build_history_entry / calculate_derived_scores need."""
    benchmark_headers: List[str]
    dropped_sparse: List[str]
    participation: Dict[str, int]
    max_participation: int
    min_avg_iq: float
    max_avg_iq: float
    min_value: float
    max_value: float
    benchmark_min_max: Dict[str, tuple]
    qualified_benchmarks: Optional[set]      # None => Pass 1 fallback
    qualified_min_reports: int

    def scores_for(self, entry: Any) -> Dict[str, float]:
        return calculate_derived_scores(
            entry, self.benchmark_headers, self.participation, self.max_participation,
            self.min_avg_iq, self.max_avg_iq, self.min_value, self.max_value,
            benchmark_min_max=self.benchmark_min_max, qualified_benchmarks=self.qualified_benchmarks,
        )

    def coverage(self, entry: Any) -> Tuple[int, int]:
        """(reported, qualified) for this entry; (0, 0) under Pass 1 fallback."""
        if not self.qualified_benchmarks:
            return (0, 0)
        n = sum(1 for b in self.qualified_benchmarks if entry.columns.get(b, "") not in MISSING_VALUE_MARKERS)
        return (n, len(self.qualified_benchmarks))

    def to_snapshot(self) -> Dict[str, Any]:
        """The parameters a later re-score needs to reproduce these numbers
        exactly: the qualified set and every normalisation bound.

        The daily run scores a pool (15 per country) and publishes the top 10
        per country, so the published rows alone cannot recover the scale they
        were normalised against. Stored on the history snapshot as `scoring`;
        `score_cohort(..., fixed=block)` consumes it.
        """
        return {
            "version": 2,
            "qualified": sorted(self.qualified_benchmarks) if self.qualified_benchmarks else None,
            "qualifiedMinReports": self.qualified_min_reports,
            "bounds": {"minAvgIq": self.min_avg_iq, "maxAvgIq": self.max_avg_iq,
                       "minValue": self.min_value, "maxValue": self.max_value},
            "benchmarkRanges": {b: [lo, hi] for b, (lo, hi) in sorted(self.benchmark_min_max.items())},
        }


def _fixed_result(benchmark_headers: List[str], participation: Dict[str, int], max_participation: int,
                  fixed: Dict[str, Any]) -> ScoringResult:
    """A ScoringResult whose qualified set and bounds come from a stored
    `to_snapshot()` block rather than from the entries being scored."""
    bounds = fixed.get("bounds") or {}
    ranges = {b: (float(lo), float(hi)) for b, (lo, hi) in (fixed.get("benchmarkRanges") or {}).items()}
    qualified = set(fixed["qualified"]) if fixed.get("qualified") else None
    return ScoringResult(list(benchmark_headers), [], participation, max_participation,
                         float(bounds.get("minAvgIq", 0.0)), float(bounds.get("maxAvgIq", 1.0)),
                         float(bounds.get("minValue", 0.0)), float(bounds.get("maxValue", 1.0)),
                         ranges, qualified, int(fixed.get("qualifiedMinReports", 0)))


def _is_reported(entry: Any, b: str) -> bool:
    return entry.columns.get(b, "") not in MISSING_VALUE_MARKERS


def drop_sparse_benchmarks(entries: List[Any], benchmark_headers: List[str], log=print) -> Tuple[List[str], List[str]]:
    """Remove benchmarks reported by fewer than MIN_COHORT_PARTICIPATION models.

    Returns (remaining_headers, dropped). Pops the cells from every entry so a
    dropped benchmark never reaches models.json. The daily run calls this
    BEFORE the gap-filling pass, then score_cohort(..., drop_sparse=False).
    """
    pre_counts, _ = build_benchmark_participation(entries, benchmark_headers)
    dropped = [b for b in benchmark_headers if pre_counts.get(b, 0) < MIN_COHORT_PARTICIPATION]
    if dropped:
        log(f"\nDropping {len(dropped)} sparse benchmarks "
            f"(< {MIN_COHORT_PARTICIPATION} of {len(entries)} models reporting):")
        for b in sorted(dropped):
            log(f"  - {b}  ({pre_counts.get(b, 0)}/{len(entries)})")
        sparse = set(dropped)
        for e in entries:
            for b in dropped:
                e.columns.pop(b, None)
        return [b for b in benchmark_headers if b not in sparse], dropped
    return list(benchmark_headers), []


def score_cohort(entries: List[Any], benchmark_headers: List[str], *, drop_sparse: bool = True,
                 log=print, fixed: Optional[Dict[str, Any]] = None) -> ScoringResult:
    """Score a cohort. With drop_sparse (the default), sparse benchmarks are
    removed first; the daily run passes False because it drops them itself
    before gap-filling.

    `fixed` is a ScoringResult.to_snapshot() block. When given, the qualified
    set and the normalisation bounds are taken from it instead of being
    derived from `entries`, so a snapshot's published rows re-score on the
    scale of the pool they were originally normalised against."""
    benchmark_headers = list(benchmark_headers)
    dropped: List[str] = []
    if drop_sparse:
        benchmark_headers, dropped = drop_sparse_benchmarks(entries, benchmark_headers, log)

    participation, max_participation = build_benchmark_participation(entries, benchmark_headers)
    if fixed is not None:
        return _fixed_result(benchmark_headers, participation, max_participation, fixed)

    benchmark_min_max: Dict[str, tuple] = {}
    for b in benchmark_headers:
        if participation.get(b, 0) <= 1:
            continue
        values = [parse_to_number(e.columns.get(b, "")) for e in entries
                  if e.columns.get(b, "") and e.columns.get(b, "") not in MISSING_VALUE_MARKERS]
        if values:
            benchmark_min_max[b] = (min(values), max(values))

    iqs, vals = [], []
    for e in entries:
        s = calculate_derived_scores(e, benchmark_headers, participation, max_participation,
                                     benchmark_min_max=benchmark_min_max)
        iqs.append(s["avgIq"]); vals.append(s["value"])
    min_avg_iq, max_avg_iq = (min(iqs), max(iqs)) if iqs else (0, 1)
    min_value, max_value = (min(vals), max(vals)) if vals else (0, 1)

    qualified_min = max(2, round(len(entries) * QUALIFIED_FRACTION))
    qualified = {b for b in benchmark_headers if sum(_is_reported(e, b) for e in entries) >= qualified_min}

    if len(qualified) < MIN_QUALIFIED_FLOOR:
        log(f"\nWARNING: only {len(qualified)} benchmarks qualified (need >= {MIN_QUALIFIED_FLOOR}). "
            f"Falling back to Pass 1 scoring.")
        return ScoringResult(benchmark_headers, dropped, participation, max_participation,
                             min_avg_iq, max_avg_iq, min_value, max_value, benchmark_min_max, None, qualified_min)

    bmm2: Dict[str, tuple] = {}
    for b in qualified:
        rng = resolve_benchmark_range(b, entries)
        if rng is not None:
            bmm2[b] = rng
    iqs2, vals2 = [], []
    for e in entries:
        s = calculate_derived_scores(e, benchmark_headers, benchmark_min_max=bmm2, qualified_benchmarks=qualified)
        iqs2.append(s["avgIq"])
        if entry_has_pricing(e):                # unpriced models are excluded from the Value bounds
            vals2.append(s["value"])
    miq, maq = (min(iqs2), max(iqs2)) if iqs2 else (0.0, 1.0)
    mv, mxv = (min(vals2), max(vals2)) if vals2 else (0.0, 1.0)

    log(f"\nQualified benchmarks ({len(qualified)} of {len(benchmark_headers)}, "
        f"threshold >= {qualified_min}/{len(entries)} of the full cohort):")
    for b in sorted(qualified):
        log(f"  ✓ {b}  ({sum(_is_reported(e, b) for e in entries)}/{len(entries)})")

    return ScoringResult(benchmark_headers, dropped, participation, max_participation,
                         miq, maq, mv, mxv, bmm2, qualified, qualified_min)
