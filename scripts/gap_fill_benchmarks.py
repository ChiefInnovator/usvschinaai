#!/usr/bin/env python3
"""AI gap-filling pass for the aiolympics scraper.

See docs/ai_gap_filling.md for the full specification.

Runs after sparse-benchmark drop and BEFORE Pass 1, so Pass 1 sees the enriched
data from the start. Uses OpenAI's Responses API with the web_search tool to
look up benchmark scores from public sources, validates the response against a
strict JSON schema, and writes the result back to entry.columns plus an audit
log line.
"""
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

import requests


# -----------------------------------------------------------------------------
# Constants from the spec
# -----------------------------------------------------------------------------

# Default model chain — `gpt-5.4` as the primary research model, `gpt-5.4-pro`
# as the stronger fallback if full 5.4 isn't available, and `gpt-5.3` as the
# last-resort fallback for older accounts. Override at runtime with the
# AI_GAP_FILL_MODEL env var.
DEFAULT_MODEL_CHAIN: List[str] = ["gpt-5.4", "gpt-5.4-pro", "gpt-5.3"]

# Reasoning tier for the Responses API. Research tasks don't need deep
# chain-of-thought, so "low" minimizes hidden reasoning tokens which are
# billed separately from visible output.
REASONING_EFFORT = "low"
DEFAULT_MAX_CALLS = 40

# Minimum seconds between successive OpenAI calls. Each call consumes ~9K input
# tokens because the web_search tool injects fetched page content into the
# prompt context, so firing calls back-to-back concentrates token usage and
# trips per-second rate limits even when the per-minute budget is fine.
# 1.5 seconds between calls → ~40 calls/minute → ~360K tokens/minute, which
# sits comfortably inside the 500K-per-minute TPM envelope.
REQUEST_INTERVAL_SECONDS = 1.5

# The top-tier reference for tiering is the full scraped cohort: top 10 of each
# country by llm-stats raw leaderboard rank, combined → 20 models total. The
# tier thresholds below use 80% / 75% / 40% of that 20-model reference as the
# qualified / Tier 1 / Tier 2 cutoffs, mirroring the original "8/10" framing
# scaled up to a 20-model reference.
TOP_COHORT_PER_COUNTRY = 10  # 10 US + 10 CN = 20 total reference set
QUALIFIED_THRESHOLD = 16     # 16 of 20 (80%) — already qualified, skip
TIER_1_FLOOR = 15            # 15 of 20 (75%) — one fill from qualifying
TIER_2_FLOOR = 8             # 8 of 20 (40%) — within reach with several fills
# Tier 3 = ≤ 7 of 20, permanently off in v1.

POSITIVE_CACHE_TTL_DAYS = 30
# Note: we deliberately do NOT cache negative results. A null score today
# might get published tomorrow, and the gap-fill pass's whole point is to
# discover newly-available scores. Re-querying nulls every run is the
# correct trade-off (freshness > API cost).

LOCALE_SUFFIXES: Tuple[str, ...] = ("-zh", "-ja", "-ko", "-de", "-fr", "-es", "-en")

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
OPENAI_MODELS_URL = "https://api.openai.com/v1/models"

REPO_ROOT = Path(__file__).parent.parent
DATA_DIR = REPO_ROOT / "data"
CACHE_FILE = DATA_DIR / "ai_gap_cache.json"
AUDIT_FILE = DATA_DIR / "ai_fill_history.jsonl"

# Mirror of MISSING_VALUE_MARKERS in scrape_models.py. Kept in sync manually
# because importing across modules creates a circular dep at the helper level.
MISSING_VALUE_MARKERS: FrozenSet[str] = frozenset(
    {"", "-", "\u2013", "\u2014", "n/a", "N/A", "null", "None"}
)


# -----------------------------------------------------------------------------
# Data shape
# -----------------------------------------------------------------------------


@dataclass
class GapCandidate:
    """One (model, benchmark) gap to fill."""
    model_name: str
    model_country: str  # 'US' or 'CN'
    model_url: str
    organization: str
    benchmark: str
    cohort_count: int       # full cohort coverage (out of 20)
    top_cohort_count: int   # top-tier reference coverage (out of 20)
    tier: int               # 1, 2, or 3 (3 is permanently off)


# -----------------------------------------------------------------------------
# Auth + cache + audit
# -----------------------------------------------------------------------------


