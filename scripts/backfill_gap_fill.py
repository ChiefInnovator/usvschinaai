#!/usr/bin/env python3
"""Retroactively run the AI gap-filling pass over stored history snapshots.

The daily scraper runs the gap-filling pass live, before Pass 1, so the day it
runs it enriches that day's snapshot only (docs/ai_gap_filling.md). The pass
was dark between 2026-04-25 and 2026-09-03, which left every snapshot in that
window scored on un-enriched data. This script replays the pass over the
snapshots we already have in models.json.

Cache economics: gap_fill_benchmarks caches positive results per
(model, benchmark) with a 30-day TTL, so a model researched for the first
snapshot is free for the other 34 days. The API cost scales with the number of
DISTINCT models across the window, not with the number of days.

Anachronism caveat: a score researched today is written into a snapshot from
weeks ago. The cache does not record when a vendor published the number, so a
backfilled cell may be a result that did not exist on that snapshot's date.
That is the accepted trade-off — the alternative is leaving the window empty.

Usage:
    python3 scripts/backfill_gap_fill.py --dry-run
    python3 scripts/backfill_gap_fill.py --days 35 --max-calls 60
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

from benchmark_names import canonicalize_benchmark_name  # noqa: E402
from validate_models import META_KEYS  # noqa: E402
import gap_fill_benchmarks as gf  # noqa: E402

MODELS_JSON = REPO_ROOT / "models.json"
CURRENT_JSON = REPO_ROOT / "current.json"

# The daily scrape researches a handful of cells and can afford the strong
# model. A 35-day backfill researches every distinct model in the window at
# once, so it runs on the cheapest tier instead — roughly 10x less per call
# than gpt-5.6-terra. gap_fill_benchmarks' comment warns that the weak tier is
# likelier to hallucinate a score; the counterweight is that fills below
# "high" confidence are dropped (--min-confidence), every accepted fill records
# its source URL in _provenance, and the daily pass keeps using the strong
# chain. Override with --model.
BACKFILL_MODEL = "gpt-5.6-luna"
DEFAULT_DAYS = 45

# Row fields that are bookkeeping, not leaderboard columns. META_KEYS covers
# the metadata/aggregate columns the scraper itself excludes from scoring
# (a test keeps the two definitions in step); these are the extra keys
# build_history_entry adds on the way into models.json.
EXTRA_NON_BENCHMARK = {"_coverage", "_provisional", "rank", "Rank"}


class HistoryEntry:
    """LeaderboardEntry-shaped adapter over one models.json history row.

    gap_fill_benchmarks only touches .name / .country / .url / .columns, so a
    duck-typed wrapper is enough and avoids importing scrape_models (which
    pulls in Playwright).
    """

    def __init__(self, row: Dict[str, Any], columns: Dict[str, Any]):
        self.row = row
        self.name = row.get("model", "")
        self.country = row.get("origin", "")
        self.url = row.get("link", "")
        self.columns = columns


def build_display_names(rows_keys: set) -> Dict[str, str]:
    """Map each space-stripped row key to the header spelling the pass expects.

    build_history_entry writes columns as ``header.replace(" ", "")``, so
    "SWE-bench Verified" is stored as "SWE-benchVerified". The gap-fill cache
    and audit log are keyed by the original spaced header, so a raw row key
    would miss every cached multi-word benchmark. Recover the original from
    the cache and audit log, which together hold every name the pass has ever
    used, matching on the canonical (alphanumeric-only) form.
    """
    canon_to_original: Dict[str, str] = {}

    def offer(name: str) -> None:
        canon = canonicalize_benchmark_name(name)
        # Prefer a spaced spelling over a squashed one when both are seen.
        if canon not in canon_to_original or (" " in name and " " not in canon_to_original[canon]):
            canon_to_original[canon] = name

    cache = gf.load_cache()
    for benchmarks in cache.values():
        for name in benchmarks:
            offer(name)
    if gf.AUDIT_FILE.exists():
        with open(gf.AUDIT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    offer(json.loads(line)["benchmark"])
                except (json.JSONDecodeError, KeyError):
                    continue

    return {k: canon_to_original.get(canonicalize_benchmark_name(k), k) for k in rows_keys}


def snapshot_benchmark_keys(snapshot: Dict[str, Any]) -> List[str]:
    """Row keys in this snapshot that are scoreable benchmark columns."""
    keys: List[str] = []
    seen = set()
    for rows in snapshot.get("teams", {}).values():
        for row in rows:
            for k in row:
                if k in seen or k in META_KEYS or k in EXTRA_NON_BENCHMARK:
                    continue
                if k.startswith("_"):
                    continue
                seen.add(k)
                keys.append(k)
    return keys


def hydrate(snapshot: Dict[str, Any], display: Dict[str, str]) -> List[HistoryEntry]:
    """Wrap a snapshot's rows as gap-fill entries, keyed by display header.

    Order matters: get_top_cohort() takes the first 10 rows per country as the
    reference set, and models.json stores each team already ranked, so US rows
    then CN rows reproduces the scraper's cohort.
    """
    entries: List[HistoryEntry] = []
    for country in ("US", "CN"):
        for row in snapshot.get("teams", {}).get(country, []):
            columns: Dict[str, Any] = {
                "Organization": row.get("organization", ""),
                "description": row.get("description", ""),
                "Released": row.get("created", ""),
            }
            for k, v in row.items():
                if k in META_KEYS or k in EXTRA_NON_BENCHMARK or k.startswith("_"):
                    continue
                columns[display.get(k, k)] = v
            prov = row.get("_provenance")
            if isinstance(prov, dict):
                columns["_provenance"] = {display.get(k, k): v for k, v in prov.items()}
            entries.append(HistoryEntry(row, columns))
    return entries


def write_back(entries: List[HistoryEntry]) -> int:
    """Copy filled cells and provenance from entry.columns back onto the rows.

    Uses the same key transform as build_history_entry so a backfilled row is
    indistinguishable in shape from one the scraper wrote.
    """
    filled = 0
    for entry in entries:
        for header, value in entry.columns.items():
            if header in ("Organization", "description", "Released"):
                continue
            if header == "_provenance" and isinstance(value, dict):
                entry.row["_provenance"] = {k.replace(" ", ""): v for k, v in value.items()}
                continue
            key = header.replace(" ", "")
            if entry.row.get(key) != value:
                entry.row[key] = value
                filled += 1
    return filled


def apply_cached(snapshots: List[Tuple[str, Dict[str, Any]]], display: Dict[str, str],
                 min_confidence: str) -> int:
    """Apply only the fills already in the cache — no API key, no calls.

    run_gap_filling_pass returns early when OPENAI_API_KEY is missing, so it
    cannot be used to spend the cache on its own. This is the part of the
    backfill that is available before the key is rotated: every
    (model, benchmark) the pass has already researched, written into every
    snapshot in the window that still has the cell empty.
    """
    cache = gf.load_cache()
    now = datetime.now(timezone.utc)
    total = 0
    for day, snap in snapshots:
        entries = hydrate(snap, display)
        headers = [display.get(k, k) for k in snapshot_benchmark_keys(snap)]
        applied = 0
        for cand in gf.build_candidates(entries, headers, enabled_tiers=frozenset({1, 2})):
            cached = cache.get(cand.model_name, {}).get(cand.benchmark)
            if not cached or not gf.cache_is_fresh(cached, now):
                continue
            if min_confidence == "high" and cached.get("confidence") != "high":
                continue
            if gf._apply_fill(entries, cand, cached, cached.get("llm_model", "")):
                applied += 1
        written = write_back(entries)
        total += written
        if written:
            print(f"  {day}: {applied} cached fills applied, {written} cells written")
    return total


def daily_snapshots(history: List[Dict[str, Any]], days: int) -> List[Tuple[str, Dict[str, Any]]]:
    """Latest snapshot per UTC day within the window, newest day first.

    One snapshot per day matches what the site and the 30-day trend read
    (social_formats.per_day_series), so backfilling the also-rans on a
    multi-run day would spend API budget on rows nothing renders.
    """
    if not history:
        return []
    newest = datetime.fromisoformat(history[0]["timestamp"])
    cutoff = newest - timedelta(days=days)
    byday: Dict[str, Dict[str, Any]] = {}
    for snap in history:  # newest-first, so the first per day is the latest
        ts = snap.get("timestamp", "")
        try:
            when = datetime.fromisoformat(ts)
        except ValueError:
            continue
        if when < cutoff:
            continue
        byday.setdefault(ts[:10], snap)
    return sorted(byday.items(), key=lambda kv: kv[0], reverse=True)


def analyze(snapshots: List[Tuple[str, Dict[str, Any]]], display: Dict[str, str]) -> None:
    """Dry-run report: candidates, cache coverage and the live-call estimate."""
    cache = gf.load_cache()
    now = datetime.now(timezone.utc)

    total_candidates = 0
    cached_resolvable = 0
    needs_call: Dict[Tuple[str, str], set] = {}
    per_day: List[Tuple[str, int, int]] = []

    for day, snap in snapshots:
        entries = hydrate(snap, display)
        headers = [display.get(k, k) for k in snapshot_benchmark_keys(snap)]
        candidates = gf.build_candidates(entries, headers, enabled_tiers=frozenset({1, 2}))
        day_cached = 0
        for cand in candidates:
            entry = cache.get(cand.model_name, {}).get(cand.benchmark)
            if entry and gf.cache_is_fresh(entry, now):
                day_cached += 1
                cached_resolvable += 1
            else:
                needs_call.setdefault((cand.model_name, cand.model_country), set()).add(cand.benchmark)
        total_candidates += len(candidates)
        per_day.append((day, len(candidates), day_cached))

    print(f"\nDays in window: {len(snapshots)}  "
          f"({snapshots[-1][0]} .. {snapshots[0][0]})")
    print(f"Gap candidates across the window: {total_candidates}")
    print(f"  resolvable from the existing cache: {cached_resolvable}")
    print(f"  needing a live lookup:              {total_candidates - cached_resolvable}")
    print(f"\nDistinct (model, benchmark) pairs to research: "
          f"{sum(len(v) for v in needs_call.values())}")
    print(f"Batched API calls required (one per model): {len(needs_call)}")

    print("\nPer day (candidates / already cached):")
    for day, n, c in per_day:
        print(f"  {day}  {n:4d} / {c:4d}")

    if needs_call:
        print("\nModels needing a live lookup:")
        for (name, country), bms in sorted(needs_call.items(), key=lambda kv: -len(kv[1])):
            print(f"  {name} ({country}) — {len(bms)}: {', '.join(sorted(bms))}")


# ---------------------------------------------------------------------------
# Re-scoring - owner decision 2026-09-04 (reverses the earlier "cells only")
# ---------------------------------------------------------------------------
# After cells are filled, each snapshot in the window is re-scored with the
# SAME implementation the daily run uses (scripts/scoring.py). The cohort is
# left exactly as it was - no deduping, no additions, no drops - only the
# numbers change, and the top 10 falls out of the filled data. Each row keeps
# its originally published scores under `_prior` the first time it is
# re-scored, so the change is auditable and reversible.

SCORE_KEYS = ("avgIq", "value", "unified", "coverage")


class ScoreEntry:
    """Row -> the duck type scoring.score_cohort needs (.columns, .name, .country)."""
    def __init__(self, row: Dict[str, Any], country: str):
        self.row, self.name, self.country, self.url = row, row.get("model", ""), country, row.get("link", "")
        self.columns: Dict[str, Any] = {k: v for k, v in row.items() if isinstance(v, str)}
        self.columns["Organization"] = row.get("organization", "")
        self.columns["Released"] = row.get("created", "")


def scoring_headers(entries: List["ScoreEntry"]) -> List[str]:
    """Benchmark columns present in the snapshot, by the validator's definition."""
    keys = set()
    for e in entries:
        keys.update(k for k in e.columns if k not in META_KEYS and k not in EXTRA_NON_BENCHMARK
                    and k not in ("Organization", "Released", "description") and not k.startswith("_"))
    return sorted(keys)


