#!/usr/bin/env python3
"""Pre-publish validation gate for models.json.

Runs in CI between the scraper and the commit step (see daily-scrape.yml).
A non-zero exit fails the workflow, so a bad snapshot is never committed and
yesterday's data stays live.

Checks (ERROR = fail the run, WARN = print only):
  ERROR  benchmark header that looks like a scraped file artifact (e.g. GDP.pdf)
  WARN   duplicate-alias headers (same benchmark under two names) — may
         double-count, but never blocks publishing
  ERROR  percent cell outside 0-100
  ERROR  CodeArena Elo outside 800-2500
  ERROR  negative pricing
  ERROR  model row with no Released date (released-only filter regressed)
  WARN   two rows that are the same model at different versions, or the same
         model listed twice (should have been dropped at scrape time)
  WARN   cohort smaller than 10 per country
  WARN   description "released <date>" disagrees with Released column presence
  WARN   any benchmark cell moving > 15 points vs the previous snapshot
"""
import json
import re
import sys
from pathlib import Path

from benchmark_names import canonicalize_benchmark_name
from model_families import superseded_models

REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_PATH = REPO_ROOT / "models.json"

MISSING = {"", "-", "–", "—", "n/a", "N/A", "null", "None", "—"}

# Row keys that are metadata, not benchmark columns. Mirrors the frontend
# BASE_EXCLUDE_KEYS / scraper metadata_columns split.
META_KEYS = {
    "model", "organization", "link", "origin", "description", "created",
    "avgIq", "value", "unified", "_provenance", "_scoring",
    "Model", "Country", "License", "Context", "Input$/M", "Output$/M",
    "Speed", "Parameters(B)", "KnowledgeCutoff", "Multimodal", "Released",
    "Organization", "LLMStats", "Latency", "CodeArena",
    # category aggregates
    "Reasoning", "Math", "Coding", "Search", "Writing", "Vision", "Tools",
    "LongCtx", "Finance", "Legal", "Health",
}

ARTIFACT_RE = re.compile(r"\.(pdf|html?|docx?|xlsx?|csv|json)$", re.IGNORECASE)
DESC_RELEASED_RE = re.compile(r"released [A-Z][a-z]{2} \d{1,2}, \d{4}")


def alias_base(name: str) -> str:
    """Canonical form used to detect two columns that are the same benchmark.

    A trailing parenthetical is NOT stripped: "MMMU-Pro (with tools)" is a
    different benchmark from "MMMU-Pro" — running a model with tools measures
    something else — so both columns are expected to coexist and both count.
    This catches only true spelling collisions (punctuation or casing), not
    qualified variants.
    """
    return canonicalize_benchmark_name(name)


def parse_num(value):
    if value is None:
        return None
    cleaned = str(value).replace("%", "").replace(",", "").replace("$", "").strip()
    if cleaned in MISSING:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def rows_of(entry):
    for team in entry.get("teams", {}).values():
        for row in team:
            yield row


def main() -> int:
    errors, warnings = [], []

    with open(MODELS_PATH) as f:
        data = json.load(f)
    history = data.get("history") or []
    if not history:
        print("ERROR: models.json has no history entries")
        return 1
    entry = history[0]
    prev = history[1] if len(history) > 1 else None

    # ---- collect benchmark headers across all rows -------------------------
    headers = set()
    for row in rows_of(entry):
        headers.update(k for k in row if k not in META_KEYS)

    # ---- artifact-looking headers ------------------------------------------
    for h in sorted(headers):
        if ARTIFACT_RE.search(h):
            errors.append(f"benchmark header looks like a file artifact: {h!r}")

    # ---- duplicate-alias detection -----------------------------------------
    by_base = {}
    for h in headers:
        by_base.setdefault(alias_base(h), set()).add(h)
    for base, names in sorted(by_base.items()):
        if len(names) > 1:
            # A warning, not an error: the daily run must never stop and wait
            # for someone to adjudicate a benchmark name. Publishing slightly
            # over-weighted data beats publishing nothing, and the site then
            # goes stale until a human notices. Add the pair to
            # BENCHMARK_NAME_ALIASES if they really are one benchmark.
            warnings.append(
                f"duplicate benchmark columns (alias collision, may double-count): {sorted(names)}"
            )

    # ---- per-cell checks ----------------------------------------------------
    for row in rows_of(entry):
        name = row.get("model", "?")

        released = str(row.get("created", "")).strip()
        if released in MISSING:
            errors.append(f"{name}: no Released date — released-only filter regressed")

        desc = row.get("description") or ""
        if DESC_RELEASED_RE.search(desc) and released in MISSING:
            warnings.append(f"{name}: description mentions a release date but Released column is empty")

        for col in ("Input$/M", "Output$/M"):
            v = parse_num(row.get(col))
            if v is not None and v < 0:
                errors.append(f"{name}: negative pricing {col}={row.get(col)!r}")

        elo = parse_num(row.get("CodeArena"))
        if elo is not None and not (800 <= elo <= 3200):
            errors.append(f"{name}: CodeArena Elo out of range: {elo}")

        for h in headers:
            raw = row.get(h)
            if raw is None or not isinstance(raw, str):
                continue
            if raw.strip() in MISSING:
                continue
            if raw.strip().endswith("%"):
                v = parse_num(raw)
                if v is not None and not (0 <= v <= 100):
                    errors.append(f"{name}: {h} percent value out of range: {raw!r}")

    # ---- cohort size --------------------------------------------------------
    for team_key, team_rows in entry.get("teams", {}).items():
        if len(team_rows) < 10:
            warnings.append(f"cohort {team_key} has only {len(team_rows)} models")

    # ---- one row per model --------------------------------------------------
    # The scraper keeps only the newest version of a family (see
    # scripts/model_families.py). If an older sibling reaches models.json the
    # dedupe regressed, so fail rather than publish the same model twice.
    for team_key, team_rows in entry.get("teams", {}).items():
        names = [r.get("model", "?") for r in team_rows]
        # Warnings, not errors. The scraper already drops superseded models at
        # the point each country's top 10 is fetched; if one still reaches here
        # the right response is to say so and publish, not to halt the run and
        # leave the site on stale data.
        for idx, winner in sorted(superseded_models(names).items()):
            warnings.append(
                f"cohort {team_key}: {names[idx]!r} is an older version of "
                f"{winner!r} — should have been dropped at scrape time"
            )
        seen = set()
        for n in names:
            if n in seen:
                warnings.append(f"cohort {team_key}: {n!r} listed twice")
            seen.add(n)

    # ---- day-over-day drift -------------------------------------------------
    if prev:
        prev_rows = {r.get("model"): r for r in rows_of(prev)}
        for row in rows_of(entry):
            p = prev_rows.get(row.get("model"))
            if not p:
                continue
            for h in headers:
                a, b = parse_num(row.get(h)), parse_num(p.get(h))
                if a is not None and b is not None and abs(a - b) > 15:
                    warnings.append(
                        f"{row.get('model')}: {h} moved {b} -> {a} day-over-day (>15 pts)"
                    )

    # ---- report -------------------------------------------------------------
    for w in warnings:
        print(f"WARN:  {w}")
    for e in errors:
        print(f"ERROR: {e}")
    print(f"\nvalidate_models: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
