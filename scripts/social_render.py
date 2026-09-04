#!/usr/bin/env python3
"""Render a day's Instagram slide(s) from social_formats' plan.

Canvas is 1080x1350 (4:5): the tallest ratio the publishing API accepts, and
it fills the 3:4 profile grid with only ~3% cropped from each side, which the
templates keep clear via --safe-x. No model is involved; every template is
filled from the `facts` dict.

  python scripts/social_render.py            # today's plan -> data/social_preview/<format>.png
  python scripts/social_render.py --all      # every format, today's facts, for review
"""
import argparse
import html
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
from social_formats import PALETTES, plan_today, build_day_facts  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = REPO_ROOT / "scripts" / "social-templates"
PREVIEW_DIR = REPO_ROOT / "data" / "social_preview"
WIDTH, HEIGHT = 1080, 1350

# Formats without a dedicated template yet fall back to the leaderboard.
TEMPLATE_FOR = {
    "head_to_head": "head_to_head", "new_challenger": "new_challenger",
    "biggest_mover": "biggest_mover", "leaderboard": "leaderboard",
    "lead_change": "leaderboard", "price_vs_power": "head_to_head",
    "benchmark_day": "leaderboard", "trend_30d": "leaderboard",
}

FLAG = {"US": "🇺🇸", "CN": "🇨🇳"}