def resolve_openai_key() -> Optional[str]:
    """Read OPENAI_API_KEY from the environment.

    No SDK fallback, no shell-out. In CI the key comes from
    ${{ secrets.OPENAI_API_KEY }}; locally it comes from .env (loaded by
    python-dotenv at scraper startup).
    """
    key = os.environ.get("OPENAI_API_KEY")
    return key if key else None


def load_cache() -> Dict[str, Dict[str, Any]]:
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[gap-fill] Warning: corrupted ai_gap_cache.json ({e}); starting fresh")
        return {}


def save_cache(cache: Dict[str, Dict[str, Any]]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)


def append_audit_entry(entry: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with open(AUDIT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def cache_is_fresh(entry: Dict[str, Any], now: datetime) -> bool:
    """Whether a cached entry is still within its TTL.

    Only positive entries (score is not None) are cached at all — we
    deliberately do NOT cache null/missing results because a vendor may
    publish the benchmark between runs and we want to re-discover it ASAP.
    If an old negative entry is still in the file from an earlier version,
    treat it as expired so it gets re-queried.
    """
    if entry.get("score") is None:
        return False
    cached_at_str = entry.get("cached_at")
    if not cached_at_str:
        return False
    try:
        cached_at = datetime.fromisoformat(cached_at_str)
    except ValueError:
        return False
    return (now - cached_at) < timedelta(days=POSITIVE_CACHE_TTL_DAYS)


# -----------------------------------------------------------------------------
# §5 useless-work filters
# -----------------------------------------------------------------------------


def _has_value(entry: Any, benchmark: str) -> bool:
    val = entry.columns.get(benchmark, "")
    return str(val).strip() not in MISSING_VALUE_MARKERS


def origin_lock(benchmark: str, entries: List[Any]) -> Optional[str]:
    """If every reporter belongs to a single country, return that country."""
    reporters = [e for e in entries if _has_value(e, benchmark)]
    if not reporters:
        return None
    origins = {e.country for e in reporters}
    return next(iter(origins)) if len(origins) == 1 else None


def is_origin_blocked(model_origin: str, benchmark: str, entries: List[Any]) -> bool:
    """A gap is blocked if the benchmark is origin-locked to the *other* country."""
    locked = origin_lock(benchmark, entries)
    return locked is not None and locked != model_origin


def has_locale_suffix(benchmark: str) -> Optional[str]:
    """Return the locale suffix if the benchmark name ends in one (e.g. '-zh')."""
    name = benchmark.lower().replace(" ", "")
    for suffix in LOCALE_SUFFIXES:
        if name.endswith(suffix):
            return suffix
    return None


def is_locale_blocked(model_country: str, benchmark: str) -> bool:
    """Drop -zh benchmarks for non-CN models, -en for non-US models, etc."""
    suffix = has_locale_suffix(benchmark)
    if suffix is None:
        return False
    if suffix == "-zh":
        return model_country != "CN"
    if suffix == "-en":
        return model_country != "US"
    # Other suffixes (-ja, -ko, -de, -fr, -es) — no cohort country reliably
    # speaks them, so skip these benchmarks entirely.
    return True


def vendor_internal_org(benchmark: str, entries: List[Any]) -> Optional[str]:
    """If every reporter belongs to a single Organization, return it."""
    reporters = [e for e in entries if _has_value(e, benchmark)]
    if not reporters:
        return None
    orgs = {e.columns.get("Organization", "") for e in reporters if e.columns.get("Organization")}
    return next(iter(orgs)) if len(orgs) == 1 else None


def is_vendor_blocked(entry: Any, benchmark: str, entries: List[Any]) -> bool:
    vendor = vendor_internal_org(benchmark, entries)
    return vendor is not None and entry.columns.get("Organization", "") != vendor


# -----------------------------------------------------------------------------
# §6 Tiering
# -----------------------------------------------------------------------------


def get_top_cohort(combined_entries: List[Any]) -> List[Any]:
    """Return the top-tier reference set: top 10 per country by llm-stats rank.

    The scraper preserves leaderboard order within each country, so this is
    the first 10 US entries plus the first 10 CN entries — 20 models total
    when both countries scrape the full top 10.

    The function name is "top cohort" and not "top 10" because the reference
    is intentionally the full 20-model cohort, not a 10-model subset.
    """
    us = [e for e in combined_entries if e.country == "US"][:TOP_COHORT_PER_COUNTRY]
    cn = [e for e in combined_entries if e.country == "CN"][:TOP_COHORT_PER_COUNTRY]
    return us + cn


def count_cohort_participation(benchmark: str, top_cohort: List[Any]) -> int:
    return sum(1 for e in top_cohort if _has_value(e, benchmark))


def assign_tier(cohort_count: int) -> int:
    """Map a cohort participation count (out of 20) to a tier.

    Tiers (0 = qualified — skip, 1 = T1, 2 = T2, 3 = T3 — permanently off):

    - **0** (qualified): >= QUALIFIED_THRESHOLD (16/20, 80%)
    - **1** (one fill from qualifying): >= TIER_1_FLOOR (15/20, 75%)
    - **2** (within reach): >= TIER_2_FLOOR (8/20, 40%)
    - **3** (hopeless): below 8/20
    """
    if cohort_count >= QUALIFIED_THRESHOLD:
        return 0
    if cohort_count >= TIER_1_FLOOR:
        return 1
    if cohort_count >= TIER_2_FLOOR:
        return 2
    return 3


def build_candidates(
    combined_entries: List[Any],
    benchmark_headers: List[str],
    enabled_tiers: FrozenSet[int] = frozenset({1, 2}),
) -> List[GapCandidate]:
    """Build the gap candidate list with §5 filters and §6 tiering applied."""
    top_cohort = get_top_cohort(combined_entries)
    top_cohort_names = {(e.name, e.country) for e in top_cohort}
    candidates: List[GapCandidate] = []

    for benchmark in benchmark_headers:
        top_cohort_count = count_cohort_participation(benchmark, top_cohort)
        cohort_count = sum(1 for e in combined_entries if _has_value(e, benchmark))
        tier = assign_tier(top_cohort_count)

        # §5.5 already-qualified filter
        if tier == 0:
            continue
        # §5.3 hopeless-tier filter
        if tier not in enabled_tiers:
            continue

        for entry in combined_entries:
            if _has_value(entry, benchmark):
                continue  # not a gap

            # §5.1 origin lock
            if is_origin_blocked(entry.country, benchmark, combined_entries):
                continue
            # §5.2 locale suffix
            if is_locale_blocked(entry.country, benchmark):
                continue
            # §5.4 vendor-internal lock
            if is_vendor_blocked(entry, benchmark, combined_entries):
                continue

            candidates.append(
                GapCandidate(
                    model_name=entry.name,
                    model_country=entry.country,
                    model_url=entry.url,
                    organization=entry.columns.get("Organization", ""),
                    benchmark=benchmark,
                    cohort_count=cohort_count,
                    top_cohort_count=top_cohort_count,
                    tier=tier,
                )
            )

    # Sort priority within candidates:
    #   1. tier ascending (T1 first)
    #   2. fills for top-cohort models first — only those move the threshold count
    #   3. distance to qualifying ascending (closer first)
    #   4. top_cohort_count descending (tie-breaker: prefer benchmarks with
    #      higher coverage within their tier)
    candidates.sort(
        key=lambda c: (
            c.tier,
            0 if (c.model_name, c.model_country) in top_cohort_names else 1,
            max(0, QUALIFIED_THRESHOLD - c.top_cohort_count),
            -c.top_cohort_count,
        )
    )
    return candidates


# -----------------------------------------------------------------------------
# §9 OpenAI Responses API
# -----------------------------------------------------------------------------


def discover_available_model(api_key: str, chain: Optional[List[str]] = None) -> Optional[str]:
    """Walk the model chain and return the first one the account can call.

    On any error talking to /v1/models, fall back to the first chain entry
    blindly — the actual call will fail later if it's truly unavailable, and
    we don't want to skip the whole pass for a flaky discovery endpoint.
    """
    if chain is None:
        chain = DEFAULT_MODEL_CHAIN
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        resp = requests.get(OPENAI_MODELS_URL, headers=headers, timeout=10)
        if resp.status_code != 200:
            print(f"[gap-fill] /v1/models returned {resp.status_code}; trying chain[0] blindly")
            return chain[0]
        available = {m["id"] for m in resp.json().get("data", [])}
    except (requests.RequestException, ValueError, KeyError) as e:
        print(f"[gap-fill] model discovery failed ({e}); trying chain[0] blindly")
        return chain[0]

    for model in chain:
        if model in available:
            return model
    print(f"[gap-fill] none of {chain} are available on this account")
    return None


# The system message is stable across every call — byte-identical so that
# OpenAI's prompt-cache can hash the prefix and bill subsequent hits at a
# discount. Do NOT interpolate per-call data (model name, benchmark list,
# URL) into this string; all variables live in the user message.
_SYSTEM_PROMPT = (
    "You are a benchmark-data researcher for a public AI leaderboard. Your job "
    "is to find verifiable, published benchmark scores for AI models. You do "
    "not estimate, guess, or interpolate. If a score is not publicly "
    "documented, return null for it and explain in one short sentence.\n\n"
    "CONSTRAINTS:\n"
    "1. Use only verifiable, public sources: vendor blog posts, model cards, "
    "papers (arXiv preprint or peer-reviewed), the model's own tech report, or "
    "established third-party leaderboards (Papers With Code, OpenLLM "
    "Leaderboard, HELM, LMArena).\n"
    "2. Do not invent scores. Do not average or estimate from neighbouring "
    "benchmarks. Do not quote unverified social-media claims.\n"
    "3. Do not use scores attributed to a different model variant. If only a "
    "Pro / Flash / High variant has a score and the caller asked about the "
    "base model (or vice versa), return null for that benchmark.\n"
    "4. The score must be the same metric and same evaluation protocol that "
    "the benchmark defines. If the source uses a non-standard variant, return "
    "null.\n"
    '5. Format percentages as "xx.x%" and Elo as integer. Use the same units '
    "the benchmark is normally reported in.\n"
    "6. Be efficient with web search. The model's official vendor page "
    "usually has multiple benchmark results on one page — fetch it ONCE and "
    "extract all requested benchmarks from it. Do not issue a separate search "
    "per benchmark.\n"
    "7. Confidence levels: 'high' = directly cited from an official primary "
    "source with no ambiguity; 'medium' = a third-party leaderboard or the "
    "source is partially ambiguous about variant/protocol; 'low' = weak "
    "provenance, do not report.\n"
    "8. CITATION RULE — every non-null score MUST include a working URL in "
    "the structured `source_url` field. Do NOT put the URL only in the "
    "`notes` field or in markdown link syntax. If you cannot cite a direct "
    "URL, set `score` to null. An uncited score is rejected regardless of "
    "confidence level."
)


def build_prompt_batch(
    model_name: str,
    model_country: str,
    model_url: str,
    organization: str,
    benchmarks: List[str],
) -> Tuple[str, str]:
    """Build (system, user) messages for a batched per-model lookup.

    The system message is `_SYSTEM_PROMPT` verbatim (stable prefix for cache
    hits). The user message is terse: just model identity and the benchmark
    list. All behavior rules (null-handling, citation requirement, batching
    efficiency, confidence levels) already live in the system prompt, so
    repeating them here is wasted tokens.
    """
    org = organization or "its provider"
    bench_list = "\n".join(f"  - {b}" for b in benchmarks)

    user = (
        f"Model: {model_name}\n"
        f"Organization: {org}\n"
        f"Country: {model_country}\n"
        f"llm-stats page: {model_url}\n\n"
        f"Benchmarks:\n{bench_list}"
    )
    return _SYSTEM_PROMPT, user


_RESULT_SCHEMA_PROPERTIES = {
    "benchmark": {"type": "string"},
    "score": {"type": ["string", "null"]},
    "source_url": {"type": ["string", "null"]},
    "source_type": {
        "type": "string",
        "enum": [
            "vendor_blog",
            "paper",
            "model_card",
            "third_party_leaderboard",
            "none",
        ],
    },
    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    "notes": {"type": ["string", "null"]},
}
_RESULT_REQUIRED = [
    "benchmark",
    "score",
    "source_url",
    "source_type",
    "confidence",
    "notes",
]


def query_openai_responses(
    system: str,
    user: str,
    *,
    model: str,
    api_key: str,
    max_output_tokens: int = 1200,
    max_retries: int = 6,
) -> Optional[Dict[str, Any]]:
    """Single Responses API call with retries. Returns parsed JSON or None.

    The schema expects a batched response: one `model` field and a `results`
    array with one entry per benchmark asked about. Caller is responsible for
    sizing `max_output_tokens` relative to the number of benchmarks in the
    batch (the orchestrator does this below).
    """
    # OpenAI quirks I learned the hard way:
    # 1. gpt-5.4-pro rejects `temperature`. Reasoning models pick their own.
    # 2. `text.format: {type: json_object}` is INCOMPATIBLE with `web_search`.
    #    Use `json_schema` (Structured Outputs) instead — that one is allowed.
    # 3. The schema must be `strict: true` and every field must be in `required`,
    #    even nullable ones — set the field's type to ["string", "null"] if it
    #    can be null, but keep it in the required array.
    body = {
        "model": model,
        "input": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "tools": [{"type": "web_search"}],
        "tool_choice": "auto",
        "reasoning": {"effort": REASONING_EFFORT},
        "max_output_tokens": max_output_tokens,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "benchmark_lookup_batch",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "results": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": _RESULT_SCHEMA_PROPERTIES,
                                "required": _RESULT_REQUIRED,
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["model", "results"],
                    "additionalProperties": False,
                },
            }
        },
        "store": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    for attempt in range(max_retries):
        try:
            resp = requests.post(OPENAI_RESPONSES_URL, headers=headers, json=body, timeout=120)
        except requests.RequestException as e:
            print(f"[gap-fill] network error ({e}); retry {attempt + 1}/{max_retries}")
            time.sleep(2 ** attempt)
            continue

        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError as e:
                print(f"[gap-fill] invalid JSON in 200 response: {e}")
                return None
        if resp.status_code == 429:
            # Honor Retry-After if present. Add exponential backoff on top so
            # repeated 429s back off rather than hammer at a fixed interval.
            try:
                retry_after = float(resp.headers.get("Retry-After", "0"))
            except ValueError:
                retry_after = 0.0
            backoff = max(retry_after, 2.0 * (2 ** attempt))
            print(f"[gap-fill] 429 rate limit; sleeping {backoff:.1f}s (attempt {attempt + 1}/{max_retries})")
            time.sleep(backoff)
            continue
        if 500 <= resp.status_code < 600:
            print(f"[gap-fill] {resp.status_code} from OpenAI; retry {attempt + 1}/{max_retries}")
            time.sleep(2 ** attempt)
            continue
        # Anything else (4xx other than 429) is a hard failure.
        print(f"[gap-fill] OpenAI returned {resp.status_code}: {resp.text[:200]}")
        return None

    return None


