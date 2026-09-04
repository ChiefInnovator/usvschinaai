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

from benchmark_names import canonicalize_benchmark_name, is_artifact_header
from cohort_selection import TEAM_SIZE, min_coverage_for, select_team
from model_families import superseded_models
from scoring import (  # noqa: E402  - single scoring implementation
    BENCHMARK_KNOWN_RANGES, MISSING_VALUE_MARKERS, build_benchmark_participation,
    calculate_derived_scores, entry_has_pricing, parse_to_number,
    resolve_benchmark_range, score_cohort, drop_sparse_benchmarks,
)

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


# Deduplicated, released candidates kept per country through enrichment and
# scoring. The published top 10 is chosen from this pool at the end (see
# cohort_selection.select_team), so a model removed for coverage is replaced
# rather than leaving the team short. 30 rows are parsed per country.
COHORT_POOL_SIZE = 15


def dedupe_superseded_versions(entries: List["LeaderboardEntry"]) -> List["LeaderboardEntry"]:
    """Drop rows that are older versions of another model in the same cohort.

    Freed slots backfill from the next-ranked model, the same way the
    released-only filter behaves. See scripts/model_families.py for the
    family/version rules.
    """
    superseded = superseded_models([e.name for e in entries])

    seen_names = set()
    kept = []
    for idx, entry in enumerate(entries):
        if idx in superseded:
            print(f"    -- skipping {entry.name}: superseded by {superseded[idx]}")
            continue
        # Belt and braces: the same model listed twice under one name.
        if entry.name in seen_names:
            print(f"    -- skipping {entry.name}: duplicate row")
            continue
        seen_names.add(entry.name)
        kept.append(entry)
    return kept


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
        # Not benchmarks, and each distorts the average in its own way:
        #   LLM Stats  — llm-stats' own composite OF the benchmarks, so scoring
        #                it counts every benchmark a second time.
        #   Latency    — seconds, where lower is better. Normalised as a
        #                benchmark it rewarded the slowest model: Claude Opus 5
        #                at 11.1s outscored Muse Spark 1.3 at 3.0s.
        #   CodeArena  — an Elo on a different scale with its own known range;
        #                it skews a flat average of percentages.
        # validate_models.META_KEYS already listed all three; the scraper did
        # not, and a test now asserts the two stay in step.
        "Latency", "LLM Stats", "LLMStats", "Code Arena", "CodeArena",
        # Category-level aggregates (rollups of individual benchmarks)
        "Reasoning", "Math", "Coding", "Search", "Writing", "Vision", "Tools",
        "Long Ctx", "LongCtx", "Finance", "Legal", "Health",
    }

    benchmark_headers = [h for h in all_headers if h not in metadata_columns and h]
    
    # Extract rows
    rows = page.query_selector_all("tbody tr")
    print(f"  Found {len(rows)} rows")
    
    candidates: List[LeaderboardEntry] = []
    # Parse every row rather than stopping at max_models, so that models dropped
    # by the released-only filter below — or by the superseded-version dedupe
    # after the loop — are backfilled by the next-ranked model instead of
    # shrinking the cohort. The dedupe cannot run inline because the newer
    # sibling is not guaranteed to rank above the older one.
    for i, row in enumerate(rows):
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
        
        # Released-only filter: unreleased preview/checkpoint models show no
        # date in llm-stats' Released column ("-"). They have no pricing and
        # often selective benchmark reporting, so they distort the rankings —
        # exclude them from the cohort entirely.
        released = columns.get("Released", "").strip()
        if released in ("", "-", "—", "–"):
            print(f"    -- skipping {name}: no release date (unreleased)")
            continue

        candidates.append(LeaderboardEntry(
            rank=len(candidates) + 1,
            name=name,
            country=origin_code,
            url=url,
            columns=columns
        ))

    entries = dedupe_superseded_versions(candidates)[:max_models]
    for position, entry in enumerate(entries, 1):
        entry.rank = position
        print(f"    {position}. {entry.name}")

    if len(entries) < max_models:
        print(
            f"  WARNING: only {len(entries)} of {max_models} models left for "
            f"{origin_code} after filtering ({len(candidates)} rows parsed). "
            f"Scoring assumes a cohort of {max_models}."
        )

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
                if is_artifact_header(detail_name):
                    print(f"    -- ignoring artifact header: {detail_name!r}")
                    continue
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
            "unified": scores["unified"],
            # Coverage of the qualified benchmark set this model was scored on,
            # and whether it was kept only to avoid publishing a short team.
            "coverage": entry.columns.get("_coverage", ""),
            "provisional": entry.columns.get("_provisional") == "true",
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
            if header in ("_coverage", "_provisional"):
                continue
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

    # Keep the static team badges in sync with the actual result. These were
    # once hand-written ("OVERALL WINNER" on the USA card) and went stale when
    # the lead changed hands — recompute from the new snapshot's top-10 totals
    # (same aggregation as the frontend and the OG/IG images).
    try:
        rows = [m for team in new_entry.get("teams", {}).values() for m in team]
        top10 = sorted(rows, key=lambda m: -float(m.get("unified", 0)))[:10]
        us_total = sum(float(m.get("unified", 0)) for m in top10 if m.get("origin") == "US")
        cn_total = sum(float(m.get("unified", 0)) for m in top10 if m.get("origin") == "CN")
        teams_meta = data.get("teams", {})
        if "usa" in teams_meta and "china" in teams_meta:
            if us_total == cn_total:
                teams_meta["usa"]["badge"] = teams_meta["china"]["badge"] = "TIED"
            else:
                teams_meta["usa"]["badge"] = "OVERALL WINNER" if us_total > cn_total else "RUNNER UP"
                teams_meta["china"]["badge"] = "OVERALL WINNER" if cn_total > us_total else "RUNNER UP"
    except Exception as e:
        print(f"Warning: could not recompute team badges ({e})")

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

    # Also emit current.json: identical top-level shape but history truncated
    # to the latest entry only. index.html fetches this (~40 KB) instead of the
    # full multi-MB archive; models.json remains the complete dataset that the
    # schema.org Dataset block and history.html point at.
    current = {k: v for k, v in data.items() if k != "history"}
    current["history"] = data["history"][:1]
    current_path = models_path.parent / "current.json"
    with open(current_path, 'w') as f:
        json.dump(current, f, indent=2)

    print(f"\n✅ Successfully prepended entry to models.json (+ wrote current.json)")


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


