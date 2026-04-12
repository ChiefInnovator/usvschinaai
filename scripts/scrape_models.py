#!/usr/bin/env python3
"""
Scrape LLM leaderboard data from llm-stats.com with staged architecture.
Supports --leaderboard-basic (Stage 1), --leaderboard-full (Stage 2), and full scrape (Stage 3).
"""
import argparse
import codecs
import csv
import json
import os
import shutil
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from playwright.sync_api import sync_playwright

# Load .env at module import so OPENAI_API_KEY (and any other env vars) are
# available before run_gap_filling_pass needs them. CI provides these via
# GitHub Actions secrets directly so the load_dotenv call is a no-op there.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    # python-dotenv is optional at import time so the scraper can still run
    # in minimal environments. Gap-fill will skip if OPENAI_API_KEY is unset.
    pass

# Local module — gap-filling pass between sparse-drop and Pass 1
sys.path.insert(0, str(Path(__file__).parent))
from gap_fill_benchmarks import run_gap_filling_pass  # noqa: E402


@dataclass
class LeaderboardEntry:
    """Represents a single model row from the leaderboard table."""
    rank: int
    name: str
    country: str
    url: str
    columns: Dict[str, str] = field(default_factory=dict)  # Header -> raw value


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
    # LMSYS methodology; top frontier models currently sit around 1500–2000
    # (Apr 2026 snapshot). (1000, 2000) anchors on the published floor and a
    # defensible ceiling so the scale doesn't drift as new models enter.
    "CodeArena": (1000.0, 2000.0),
}


# Some benchmarks appear under an abbreviation on the leaderboard table and a
# different spelled-out name on the detail page. Canonicalization can't fuzzy-match
# across these — they need an explicit alias. Map either direction into a shared
# canonical token so both forms collapse to the same key.
BENCHMARK_NAME_ALIASES: Dict[str, str] = {
    # canonicalized form -> shared canonical token
    "humanityslastexam": "hle",
    "hle": "hle",
}


def canonicalize_benchmark_name(name: str) -> str:
    """Lowercased, alphanumeric-only form for fuzzy benchmark-name matching.

    Known abbreviation variants (e.g. "Humanity's Last Exam" ↔ "HLE") are collapsed
    through BENCHMARK_NAME_ALIASES so both forms resolve to the same key.
    """
    canon = re.sub(r"[^a-z0-9]", "", name.lower())
    return BENCHMARK_NAME_ALIASES.get(canon, canon)


# Benchmark records in the flight payload are flat objects delimited by `{` / `}`.
# Scanning between braces is more robust than a single cross-record regex: it can
# handle records where ``normalized_score`` is ``null`` (which a numeric-only pattern
# used to backtrack past, bridging into the next record's JSON and capturing garbage
# like `GDPval-AA","description":"GDPval-AA is an evaluation..."` as a "benchmark
# name"). ``[^{}]`` is safe as the flight JSON never nests objects inside a single
# benchmark record — arrays use ``[...]`` and string values don't include literal
# braces in llm-stats' schema.
_DETAIL_RECORD_PATTERN = re.compile(r"\{[^{}]*?\\\"benchmark_id\\\"[^{}]*?\}")
_DETAIL_NAME_PATTERN = re.compile(r'\\"name\\":\\"(.+?)\\",')
_DETAIL_NORM_PATTERN = re.compile(r'\\"normalized_score\\":(null|[0-9.]+)')


def extract_detail_benchmarks(page) -> Dict[str, str]:
    """Parse benchmark scores from a model detail page's embedded Next.js flight payload.

    Uses the ``normalized_score`` field because it is consistently in the 0–1 range,
    whereas the raw ``score`` field sometimes ships as a fraction with a ``max_score``
    of 100 (e.g. SimpleVQA, ZEROBench) which yields nonsense if naively multiplied.
    Returns {benchmark_name: "xx.x%"} for every benchmark on the page.

    Records where ``normalized_score`` is ``null`` (e.g. GDPval-AA, OmniDocBench 1.5,
    Vending-Bench 2 — benchmarks where llm-stats has the raw score but hasn't decided
    how to project it onto a 0–1 scale) are skipped, not crash the parser.
    """
    try:
        html = page.content()
    except Exception:
        return {}

    results: Dict[str, str] = {}
    for record_match in _DETAIL_RECORD_PATTERN.finditer(html):
        record = record_match.group(0)

        name_match = _DETAIL_NAME_PATTERN.search(record)
        norm_match = _DETAIL_NORM_PATTERN.search(record)
        if not name_match or not norm_match:
            continue

        raw_norm = norm_match.group(1)
        if raw_norm == "null":
            continue  # benchmark hasn't been normalized yet on llm-stats; skip

        try:
            name = codecs.decode(name_match.group(1), "unicode_escape")
            normalized = float(raw_norm)
        except (UnicodeDecodeError, ValueError):
            continue

        if normalized < 0 or normalized > 1.0:
            continue  # guardrail for unexpected out-of-range values

        formatted = f"{normalized * 100:.1f}%"
        results.setdefault(name, formatted)

    return results


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

        # Normalize benchmark score to 0-100 if min/max available
        if b in benchmark_min_max:
            min_b, max_b = benchmark_min_max[b]
            if max_b > min_b:
                score = ((score - min_b) / (max_b - min_b)) * 100

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
        norm_avg_iq = ((avg_iq - min_avg_iq) / (max_avg_iq - min_avg_iq)) * 100
    else:
        norm_avg_iq = avg_iq
    
    if min_value is not None and max_value is not None and max_value > min_value:
        norm_value = ((value - min_value) / (max_value - min_value)) * 100
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


def write_csv(
    entries: List[LeaderboardEntry],
    filepath: Path,
    headers: List[str],
    include_derived: bool = True,
    benchmark_headers: Optional[List[str]] = None,
    rank_column_name: str = "Rank",
    participation: Optional[Dict[str, int]] = None,
    max_participation: Optional[int] = None,
    min_avg_iq: Optional[float] = None,
    max_avg_iq: Optional[float] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    benchmark_min_max: Optional[Dict[str, tuple]] = None,
    qualified_benchmarks: Optional[set] = None,
):
    """Write entries to CSV file."""
    # Remove empty headers to avoid blank columns (llm-stats sometimes emits an empty col)
    cleaned_headers = [h for h in headers if h.strip()]
    # Don't duplicate Model/Country if they're already in headers
    base_headers = [rank_column_name]
    if "Model" not in cleaned_headers:
        base_headers.append("Model")
    if "Country" not in cleaned_headers:
        base_headers.append("Country")
    csv_headers = base_headers + cleaned_headers
    if include_derived and benchmark_headers:
        csv_headers.extend(["AvgIQ", "Value", "Unified"])
    
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(csv_headers)

        for entry in entries:
            row = [entry.rank]

            # Add Model and Country if not in headers
            if "Model" not in cleaned_headers:
                row.append(entry.name)
            if "Country" not in cleaned_headers:
                row.append(entry.country)

            # Add column values
            for header in cleaned_headers:
                if header == "URL":
                    row.append(entry.url)
                elif header == "Model":
                    row.append(entry.name)
                elif header == "Country":
                    row.append(entry.country)
                else:
                    row.append(entry.columns.get(header, ""))

            # Add derived scores with normalization
            if include_derived and benchmark_headers:
                scores = calculate_derived_scores(
                    entry,
                    benchmark_headers,
                    participation,
                    max_participation,
                    min_avg_iq,
                    max_avg_iq,
                    min_value,
                    max_value,
                    benchmark_min_max=benchmark_min_max,
                    qualified_benchmarks=qualified_benchmarks,
                )
                row.extend([
                    scores["avgIq"],
                    scores["value"],
                    scores["unified"]
                ])

            writer.writerow(row)
    
    print(f"  Written to: {filepath.name}")


