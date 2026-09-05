#!/usr/bin/env python3
"""Produce today's Instagram carousel from the day's data.

Runs inside the daily scrape, which already has Playwright and the OpenAI key:

  1. social_formats.plan_today picks the format and palette (no repeats),
  2. social_render draws the cover slide and the leaderboard slide into social/,
  3. social_caption writes the caption (gpt-5.6-luna, terra on high-weight days),
  4. social/plan.json records slides, URLs and caption for post_to_instagram.py,
  5. data/social_history.jsonl gets the day's record so tomorrow rotates away.

Slide files are date-stamped so their URLs are new every day: Instagram fetches
the image by URL and a CDN can serve a stale file under a reused name. Only the
current day's slides are kept in social/; git history keeps the rest.

    python scripts/social_publish.py                    # -> social/ (the real thing)
    python scripts/social_publish.py --out /tmp/x       # rehearsal: no history record
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from social_formats import plan_today, build_chart_facts, read_history, append_history  # noqa: E402
from social_caption import generate_caption, render_caption  # noqa: E402
import social_render as sr  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SOCIAL_DIR = REPO_ROOT / "social"
SITE = "https://usvschina.ai"
PLAN_FILE = "plan.json"


def slide_filename(date: str, index: int, fmt: str, palette: str) -> str:
    return f"{date}-{index}-{fmt}-{palette}.png"


def slides_for(fmt: str, palette: str) -> List[Tuple[str, str]]:
    """The day's cover, then the leaderboard as slide 2 (unless it is the cover)."""
    return [(fmt, palette)] + ([("leaderboard", palette)] if fmt != "leaderboard" else [])


def prune(out_dir: Path, keep_date: str) -> List[str]:
    """Delete slides from earlier days. Returns the names removed."""
    removed = []
    for p in sorted(out_dir.glob("*.png")):
        if not p.name.startswith(keep_date):
            p.unlink()
            removed.append(p.name)
    return removed


def history_record(plan: Dict[str, Any]) -> Dict[str, Any]:
    rec = {k: plan[k] for k in ("date", "timestamp", "format", "palette")}
    if plan.get("benchmark"):
        rec["benchmark"] = plan["benchmark"]
    return rec


def publish(data: Dict[str, Any], out_dir: Path = SOCIAL_DIR, api_key: Optional[str] = None,
            today: Optional[datetime] = None,
            history: Optional[List[Dict[str, Any]]] = None) -> Tuple[Dict[str, Any], List[str]]:
    """Render the slides, write the caption and plan.json. Returns (plan, removed)."""
    today = today or datetime.now(timezone.utc)
    history = read_history() if history is None else history
    plan = plan_today(data, history, today)
    fmt, palette, facts = plan["format"], plan["palette"], plan["facts"]
    recent_b = [h.get("benchmark") for h in history if h.get("benchmark")]
    charts = build_chart_facts(data, recent_b, today)

    out_dir.mkdir(parents=True, exist_ok=True)
    names = []
    for i, (f, p) in enumerate(slides_for(fmt, palette), 1):
        name = slide_filename(facts["date"], i, f, p)
        sr.render_png(sr.fill(f, p, facts, charts), out_dir / name)
        names.append(name)

    cap = generate_caption(facts, fmt, plan["weight"], api_key)
    record = {
        "date": facts["date"], "timestamp": facts["timestamp"],
        "format": fmt, "palette": palette, "weight": plan["weight"],
        "slides": names, "urls": [f"{SITE}/social/{n}" for n in names],
        "caption": render_caption(cap), "caption_source": cap.get("_source", ""),
        "generated_at": today.isoformat(),
    }
    if fmt == "benchmark_day" and charts.get("benchmark"):
        record["benchmark"] = charts["benchmark"]
    removed = prune(out_dir, facts["date"])
    (out_dir / PLAN_FILE).write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return record, removed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(SOCIAL_DIR), help="slide directory (default: social/)")
    ap.add_argument("--models-json", type=Path, default=REPO_ROOT / "models.json")
    args = ap.parse_args()
    out_dir = Path(args.out).resolve()

    with open(args.models_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    record, removed = publish(data, out_dir)
    if out_dir == SOCIAL_DIR.resolve():
        append_history(history_record(record))
    else:
        print("[social] rehearsal: history not recorded")

    print(f"[social] {record['date']}: {record['format']} / {record['palette']} "
          f"(weight {record['weight']}), caption via {record['caption_source']}")
    for u in record["urls"]:
        print(f"  {u}")
    if removed:
        print(f"[social] removed {len(removed)} older slide(s)")
    print(f"\n{record['caption']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
