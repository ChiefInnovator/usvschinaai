#!/usr/bin/env python3
"""AI gap-filling pass for the usvschinaai scraper.

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

from avg_iq_benchmarks import load_config, selected_value


# -----------------------------------------------------------------------------
# Constants from the spec
# -----------------------------------------------------------------------------

# Default model chain — `gpt-5.6-terra` as the primary research model: a
# generation newer than gpt-5.4 and cheaper ($2.00/$12.00 per M vs
# $2.50/$15.00), and it supports everything this pass needs (Responses API,
# the web_search tool, json_schema structured outputs, reasoning effort).
# `gpt-5.6-sol` is the stronger fallback and `gpt-5.4` the last resort if the
# 5.6 line isn't available on the account. Not using gpt-5.6-luna despite it
# being ~10x cheaper: it is the weakest tier, and a hallucinated benchmark
# score gets published as fact, which is worse than leaving the cell empty.
# Override with AI_GAP_FILL_MODEL.
DEFAULT_MODEL_CHAIN: List[str] = ["gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.4"]

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


POSITIVE_CACHE_TTL_DAYS = 30
# Note: we deliberately do NOT cache negative results. A null score today
# might get published tomorrow, and the gap-fill pass's whole point is to
# discover newly-available scores. Re-querying nulls every run is the
# correct trade-off (freshness > API cost).

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
OPENAI_MODELS_URL = "https://api.openai.com/v1/models"


class QuotaExhausted(Exception):
    """The API key is out of quota (billing) — no retry can succeed."""


class RateLimitedOut(Exception):
    """Every retry attempt for one call returned 429 without recovering."""

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


def build_candidates(combined_entries: List[Any]) -> List[GapCandidate]:
    """Research every missing configured Avg IQ component for every retained model.

    Neither participation, country, model coverage nor a reported sibling version
    makes a missing result ineligible. Exact version/protocol validation still
    applies to the evidence returned by research.
    """
    return [
        GapCandidate(
            model_name=entry.name, model_country=entry.country,
            model_url=entry.url, organization=entry.columns.get("Organization", ""),
            benchmark=component["name"],
        )
        for entry in combined_entries
        for component in load_config()["benchmarks"]
        if not selected_value(entry.columns, component["name"])
    ]


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
    "Pro / Flash model variant has a score and the caller asked about the "
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
    "confidence level.\n"
    "9. Match the exact requested benchmark version and subset. Never copy a "
    "score from a sibling version or combine incompatible configurations. "
    "Effort settings are not different model identities. For each requested benchmark, use the highest verified score across all reasoning effort levels independently; do not require the effort level to match other benchmarks. Preserve exact model release, benchmark version and protocol; reject fallback to a different model. Report the winning effort and source configuration in notes.\n"
    "10. Search beyond launch summaries: official model cards and PDF system "
    "cards, benchmark operator current and archived tables, evaluator datasets, "
    "and other vendors' comparative release tables. Follow citations to the "
    "numeric result. NVIDIA or other evaluator reports may contain original "
    "model baselines: use only the exact original-model column, never a "
    "quantized derivative's score. Check footnotes for fallback models and "
    "modified datasets. Humanity’s Last Exam is not Agents’ Last Exam. Do not substitute text-only, tool-enabled or revised HLE variants without matching the selected protocol. SWE-bench Verified is not SWE-bench Pro or Lite. Original Toolathlon is not Toolathlon-Verified; "
    "CharXiv-R means reasoning, not descriptive accuracy. If an image-only "
    "table cannot be read reliably, return null. Exhaust these source routes "
    "for still-missing requested benchmarks; do not stop at the launch page.\n"
    "11. Audit-informed source routes: check llm-stats benchmark leaderboards "
    "as well as model detail pages, following pagination. Check Vals "
    "(https://www.vals.ai/benchmarks/) for MMLU-Pro, AIME, LiveCodeBench, "
    "SWE-bench Verified, GPQA Diamond and Terminal-Bench 2.1. Inspect embedded "
    "structured results when rendered summaries omit numbers; use the exact "
    "model row and selected task, not a headline or comparison snippet. An "
    "archived benchmark can still contain usable results; archived does not "
    "mean the requested model was never evaluated.\n"
    "12. Metric checks: Vals AIME 'overall' combines 2024 and 2025; use only "
    "the 'aime_2025' task. Vals MMLU-Pro uses overall accuracy across 14 "
    "subjects, not the highest subject. LiveCodeBench must be v6 overall "
    "code generation, not an easy/medium/hard subset. GPQA Diamond is not "
    "generic GPQA. On https://agents-last-exam.org/api/demo/leaderboard use "
    "split='full' and passRate, never avgScore or a sub-split. OfficeQA Pro "
    "requires full-corpus evaluation, not oracle pages or OfficeQA-Full; "
    "consult https://arxiv.org/html/2603.08655v1 and retain the harness and "
    "document-parsing configuration. BrowseComp is not BrowseComp-Plus, "
    "BrowseComp-zh or DeepSearchQA. Keep original DeepSWE and DeepSWE 1.1 "
    "separate on the operator's versioned leaderboard.\n"
    "13. Historical evidence: record any independently verified publication "
    "date and its supporting citation in notes. Do not use a model release, "
    "benchmark launch, evaluation-start date or page-wide update date as "
    "the publication date of an individual result. Dated source revisions "
    "must actually contain the value. Unknown dates remain unknown. If a "
    "source model ID includes a release date or preview suffix, verify the "
    "identity before mapping it; effort suffixes alone do not disqualify it. "
    "For null results, distinguish no matching row, incompatible metric or "
    "subset, ambiguous release identity, inaccessible source, and incomplete "
    "pagination. Never treat an inaccessible or partial table as proof that "
    "a result does not exist."
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
            "system_card",
            "official_leaderboard",
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

    all_attempts_429 = True
    for attempt in range(max_retries):
        try:
            resp = requests.post(OPENAI_RESPONSES_URL, headers=headers, json=body, timeout=120)
        except requests.RequestException as e:
            all_attempts_429 = False
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
            # Quota-class 429s (insufficient_quota = the key is out of billing
            # credit) never recover — abort instead of sleeping through the
            # backoff ladder. Before this check, a dead key cost every batch
            # the full 126s ladder: 20 batches x 126s = 42 wasted minutes per
            # run (observed Apr 25 - Aug 29, with zero fills accepted).
            err_text = resp.text[:500]
            if "insufficient_quota" in err_text or "billing" in err_text.lower():
                raise QuotaExhausted(err_text)
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
            all_attempts_429 = False
            print(f"[gap-fill] {resp.status_code} from OpenAI; retry {attempt + 1}/{max_retries}")
            time.sleep(2 ** attempt)
            continue
        # Anything else (4xx other than 429) is a hard failure.
        print(f"[gap-fill] OpenAI returned {resp.status_code}: {resp.text[:200]}")
        return None

    if all_attempts_429:
        # Six straight 429s spanning >2 minutes of backoff is not pacing —
        # the key is effectively rate-dead for this run. Let the caller decide
        # whether to abort the whole pass.
        raise RateLimitedOut(f"all {max_retries} attempts returned 429")
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
        "system_card",
        "official_leaderboard",
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
    notes = (validated.get("notes") or "").lower()
    if "fallback" in notes or "toolathlon-verified" in notes:
        return False
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
            "notes": validated.get("notes") or "",
        }
        entry.columns["_provenance"] = provenance
        return True
    return False


def _group_by_model(
    candidates: List[GapCandidate],
) -> List[Tuple[GapCandidate, List[GapCandidate]]]:
    """Batch all missing components per model, preserving incoming model order."""
    groups: Dict[Tuple[str, str], List[GapCandidate]] = {}
    for cand in candidates:
        groups.setdefault((cand.model_name, cand.model_country), []).append(cand)
    return [(cands[0], cands) for cands in groups.values()]


def run_gap_filling_pass(
    combined_entries: List[Any],
    *,
    max_calls: int = DEFAULT_MAX_CALLS,
    min_confidence: str = "high",
    scraper_run_ts: str = "",
    skip_pairs: Optional[set] = None,
    on_batch=None,
) -> int:
    """Orchestrate one gap-filling pass. Mutates combined_entries in place.

    Returns the number of cells filled (cache hits + fresh fills accepted).

    `skip_pairs` is a set of (model_name, benchmark) never to research;
    `on_batch(model_name, benchmarks)` is called once per answered batch.
    Together they let a caller that replays the pass over many days (the
    history backfill) remember what it has already asked, because null
    results are deliberately not cached here.

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

    candidates = build_candidates(combined_entries)
    print(f"[gap-fill] {len(candidates)} missing results across the nineteen configured Avg IQ benchmarks")
    if skip_pairs:
        before = len(candidates)
        candidates = [c for c in candidates if (c.model_name, c.benchmark) not in skip_pairs]
        print(f"[gap-fill] {before - len(candidates)} skipped as already researched")
    if not candidates:
        return 0

    groups = _group_by_model(candidates)
    print(f"[gap-fill] grouped into {len(groups)} per-model batches")

    cache = load_cache()
    now = datetime.now(timezone.utc)

    cache_hits = 0
    schema_failures = 0
    fills_accepted = 0
    fills_dropped_low_conf = 0
    api_calls = 0
    # Consecutive batches whose every retry 429'd. Two in a row aborts the
    # pass — see the RateLimitedOut handler below.
    rate_limited_batches = 0

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
                    # An unaccepted cached lead is still a gap. Research it
                    # again for better evidence instead of suppressing retries.
                    fills_dropped_low_conf += 1
                else:
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

        print(
            f"[gap-fill] [{api_calls}/{max_calls}] {model_name} ({rep.model_country}) "
            f"→ {len(batch_benchmarks)} benchmarks"
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
        try:
            raw = query_openai_responses(
                system,
                user,
                model=model,
                api_key=api_key,
                max_output_tokens=max_out,
            )
        except QuotaExhausted as e:
            print(f"[gap-fill] ABORTING PASS: API key out of quota — {e}")
            print("[gap-fill] fix billing at platform.openai.com; skipping remaining batches")
            break
        except RateLimitedOut:
            rate_limited_batches += 1
            if rate_limited_batches >= 2:
                print("[gap-fill] ABORTING PASS: 2 consecutive batches exhausted all "
                      "retries on 429 — key is rate-dead this run; skipping remaining batches")
                break
            continue
        rate_limited_batches = 0
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
        if on_batch is not None:
            on_batch(model_name, list(batch_benchmarks))

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
