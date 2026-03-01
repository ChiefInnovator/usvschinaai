#!/usr/bin/env python3
"""
Generate og-image.png and ig-image.png from models.json data using Playwright.
OG image: 1200x630 landscape for social sharing.
IG image: 1080x1920 portrait for Instagram with top-10 leaderboard.
Both images are compressed via Pillow to minimize file size.
"""
import json
import re
import sys
import time
from pathlib import Path

from dateutil.parser import parse as parse_date
from PIL import Image
from playwright.sync_api import sync_playwright


def load_scores(models_path):
    """Read models.json and compute team scores mirroring index.html JS logic.

    The frontend calculateTotals() (index.html:765-806) does:
      1. Combine US + CN models, sort by unified desc, take top 10
      2. Sum unified for each country's models in top 10 → Total Score
      3. Average avgIq and value for each country → Avg IQ / Avg Value
    We replicate that here so the OG image shows the same numbers.
    """
    with open(models_path) as f:
        data = json.load(f)

    history = data.get("history", [])
    if not history:
        raise ValueError("No history entries in models.json")

    entry = history[0]
    timestamp = entry.get("timestamp", "")

    # Combine all models from both teams
    all_models = []
    for origin_key, origin_label in [("US", "US"), ("CN", "CN")]:
        for m in entry.get("teams", {}).get(origin_key, []):
            all_models.append({
                "origin": origin_label,
                "unified": float(m.get("unified", 0)),
                "iq": float(m.get("avgIq", 0)),
                "value": float(m.get("value", 0)),
            })

    # Sort by unified descending, take top 10
    all_models.sort(key=lambda m: m["unified"], reverse=True)
    top10 = all_models[:10]

    us_in_top10 = [m for m in top10 if m["origin"] == "US"]
    cn_in_top10 = [m for m in top10 if m["origin"] == "CN"]

    us_total = sum(m["unified"] for m in us_in_top10)
    cn_total = sum(m["unified"] for m in cn_in_top10)

    us_avg_iq = (sum(m["iq"] for m in us_in_top10) / len(us_in_top10)) if us_in_top10 else 0
    us_avg_val = (sum(m["value"] for m in us_in_top10) / len(us_in_top10)) if us_in_top10 else 0
    cn_avg_iq = (sum(m["iq"] for m in cn_in_top10) / len(cn_in_top10)) if cn_in_top10 else 0
    cn_avg_val = (sum(m["value"] for m in cn_in_top10) / len(cn_in_top10)) if cn_in_top10 else 0

    # Format the timestamp
    date_str = ""
    if timestamp:
        try:
            dt = parse_date(timestamp)
            date_str = dt.strftime("%B %d, %Y").replace(" 0", " ")
        except Exception:
            date_str = timestamp

    us_leads = us_total > cn_total

    return {
        "date_str": date_str,
        "us_total": f"{us_total:.2f}",
        "cn_total": f"{cn_total:.2f}",
        "us_avg_iq": f"{us_avg_iq:.1f}",
        "us_avg_val": f"{us_avg_val:.1f}",
        "cn_avg_iq": f"{cn_avg_iq:.1f}",
        "cn_avg_val": f"{cn_avg_val:.1f}",
        "us_score_color": "#3b82f6" if us_leads else "#f8fafc",
        "cn_score_color": "#ef4444" if not us_leads else "#f8fafc",
        "us_leading_display": "flex" if us_leads else "none",
        "cn_leading_display": "none" if us_leads else "flex",
        "us_ring": "2px solid rgba(59, 130, 246, 0.6)" if us_leads else "2px solid rgba(59, 130, 246, 0.3)",
        "cn_ring": "2px solid rgba(239, 68, 68, 0.6)" if not us_leads else "2px solid rgba(239, 68, 68, 0.3)",
        "us_shadow": "0 0 30px rgba(59, 130, 246, 0.4)" if us_leads else "0 0 20px rgba(59, 130, 246, 0.2)",
        "cn_shadow": "0 0 30px rgba(239, 68, 68, 0.4)" if not us_leads else "0 0 20px rgba(239, 68, 68, 0.2)",
    }


def load_top10_models(models_path):
    """Return the top 10 models with name, origin, and unified score."""
    with open(models_path) as f:
        data = json.load(f)

    entry = data["history"][0]
    all_models = []
    for team_key in ["US", "CN"]:
        for m in entry["teams"][team_key]:
            all_models.append({
                "name": m["model"],
                "origin": team_key,
                "unified": float(m.get("unified", 0)),
            })
    all_models.sort(key=lambda m: m["unified"], reverse=True)
    return all_models[:10]


