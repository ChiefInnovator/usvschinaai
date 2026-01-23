#!/usr/bin/env python3
"""
Scrape LLM leaderboard data from llm-stats.com with staged architecture.
Supports --leaderboard-basic (Stage 1), --leaderboard-full (Stage 2), and full scrape (Stage 3).
"""
import argparse
import csv
import json
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from playwright.sync_api import sync_playwright


@dataclass
class LeaderboardEntry:
    """Represents a single model row from the leaderboard table."""
    rank: int
    name: str
    country: str
    url: str
    columns: Dict[str, str] = field(default_factory=dict)  # Header -> raw value
    
    # Stage 3 metadata (populated later)
    company: str = ""
    company_link: str = ""
    description: str = ""
    created: str = ""


def parse_to_number(value: str) -> float:
    """Convert raw string to number for calculations. Non-numeric → 0."""
    if not value or not isinstance(value, str):
        return 0.0
    
    cleaned = value.replace("%", "").replace(",", "").replace("$", "").strip()
    
    # Handle common placeholders
    if cleaned in ["-", "n/a", "N/A", "", "null", "None"]:
        return 0.0
    
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def calculate_derived_scores(
    entry: LeaderboardEntry,
    benchmark_headers: List[str],
    participation: Optional[Dict[str, int]] = None,
    max_participation: Optional[int] = None,
    min_avg_iq: Optional[float] = None,
    max_avg_iq: Optional[float] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    benchmark_min_max: Optional[Dict[str, tuple]] = None
) -> Dict[str, float]:
    """Calculate total, avgIq, value, unified from raw columns with participation weighting.
    If benchmark_min_max provided, normalize each benchmark score to 0-100 before weighting.
    If min/max values provided, normalize AvgIQ and Value to 0-100 before computing Unified.
    """
    if participation is None:
        participation = {}
    if not max_participation or max_participation <= 0:
        max_participation = max(participation.values(), default=1)
    if max_participation <= 0:
        max_participation = 1
    if benchmark_min_max is None:
        benchmark_min_max = {}
    
    total_weighted = 0.0
    weight_sum = 0.0
    for b in benchmark_headers:
        raw_val = entry.columns.get(b, "")
        # Skip missing/placeholder cells
        if raw_val in ["", "-", "n/a", "N/A", "null", "None"]:
            continue
        # Skip benchmarks with a single participant across the cohort
        part = participation.get(b, 0) if participation else 0
        if part <= 1:
            continue

        score = parse_to_number(raw_val)
        
        # Normalize benchmark score to 0-100 if min/max available
        if b in benchmark_min_max:
            min_b, max_b = benchmark_min_max[b]
            if max_b > min_b:
                score = ((score - min_b) / (max_b - min_b)) * 100
        
        # Participation-based weight; fallback to 1 if not provided
        weight = (part / max_participation) if max_participation else 1.0
        total_weighted += score * weight
        weight_sum += weight
    
    avg_iq = total_weighted / weight_sum if weight_sum > 0 else 0.0
    
    # Value (avgIq / total cost: input + output)
    cost_in = parse_to_number(entry.columns.get("Input $/M", "0"))
    cost_out = parse_to_number(entry.columns.get("Output $/M", "0"))
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
    
    # Unified (70% normalized capability, 30% normalized cost efficiency)
    unified = norm_avg_iq * 0.7 + norm_value * 0.3
    # Scale final Unified by 10 as requested
    unified *= 10
    
    return {
        "total": round(total_weighted, 2),
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
    benchmark_min_max: Optional[Dict[str, tuple]] = None
):
    """Write entries to CSV file."""
    # Remove empty headers to avoid blank columns (llm-stats sometimes emits an empty col)
    cleaned_headers = [h for h in headers if h.strip()]
    csv_headers = [rank_column_name, "Model", "Country"] + cleaned_headers
    if include_derived and benchmark_headers:
        csv_headers.extend(["AvgIQ", "Value", "Unified"])
    
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(csv_headers)
        
        for entry in entries:
            row = [entry.rank, entry.name, entry.country]
            
            # Add column values
            for header in cleaned_headers:
                if header == "URL":
                    row.append(entry.url)
                else:
                    row.append(entry.columns.get(header, ""))
            
            # Add derived scores with normalization
            if include_derived and benchmark_headers:
                scores = calculate_derived_scores(entry, benchmark_headers, participation, max_participation, min_avg_iq, max_avg_iq, min_value, max_value, benchmark_min_max=benchmark_min_max)
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
    benchmark_min_max: Optional[Dict[str, tuple]] = None
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
    benchmark_min_max: Optional[Dict[str, tuple]] = None
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
            scores = calculate_derived_scores(entry, benchmark_headers, participation, max_participation, min_avg_iq, max_avg_iq, min_value, max_value, benchmark_min_max=benchmark_min_max)
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
    
    # Apply country filter
    country_button = page.wait_for_selector("button:has-text('Country')", timeout=10000)
    country_button.click()
    time.sleep(1)
    
    # Try different selectors for country option
    country_selectors = [
        f"text='🇨🇳 {country_name}'",
        f"text='🇺🇸 {country_name}'",
        f"text='{country_name}'"
    ]
    
    country_option = None
    for selector in country_selectors:
        try:
            country_option = page.wait_for_selector(selector, timeout=5000)
            if country_option:
                break
        except:
            continue
    
    if not country_option:
        print(f"ERROR: Could not find {country_name} option")
        return [], [], []
    
    country_option.click()
    time.sleep(2)
    
    # Extract all table headers
    header_elements = page.query_selector_all("thead th")
    all_headers = [h.inner_text().strip() for h in header_elements]
    print(f"  Found {len(all_headers)} columns")
    
    # Identify benchmark columns
    metadata_columns = {
        "Rank", "Model", "Country", "License", "Context", "Input", "Output",
        "Speed", "Organization", "Created", "Description", "Input $/M", "Output $/M"
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
                # Special handling for Multimodal column: green checkmark = Yes, grey X = No
                if header == "Multimodal":
                    html = cells[col_idx].inner_html()
                    
                    # Check for green checkmark (lucide-check class with green color)
                    is_checkmark = ("lucide-check" in html) or ("text-green" in html)
                    
                    # Check for X icon (lucide-x or lucide-close class with grey/neutral color)
                    is_x = ("lucide-x" in html or "lucide-close" in html) or ("text-gray" in html or "text-neutral" in html)
                    
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


def enrich_with_metadata(page, entries: List[LeaderboardEntry]) -> List[LeaderboardEntry]:
    """Navigate to each model page and extract company, description, etc."""
    print(f"\nEnriching {len(entries)} models with metadata from detail pages...")
    
    for i, entry in enumerate(entries):
        print(f"  [{i+1}/{len(entries)}] {entry.name}")
        
        try:
            page.goto(entry.url, timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(1)
            
            # Try to extract company/organization from the page
            try:
                company_elem = page.query_selector("text=/Organization|Company/i")
                if company_elem:
                    parent = company_elem.evaluate_handle("el => el.parentElement")
                    company_text = parent.as_element().inner_text() if parent else ""
                    entry.company = company_text.replace("Organization", "").replace("Company", "").strip()[:100]
            except:
                pass
            
            # Try meta description
            try:
                desc_elem = page.query_selector("meta[name='description']")
                if desc_elem:
                    desc = desc_elem.get_attribute("content")
                    if desc:
                        entry.description = desc[:200]
            except:
                pass
            
            # Company link
            entry.company_link = entry.url
            
        except Exception as e:
            print(f"    Warning: Failed to fetch metadata - {e}")
            continue
    
    return entries


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
    max_participation: Optional[int] = None
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
        scores = calculate_derived_scores(entry, benchmark_headers, participation, max_participation)
        
        row = {
            "model": entry.name,
            "company": entry.company,
            "link": entry.url,
            "origin": entry.country,
            "description": entry.description,
            "created": entry.created,
            "total": scores["total"],
            "avgIq": scores["avgIq"],
            "value": scores["value"],
            "unified": scores["unified"]
        }
        
        # Add all raw column values
        for header, value in entry.columns.items():
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
    
    with open(models_path, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"\n✅ Successfully prepended entry to models.json")


def build_benchmark_participation(entries: List[LeaderboardEntry], benchmark_headers: List[str]) -> Tuple[Dict[str, int], int]:
    """Count participation per benchmark and return counts with max participation."""
    counts: Dict[str, int] = {b: 0 for b in benchmark_headers}
    for entry in entries:
        for b in benchmark_headers:
            raw_val = entry.columns.get(b, "")
            if raw_val not in ["", "-", "n/a", "N/A", "null", "None"]:
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
                        if raw_val and raw_val not in ["", "-", "n/a", "N/A", "null", "None"]:
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
                us_entries = enrich_with_metadata(page, us_entries)
                cn_entries = enrich_with_metadata(page, cn_entries)
                
                print(format_table(
                    us_entries,
                    "🇺🇸 United States - Top 10 Models (Enriched)",
                    all_headers,
                    max_col_width=args.max_col_width,
                    include_derived=True,
                    benchmark_headers=benchmark_headers,
                    participation=participation_counts,
                    max_participation=max_participation
                ))
                
                print(format_table(
                    cn_entries,
                    "🇨🇳 China - Top 10 Models (Enriched)",
                    all_headers,
                    max_col_width=args.max_col_width,
                    include_derived=True,
                    benchmark_headers=benchmark_headers,
                    participation=participation_counts,
                    max_participation=max_participation
                ))
                
                print("\nWriting CSV files...")
                write_csv(us_entries, workspace_dir / f"stage{stage_num}_us.csv", all_headers, include_derived=True, benchmark_headers=benchmark_headers, participation=participation_counts, max_participation=max_participation)
                write_csv(cn_entries, workspace_dir / f"stage{stage_num}_cn.csv", all_headers, include_derived=True, benchmark_headers=benchmark_headers, participation=participation_counts, max_participation=max_participation)
            
            # Write JSON if requested (or always for metadata stage)
            if args.write_json or stage == "metadata":
                print("\nWriting JSON...")
                backup_models_json(models_path)
                new_entry = build_history_entry(us_entries, cn_entries, all_headers, benchmark_headers, participation_counts, max_participation)
                prepend_history(models_path, new_entry)
                
                print(f"\nTimestamp: {new_entry['timestamp']}")
                print(f"US models: {len(us_entries)}")
                print(f"CN models: {len(cn_entries)}")
            
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
    
    args = parser.parse_args()
    
    run_scraper(args)


if __name__ == "__main__":
    main()