def rescore_snapshot(snapshot: Dict[str, Any]) -> int:
    """Re-score one snapshot in place. Returns how many rows changed."""
    from scoring import build_benchmark_participation, MIN_COHORT_PARTICIPATION, score_cohort
    entries = [ScoreEntry(r, c) for c in ("US", "CN") for r in snapshot.get("teams", {}).get(c, [])]
    if not entries:
        return 0
    headers = scoring_headers(entries)
    # Mirror the daily run's sparse drop for scoring purposes WITHOUT deleting
    # the cells from history: score only benchmarks enough of the cohort report.
    counts, _ = build_benchmark_participation(entries, headers)
    headers = [b for b in headers if counts.get(b, 0) >= MIN_COHORT_PARTICIPATION]
    result = score_cohort(entries, headers, drop_sparse=False, log=lambda *a, **k: None)
    changed = 0
    for e in entries:
        s = result.scores_for(e)
        n, q = result.coverage(e)
        new = {"avgIq": s["avgIq"], "value": s["value"], "unified": s["unified"],
               "coverage": f"{n}/{q}" if q else ""}
        old = {k: e.row.get(k) for k in SCORE_KEYS}
        if any(old.get(k) != new[k] for k in SCORE_KEYS):
            e.row.setdefault("_prior", {k: old[k] for k in SCORE_KEYS if old.get(k) is not None})
            e.row.update(new)
            changed += 1
    return changed