def build_top10_html(top10):
    """Build HTML rows for the top 10 leaderboard in the IG template."""
    rows = []
    for i, m in enumerate(top10, 1):
        flag = "\U0001F1FA\U0001F1F8" if m["origin"] == "US" else "\U0001F1E8\U0001F1F3"
        color_class = "row-us" if m["origin"] == "US" else "row-cn"
        rows.append(
            f'<div class="model-row {color_class}">'
            f'<span class="model-rank">{i}.</span>'
            f'<span class="model-flag">{flag}</span>'
            f'<span class="model-name">{m["name"]}</span>'
            f'<span class="model-dots"></span>'
            f'<span class="model-score">{m["unified"]:.2f}</span>'
            f'</div>'
        )
    return "\n".join(rows)


def load_news_items(news_path):
    """Read news.json and return all items sorted by relevance for the marquee."""
    try:
        with open(news_path) as f:
            data = json.load(f)
        items = data.get("items") or []
        if not items:
            return None
        # Sort by relevance descending
        items.sort(key=lambda a: a.get("relevanceScore", 0), reverse=True)
        result = []
        for item in items:
            country = item.get("country", "US")
            flag = ("\U0001F1E8\U0001F1F3" if country == "CN"
                    else "\U0001F1FA\U0001F1F8" if country == "US"
                    else "\U0001F30D")
            result.append({
                "headline": item.get("headline", ""),
                "source": item.get("source", ""),
                "flag": flag,
            })
        return result
    except Exception:
        return None


def build_news_html(news_items):
    """Build the inner HTML for the news marquee track from news items."""
    if not news_items:
        return ""
    parts = []
    for item in news_items:
        parts.append(
            f'<span class="news-item">'
            f'<span class="news-flag">{item["flag"]}</span>'
            f'<span class="news-headline">{item["headline"]}</span>'
            f'<span class="news-source">({item["source"]})</span>'
            f'</span>'
            f'<span class="news-sep">\u2022</span>'
        )
    single = "".join(parts)
    # Duplicate for seamless scroll appearance
    return single + single


def build_html(scores, news_items, template_path):
    """Load the OG HTML template and replace placeholders with computed scores."""
    template = template_path.read_text(encoding="utf-8")

    news_display = "flex" if news_items else "none"
    news_track_html = build_news_html(news_items) if news_items else ""

    replacements = {
        "{{DATE_STR}}": scores["date_str"],
        "{{US_TOTAL}}": scores["us_total"],
        "{{CN_TOTAL}}": scores["cn_total"],
        "{{US_AVG_IQ}}": scores["us_avg_iq"],
        "{{US_AVG_VAL}}": scores["us_avg_val"],
        "{{CN_AVG_IQ}}": scores["cn_avg_iq"],
        "{{CN_AVG_VAL}}": scores["cn_avg_val"],
        "{{US_SCORE_COLOR}}": scores["us_score_color"],
        "{{CN_SCORE_COLOR}}": scores["cn_score_color"],
        "{{US_LEADING_DISPLAY}}": scores["us_leading_display"],
        "{{CN_LEADING_DISPLAY}}": scores["cn_leading_display"],
        "{{US_RING}}": scores["us_ring"],
        "{{CN_RING}}": scores["cn_ring"],
        "{{US_SHADOW}}": scores["us_shadow"],
        "{{CN_SHADOW}}": scores["cn_shadow"],
        "{{NEWS_DISPLAY}}": news_display,
        "{{NEWS_TRACK}}": news_track_html,
    }

    html = template
    for placeholder, value in replacements.items():
        html = html.replace(placeholder, value)
    return html