def write_json(
    entries: List[LeaderboardEntry],
    filepath: Path,
    headers: List[str],
    include_derived: bool = True,
    benchmark_headers: Optional[List[str]] = None,
    participation: Optional[Dict[str, int]] = None,
    max_participation: Optional[int] = None,
    min_avg_iq: Optional[float] = None,
    max_avg_iq: Optional[float] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    benchmark_min_max: Optional[Dict[str, tuple]] = None,
    qualified_benchmarks: Optional[set] = None,
):
    """Write entries to JSON file in the current order."""
    cleaned_headers = [h for h in headers if h.strip()]
    out_rows = []
    for entry in entries:
        row: Dict[str, Any] = {
            "Rank": entry.rank,
            "Model": entry.name,
            "Country": entry.country,
        }
        for h in cleaned_headers:
            if h == "URL":
                row[h] = entry.url
            else:
                row[h] = entry.columns.get(h, "")
        if include_derived and benchmark_headers:
            scores = calculate_derived_scores(
                entry,
                benchmark_headers,
                participation,
                max_participation,
                min_avg_iq,
                max_avg_iq,
                min_value,
                max_value,
                benchmark_min_max=benchmark_min_max,
                qualified_benchmarks=qualified_benchmarks,
            )
            row.update({
                "AvgIQ": scores["avgIq"],
                "Value": scores["value"],
                "Unified": scores["unified"],
            })
        out_rows.append(row)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(out_rows, f, ensure_ascii=False, indent=2)
    print(f"  Written to: {filepath.name}")


def format_table(
    entries: List[LeaderboardEntry],
    title: str,
    headers: List[str],
    max_col_width: int = 36,
    model_col_extra: int = 0,
    include_derived: bool = True,
    benchmark_headers: Optional[List[str]] = None,
    rank_column_name: str = "Rank",
    participation: Optional[Dict[str, int]] = None,
    max_participation: Optional[int] = None,
    min_avg_iq: Optional[float] = None,
    max_avg_iq: Optional[float] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    benchmark_min_max: Optional[Dict[str, tuple]] = None,
    qualified_benchmarks: Optional[set] = None,
) -> str:
    """Format entries as a readable table with column width limits."""
    lines = []
    lines.append(f"\n{'=' * 80}")
    lines.append(f"{title}")
    lines.append(f"{'=' * 80}")
    
    # Build display headers
    display_headers = [rank_column_name, "Model"] + headers
    if include_derived and benchmark_headers:
        display_headers.extend(["AvgIQ", "Value", "Unified"])
    
    # Compute per-column widths, adding extra width for Model column if requested
    col_widths = [max_col_width for _ in display_headers]
    if len(col_widths) > 1:
        col_widths[1] = max_col_width + max(0, model_col_extra)
    
    # Truncate headers per-column and render header row
    truncated_headers = [h[:w] for h, w in zip(display_headers, col_widths)]
    header_row = " | ".join((f"{h:<{w}}")[:w] for h, w in zip(truncated_headers, col_widths))
    lines.append(header_row)
    lines.append("-" * len(header_row))
    
    # Data rows
    for entry in entries:
        row_values = [str(entry.rank), entry.name]
        
        # Add raw column values
        for header in headers:
            if header == "URL":
                row_values.append(entry.url)
            else:
                val = entry.columns.get(header, "")
                row_values.append(str(val))
        
        # Add derived scores with normalization
        if include_derived and benchmark_headers:
            scores = calculate_derived_scores(
                entry,
                benchmark_headers,
                participation,
                max_participation,
                min_avg_iq,
                max_avg_iq,
                min_value,
                max_value,
                benchmark_min_max=benchmark_min_max,
                qualified_benchmarks=qualified_benchmarks,
            )
            row_values.extend([
                str(scores["avgIq"]),
                str(scores["value"]),
                str(scores["unified"])
            ])
        
        # Truncate values per-column and format
        row_values = [v[:w] if len(v) > w else v for v, w in zip(row_values, col_widths)]
        row = " | ".join((f"{v:<{w}}")[:w] for v, w in zip(row_values, col_widths))
        lines.append(row)
    
    lines.append(f"{'=' * 80}\n")
    return "\n".join(lines)