def rescore_window(snapshots: List[Tuple[str, Dict[str, Any]]]) -> int:
    total = 0
    for day, snap in snapshots:
        n = rescore_snapshot(snap)
        total += n
        print(f"[rescore] {day}: {n} rows re-scored")
    return total


def recompute_badges(data: Dict[str, Any]) -> None:
    """Same aggregation as prepend_history: top-10 unified totals decide the badges."""
    history = data.get("history") or []
    if not history:
        return
    rows = [m for team in history[0].get("teams", {}).values() for m in team]
    top10 = sorted(rows, key=lambda m: -float(m.get("unified", 0)))[:10]
    us = sum(float(m.get("unified", 0)) for m in top10 if m.get("origin") == "US")
    cn = sum(float(m.get("unified", 0)) for m in top10 if m.get("origin") == "CN")
    teams = data.get("teams", {})
    if "usa" in teams and "china" in teams:
        if us == cn:
            teams["usa"]["badge"] = teams["china"]["badge"] = "TIED"
        else:
            teams["usa"]["badge"] = "OVERALL WINNER" if us > cn else "RUNNER UP"
            teams["china"]["badge"] = "OVERALL WINNER" if cn > us else "RUNNER UP"


def save(data: Dict[str, Any], models_path: Path) -> None:
    """Write models.json, and re-emit current.json from its newest entry.

    Mirrors prepend_history's dual write so index.html (which reads the small
    current.json) does not drift from the archive it was derived from.
    """
    with open(models_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"[backfill] wrote {models_path}")
    if models_path == MODELS_JSON:
        current = {k: v for k, v in data.items() if k != "history"}
        current["history"] = data["history"][:1]
        with open(CURRENT_JSON, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)
        print(f"[backfill] wrote {CURRENT_JSON}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS,
                    help=f"Window size in days, counted back from the newest snapshot (default: {DEFAULT_DAYS})")
    ap.add_argument("--no-rescore", action="store_true",
                    help="Fill cells only; leave avgIq/value/unified as published (the pre-2026-09-04 behaviour)")
    ap.add_argument("--rescore-only", action="store_true",
                    help="Make no fills; just re-score every snapshot in the window with today's scorer")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report what would be filled; make no API calls and write nothing")
    ap.add_argument("--cache-only", action="store_true",
                    help="Apply only fills already in data/ai_gap_cache.json; never call the API")
    ap.add_argument("--max-calls", type=int, default=gf.DEFAULT_MAX_CALLS,
                    help=f"Live API call ceiling for the whole run (default: {gf.DEFAULT_MAX_CALLS})")
    ap.add_argument("--model", default=BACKFILL_MODEL,
                    help=f"Research model for this run (default: {BACKFILL_MODEL}). "
                         "Set to a chain entry from gap_fill_benchmarks.DEFAULT_MODEL_CHAIN "
                         "to match the daily scrape instead.")
    ap.add_argument("--min-confidence", default="high", choices=("high", "any"),
                    help="Drop fills below this confidence (default: high)")
    ap.add_argument("--models-json", type=Path, default=MODELS_JSON)
    args = ap.parse_args()

    # gap_fill_benchmarks reads the model from the environment and still
    # walks its fallback chain if the account cannot call this one.
    os.environ["AI_GAP_FILL_MODEL"] = args.model

    with open(args.models_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    history = data.get("history") or []
    snapshots = daily_snapshots(history, args.days)
    if not snapshots:
        print("No snapshots in the requested window; nothing to do.")
        return 0

    all_keys = set()
    for _, snap in snapshots:
        all_keys.update(snapshot_benchmark_keys(snap))
    display = build_display_names(all_keys)

    if args.dry_run:
        analyze(snapshots, display)
        return 0

    def finish(total_filled: int) -> int:
        rescored = 0
        if not args.no_rescore:
            rescored = rescore_window(snapshots)
            recompute_badges(data)
            print(f"[rescore] {rescored} rows re-scored across {len(snapshots)} days")
        if total_filled or rescored:
            save(data, args.models_json)
        return 0

    if args.rescore_only:
        print(f"\n[backfill] rescore-only over {len(snapshots)} days "
              f"({snapshots[-1][0]} .. {snapshots[0][0]})")
        return finish(0)

    if args.cache_only:
        print(f"\n[backfill] cache-only over {len(snapshots)} days "
              f"({snapshots[-1][0]} .. {snapshots[0][0]})")
        total_filled = apply_cached(snapshots, display, args.min_confidence)
        print(f"\n[backfill] {total_filled} cells filled from cache")
        return finish(total_filled)

    # --max-calls is a ceiling on the whole run, not per day, so the count has
    # to survive across days. run_gap_filling_pass reports fills, not calls,
    # and one batched call caches many cells — counting cache growth would
    # overcharge the budget several-fold. Count the HTTP calls themselves.
    calls_made = 0
    real_query = gf.query_openai_responses

    def counting_query(*a, **kw):
        nonlocal calls_made
        calls_made += 1
        return real_query(*a, **kw)

    gf.query_openai_responses = counting_query

    total_filled = 0
    try:
        # Spent newest-day first, so if the ceiling bites it is the stale end
        # of the window that goes unfilled.
        for day, snap in snapshots:
            remaining = args.max_calls - calls_made
            if remaining <= 0:
                print(f"\n[backfill] call budget exhausted; stopping before {day}")
                break
            entries = hydrate(snap, display)
            headers = [display.get(k, k) for k in snapshot_benchmark_keys(snap)]
            print(f"\n=== {day} ({snap.get('timestamp')}) — {len(entries)} models, "
                  f"{len(headers)} benchmark columns ===")
            try:
                gf.run_gap_filling_pass(
                    entries, headers,
                    max_calls=remaining,
                    min_confidence=args.min_confidence,
                    scraper_run_ts=f"backfill:{day}",
                )
            except Exception as e:
                print(f"[backfill] pass failed for {day} ({e}); leaving the day unchanged")
                continue
            day_filled = write_back(entries)
            total_filled += day_filled
            print(f"[backfill] {day}: {day_filled} cells written "
                  f"({calls_made}/{args.max_calls} API calls used)")
    finally:
        gf.query_openai_responses = real_query

    print(f"\n[backfill] {total_filled} cells filled across {len(snapshots)} days")
    return finish(total_filled)


if __name__ == "__main__":
    raise SystemExit(main())
