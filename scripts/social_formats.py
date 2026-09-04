#!/usr/bin/env python3
"""Decide what today's Instagram post is about, and what it looks like.

Everything here is deterministic and costs no tokens: which story the data
tells today (a lead change, a new challenger, a big mover), which template
tells it, and which palette it wears. The images are rendered from these
facts by social_render.py; only the caption (social_caption.py) touches a
model, and it receives the compact `facts` dict from build_day_facts()
rather than models.json.

Why this exists: the account posted the same dark leaderboard tile every
day, and nine of them in a row on the profile grid read as a bot. Formats
rotate by what happened, and palettes are forbidden from repeating on
consecutive days, so the grid reads as a designed mosaic.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
SOCIAL_HISTORY = REPO_ROOT / "data" / "social_history.jsonl"

# Formats, highest editorial weight first. A format's weight decides both
# whether an event-driven story beats the rotation and which caption model
# is worth paying for (see social_caption.py).
FORMATS = [
    ("lead_change",     4),   # USA/China total flipped since the previous day
    ("new_challenger",  3),   # a model entered the top 10
    ("biggest_mover",   2),   # largest rank change day-over-day (>= 2 places)
    ("head_to_head",    1),   # #1 US vs #1 China - always available
    ("price_vs_power",  1),   # the cheapest strong model - always available
    ("benchmark_day",   1),   # one qualified benchmark, top five
    ("trend_30d",       1),   # lead margin over the last 30 days (Sundays)
    ("leaderboard",     0),   # the full top 10 - a cadence element, not the feed
]
FORMAT_WEIGHT = dict(FORMATS)
NO_REPEAT_DAYS = 5

# Each format has two palettes so the same story two days apart still looks
# different, and the chooser refuses yesterday's palette outright.
PALETTES = {
    "midnight":  {"bg": "#020617", "bg2": "#0f172a", "ink": "#f8fafc", "muted": "#94a3b8", "accent": "#fbbf24"},
    "newsprint": {"bg": "#eef2f7", "bg2": "#dfe6ee", "ink": "#0b1f3a", "muted": "#4b5b70", "accent": "#b45309"},  # amber: accent must differ from ink or highlights vanish
    "cobalt":    {"bg": "#1e3a8a", "bg2": "#1d4ed8", "ink": "#eff6ff", "muted": "#bfdbfe", "accent": "#facc15"},
    "signal":    {"bg": "#7f1d1d", "bg2": "#b91c1c", "ink": "#fff1f2", "muted": "#fecaca", "accent": "#fde68a"},
    "graphite":  {"bg": "#1f2937", "bg2": "#111827", "ink": "#f9fafb", "muted": "#9ca3af", "accent": "#f59e0b"},
    "sunrise":   {"bg": "#f97316", "bg2": "#db2777", "ink": "#fffbeb", "muted": "#ffe4e6", "accent": "#0b1f3a"},
}
# Team colours are constant across palettes so the encoding never changes.
TEAM = {"US": "#3b82f6", "CN": "#ef4444"}

FORMAT_PALETTES = {
    "lead_change":    ["cobalt", "signal"],       # picked by who leads
    "new_challenger": ["graphite", "newsprint"],
    "biggest_mover":  ["graphite", "sunrise"],
    "head_to_head":   ["newsprint", "midnight"],
    "price_vs_power": ["sunrise", "newsprint"],
    "benchmark_day":  ["cobalt", "graphite"],
    "trend_30d":      ["newsprint", "cobalt"],
    "leaderboard":    ["midnight", "graphite"],
}


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------

def _board(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = [dict(r, origin=team) for team, rs in entry.get("teams", {}).items() for r in rs]
    rows.sort(key=lambda r: -float(r.get("unified", 0)))
    return rows


def _totals(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    """Mirror index.html calculateTotals(): sum unified per team over the combined top 10."""
    top = rows[:10]
    return {
        "US": round(sum(float(r.get("unified", 0)) for r in top if r["origin"] == "US"), 2),
        "CN": round(sum(float(r.get("unified", 0)) for r in top if r["origin"] == "CN"), 2),
    }


def _date(ts: str) -> Optional[str]:
    try:
        return datetime.fromisoformat(ts).astimezone(timezone.utc).date().isoformat()
    except (TypeError, ValueError):
        return None


def previous_day_entry(history: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The newest snapshot from a UTC day before today's - not an earlier run today."""
    if not history:
        return None
    today = _date(history[0].get("timestamp", ""))
    for entry in history[1:]:
        if _date(entry.get("timestamp", "")) != today:
            return entry
    return None