def scrape_country_leaderboard(
    page,
    country_name: str,
    origin_code: str,
    max_models: int = 10,
    stage: str = "basic"
) -> Tuple[List[LeaderboardEntry], List[str], List[str]]:
    """
    Scrape top-10 models for a country from the leaderboard.
    """
    print(f"\nScraping {country_name} ({origin_code})...")
    
    # Navigate to leaderboard
    page.goto("https://llm-stats.com/leaderboards/llm-leaderboard", timeout=60000)
    page.wait_for_load_state("domcontentloaded")
    time.sleep(3)
    
    # Apply country filter. The exact selector is brittle — llm-stats sometimes
    # ships the filter as a labelled button, sometimes as a generic dropdown
    # trigger. Try a few shapes before giving up so a UI rename on their side
    # doesn't silently produce empty results.
    country_button_selectors = [
        "button:has-text('Country')",
        "button:has-text('country')",
        "[role='button']:has-text('Country')",
        "[data-testid*='country']",
    ]
    country_button = None
    for selector in country_button_selectors:
        try:
            country_button = page.wait_for_selector(selector, timeout=5000)
            if country_button:
                break
        except Exception:
            continue
    if not country_button:
        print(
            f"ERROR: Could not find the Country filter trigger on llm-stats. "
            f"The page DOM may have changed. Tried: {country_button_selectors}. "
            f"Update country_button_selectors in scrape_country_leaderboard()."
        )
        return [], [], []
    country_button.click()
    time.sleep(1)

    # Try different selectors for country option (flag emoji + name, or just name).
    country_selectors = [
        f"text='🇨🇳 {country_name}'",
        f"text='🇺🇸 {country_name}'",
        f"text='{country_name}'",
        f"[role='option']:has-text('{country_name}')",
        f"button:has-text('{country_name}')",
    ]

    country_option = None
    for selector in country_selectors:
        try:
            country_option = page.wait_for_selector(selector, timeout=5000)
            if country_option:
                break
        except Exception:
            continue

    if not country_option:
        print(
            f"ERROR: Could not find the {country_name} option in the country filter. "
            f"The dropdown DOM or labels may have changed. Tried: {country_selectors}. "
            f"Update country_selectors in scrape_country_leaderboard()."
        )
        return [], [], []

    country_option.click()
    time.sleep(2)
    
    # Extract all table headers
    header_elements = page.query_selector_all("thead th")
    all_headers = [h.inner_text().strip() for h in header_elements]
    print(f"  Found {len(all_headers)} columns")
    
    # Identify benchmark columns (exclude metadata/non-benchmark columns).
    #
    # The llm-stats leaderboard also emits per-category aggregate columns that roll
    # up individual benchmarks (Reasoning, Math, Coding, Search, Writing, Vision,
    # Tools, Long Ctx, Finance, Legal, Health). Keeping them as benchmarks would
    # double-count — each individual GPQA/AIME/etc. already feeds the "Reasoning"
    # aggregate, so scoring across both drags outliers twice. We retain the raw
    # columns for display but exclude them from the scoring set.
    metadata_columns = {
        "Rank", "Model", "Country", "License", "Context", "Input", "Output",
        "Speed", "Organization", "Created", "Description",
        "Input $/M", "Output $/M", "Input$/M", "Output$/M",
        "Parameters (B)", "Parameters(B)", "Knowledge Cutoff", "KnowledgeCutoff",
        "Multimodal", "Released",
        # Category-level aggregates (rollups of individual benchmarks)
        "Reasoning", "Math", "Coding", "Search", "Writing", "Vision", "Tools",
        "Long Ctx", "LongCtx", "Finance", "Legal", "Health",
    }

    benchmark_headers = [h for h in all_headers if h not in metadata_columns and h]
    
    # Extract rows
    rows = page.query_selector_all("tbody tr")
    print(f"  Found {len(rows)} rows")
    
    entries = []
    for i, row in enumerate(rows[:max_models]):
        # Get model link
        link_elem = row.query_selector("a")
        if not link_elem:
            continue
        
        name = link_elem.inner_text().strip()
        url = link_elem.get_attribute("href")
        if not url.startswith("http"):
            url = f"https://llm-stats.com{url}"
        
        # Extract all cell values
        cells = row.query_selector_all("td")
        columns = {}
        
        for col_idx, header in enumerate(all_headers):
            if col_idx < len(cells):
                raw_value = cells[col_idx].inner_text().strip()
                # Special handling for Multimodal column: llm-stats renders this
                # as an icon (no readable text), so we have to look at the cell's
                # inner HTML to decide Yes/No. The class names below are llm-stats'
                # current Lucide icon set; if they ever swap icon libraries we
                # need to fall back to checking aria-label / title / role attrs.
                if header == "Multimodal":
                    html = cells[col_idx].inner_html().lower()

                    # Positive signals: a check icon, a generic "yes/true/supported"
                    # label, or a green colour utility class.
                    positive_signals = (
                        "lucide-check", "icon-check", "checkmark",
                        "text-green", "text-emerald", "fill-green",
                        'aria-label="yes"', 'aria-label="true"', 'aria-label="supported"',
                        'title="yes"', 'title="true"', 'title="supported"',
                    )

                    # Negative signals: an X / close icon, an explicit no/false
                    # label, or a grey/neutral colour utility class.
                    negative_signals = (
                        "lucide-x", "lucide-close", "icon-x", "icon-close",
                        "text-gray", "text-neutral", "text-slate", "text-zinc",
                        'aria-label="no"', 'aria-label="false"',
                        'title="no"', 'title="false"',
                    )

                    is_checkmark = any(sig in html for sig in positive_signals)
                    is_x = any(sig in html for sig in negative_signals)

                    if is_checkmark and not is_x:
                        raw_value = "Yes"
                    elif is_x or (raw_value in ["", "-"]):
                        raw_value = "No"
                    
                columns[header] = raw_value
        
        entry = LeaderboardEntry(
            rank=i + 1,
            name=name,
            country=origin_code,
            url=url,
            columns=columns
        )
        
        entries.append(entry)
        print(f"    {i+1}. {name}")
    
    return entries, all_headers, benchmark_headers


def scrape_global_leaderboard(page) -> Dict[str, int]:
    """
    Scrape global leaderboard (no country filter) to get llm-stats rankings.
    Returns a dict mapping model names to their global ranking.
    """
    print(f"\nScraping global leaderboard (no country filter)...")
    
    # Navigate to leaderboard
    page.goto("https://llm-stats.com/leaderboards/llm-leaderboard", timeout=60000)
    page.wait_for_load_state("domcontentloaded")
    time.sleep(3)
    
    # No country filter - just extract all models and their positions
    rows = page.query_selector_all("tbody tr")
    print(f"  Found {len(rows)} rows in global leaderboard")
    
    global_rankings = {}
    for i, row in enumerate(rows):
        # Get model link
        link_elem = row.query_selector("a")
        if not link_elem:
            continue
        
        name = link_elem.inner_text().strip()
        # Rank is based on row position (1-indexed)
        global_rankings[name] = i + 1
    
    return global_rankings


