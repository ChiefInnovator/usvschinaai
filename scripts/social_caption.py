#!/usr/bin/env python3
"""Write the day's Instagram caption from the compact facts dict.

This is the only place in the social pipeline that spends tokens, and it
spends as few as the job allows:

  Model routing   gpt-5.6-luna for a routine day; gpt-5.6-terra only when the
                  story carries weight (a lead change or a new #1), where a
                  sharper hook is worth ~10x the pennies. SOCIAL_CAPTION_MODEL
                  overrides.
  Input size      the ~600-token facts dict from social_formats, never
                  models.json (~40k tokens). Input is the whole budget.
  Output cap      json_schema-constrained, max_output_tokens=350, reasoning
                  effort low. No preamble to pay for.
  Cache-friendly  the system prompt is a fixed prefix so prompt caching
                  applies if it ever exceeds the provider's minimum; today it
                  is short enough that the real saving is not sending it much.
  Result cache    keyed by snapshot timestamp + format, so a re-dispatch or a
                  same-day replacement costs nothing.
  One attempt     no retry loop; any failure falls back to a deterministic
                  caption. A missed flourish is cheaper than a retry storm.
  Ledger          every call appends tokens and USD to data/social_cost.jsonl.

Batching is deliberately absent: at one call a day there is nothing to batch.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = REPO_ROOT / "data" / "social_caption_cache.json"
LEDGER_PATH = REPO_ROOT / "data" / "social_cost.jsonl"
RESPONSES_URL = "https://api.openai.com/v1/responses"

# USD per million tokens (input, cached input, output), from the pricing page
# on 2026-09-03. Used only for the ledger.
PRICES = {
    "gpt-5.6-luna":  (0.20, 0.02, 1.20),
    "gpt-5.6-terra": (2.00, 0.20, 12.00),
    "gpt-5.4-nano":  (0.20, 0.02, 1.25),
}
ROUTINE_MODEL = "gpt-5.6-luna"
STRONG_MODEL = "gpt-5.6-terra"
ESCALATE_AT_WEIGHT = 3     # lead_change (4) and new_challenger (3)
MAX_OUTPUT_TOKENS = 350

SYSTEM_PROMPT = (
    "You write Instagram captions for usvschina.ai, a daily scoreboard of US "
    "versus Chinese AI models. Voice: sharp, plain, specific; sports-desk energy, "
    "no hype words, no emojis in the hook. Use only numbers present in the facts. "
    "Return JSON: hook (<=90 chars, a claim not a description), bullets (exactly 3, "
    "<=110 chars each, each with a number), question (<=100 chars, invites a take), "
    "hashtags (6 to 8, no spaces, mix broad and specific)."
)

CAPTION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "hook": {"type": "string", "maxLength": 90},
        "bullets": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "string", "maxLength": 110}},
        "question": {"type": "string", "maxLength": 100},
        "hashtags": {"type": "array", "minItems": 6, "maxItems": 8, "items": {"type": "string", "maxLength": 30}},
    },
    "required": ["hook", "bullets", "question", "hashtags"],
}

BASE_TAGS = ["#AI", "#ArtificialIntelligence", "#USvsChina", "#LLM", "#AIRace", "#TechNews"]


def choose_caption_model(weight: int) -> str:
    override = os.environ.get("SOCIAL_CAPTION_MODEL", "").strip()
    if override:
        return override
    return STRONG_MODEL if weight >= ESCALATE_AT_WEIGHT else ROUTINE_MODEL


def cost_usd(model: str, usage: Dict[str, Any]) -> float:
    pin, pcached, pout = PRICES.get(model, (0.0, 0.0, 0.0))
    inp = int(usage.get("input_tokens", 0))
    cached = int((usage.get("input_tokens_details") or {}).get("cached_tokens", 0))
    out = int(usage.get("output_tokens", 0))
    return round(((inp - cached) * pin + cached * pcached + out * pout) / 1_000_000, 6)


def fallback_caption(facts: Dict[str, Any], fmt: str) -> Dict[str, Any]:
    """Deterministic, number-true caption when the model is unavailable."""
    t = facts["totals"]; top = facts["top10"]
    lead = "Team USA" if facts["leader"] == "US" else "Team China" if facts["leader"] == "CN" else "Neither team"
    hook = {
        "lead_change": f"{lead} takes the lead in the AI race",
        "new_challenger": f"{(facts.get('brand_new') or facts.get('new_entrants') or [top[0]['model']])[0]} lands in the top 10",
        "biggest_mover": f"{facts['biggest_mover']['model']} moves {abs(facts['biggest_mover']['places'])} places" if facts.get("biggest_mover") else f"{top[0]['model']} holds #1",
        "head_to_head": f"{facts['first_us']['model']} vs {facts['first_cn']['model']}",
    }.get(fmt, f"{lead} leads by {facts['margin']:.0f}")
    bullets = [
        f"#1 overall: {top[0]['model']} at {top[0]['unified']:.0f} Unified",
        f"Team USA {t['US']:.0f} vs Team China {t['CN']:.0f}",
        f"{facts['us_in_top10']} US and {facts['cn_in_top10']} Chinese models in the top 10",
    ]
    return {"hook": hook[:90], "bullets": [b[:110] for b in bullets],
            "question": "Which lab would you bet on for the rest of 2026?", "hashtags": BASE_TAGS}


def _load_cache() -> Dict[str, Any]:
    try:
        return json.loads(CACHE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _save_cache(cache: Dict[str, Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2))


def _ledger(record: Dict[str, Any]) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")


def call_model(model: str, facts: Dict[str, Any], fmt: str, api_key: str) -> Dict[str, Any]:
    """One Responses API call, schema-constrained, capped. Raises on any problem."""
    body = {
        "model": model,
        "instructions": SYSTEM_PROMPT,                      # stable prefix first
        "input": json.dumps({"format": fmt, "facts": facts}, separators=(",", ":")),
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "reasoning": {"effort": "low"},
        "text": {"format": {"type": "json_schema", "name": "caption", "strict": True, "schema": CAPTION_SCHEMA}},
    }
    r = requests.post(RESPONSES_URL, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                      json=body, timeout=60)
    r.raise_for_status()
    data = r.json()
    text = ""
    for item in data.get("output", []):
        for c in item.get("content", []) or []:
            if c.get("type") == "output_text":
                text = c.get("text", "")
    caption = json.loads(text)
    caption["_usage"] = data.get("usage", {})
    return caption


def generate_caption(facts: Dict[str, Any], fmt: str, weight: int,
                     api_key: Optional[str] = None, use_cache: bool = True) -> Dict[str, Any]:
    key = f"{facts.get('timestamp', '')}|{fmt}"
    cache = _load_cache() if use_cache else {}
    if key in cache:
        return dict(cache[key], _source="cache")

    api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return dict(fallback_caption(facts, fmt), _source="fallback:no-key")

    model = choose_caption_model(weight)
    try:
        caption = call_model(model, facts, fmt, api_key)
    except Exception as exc:  # network, HTTP, schema, JSON — one attempt only
        print(f"[caption] {model} failed ({exc}); using fallback")
        return dict(fallback_caption(facts, fmt), _source=f"fallback:{type(exc).__name__}")

    usage = caption.pop("_usage", {})
    _ledger({"ts": datetime.now(timezone.utc).isoformat(), "model": model, "format": fmt,
             "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
             "cached_tokens": (usage.get("input_tokens_details") or {}).get("cached_tokens", 0),
             "usd": cost_usd(model, usage)})
    if use_cache:
        cache[key] = caption
        _save_cache(cache)
    return dict(caption, _source=model)


def render_caption(caption: Dict[str, Any]) -> str:
    lines = [caption["hook"], ""] + [f"• {b}" for b in caption["bullets"]] + ["", caption["question"], "",
             "Live board: usvschina.ai", "", " ".join(t if t.startswith("#") else f"#{t}" for t in caption["hashtags"])]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from social_formats import plan_today
    plan = plan_today(json.load(open(REPO_ROOT / "models.json")))
    cap = generate_caption(plan["facts"], plan["format"], plan["weight"])
    print(f"[caption] source={cap.get('_source')} model={choose_caption_model(plan['weight'])}\n")
    print(render_caption(cap))