def e(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def _price(m: Dict[str, Any]) -> str:
    p = m.get("price_in")
    return "—" if p is None else (f"${p:.2f}" if p >= 0.1 else f"${p:.3f}")


def _date_long(facts: Dict[str, Any]) -> str:
    try:
        return datetime.fromisoformat(facts["timestamp"]).strftime("%A, %B %-d, %Y")
    except (KeyError, ValueError):
        return facts.get("date", "")


def _leader_line(facts: Dict[str, Any]) -> str:
    t = facts["totals"]
    if facts["leader"] == "TIE":
        return "Dead heat"
    who = "Team USA leads" if facts["leader"] == "US" else "Team China leads"
    return f"{who} by {facts['margin']:.0f}"


def fill(fmt: str, palette: str, facts: Dict[str, Any]) -> str:
    tpl = (TEMPLATES / f"{TEMPLATE_FOR[fmt]}.html").read_text()
    base = (TEMPLATES / "_base.css").read_text()
    for k, v in PALETTES[palette].items():
        base = base.replace("{{" + k + "}}", v)
    vals: Dict[str, str] = {"base_css": base, "date_long": e(_date_long(facts)), "leader_line": e(_leader_line(facts))}

    top10 = facts["top10"]
    us, cn = facts.get("first_us") or {}, facts.get("first_cn") or {}
    vals.update({
        "us_name": e(us.get("model")), "us_org": e(us.get("org")), "us_unified": e(f"{us.get('unified', 0):.0f}"),
        "us_iq": e(f"{us.get('iq', 0):.1f}"), "us_price": e(_price(us)),
        "cn_name": e(cn.get("model")), "cn_org": e(cn.get("org")), "cn_unified": e(f"{cn.get('unified', 0):.0f}"),
        "cn_iq": e(f"{cn.get('iq', 0):.1f}"), "cn_price": e(_price(cn)),
        "us_rank": e(us.get("rank", "")), "cn_rank": e(cn.get("rank", "")),
    })

    if fmt == "new_challenger":
        brand_new = facts.get("brand_new") or []
        name = (brand_new or facts.get("new_entrants") or [top10[0]["model"]])[0]
        m = next((r for r in top10 if r["model"] == name), top10[0])
        is_new = name in brand_new
        vals.update({"headline": "New on the board" if is_new else "Into the top 10",
                     "verb": "enters at" if is_new else "climbs to",
                     "name": e(m["model"]), "org": e(m["org"]), "rank": e(m["rank"]), "team_flag": FLAG[m["origin"]],
                     "unified": e(f"{m['unified']:.0f}"), "iq": e(f"{m['iq']:.1f}"), "price": e(_price(m))})
        cells = []
        for r in top10[:4]:
            hot = " hot" if r["model"] == m["model"] else ""
            cells.append(f'<div class="cell{hot}">#{r["rank"]} {FLAG[r["origin"]]}<b>{e(r["model"])}</b></div>')
        vals["top5_cells"] = "".join(cells)

    if fmt == "biggest_mover":
        mv = facts.get("biggest_mover") or {"model": top10[0]["model"], "places": 0}
        m = next((r for r in top10 if r["model"] == mv["model"]), top10[0])
        places = int(mv["places"])
        to_rank, from_rank = m["rank"], m["rank"] + places
        vals.update({"arrow": "▲" if places >= 0 else "▼", "places": e(abs(places)), "name": e(m["model"]),
                     "team_flag": FLAG[m["origin"]], "from_rank": e(from_rank), "to_rank": e(to_rank),
                     "unified": e(f"{m['unified']:.0f}")})
        lo, hi = sorted((from_rank, to_rank))
        rungs = []
        for rk in range(max(1, hi), max(0, lo - 1), -1):
            h = 100 - (rk - 1) * (90 / max(hi, 1))
            cls = " now" if rk == to_rank else ""
            rungs.append(f'<div class="rung{cls}" style="height:{h:.0f}%"><span>#{rk}</span></div>')
        vals["ladder"] = "".join(rungs[:14])

    # leaderboard fields are always filled (it's the fallback template too)
    t = facts["totals"]
    vals.update({
        "leader_headline": e("Team USA leads" if facts["leader"] == "US" else "Team China leads" if facts["leader"] == "CN" else "Dead heat"),
        "us_total": e(f"{t['US']:.0f}"), "cn_total": e(f"{t['CN']:.0f}"),
        "us_count": e(facts["us_in_top10"]), "cn_count": e(facts["cn_in_top10"]),
        "rows": "".join(
            f'<div class="row {r["origin"].lower()}"><span class="n display">{r["rank"]}</span>'
            f'<span class="m">{FLAG[r["origin"]]} {e(r["model"])}</span><span class="s display">{r["unified"]:.0f}</span></div>'
            for r in top10),
    })
    for k, v in vals.items():
        tpl = tpl.replace("{{" + k + "}}", v)
    return tpl


def render_png(html_text: str, out: Path) -> Path:
    from playwright.sync_api import sync_playwright
    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        try:
            page = b.new_page(viewport={"width": WIDTH, "height": HEIGHT})
            page.set_content(html_text, wait_until="networkidle")
            page.screenshot(path=str(out), type="png")
        finally:
            b.close()
    return out


def render_plan(plan: Dict[str, Any], out_dir: Path = PREVIEW_DIR) -> List[Path]:
    """The day's cover slide plus the leaderboard as a second slide."""
    fmt, pal, facts = plan["format"], plan["palette"], plan["facts"]
    slides = [(fmt, pal)]
    if fmt != "leaderboard":
        slides.append(("leaderboard", pal))
    return [render_png(fill(f, p, facts), out_dir / f"{i+1:02d}_{f}_{p}.png") for i, (f, p) in enumerate(slides)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="render every format for review")
    ap.add_argument("--out", default=str(PREVIEW_DIR))
    args = ap.parse_args()
    data = json.load(open(REPO_ROOT / "models.json"))
    out = Path(args.out)
    if args.all:
        facts = build_day_facts(data)
        from social_formats import FORMAT_PALETTES
        for fmt, pals in FORMAT_PALETTES.items():
            if TEMPLATE_FOR.get(fmt) != fmt:
                continue  # no dedicated template yet
            for pal in pals:
                print("  wrote", render_png(fill(fmt, pal, facts), out / f"{fmt}__{pal}.png").name)
        return
    plan = plan_today(data)
    for p in render_plan(plan, out):
        print("  wrote", p.name)


if __name__ == "__main__":
    main()