# Year-bearing strings that must not rot across a New Year rollover. Applied
# to every public page on each daily run — no manual bump needed. Patterns are
# anchored on the surrounding words so unrelated four-digit numbers (scores,
# benchmark names like "AIME 2025") are never touched.
_PAGE_YEAR_PATTERNS = (
    re.compile(r"(Compare Top AI Models )\d{4}"),
    re.compile(r"(AI Race Timeline )\d{4}"),
    re.compile(r"(&copy; )\d{4}( US vs CHINA AI)"),
)


def update_page_years(paths: List[Path], run_date: Optional[str] = None) -> bool:
    """Rewrite the year in titles/OG tags/footers on every page to the run year.

    "Compare Top AI Models 2025" was still shipping in social previews in
    Aug 2026 — this keeps those strings current automatically at each rollover.
    Returns True if any file changed.
    """
    if run_date:
        try:
            from dateutil.parser import parse as parse_date
            year = parse_date(run_date).strftime("%Y")
        except Exception:
            year = datetime.now().strftime("%Y")
    else:
        year = datetime.now().strftime("%Y")

    changed_any = False
    for path in paths:
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8")
        new_src = src
        for pat in _PAGE_YEAR_PATTERNS:
            new_src = pat.sub(lambda m: m.group(1) + year + (m.group(2) if m.lastindex and m.lastindex > 1 else ""), new_src)
        if new_src != src:
            path.write_text(new_src, encoding="utf-8")
            print(f"Updated year strings in {path.name} → {year}")
            changed_any = True
    return changed_any


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
                page, "United States", "US", max_models=COHORT_POOL_SIZE, stage=stage
            )
            
            cn_entries, cn_headers, cn_benchmarks = scrape_country_leaderboard(
                page, "China", "CN", max_models=COHORT_POOL_SIZE, stage=stage
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
                    # Unpriced models are excluded from the Value bounds — see
                    # entry_has_pricing.
                    if entry_has_pricing(e):
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

                # Sparse-benchmark drop, then gap-fill, then scoring. The scoring
                # itself lives in scripts/scoring.py - one implementation shared
                # with the history backfill so the two can never disagree.
                cohort_size = len(combined_entries)
                benchmark_headers, sparse_benchmarks = drop_sparse_benchmarks(combined_entries, benchmark_headers)
                if sparse_benchmarks:
                    sparse_set = set(sparse_benchmarks)
                    all_headers = [h for h in all_headers if h not in sparse_set]

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

                scoring = score_cohort(combined_entries, benchmark_headers, drop_sparse=False)
                benchmark_headers = scoring.benchmark_headers
                participation_counts, max_participation = scoring.participation, scoring.max_participation
                min_avg_iq, max_avg_iq = scoring.min_avg_iq, scoring.max_avg_iq
                min_value, max_value = scoring.min_value, scoring.max_value
                benchmark_min_max = scoring.benchmark_min_max
                qualified_benchmarks = scoring.qualified_benchmarks

                # -----------------------------------------------------------------
                # Pick each country's published top 10 from the pool, ranked by the
                # final unified score among models meeting minimum coverage. Under
                # a Pass 1 fallback there is no coverage concept and it is plain
                # top-N. See cohort_selection.select_team.
                # -----------------------------------------------------------------
                def _final_unified(e: LeaderboardEntry) -> float:
                    return scoring.scores_for(e)["unified"]

                def _coverage(e: LeaderboardEntry) -> int:
                    return scoring.coverage(e)[0]

                if qualified_benchmarks:
                    qualified_set = qualified_benchmarks
                    min_cov = min_coverage_for(len(qualified_set))
                    for e in combined_entries:
                        e.columns["_coverage"] = f"{_coverage(e)}/{len(qualified_set)}"
                else:
                    qualified_set, min_cov = set(), 0

                print(f"\nSelecting {TEAM_SIZE} per country from the pool "
                      f"(US {len(us_entries)}, CN {len(cn_entries)}); "
                      f"minimum coverage {min_cov}/{len(qualified_set)}:")
                picked = {}
                for code, pool in (("US", us_entries), ("CN", cn_entries)):
                    chosen, provisional = select_team(pool, _final_unified, _coverage, min_cov, TEAM_SIZE)
                    for e in provisional:
                        e.columns["_provisional"] = "true"
                    left_out = [e for e in pool if e not in chosen]
                    picked[code] = chosen
                    print(f"  {code}: {len(chosen)} chosen, {len(provisional)} provisional "
                          f"(under coverage, kept so the team is not short), {len(left_out)} left out")
                    for e in provisional:
                        print(f"     ~ {e.name} — {_coverage(e)}/{len(qualified_set)} (provisional)")
                    for e in left_out:
                        print(f"     -- {e.name} — {_coverage(e)}/{len(qualified_set)}, unified {_final_unified(e):.1f}")
                us_entries = picked["US"]
                cn_entries = picked["CN"]
                combined_entries = us_entries + cn_entries

                print(f"\nFinal Top 10:")
                for i, e in enumerate(sorted(combined_entries, key=_final_unified, reverse=True)[:10], 1):
                    print(f"  {i:>2}. {e.name} ({e.country})")

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
                    update_page_years(
                        [workspace_dir / p for p in
                         ("index.html", "history.html", "about.html", "privacy.html", "terms.html")],
                        run_date=run_date,
                    )
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