def enrich_with_metadata(
    page,
    entries: List[LeaderboardEntry],
    known_benchmark_headers: Optional[List[str]] = None,
    canonical_header_map: Optional[Dict[str, str]] = None,
) -> Tuple[List[LeaderboardEntry], List[str]]:
    """Extract metadata and detail-page benchmark scores from model detail pages.

    Pulls the meta description (as before) plus every benchmark score embedded in the
    detail page's flight payload. Scores that match an existing leaderboard header
    (fuzzy match via canonicalize_benchmark_name) fill in missing cells only; scores
    for benchmarks the leaderboard doesn't expose become new headers.

    Returns (entries, new_headers) where new_headers is the ordered list of benchmark
    names discovered on detail pages that were not already in known_benchmark_headers.
    """
    print(f"\nEnriching {len(entries)} models with descriptions and detail benchmarks...")

    if canonical_header_map is None:
        canonical_header_map = {}
    # Seed the canonical map from any already-known leaderboard headers so we can
    # detect fuzzy matches and fill blanks instead of creating duplicate columns.
    for header in (known_benchmark_headers or []):
        canonical_header_map.setdefault(canonicalize_benchmark_name(header), header)

    new_headers: List[str] = []

    for i, entry in enumerate(entries):
        print(f"  [{i+1}/{len(entries)}] {entry.name}")

        try:
            page.goto(entry.url, timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(1)

            # Extract meta description
            try:
                desc_elem = page.query_selector("meta[name='description']")
                if desc_elem:
                    desc = desc_elem.get_attribute("content")
                    if desc:
                        entry.columns["description"] = desc[:200]
            except Exception:
                pass

            # Extract benchmark scores from the embedded flight payload
            detail_scores = extract_detail_benchmarks(page)
            for detail_name, detail_value in detail_scores.items():
                canon = canonicalize_benchmark_name(detail_name)
                if not canon:
                    continue

                if canon in canonical_header_map:
                    # Known benchmark — fill in only if the existing cell is blank.
                    canonical_key = canonical_header_map[canon]
                    existing = entry.columns.get(canonical_key, "")
                    if existing in MISSING_VALUE_MARKERS:
                        entry.columns[canonical_key] = detail_value
                else:
                    # Brand-new benchmark — add it as a new column, using the
                    # detail-page name verbatim.
                    canonical_header_map[canon] = detail_name
                    entry.columns[detail_name] = detail_value
                    new_headers.append(detail_name)

        except Exception as e:
            print(f"    Warning: Failed to fetch metadata - {e}")
            continue

    return entries, new_headers


def backup_models_json(models_path: Path) -> Path:
    """Create timestamped backup of models.json."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S")
    backup_path = models_path.with_name(f"models.backup-{timestamp}.json")
    
    if models_path.exists():
        shutil.copy2(models_path, backup_path)
        print(f"Created backup: {backup_path.name}")
    
    return backup_path


def build_history_entry(
    us_entries: List[LeaderboardEntry],
    cn_entries: List[LeaderboardEntry],
    all_headers: List[str],
    benchmark_headers: List[str],
    participation: Optional[Dict[str, int]] = None,
    max_participation: Optional[int] = None,
    min_avg_iq: Optional[float] = None,
    max_avg_iq: Optional[float] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    benchmark_min_max: Optional[Dict[str, tuple]] = None,
    qualified_benchmarks: Optional[set] = None,
) -> Dict[str, Any]:
    """Build models.json history entry from scraped data."""
    # Get timezone-aware timestamp
    now_local = datetime.now()
    now_utc = datetime.now(timezone.utc)
    offset_seconds = (now_local - now_utc.replace(tzinfo=None)).total_seconds()
    offset_hours = int(offset_seconds / 3600)
    offset_minutes = int((abs(offset_seconds) % 3600) / 60)
    tz_sign = '+' if offset_hours >= 0 else '-'
    tz_str = f"{tz_sign}{abs(offset_hours):02d}:{offset_minutes:02d}"
    timestamp = now_local.strftime(f"%Y-%m-%dT%H:%M:%S{tz_str}")

    def entry_to_row(entry: LeaderboardEntry) -> Dict[str, Any]:
        """Convert LeaderboardEntry to models.json row format."""
        scores = calculate_derived_scores(
            entry,
            benchmark_headers,
            participation,
            max_participation,
            min_avg_iq,
            max_avg_iq,
            min_value,
            max_value,
            benchmark_min_max=benchmark_min_max,
            qualified_benchmarks=qualified_benchmarks,
        )

        # Get organization from table column, description from metadata enrichment
        organization = entry.columns.get("Organization", "")
        description = entry.columns.get("description", "")
        released = entry.columns.get("Released", "")

        row = {
            "model": entry.name,
            "organization": organization,
            "link": entry.url,
            "origin": entry.country,
            "description": description,
            "created": released,
            "avgIq": scores["avgIq"],
            "value": scores["value"],
            "unified": scores["unified"]
        }

        # Add all raw column values (preserve original keys without modification)
        for header, value in entry.columns.items():
            if not header.strip():
                continue
            # Don't duplicate fields we already added
            if header in ["Organization", "description", "Released"]:
                continue
            # Provenance dict needs its inner keys space-stripped to match
            # the score keys on this row (see below for the score-key rule).
            if header == "_provenance" and isinstance(value, dict):
                row["_provenance"] = {
                    inner.replace(" ", ""): entry_val
                    for inner, entry_val in value.items()
                }
                continue
            # Keep original header format for all other columns
            key = header.replace(" ", "")
            if key not in row:
                row[key] = value

        return row
    
    us_rows = [entry_to_row(e) for e in us_entries]
    cn_rows = [entry_to_row(e) for e in cn_entries]
    
    return {
        "timestamp": timestamp,
        "teams": {
            "US": us_rows,
            "CN": cn_rows
        }
    }


def prepend_history(models_path: Path, new_entry: Dict[str, Any]):
    """Prepend new history entry to models.json."""
    with open(models_path, 'r') as f:
        data = json.load(f)

    if 'history' not in data:
        data['history'] = []

    data['history'].insert(0, new_entry)

    # Update footerText with the latest timestamp
    ts = new_entry.get("timestamp", "")
    if ts and "metadata" in data:
        try:
            from dateutil.parser import parse as parse_date
            dt = parse_date(ts)
            date_label = dt.strftime("%b %d, %Y").replace(" 0", " ")
        except Exception:
            date_label = ts[:10]
        data["metadata"]["footerText"] = (
            f"Data Audited {date_label} | Source: llm-stats.com | "
            "IQ = flat average over the qualified benchmark set "
            "(two-pass scoring, category aggregates excluded)"
        )

    with open(models_path, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"\n✅ Successfully prepended entry to models.json")


# URLs whose <lastmod> should get bumped every time the daily scraper runs.
# Static pages (about/privacy/terms/humans) are intentionally excluded — their
# lastmod should only move when the content actually changes.
_DAILY_SITEMAP_URLS = {
    "https://usvschina.ai/",
    "https://usvschina.ai/index.html",
    "https://usvschina.ai/history.html",
    "https://usvschina.ai/llms.txt",
    "https://usvschina.ai/models.json",
}


_INDEX_META_DATE_PATTERN = re.compile(
    r'(<meta name="description"[^>]*content="[^"]*?Updated )([A-Z][a-z]+ \d{4})(\.")'
)


def update_index_meta_description(index_path: Path, run_date: Optional[str] = None) -> bool:
    """Rewrite the trailing "Updated <Month Year>." in index.html's meta description.

    The scraper runs daily; without this, the meta description (and the snippet
    Google / social previews show) drifts months out of date and starts hurting
    SEO/AEO trust signals. We anchor the rewrite on a tight regex so unrelated
    meta tags are untouched.
    """
    if not index_path.exists():
        print(f"Warning: {index_path.name} not found; skipping meta-description update.")
        return False

    if run_date:
        try:
            from dateutil.parser import parse as parse_date
            dt = parse_date(run_date)
        except Exception:
            dt = datetime.now()
    else:
        dt = datetime.now()

    new_label = dt.strftime("%B %Y")  # e.g. "April 2026"
    src = index_path.read_text(encoding="utf-8")

    match = _INDEX_META_DATE_PATTERN.search(src)
    if not match:
        print(f"Warning: meta description in {index_path.name} did not match expected "
              f"'Updated <Month Year>.' pattern; left unchanged.")
        return False

    if match.group(2) == new_label:
        return False  # already current; no rewrite needed

    new_src = _INDEX_META_DATE_PATTERN.sub(rf"\g<1>{new_label}\g<3>", src, count=1)
    index_path.write_text(new_src, encoding="utf-8")
    print(f"Updated index.html meta description: {match.group(2)} → {new_label}")
    return True


def update_sitemap_lastmod(sitemap_path: Path, run_date: Optional[str] = None) -> bool:
    """Bump <lastmod> to today on every URL in _DAILY_SITEMAP_URLS.

    Parses the sitemap as plain text so we don't need an XML dependency and so
    the diff stays tight (only the dates change, indentation preserved).
    Returns True if the file was rewritten, False if nothing needed updating or
    the sitemap is missing.
    """
    if not sitemap_path.exists():
        print(f"Warning: sitemap {sitemap_path.name} not found; skipping lastmod update.")
        return False

    today = run_date or datetime.now().strftime("%Y-%m-%d")
    lines = sitemap_path.read_text(encoding="utf-8").splitlines(keepends=True)

    rewritten: List[str] = []
    current_loc: Optional[str] = None
    changed = False

    loc_pattern = re.compile(r"<loc>\s*([^<]+?)\s*</loc>")
    lastmod_pattern = re.compile(r"(<lastmod>)\s*[^<]*\s*(</lastmod>)")

    for line in lines:
        loc_match = loc_pattern.search(line)
        if loc_match:
            current_loc = loc_match.group(1).strip()
            rewritten.append(line)
            continue

        if current_loc in _DAILY_SITEMAP_URLS and lastmod_pattern.search(line):
            new_line = lastmod_pattern.sub(rf"\g<1>{today}\g<2>", line)
            if new_line != line:
                changed = True
            rewritten.append(new_line)
            continue

        rewritten.append(line)

    if changed:
        sitemap_path.write_text("".join(rewritten), encoding="utf-8")
        print(f"Updated sitemap lastmod → {today} on {len(_DAILY_SITEMAP_URLS)} daily URLs")
    return changed


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


def run_scraper(args):
    """Main scraper execution."""
    workspace_dir = Path(__file__).parent.parent
    models_path = workspace_dir / "models.json"
    
    # Determine stage
    if args.leaderboard_basic:
        stage = "basic"
        stage_name = "Stage 1: Basic Leaderboard"
        stage_num = 1
    elif args.leaderboard_full:
        stage = "full"
        stage_name = "Stage 2: Full Leaderboard"
        stage_num = 2
    else:
        stage = "metadata"
        stage_name = "Stage 3: Full Scrape with Metadata"
        stage_num = 3
    
    print(f"\n{'='*80}")
    print(f"{stage_name}")
    print(f"{'='*80}")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.debug)
        page = browser.new_page()
        
        try:
            # Scrape both countries
            us_entries, us_headers, us_benchmarks = scrape_country_leaderboard(
                page, "United States", "US", max_models=10, stage=stage
            )
            
            cn_entries, cn_headers, cn_benchmarks = scrape_country_leaderboard(
                page, "China", "CN", max_models=10, stage=stage
            )
            
            # Use US headers as canonical
            all_headers = us_headers
            benchmark_headers = us_benchmarks
            
            # Build participation weighting across combined entries (US + CN)
            combined_entries = us_entries + cn_entries
            participation_counts, max_participation = build_benchmark_participation(combined_entries, benchmark_headers)
            
            # Stage-specific behavior
            if stage == "basic":
                # Get global leaderboard rankings
                global_rankings = scrape_global_leaderboard(page)
                
                # Add llm-stats ranking to entries
                for entry in us_entries:
                    entry.columns["llm-stats ranking"] = str(global_rankings.get(entry.name, "N/A"))
                for entry in cn_entries:
                    entry.columns["llm-stats ranking"] = str(global_rankings.get(entry.name, "N/A"))
                
                # Combine and sort by leaderboard rank
                all_entries = us_entries + cn_entries
                def get_rank(entry):
                    rank_str = entry.columns.get("llm-stats ranking", "N/A")
                    if rank_str == "N/A":
                        return float('inf')
                    try:
                        return int(rank_str)
                    except ValueError:
                        return float('inf')
                
                all_entries.sort(key=get_rank)
                
                # Update entry.rank to be the llm-stats ranking
                for entry in all_entries:
                    rank_str = entry.columns.get("llm-stats ranking", "N/A")
                    if rank_str != "N/A":
                        try:
                            entry.rank = int(rank_str)
                        except ValueError:
                            pass
                
                print(format_table(
                    all_entries,
                    "🏆 Top 20 Models (US + China) Sorted by Leaderboard Rank",
                    ["Country", "URL"],
                    max_col_width=15,
                    include_derived=False,
                    rank_column_name="Rank"
                ))
                
                print("\nWriting CSV files...")
                write_csv(all_entries, workspace_dir / f"stage{stage_num}_combined.csv", ["llm-stats ranking", "Country", "URL"], include_derived=False, rank_column_name="Leaderboard Rank")
                write_csv(us_entries, workspace_dir / f"stage{stage_num}_us.csv", ["llm-stats ranking", "Country", "URL"], include_derived=False, rank_column_name="Leaderboard Rank")
                write_csv(cn_entries, workspace_dir / f"stage{stage_num}_cn.csv", ["llm-stats ranking", "Country", "URL"], include_derived=False, rank_column_name="Leaderboard Rank")
                
            elif stage == "full":
                # Get global leaderboard rankings
                global_rankings = scrape_global_leaderboard(page)
                
                # Combine entries and compute global rank for reference
                all_entries = us_entries + cn_entries
                for entry in all_entries:
                    rank_value = global_rankings.get(entry.name, float('inf'))
                    entry.rank = rank_value if isinstance(rank_value, int) else float('inf')
                
                # Calculate min/max for each benchmark (normalize scores across all models)
                benchmark_min_max = {}
                for b in benchmark_headers:
                    # Exclude benchmarks with a single participant from normalization as well
                    if participation_counts.get(b, 0) <= 1:
                        continue
                    values = []
                    for e in all_entries:
                        raw_val = e.columns.get(b, "")
                        if raw_val and raw_val not in MISSING_VALUE_MARKERS:
                            values.append(parse_to_number(raw_val))
                    if values:
                        benchmark_min_max[b] = (min(values), max(values))
                
                # Calculate min/max for normalization (first pass with benchmark normalization)
                avg_iq_values = []
                value_values = []
                for e in all_entries:
                    scores = calculate_derived_scores(e, benchmark_headers, participation_counts, max_participation, benchmark_min_max=benchmark_min_max)
                    avg_iq_values.append(scores["avgIq"])
                    value_values.append(scores["value"])
                
                min_avg_iq = min(avg_iq_values) if avg_iq_values else 0
                max_avg_iq = max(avg_iq_values) if avg_iq_values else 1
                min_value = min(value_values) if value_values else 0
                max_value = max(value_values) if value_values else 1
                
                # Sort by Unified (desc) using normalized AvgIQ and Value
                all_entries.sort(
                    key=lambda e: -calculate_derived_scores(
                        e,
                        benchmark_headers,
                        participation_counts,
                        max_participation,
                        min_avg_iq,
                        max_avg_iq,
                        min_value,
                        max_value,
                        benchmark_min_max=benchmark_min_max,
                    )["unified"]
                )
                
                # Only display: Rank, Model, Country, Organization + derived scores
                display_headers = ["Country", "Organization"]
                
                print(format_table(
                    all_entries,
                    "🏆 Top 20 Models (US + China) - Comparison with Derived Scores",
                    display_headers,
                    max_col_width=15,
                    model_col_extra=5,
                    include_derived=True,
                    benchmark_headers=benchmark_headers,
                    participation=participation_counts,
                    max_participation=max_participation,
                    min_avg_iq=min_avg_iq,
                    max_avg_iq=max_avg_iq,
                    min_value=min_value,
                    max_value=max_value,
                    benchmark_min_max=benchmark_min_max
                ))
                
                print("\nWriting CSV/JSON files...")
                write_csv(
                    all_entries,
                    workspace_dir / f"stage{stage_num}_combined.csv",
                    all_headers,
                    include_derived=True,
                    benchmark_headers=benchmark_headers,
                    participation=participation_counts,
                    max_participation=max_participation,
                    min_avg_iq=min_avg_iq,
                    max_avg_iq=max_avg_iq,
                    min_value=min_value,
                    max_value=max_value,
                    benchmark_min_max=benchmark_min_max,
                )
                write_csv(
                    us_entries,
                    workspace_dir / f"stage{stage_num}_us.csv",
                    all_headers,
                    include_derived=True,
                    benchmark_headers=benchmark_headers,
                    participation=participation_counts,
                    max_participation=max_participation,
                    min_avg_iq=min_avg_iq,
                    max_avg_iq=max_avg_iq,
                    min_value=min_value,
                    max_value=max_value,
                    benchmark_min_max=benchmark_min_max,
                )
                write_csv(
                    cn_entries,
                    workspace_dir / f"stage{stage_num}_cn.csv",
                    all_headers,
                    include_derived=True,
                    benchmark_headers=benchmark_headers,
                    participation=participation_counts,
                    max_participation=max_participation,
                    min_avg_iq=min_avg_iq,
                    max_avg_iq=max_avg_iq,
                    min_value=min_value,
                    max_value=max_value,
                    benchmark_min_max=benchmark_min_max,
                )
                # Combined JSON export in the same (Unified-desc) order
                write_json(
                    all_entries,
                    workspace_dir / f"stage{stage_num}_combined.json",
                    all_headers,
                    include_derived=True,
                    benchmark_headers=benchmark_headers,
                    participation=participation_counts,
                    max_participation=max_participation,
                    min_avg_iq=min_avg_iq,
                    max_avg_iq=max_avg_iq,
                    min_value=min_value,
                    max_value=max_value,
                    benchmark_min_max=benchmark_min_max,
                )

                # Create per-country Unified summaries and top-3 lists
                summaries: Dict[str, Dict[str, Any]] = {}
                per_country_rows: Dict[str, List[Dict[str, Any]]] = {"US": [], "CN": []}
                # Precompute unified for each entry with same normalization
                for e in all_entries:
                    s = calculate_derived_scores(
                        e,
                        benchmark_headers,
                        participation_counts,
                        max_participation,
                        min_avg_iq,
                        max_avg_iq,
                        min_value,
                        max_value,
                        benchmark_min_max=benchmark_min_max,
                    )
                    per_country_rows.setdefault(e.country, []).append({
                        "Model": e.name,
                        "Country": e.country,
                        "Unified": s["unified"],
                        "AvgIQ": s["avgIq"],
                        "Value": s["value"],
                    })

                aggregates_csv = workspace_dir / f"stage{stage_num}_country_aggregates.csv"
                with open(aggregates_csv, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["Country", "Models", "TotalUnified", "AvgUnified"])
                    for code, rows in per_country_rows.items():
                        if not rows:
                            continue
                        total = sum(r["Unified"] for r in rows)
                        avg = total / len(rows)
                        summaries[code] = {"country": code, "models": len(rows), "totalUnified": round(total, 2), "avgUnified": round(avg, 2)}
                        writer.writerow([code, len(rows), round(total, 2), round(avg, 2)])
                print(f"  Written to: {aggregates_csv.name}")

                # Top 3 per country JSON summary
                summary_json = workspace_dir / f"stage{stage_num}_summary.json"
                top3: Dict[str, List[Dict[str, Any]]] = {}
                for code, rows in per_country_rows.items():
                    rows_sorted = sorted(rows, key=lambda r: -r["Unified"])[:3]
                    top3[code] = rows_sorted
                with open(summary_json, "w", encoding="utf-8") as f:
                    json.dump({"aggregates": summaries, "top3": top3}, f, ensure_ascii=False, indent=2)
                print(f"  Written to: {summary_json.name}")

                # Print concise top-3 per country to console
                for code in ("US", "CN"):
                    if code in top3:
                        print(f"Top 3 {code} by Unified:")
                        for i, r in enumerate(top3[code], 1):
                            print(f"  {i}. {r['Model']} — Unified {r['Unified']:.2f}")
                
            else:  # metadata stage
                # Enrich detail pages. Share one canonical-name map across both countries
                # so a benchmark first discovered for a US model isn't duplicated when
                # the same name shows up for a CN model.
                canonical_header_map: Dict[str, str] = {}
                us_entries, us_new_headers = enrich_with_metadata(
                    page, us_entries, benchmark_headers, canonical_header_map
                )
                cn_entries, cn_new_headers = enrich_with_metadata(
                    page, cn_entries, benchmark_headers + us_new_headers, canonical_header_map
                )

                # Merge new benchmarks into the working header lists
                discovered_headers: List[str] = []
                for h in us_new_headers + cn_new_headers:
                    if h not in benchmark_headers and h not in discovered_headers:
                        discovered_headers.append(h)
                if discovered_headers:
                    print(f"\nDiscovered {len(discovered_headers)} new benchmarks on detail pages:")
                    for h in discovered_headers:
                        print(f"  + {h}")
                    benchmark_headers = benchmark_headers + discovered_headers
                    all_headers = all_headers + discovered_headers

                combined_entries = us_entries + cn_entries

                # Drop benchmarks that barely anyone reports. A benchmark needs
                # at least MIN_COHORT_PARTICIPATION non-missing cells across the
                # cohort or we drop it entirely. We drop from both benchmark_headers
                # (so it doesn't participate in scoring) AND from every entry's
                # column dict (so it doesn't land in models.json at all).
                #
                # The floor is an absolute count (4) rather than a fraction so the
                # rule stays stable as the cohort changes size and so a "merely
                # sparse" benchmark can still slip in if four providers happen to
                # publish it.
                MIN_COHORT_PARTICIPATION = 4
                cohort_size = len(combined_entries)
                pre_drop_counts, _ = build_benchmark_participation(
                    combined_entries, benchmark_headers
                )
                sparse_benchmarks = [
                    b for b in benchmark_headers
                    if pre_drop_counts.get(b, 0) < MIN_COHORT_PARTICIPATION
                ]
                if sparse_benchmarks:
                    print(f"\nDropping {len(sparse_benchmarks)} sparse benchmarks "
                          f"(< {MIN_COHORT_PARTICIPATION} of {cohort_size} models reporting):")
                    for b in sorted(sparse_benchmarks):
                        print(f"  - {b}  ({pre_drop_counts.get(b, 0)}/{cohort_size})")
                    sparse_set = set(sparse_benchmarks)
                    benchmark_headers = [b for b in benchmark_headers if b not in sparse_set]
                    all_headers = [h for h in all_headers if h not in sparse_set]
                    for e in combined_entries:
                        for b in sparse_benchmarks:
                            e.columns.pop(b, None)

                # -------------------------------------------------------------
                # Gap-Filling Pass — runs BEFORE Pass 1 so the scoring sees the
                # enriched data from the start. See docs/ai_gap_filling.md.
                # Skipped automatically if --no-gap-fill is set, OPENAI_API_KEY
                # is missing, or no candidates exist after the §5/§6 filters.
                # -------------------------------------------------------------
                if not getattr(args, "no_gap_fill", False):
                    scrape_run_ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                    try:
                        run_gap_filling_pass(
                            combined_entries,
                            benchmark_headers,
                            max_calls=getattr(args, "gap_fill_max_calls", 40),
                            scraper_run_ts=scrape_run_ts,
                        )
                    except Exception as gap_err:
                        print(f"[gap-fill] pass crashed ({gap_err}); proceeding to Pass 1 unaffected")
                else:
                    print("\n[gap-fill] disabled by --no-gap-fill")

                # Rebuild participation counts now that the header set and cell values
                # have both expanded from detail-page enrichment AND any gap-fills.
                participation_counts, max_participation = build_benchmark_participation(
                    combined_entries, benchmark_headers
                )

                # Calculate per-benchmark min/max for normalization (exclude single-participant benchmarks)
                benchmark_min_max = {}
                for b in benchmark_headers:
                    if participation_counts.get(b, 0) <= 1:
                        continue
                    values = []
                    for e in combined_entries:
                        raw_val = e.columns.get(b, "")
                        if raw_val and raw_val not in MISSING_VALUE_MARKERS:
                            values.append(parse_to_number(raw_val))
                    if values:
                        benchmark_min_max[b] = (min(values), max(values))

                # Compute min/max for AvgIQ and Value using normalized benchmark scores
                avg_iq_values = []
                value_values = []
                for e in combined_entries:
                    scores = calculate_derived_scores(
                        e,
                        benchmark_headers,
                        participation_counts,
                        max_participation,
                        benchmark_min_max=benchmark_min_max,
                    )
                    avg_iq_values.append(scores["avgIq"])
                    value_values.append(scores["value"])

                min_avg_iq = min(avg_iq_values) if avg_iq_values else 0
                max_avg_iq = max(avg_iq_values) if avg_iq_values else 1
                min_value = min(value_values) if value_values else 0
                max_value = max(value_values) if value_values else 1

                # -----------------------------------------------------------------
                # Pass 2: two-pass scoring with convergence iteration
                # -----------------------------------------------------------------
                # 1. Rank all models by Pass 1 Unified to pick the Initial Top 10.
                # 2. Determine the qualified benchmark set: benchmarks where >= 8 of
                #    the current top 10 reported a value.
                # 3. Rescore every model (not just the top 10) using only qualified
                #    benchmarks and a flat average — so a model that skipped an
                #    "easy win" benchmark is no longer penalised for the absence.
                # 4. The Pass 2 ranking can produce a *different* top 10 than Pass 1
                #    used to derive the qualified set. If we don't iterate, benchmarks
                #    that should qualify based on the actual final top 10 can be
                #    excluded simply because Pass 1 happened to put a non-reporting
                #    model in its top 10. To fix this, we re-derive the qualified
                #    set from the new Pass 2 top 10 and re-run Pass 2. We loop until
                #    the qualified set is stable, capped at MAX_QUALIFIED_ITERATIONS
                #    to prevent oscillation in pathological cases.
                # If fewer than 3 benchmarks qualify, fall back to Pass 1 silently.
                QUALIFIED_THRESHOLD = 8
                MIN_QUALIFIED_FLOOR = 3
                MAX_QUALIFIED_ITERATIONS = 5
                qualified_benchmarks: Optional[set] = None

                def _pass1_unified(e: LeaderboardEntry) -> float:
                    return calculate_derived_scores(
                        e,
                        benchmark_headers,
                        participation_counts,
                        max_participation,
                        min_avg_iq,
                        max_avg_iq,
                        min_value,
                        max_value,
                        benchmark_min_max=benchmark_min_max,
                    )["unified"]

                def _qualified_for_top10(top10: List[LeaderboardEntry]) -> set:
                    """Return benchmarks reported by ≥ QUALIFIED_THRESHOLD of the given top 10."""
                    out = set()
                    for b in benchmark_headers:
                        count = sum(
                            1 for e in top10
                            if e.columns.get(b, "") not in MISSING_VALUE_MARKERS
                        )
                        if count >= QUALIFIED_THRESHOLD:
                            out.add(b)
                    return out

                def _rank_with_qset(qset: set) -> Tuple[List[LeaderboardEntry], Dict[str, tuple], float, float, float, float]:
                    """Compute Pass 2 ranking + min/max under the given qualified set.

                    Returns (top10, pass2_benchmark_min_max, min_iq, max_iq, min_v, max_v).
                    """
                    bmm: Dict[str, tuple] = {}
                    for b in qset:
                        rng = resolve_benchmark_range(b, combined_entries)
                        if rng is not None:
                            bmm[b] = rng

                    iqs: List[float] = []
                    vals: List[float] = []
                    for e in combined_entries:
                        s = calculate_derived_scores(
                            e,
                            benchmark_headers,
                            benchmark_min_max=bmm,
                            qualified_benchmarks=qset,
                        )
                        iqs.append(s["avgIq"])
                        vals.append(s["value"])
                    miq, maq = (min(iqs), max(iqs)) if iqs else (0.0, 1.0)
                    mv, mxv = (min(vals), max(vals)) if vals else (0.0, 1.0)

                    def _unified(e: LeaderboardEntry) -> float:
                        return calculate_derived_scores(
                            e,
                            benchmark_headers,
                            min_avg_iq=miq,
                            max_avg_iq=maq,
                            min_value=mv,
                            max_value=mxv,
                            benchmark_min_max=bmm,
                            qualified_benchmarks=qset,
                        )["unified"]

                    new_top10 = sorted(combined_entries, key=_unified, reverse=True)[:10]
                    return new_top10, bmm, miq, maq, mv, mxv

                initial_top10 = sorted(combined_entries, key=_pass1_unified, reverse=True)[:10]
                print(f"\n--- Pass 2 / Two-pass scoring ---")
                print(f"Pass 1 Top 10 (used as the seed for the qualified-set search):")
                for i, e in enumerate(initial_top10, 1):
                    print(f"  {i:>2}. {e.name} ({e.country})")

                current_top10 = initial_top10
                qualified_set = _qualified_for_top10(current_top10)

                if len(qualified_set) < MIN_QUALIFIED_FLOOR:
                    print(f"\nWARNING: only {len(qualified_set)} benchmarks qualified "
                          f"(need >= {MIN_QUALIFIED_FLOOR}). Falling back to Pass 1 scoring.")
                else:
                    # Iterate: re-derive qualified set from each new Pass 2 top 10 and
                    # re-rank, until the set stops changing.
                    seen_qsets: List[set] = [qualified_set]
                    converged = False
                    pass2_bmm: Dict[str, tuple] = {}
                    pass2_miq = pass2_maq = pass2_mv = pass2_mxv = 0.0
                    for iteration in range(1, MAX_QUALIFIED_ITERATIONS + 1):
                        new_top10, pass2_bmm, pass2_miq, pass2_maq, pass2_mv, pass2_mxv = _rank_with_qset(qualified_set)
                        new_qset = _qualified_for_top10(new_top10)
                        added = sorted(new_qset - qualified_set)
                        removed = sorted(qualified_set - new_qset)
                        if not added and not removed:
                            print(f"\nQualified set converged after {iteration} iteration(s).")
                            current_top10 = new_top10
                            converged = True
                            break
                        print(
                            f"\nIteration {iteration}: qualified set changed. "
                            f"+{len(added)} added, -{len(removed)} removed."
                        )
                        if added:
                            print(f"  added: {', '.join(added)}")
                        if removed:
                            print(f"  removed: {', '.join(removed)}")
                        # Detect oscillation: if we've already seen this exact set, stop.
                        if any(new_qset == prev for prev in seen_qsets):
                            print(
                                f"  → oscillation detected (set repeats a previous iteration); "
                                f"stopping at iteration {iteration}."
                            )
                            current_top10 = new_top10
                            qualified_set = new_qset
                            break
                        seen_qsets.append(new_qset)
                        qualified_set = new_qset
                        current_top10 = new_top10
                    else:
                        print(
                            f"\nReached MAX_QUALIFIED_ITERATIONS ({MAX_QUALIFIED_ITERATIONS}) "
                            f"without convergence. Using last computed qualified set."
                        )

                    qualified_benchmarks = qualified_set

                    print(f"\nFinal qualified benchmarks ({len(qualified_set)} of {len(benchmark_headers)}, "
                          f"threshold >= {QUALIFIED_THRESHOLD}/10 of Pass 2 Top 10):")
                    for b in sorted(qualified_set):
                        count = sum(
                            1 for e in current_top10
                            if e.columns.get(b, "") not in MISSING_VALUE_MARKERS
                        )
                        print(f"  ✓ {b}  ({count}/10)")

                    print(f"\nFinal Pass 2 Top 10:")
                    for i, e in enumerate(current_top10, 1):
                        print(f"  {i:>2}. {e.name} ({e.country})")

                    benchmark_min_max = pass2_bmm
                    min_avg_iq = pass2_miq
                    max_avg_iq = pass2_maq
                    min_value = pass2_mv
                    max_value = pass2_mxv

                    print(f"\nPass 2 scoring applied. Non-qualified benchmarks are kept as raw columns "
                          f"but excluded from AvgIQ / Unified.")

                # -----------------------------------------------------------------
                # From here on, every helper is called with qualified_benchmarks, so
                # if Pass 2 ran it governs scoring. If Pass 2 fell back, the variable
                # stays None and the helpers behave exactly as Pass 1.
                # -----------------------------------------------------------------

                print(format_table(
                    us_entries,
                    "🇺🇸 United States - Top 10 Models (Enriched)",
                    all_headers,
                    max_col_width=args.max_col_width,
                    include_derived=True,
                    benchmark_headers=benchmark_headers,
                    participation=participation_counts,
                    max_participation=max_participation,
                    min_avg_iq=min_avg_iq,
                    max_avg_iq=max_avg_iq,
                    min_value=min_value,
                    max_value=max_value,
                    benchmark_min_max=benchmark_min_max,
                    qualified_benchmarks=qualified_benchmarks,
                ))

                print(format_table(
                    cn_entries,
                    "🇨🇳 China - Top 10 Models (Enriched)",
                    all_headers,
                    max_col_width=args.max_col_width,
                    include_derived=True,
                    benchmark_headers=benchmark_headers,
                    participation=participation_counts,
                    max_participation=max_participation,
                    min_avg_iq=min_avg_iq,
                    max_avg_iq=max_avg_iq,
                    min_value=min_value,
                    max_value=max_value,
                    benchmark_min_max=benchmark_min_max,
                    qualified_benchmarks=qualified_benchmarks,
                ))

                # Metadata stage used to also write stage3_us.csv and stage3_cn.csv,
                # but models.json is the real output and those CSVs were redundant
                # clutter. They're intentionally not written here.

            # Write JSON if requested (or always for metadata stage, unless dry-run)
            if (args.write_json or stage == "metadata") and not args.dry_run:
                print("\nWriting JSON...")
                backup_path = backup_models_json(models_path)
                new_entry = build_history_entry(
                    us_entries,
                    cn_entries,
                    all_headers,
                    benchmark_headers,
                    participation_counts,
                    max_participation,
                    min_avg_iq,
                    max_avg_iq,
                    min_value,
                    max_value,
                    benchmark_min_max=benchmark_min_max,
                    qualified_benchmarks=qualified_benchmarks,
                )
                prepend_history(models_path, new_entry)

                # Bump sitemap.xml <lastmod> on the daily-refresh URLs so crawlers
                # actually see the new content as fresh. Uses the new entry's
                # timestamp date so local-time / UTC don't drift apart.
                ts_iso = new_entry.get("timestamp", "")
                try:
                    run_date = ts_iso[:10] if ts_iso else datetime.now().strftime("%Y-%m-%d")
                    update_sitemap_lastmod(workspace_dir / "sitemap.xml", run_date=run_date)
                except Exception as sitemap_err:
                    print(f"Warning: could not update sitemap.xml: {sitemap_err}")

                # Refresh the "Updated <Month Year>" suffix in index.html's meta
                # description so SEO previews (Google / social cards) reflect the
                # current month, not whatever month the file was last hand-edited.
                try:
                    update_index_meta_description(workspace_dir / "index.html", run_date=run_date)
                except Exception as meta_err:
                    print(f"Warning: could not update index.html meta description: {meta_err}")

                # The backup is a pre-write safety net — once prepend_history has
                # successfully rewritten models.json, git is the real recovery
                # mechanism and the backup is just noise in the workspace.
                try:
                    if backup_path and backup_path.exists():
                        backup_path.unlink()
                        print(f"Removed backup {backup_path.name} (models.json write succeeded)")
                except Exception as cleanup_err:
                    print(f"Warning: could not remove backup {backup_path.name}: {cleanup_err}")

                print(f"\nTimestamp: {new_entry['timestamp']}")
                print(f"US models: {len(us_entries)}")
                print(f"CN models: {len(cn_entries)}")
            elif args.dry_run and stage == "metadata":
                # In dry-run mode, still build the entry so we can preview it, but
                # don't touch models.json.
                new_entry = build_history_entry(
                    us_entries,
                    cn_entries,
                    all_headers,
                    benchmark_headers,
                    participation_counts,
                    max_participation,
                    min_avg_iq,
                    max_avg_iq,
                    min_value,
                    max_value,
                    benchmark_min_max=benchmark_min_max,
                    qualified_benchmarks=qualified_benchmarks,
                )
                dry_path = workspace_dir / f"stage{stage_num}_dryrun.json"
                with open(dry_path, "w", encoding="utf-8") as f:
                    json.dump(new_entry, f, ensure_ascii=False, indent=2)
                print(f"\n[dry-run] Preview entry written to {dry_path.name} (models.json NOT modified)")
                print(f"Timestamp: {new_entry['timestamp']}")
                print(f"US models: {len(us_entries)}")
                print(f"CN models: {len(cn_entries)}")
                print(f"Benchmarks in final set: {len(benchmark_headers)}")
            
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(
        description="Scrape llm-stats.com leaderboard with staged architecture"
    )
    
    parser.add_argument(
        "--leaderboard-basic",
        action="store_true",
        help="Stage 1: Extract basic leaderboard data (rank, name, country, URL)"
    )
    
    parser.add_argument(
        "--leaderboard-full",
        action="store_true",
        help="Stage 2: Extract all leaderboard columns with derived scores"
    )
    
    parser.add_argument(
        "--write-json",
        action="store_true",
        help="Write output to models.json (auto-enabled for Stage 3)"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the pipeline without modifying models.json. Metadata stage writes "
             "a preview to stageN_dryrun.json instead."
    )
    
    parser.add_argument(
        "--max-col-width",
        type=int,
        default=36,
        help="Maximum column width for table output (default: 36)"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Run browser in visible mode (not headless)"
    )

    parser.add_argument(
        "--no-gap-fill",
        action="store_true",
        help="Skip the AI gap-filling pass entirely. Pass 1 and Pass 2 still run."
    )

    parser.add_argument(
        "--gap-fill-max-calls",
        type=int,
        default=40,
        help="Maximum number of OpenAI calls per gap-filling pass (default: 40). "
             "Set low (e.g. 2) for smoke testing."
    )

    args = parser.parse_args()
    
    run_scraper(args)


if __name__ == "__main__":
    main()