def _num(v) -> Optional[float]:
    try:
        return float(str(v).replace("%", "").replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def build_day_facts(data: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the templates and the caption need, and nothing else.

    Kept small on purpose: this dict - not models.json - is what goes to the
    caption model, so it is the whole input-token budget (~400 tokens).
    """
    history = data.get("history") or []
    if not history:
        raise ValueError("no history")
    today, prev = history[0], previous_day_entry(history)
    rows = _board(today)
    totals = _totals(rows)
    leader = "US" if totals["US"] > totals["CN"] else "CN" if totals["CN"] > totals["US"] else "TIE"

    prev_rows = _board(prev) if prev else []
    prev_totals = _totals(prev_rows) if prev_rows else None
    prev_leader = None
    if prev_totals:
        prev_leader = "US" if prev_totals["US"] > prev_totals["CN"] else "CN" if prev_totals["CN"] > prev_totals["US"] else "TIE"

    pos = {r["model"]: i for i, r in enumerate(rows, 1)}
    prev_pos = {r["model"]: i for i, r in enumerate(prev_rows, 1)}
    top10_names = [r["model"] for r in rows[:10]]
    prev_top10 = {r["model"] for r in prev_rows[:10]}

    prev_all = set(prev_pos)
    # Genuinely new = absent from the whole previous board, not just its top 10.
    # "Qwen3.8 Flash enters at #3" was wrong: it was #16 the day before.
    brand_new = [m for m in top10_names if prev_rows and m not in prev_all]
    new_entrants = [m for m in top10_names if prev_rows and m not in prev_top10]
    movers = sorted(
        ((prev_pos[m] - pos[m], m) for m in pos if m in prev_pos and prev_pos[m] != pos[m]),
        key=lambda t: (-abs(t[0]), t[1]),
    )

    def slim(r: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "model": r["model"], "org": r.get("organization", ""), "origin": r["origin"],
            "rank": pos[r["model"]], "unified": round(float(r.get("unified", 0)), 1),
            "iq": round(float(r.get("avgIq", 0)), 1), "value": round(float(r.get("value", 0)), 1),
            "price_in": _num(r.get("Input$/M")), "price_out": _num(r.get("Output$/M")),
            "coverage": r.get("coverage", ""),
        }

    first_us = next((r for r in rows if r["origin"] == "US"), None)
    first_cn = next((r for r in rows if r["origin"] == "CN"), None)

    return {
        "date": _date(today.get("timestamp", "")),
        "timestamp": today.get("timestamp", ""),
        "totals": totals, "leader": leader,
        "prev_totals": prev_totals, "prev_leader": prev_leader,
        "margin": round(abs(totals["US"] - totals["CN"]), 1),
        "top10": [slim(r) for r in rows[:10]],
        "first_us": slim(first_us) if first_us else None,
        "first_cn": slim(first_cn) if first_cn else None,
        "new_entrants": new_entrants,
        "brand_new": brand_new,
        "biggest_mover": {"model": movers[0][1], "places": movers[0][0]} if movers else None,
        "us_in_top10": sum(1 for r in rows[:10] if r["origin"] == "US"),
        "cn_in_top10": sum(1 for r in rows[:10] if r["origin"] == "CN"),
    }


# ---------------------------------------------------------------------------
# Events -> format
# ---------------------------------------------------------------------------

def detect_events(facts: Dict[str, Any]) -> List[Tuple[int, str]]:
    """Formats the data justifies today, best first."""
    out: List[Tuple[int, str]] = []
    if facts.get("prev_leader") and facts["prev_leader"] != facts["leader"] and facts["leader"] != "TIE":
        out.append((FORMAT_WEIGHT["lead_change"], "lead_change"))
    if facts.get("new_entrants"):
        out.append((FORMAT_WEIGHT["new_challenger"], "new_challenger"))
    mover = facts.get("biggest_mover")
    if mover and abs(mover["places"]) >= 2:
        out.append((FORMAT_WEIGHT["biggest_mover"], "biggest_mover"))
    return sorted(out, key=lambda t: -t[0])


ROTATION = ["head_to_head", "price_vs_power", "benchmark_day", "leaderboard"]


def choose_format(facts: Dict[str, Any], recent: List[str], today: Optional[datetime] = None) -> str:
    """Event-driven story if there is one not used in the last NO_REPEAT_DAYS;
    otherwise the next rotation format not used recently; Sundays get the trend."""
    recent_set = set(recent[-NO_REPEAT_DAYS:])
    for _, fmt in detect_events(facts):
        if fmt not in recent_set:
            return fmt
    today = today or datetime.now(timezone.utc)
    if today.weekday() == 6 and "trend_30d" not in recent_set:
        return "trend_30d"
    for fmt in ROTATION:
        if fmt not in recent_set:
            return fmt
    # Everything used recently (only possible with a very short history): least recent wins.
    return min(ROTATION, key=lambda f: (len(recent) - 1 - recent[::-1].index(f)) if f in recent else -1)


def choose_palette(fmt: str, facts: Dict[str, Any], recent_palettes: List[str]) -> str:
    """The format's palette family, never the same palette as yesterday."""
    options = list(FORMAT_PALETTES[fmt])
    if fmt == "lead_change":
        options = ["cobalt", "signal"] if facts.get("leader") == "US" else ["signal", "cobalt"]
    yesterday = recent_palettes[-1] if recent_palettes else None
    for p in options:
        if p != yesterday:
            return p
    return options[0]


# ---------------------------------------------------------------------------
# History (what was posted on previous days)
# ---------------------------------------------------------------------------

def read_history(path: Path = SOCIAL_HISTORY) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def append_history(record: Dict[str, Any], path: Path = SOCIAL_HISTORY) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


def plan_today(data: Dict[str, Any], history: Optional[List[Dict[str, Any]]] = None,
               today: Optional[datetime] = None) -> Dict[str, Any]:
    """facts + format + palette for today, in one call."""
    facts = build_day_facts(data)
    history = read_history() if history is None else history
    # Ignore an earlier plan from the same day so a re-run picks the same story.
    prior = [h for h in history if h.get("date") != facts["date"]]
    recent_formats = [h["format"] for h in prior]
    recent_palettes = [h["palette"] for h in prior]
    fmt = choose_format(facts, recent_formats, today)
    palette = choose_palette(fmt, facts, recent_palettes)
    return {"facts": facts, "format": fmt, "palette": palette, "weight": FORMAT_WEIGHT[fmt]}