def build_ig_html(scores, top10, template_path):
    """Load the IG HTML template and replace placeholders with scores and leaderboard."""
    template = template_path.read_text(encoding="utf-8")

    us_count = sum(1 for m in top10 if m["origin"] == "US")
    cn_count = sum(1 for m in top10 if m["origin"] == "CN")
    total = us_count + cn_count
    us_bar_pct = round(us_count / total * 100) if total else 50
    cn_bar_pct = 100 - us_bar_pct

    replacements = {
        "{{DATE_STR}}": scores["date_str"],
        "{{US_TOTAL}}": scores["us_total"],
        "{{CN_TOTAL}}": scores["cn_total"],
        "{{US_AVG_IQ}}": scores["us_avg_iq"],
        "{{US_AVG_VAL}}": scores["us_avg_val"],
        "{{CN_AVG_IQ}}": scores["cn_avg_iq"],
        "{{CN_AVG_VAL}}": scores["cn_avg_val"],
        "{{US_SCORE_COLOR}}": scores["us_score_color"],
        "{{CN_SCORE_COLOR}}": scores["cn_score_color"],
        "{{US_LEADING_DISPLAY}}": scores["us_leading_display"],
        "{{CN_LEADING_DISPLAY}}": scores["cn_leading_display"],
        "{{US_RING}}": scores["us_ring"],
        "{{CN_RING}}": scores["cn_ring"],
        "{{US_SHADOW}}": scores["us_shadow"],
        "{{CN_SHADOW}}": scores["cn_shadow"],
        "{{TOP10_ROWS}}": build_top10_html(top10),
        "{{US_MODEL_COUNT}}": str(us_count),
        "{{CN_MODEL_COUNT}}": str(cn_count),
        "{{US_BAR_PCT}}": str(us_bar_pct),
        "{{CN_BAR_PCT}}": str(cn_bar_pct),
    }

    html = template
    for placeholder, value in replacements.items():
        html = html.replace(placeholder, value)
    return html


def screenshot_html(html, output_path, width, height):
    """Use Playwright to render HTML at given dimensions and save a screenshot."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.set_content(html, wait_until="networkidle")
            page.screenshot(path=str(output_path), type="png")
        finally:
            browser.close()


def compress_png(path):
    """Compress a PNG file in-place using Pillow for smaller file size."""
    original_size = path.stat().st_size
    img = Image.open(path)
    img.save(path, format="PNG", optimize=True)
    compressed_size = path.stat().st_size
    saved = original_size - compressed_size
    pct = (saved / original_size * 100) if original_size > 0 else 0
    print(f"Compressed {path.name}: {original_size:,} → {compressed_size:,} bytes ({pct:.1f}% smaller)")


def update_og_image_version(workspace):
    """Update og:image and twitter:image URLs in all HTML files with a cache-busting version."""
    version = int(time.time())
    html_files = list(workspace.glob("*.html"))
    og_pattern = re.compile(
        r'(<meta\s+property="og:image"\s+content="https://usvschina\.ai/og-image\.png)(\?v=\d+)?(")'
    )
    tw_pattern = re.compile(
        r'(<meta\s+name="twitter:image"\s+content="https://usvschina\.ai/og-image\.png)(\?v=\d+)?(")'
    )
    updated = []
    for html_file in html_files:
        content = html_file.read_text(encoding="utf-8")
        new_content = og_pattern.sub(rf"\g<1>?v={version}\3", content)
        new_content = tw_pattern.sub(rf"\g<1>?v={version}\3", new_content)
        if new_content != content:
            html_file.write_text(new_content, encoding="utf-8")
            updated.append(html_file.name)
    if updated:
        print(f"Updated og:image version to ?v={version} in: {', '.join(updated)}")
    return updated


def main():
    workspace = Path(__file__).resolve().parent.parent
    models_path = workspace / "models.json"
    news_path = workspace / "news.json"
    og_template_path = workspace / "scripts" / "og-template.html"
    ig_template_path = workspace / "scripts" / "ig-template.html"
    og_output_path = workspace / "og-image.png"
    ig_output_path = workspace / "ig-image.png"

    if not models_path.exists():
        print("ERROR: models.json not found")
        sys.exit(1)
    if not og_template_path.exists():
        print("ERROR: og-template.html not found")
        sys.exit(1)

    try:
        scores = load_scores(models_path)
        print(f"Scores: US {scores['us_total']} | CN {scores['cn_total']}")

        # --- OG image (1200x630) ---
        news_items = load_news_items(news_path)
        if news_items:
            print(f"News: {len(news_items)} items loaded")
        else:
            print("No news items available — marquee hidden")

        og_html = build_html(scores, news_items, og_template_path)
        screenshot_html(og_html, og_output_path, 1200, 630)
        compress_png(og_output_path)
        print(f"Saved OG image: {og_output_path}")

        # --- IG image (1080x1920) ---
        if ig_template_path.exists():
            top10 = load_top10_models(models_path)
            ig_html = build_ig_html(scores, top10, ig_template_path)
            screenshot_html(ig_html, ig_output_path, 1080, 1920)
            compress_png(ig_output_path)
            print(f"Saved IG image: {ig_output_path}")
        else:
            print("Skipping IG image — ig-template.html not found")

        update_og_image_version(workspace)

        print("Image generation complete.")
    except Exception as e:
        print(f"ERROR generating images: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
