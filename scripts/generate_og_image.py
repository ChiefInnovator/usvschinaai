#!/usr/bin/env python3
"""
Generate og-image-{timestamp}.png from models.json data using Playwright.
Renders a self-contained HTML template at 1200x630 and screenshots it.
Updates og:image meta tags in HTML files to point to the new filename.
"""
import glob as globmod
import json
import re
import sys
import time
from pathlib import Path

from dateutil.parser import parse as parse_date
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
    """Load the HTML template and replace placeholders with computed scores."""
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


def screenshot_html(html, output_path):
    """Use Playwright to render HTML at 1200x630 and save a screenshot."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1200, "height": 630})
            page.set_content(html, wait_until="networkidle")
            page.screenshot(path=str(output_path), type="png")
        finally:
            browser.close()
    print(f"Saved OG image: {output_path}")


def remove_old_og_images(workspace, keep=None):
    """Delete previous og-image-{timestamp}.png files, optionally keeping one."""
    for old in workspace.glob("og-image-*.png"):
        # Only match timestamped files (digits after dash), skip og-image-original.png etc.
        stem = old.stem  # e.g. "og-image-1772372524"
        suffix = stem.replace("og-image-", "", 1)
        if not suffix.isdigit():
            continue
        if keep and old.name == keep:
            continue
        old.unlink()
        print(f"Removed old OG image: {old.name}")


def update_html_meta_tags(workspace, new_filename):
    """Update og:image and twitter:image meta tags in all HTML files."""
    pattern = re.compile(r'og-image[^"]*\.png(?:\?v=\d+)?')
    for html_file in ["index.html", "history.html", "about.html"]:
        path = workspace / html_file
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        updated = pattern.sub(new_filename, content)
        if updated != content:
            path.write_text(updated, encoding="utf-8")
            print(f"Updated {html_file} → {new_filename}")


def main():
    workspace = Path(__file__).resolve().parent.parent
    models_path = workspace / "models.json"
    news_path = workspace / "news.json"
    template_path = workspace / "scripts" / "og-template.html"

    # Generate timestamped filename
    ts = int(time.time())
    filename = f"og-image-{ts}.png"
    output_path = workspace / filename

    if not models_path.exists():
        print("ERROR: models.json not found")
        sys.exit(1)
    if not template_path.exists():
        print("ERROR: og-template.html not found")
        sys.exit(1)

    try:
        scores = load_scores(models_path)
        print(f"Scores: US {scores['us_total']} | CN {scores['cn_total']}")

        news_items = load_news_items(news_path)
        if news_items:
            print(f"News: {len(news_items)} items loaded")
        else:
            print("No news items available — marquee hidden")

        html = build_html(scores, news_items, template_path)
        screenshot_html(html, output_path)

        # Remove old og-image-*.png files, keep the new one
        remove_old_og_images(workspace, keep=filename)

        # Update meta tags in HTML files to point to new image
        update_html_meta_tags(workspace, filename)

        print("OG image generation complete.")
    except Exception as e:
        print(f"ERROR generating OG image: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