def extract_json_from_response(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Pull the strict JSON object out of an OpenAI Responses API result.

    If extraction fails, print a short diagnostic describing WHY so future
    failures are self-documenting instead of a silent "no valid JSON".
    """
    # Convenience field exposed by some Responses API versions
    if isinstance(raw.get("output_text"), str):
        try:
            return json.loads(raw["output_text"])
        except json.JSONDecodeError:
            pass

    output = raw.get("output", [])
    found_message = False
    for item in output:
        if item.get("type") != "message":
            continue
        found_message = True
        for content in item.get("content", []):
            ctype = content.get("type")
            if ctype == "refusal":
                refusal = content.get("refusal", "")
                print(f"[gap-fill]   model refused: {refusal[:200]}")
                return None
            if ctype in ("output_text", "text"):
                text = content.get("text", "")
                if not text:
                    continue
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    m = re.search(r"\{.*\}", text, re.DOTALL)
                    if m:
                        try:
                            return json.loads(m.group(0))
                        except json.JSONDecodeError:
                            print(f"[gap-fill]   JSON parse failed; head: {text[:200]}")
                            continue
                    else:
                        print(f"[gap-fill]   no JSON object in text; head: {text[:200]}")

    # Nothing parseable — describe what the response actually contained.
    if not found_message:
        types = [i.get("type", "?") for i in output]
        status = raw.get("status", "?")
        incomplete = raw.get("incomplete_details")
        print(
            f"[gap-fill]   no message item in response. status={status} "
            f"incomplete={incomplete} items={types}"
        )
    return None


# Extract the first http(s) URL from a free-text field. gpt-5.4-mini has a
# habit of dumping citations into the `notes` string as markdown links like
# `([openai.com](https://openai.com/...))` instead of populating the
# structured `source_url` field. Pulling the URL back out saves these from
# being rejected for missing citations.
_URL_IN_TEXT = re.compile(r"https?://[^\s\)\]]+")


def _salvage_url_from_notes(notes: Any) -> Optional[str]:
    if not isinstance(notes, str) or not notes:
        return None
    match = _URL_IN_TEXT.search(notes)
    return match.group(0) if match else None


def _validate_result_entry(entry: Dict[str, Any], benchmark: str) -> Optional[Dict[str, Any]]:
    """Validate a single result-object entry from the batched `results` array.

    Returns the entry dict if valid, None otherwise. The entry's `benchmark`
    field is rewritten to the caller-provided `benchmark` so downstream code
    can always use the requested name as the cache key, even if the model
    returned a slightly-different capitalization.

    Validation rules beyond schema shape:
    - If `score` is not None, a citation is mandatory. `source_url` must be
      non-empty; if it's missing we try to salvage one from the `notes`
      field (mini models love putting markdown links there).
    - `source_type` must be one of the allowed enum values.
    - `confidence` must be one of "high"/"medium"/"low".
    """
    required = {"benchmark", "score", "source_url", "source_type", "confidence"}
    if not all(k in entry for k in required):
        return None

    score = entry["score"]
    if score is not None:
        if isinstance(score, str):
            cleaned = score.replace("%", "").replace(",", "").strip()
            try:
                num = float(cleaned)
            except ValueError:
                return None
            if "%" in score:
                if not 0 <= num <= 100:
                    return None
            else:
                if "CodeArena" in benchmark and not 500 <= num <= 3000:
                    return None
        elif isinstance(score, (int, float)):
            if "CodeArena" in benchmark and not 500 <= score <= 3000:
                return None
        else:
            return None

    if entry["confidence"] not in ("high", "medium", "low"):
        return None
    if entry["source_type"] not in (
        "vendor_blog",
        "paper",
        "model_card",
        "third_party_leaderboard",
        "none",
    ):
        return None

    # Normalize the benchmark name back to what we asked for — the model
    # sometimes returns "SWE-Bench Verified" vs "SWE-bench Verified".
    entry = dict(entry)
    entry["benchmark"] = benchmark

    # If there's a score but no structured source_url, try to salvage one
    # from the notes field. If still nothing, reject the fill — we don't
    # accept uncited fills at any confidence level.
    if score is not None:
        source_url = entry.get("source_url") or ""
        if not source_url:
            salvaged = _salvage_url_from_notes(entry.get("notes"))
            if salvaged:
                entry["source_url"] = salvaged
            else:
                # No citation anywhere — reject the whole entry by treating
                # it as a null score. We still cache the rejection so we
                # don't re-query it for the negative TTL window.
                entry = dict(entry)
                entry["score"] = None
                entry["confidence"] = "low"
                if not entry.get("notes"):
                    entry["notes"] = "rejected: score present but no citation URL"
    return entry


def validate_batch_response(
    parsed: Dict[str, Any],
    expected_benchmarks: List[str],
) -> Optional[Dict[str, Dict[str, Any]]]:
    """Validate a batched response. Returns {benchmark: validated_entry}.

    - Pulls the `results` array from the parsed top-level object.
    - Matches each result to one of the expected benchmarks (by exact name
      first, then by case-insensitive match as a safety net).
    - Validates each matched result via `_validate_result_entry`.
    - Drops results that reference unknown benchmarks.

    Returns None only if the response is completely malformed (no `results`
    array at all). Individual invalid entries are dropped, but a partially
    valid response still yields a dict of what was usable.
    """
    if not isinstance(parsed, dict):
        return None
    results = parsed.get("results")
    if not isinstance(results, list):
        return None

    expected_lookup = {b.lower().strip(): b for b in expected_benchmarks}
    out: Dict[str, Dict[str, Any]] = {}
    for entry in results:
        if not isinstance(entry, dict):
            continue
        raw_bench = str(entry.get("benchmark", "")).strip()
        if not raw_bench:
            continue
        canonical = expected_lookup.get(raw_bench.lower())
        if canonical is None:
            # Model returned a benchmark we didn't ask about — drop it.
            continue
        validated = _validate_result_entry(entry, canonical)
        if validated is not None:
            out[canonical] = validated
    return out


# -----------------------------------------------------------------------------
# Orchestration
# -----------------------------------------------------------------------------


def _format_score(score: Any) -> str:
    """Coerce the LLM-returned score into the same string format used in entry.columns."""
    if isinstance(score, str):
        return score
    if isinstance(score, (int, float)):
        if isinstance(score, float):
            return f"{score:.1f}"
        return str(score)
    return str(score)


def _apply_fill(
    combined_entries: List[Any],
    candidate: GapCandidate,
    validated: Dict[str, Any],
    llm_model: str,
) -> bool:
    """Find the entry and write the score + provenance entry into entry.columns.

    Returns True if a row was successfully updated.
    """
    for entry in combined_entries:
        if entry.name != candidate.model_name or entry.country != candidate.model_country:
            continue
        entry.columns[candidate.benchmark] = _format_score(validated["score"])
        provenance = entry.columns.get("_provenance")
        if not isinstance(provenance, dict):
            provenance = {}
        provenance[candidate.benchmark] = {
            "source": "ai_filled",
            "llm_model": llm_model,
            "url": validated.get("source_url", ""),
            "confidence": validated.get("confidence", ""),
            "source_type": validated.get("source_type", ""),
        }
        entry.columns["_provenance"] = provenance
        return True
    return False


def _group_by_model(
    candidates: List[GapCandidate],
    top_cohort_names: Optional[set] = None,
) -> List[Tuple[GapCandidate, List[GapCandidate]]]:
    """Group candidates by (model_name, model_country) and sort for max-fill.

    Sort priority (budget is spent top-down, so earlier groups fire first):
      1. Group contains a Tier-1 candidate (closest to qualifying). T1 fills
         have the highest threshold-moving value per call.
      2. Group's model is in the top-cohort reference set. Fills for
         top-cohort models directly increment the qualified-set count; fills
         for laggard models only pay off on the next scrape's iteration.
      3. Lowest tier in the group (T1 < T2 < T3).
      4. Largest group size — more benchmarks per API call = better token
         amortization.

    The representative entry in each tuple carries the group's model
    identity; the full candidate list drives the batched prompt.
    """
    groups: Dict[Tuple[str, str], List[GapCandidate]] = {}
    for cand in candidates:
        key = (cand.model_name, cand.model_country)
        groups.setdefault(key, []).append(cand)

    top_cohort_names = top_cohort_names or set()
    items: List[Tuple[GapCandidate, List[GapCandidate]]] = []
    for cands in groups.values():
        items.append((cands[0], cands))

    def _sort_key(item: Tuple[GapCandidate, List[GapCandidate]]) -> Tuple[int, int, int, int]:
        rep, cands = item
        has_t1 = 0 if any(c.tier == 1 for c in cands) else 1
        is_top = 0 if (rep.model_name, rep.model_country) in top_cohort_names else 1
        min_tier = min(c.tier for c in cands)
        group_size = -len(cands)  # descending
        return (has_t1, is_top, min_tier, group_size)

    items.sort(key=_sort_key)
    return items


def run_gap_filling_pass(
    combined_entries: List[Any],
    benchmark_headers: List[str],
    *,
    max_calls: int = DEFAULT_MAX_CALLS,
    min_confidence: str = "high",
    scraper_run_ts: str = "",
) -> int:
    """Orchestrate one gap-filling pass. Mutates combined_entries in place.

    Returns the number of cells filled (cache hits + fresh fills accepted).

    **Batching:** candidates are grouped by model and emitted as ONE API call
    per model, asking for all the model's missing benchmarks in a single
    request. This amortizes the ~8K-token web_search content cost across
    N benchmarks, producing a 2–3× token saving versus the original per-
    benchmark approach.
    """
    api_key = resolve_openai_key()
    if not api_key:
        print("\n[gap-fill] OPENAI_API_KEY not set; skipping gap-filling pass.")
        print("           Set it in .env (local) or via the OPENAI_API_KEY GitHub Actions secret (CI).")
        return 0

    print("\n--- Gap-Filling Pass ---")

    model = os.environ.get("AI_GAP_FILL_MODEL")
    if model:
        chain = [model] + [m for m in DEFAULT_MODEL_CHAIN if m != model]
    else:
        chain = DEFAULT_MODEL_CHAIN
    model = discover_available_model(api_key, chain=chain)
    if not model:
        print("[gap-fill] no usable model in chain; skipping pass.")
        return 0
    print(f"[gap-fill] using model: {model}")

    candidates = build_candidates(combined_entries, benchmark_headers, enabled_tiers=frozenset({1, 2}))
    print(f"[gap-fill] {len(candidates)} candidate gaps after §5 filters and §6 tiering")
    if not candidates:
        return 0

    top_cohort_set = {(e.name, e.country) for e in get_top_cohort(combined_entries)}
    groups = _group_by_model(candidates, top_cohort_names=top_cohort_set)
    print(f"[gap-fill] grouped into {len(groups)} per-model batches")

    cache = load_cache()
    now = datetime.now(timezone.utc)

    cache_hits = 0
    schema_failures = 0
    fills_accepted = 0
    fills_dropped_low_conf = 0
    api_calls = 0

    for rep, cands in groups:
        if api_calls >= max_calls:
            print(f"[gap-fill] hit max_calls={max_calls}; stopping")
            break

        model_name = rep.model_name
        # Split into cached vs needs-fetch partitions. cache_is_fresh() only
        # returns True for positive entries, so null scores always fall
        # through to the batch.
        batch_benchmarks: List[str] = []
        batch_candidates: List[GapCandidate] = []
        for cand in cands:
            cache_entry = cache.get(cand.model_name, {}).get(cand.benchmark)
            if cache_entry and cache_is_fresh(cache_entry, now):
                cache_hits += 1
                cached_conf = cache_entry.get("confidence", "low")
                if min_confidence == "high" and cached_conf != "high":
                    fills_dropped_low_conf += 1
                    continue
                if _apply_fill(combined_entries, cand, cache_entry, cache_entry.get("llm_model", model)):
                    fills_accepted += 1
                continue
            batch_benchmarks.append(cand.benchmark)
            batch_candidates.append(cand)

        if not batch_benchmarks:
            continue  # Every candidate in this group was cache-resolved

        # Live LLM call for the batch
        if api_calls > 0:
            time.sleep(REQUEST_INTERVAL_SECONDS)
        api_calls += 1

        tier_summary = ",".join(f"T{c.tier}" for c in batch_candidates)
        print(
            f"[gap-fill] [{api_calls}/{max_calls}] {model_name} ({rep.model_country}) "
            f"→ {len(batch_benchmarks)} benchmarks [{tier_summary}]"
        )

        # Size max_output_tokens to the batch.
        #
        # max_output_tokens on the Responses API is a hard cap on REASONING +
        # VISIBLE output combined. Reasoning models spend ~1500+ hidden tokens
        # per call even at `effort: "low"`, so the cap needs to be much bigger
        # than the visible-JSON estimate alone. Measured values on real calls:
        #   - Reasoning overhead per call: ~1500–2500 tokens
        #   - Visible JSON per result: ~200 tokens
        #   - Schema/wrapper overhead: ~200 tokens
        # Floor of 5000 so single-benchmark batches still have headroom for
        # several web_search tool calls + reasoning between them without
        # risking a truncated final message item.
        max_out = max(5000, 2500 + 300 * len(batch_benchmarks))

        system, user = build_prompt_batch(
            model_name=model_name,
            model_country=rep.model_country,
            model_url=rep.model_url,
            organization=rep.organization,
            benchmarks=batch_benchmarks,
        )
        raw = query_openai_responses(
            system,
            user,
            model=model,
            api_key=api_key,
            max_output_tokens=max_out,
        )
        if raw is None:
            continue

        parsed = extract_json_from_response(raw)
        if parsed is None:
            schema_failures += 1
            print("  → no valid JSON in response")
            continue

        validated_map = validate_batch_response(parsed, batch_benchmarks)
        if validated_map is None:
            schema_failures += 1
            print("  → batch schema validation failed")
            continue

        # Apply each validated result to its matching candidate
        for cand in batch_candidates:
            entry = validated_map.get(cand.benchmark)
            if entry is None:
                # Model omitted this benchmark from its response. Treat as a
                # soft null — do NOT cache it, because a vendor may publish
                # the missing score between now and the next scrape run.
                print(f"  · {cand.benchmark}: omitted from response")
                continue

            # Null / missing scores are deliberately NOT cached — see
            # cache_is_fresh() for the rationale (freshness over cost).
            if entry["score"] is None:
                print(f"  · {cand.benchmark}: null ({(entry.get('notes') or '')[:60]})")
                continue

            # Positive result: cache it so the next scrape can skip the call.
            cache.setdefault(cand.model_name, {})[cand.benchmark] = {
                **entry,
                "cached_at": now.isoformat(),
                "llm_model": model,
            }

            if entry["confidence"] != "high" and min_confidence == "high":
                fills_dropped_low_conf += 1
                print(f"  · {cand.benchmark}: dropped (confidence={entry['confidence']})")
                continue

            if _apply_fill(combined_entries, cand, entry, model):
                append_audit_entry(
                    {
                        "ts": now.isoformat(),
                        "model": cand.model_name,
                        "benchmark": cand.benchmark,
                        "score": _format_score(entry["score"]),
                        "source_url": entry.get("source_url", ""),
                        "source_type": entry.get("source_type", ""),
                        "confidence": entry["confidence"],
                        "llm_model": model,
                        "scraper_run": scraper_run_ts,
                    }
                )
                fills_accepted += 1
                print(
                    f"  · {cand.benchmark}: ACCEPTED {entry['score']} "
                    f"({(entry.get('source_url') or '')[:50]})"
                )

    save_cache(cache)

    print()
    print(f"[gap-fill] cache hits              : {cache_hits}")
    print(f"[gap-fill] live API calls          : {api_calls}")
    print(f"[gap-fill] schema failures         : {schema_failures}")
    print(f"[gap-fill] dropped low-confidence  : {fills_dropped_low_conf}")
    print(f"[gap-fill] fills accepted          : {fills_accepted}")

    return fills_accepted
