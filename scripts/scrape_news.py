#!/usr/bin/env python3
"""
Fetch AI news about the US-China AI race from NewsData.io.
Writes news.json to the repository root.
"""
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

try:
    from dateutil.parser import parse as _parse_iso_date
except ImportError:  # pragma: no cover — optional at import time
    _parse_iso_date = None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
NEWSDATA_API_URL = "https://newsdata.io/api/1/latest"
MAX_ARTICLES = 20
MAX_HEADLINE_LENGTH = 120
# Drop articles older than this many days from the merge so the feed can't
# accumulate stale-but-high-relevance headlines that crowd out new ones.
MAX_ARTICLE_AGE_DAYS = 14

RELEVANCE_KEYWORDS_HIGH = [
    "openai", "anthropic", "google", "deepseek", "alibaba", "meta",
    "gpt", "gemini", "claude", "deepseek", "qwen", "llama",
    "benchmark", "gpqa", "mmlu", "swe-bench", "arc-agi",
]

RELEVANCE_KEYWORDS_MEDIUM = [
    "artificial intelligence", "machine learning", "ai model",
    "released", "launched", "achieved", "breakthrough", "regulation",
    "chips", "semiconductor", "nvidia", "export controls",
]

US_KEYWORDS = [
    "united states", "american", "openai", "google", "anthropic",
    "meta", "microsoft", "u.s.", "usa",
]

CN_KEYWORDS = [
    "china", "chinese", "deepseek", "alibaba", "baidu",
    "tencent", "bytedance", "qwen", "huawei",
]


def fetch_news(api_key):
    """Fetch articles from NewsData.io latest endpoint."""
    params = {
        "apikey": api_key,
        "q": "US AND CHINA AND AI",
        "country": "us,cn",
        "language": "en",
        "category": "technology,science",
        "removeduplicate": 1,
        "size": 10,
    }
    try:
        resp = requests.get(NEWSDATA_API_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "success":
            msg = data.get("results", {})
            print(f"  API error: {msg}")
            return []
        return data.get("results") or []
    except Exception as e:
        print(f"  Request failed: {e}")
        return []


def determine_country(article):
    """Determine if an article is about US, CN, or Both."""
    text = " ".join([
        article.get("title") or "",
        article.get("description") or "",
        " ".join(article.get("keywords") or []),
    ]).lower()

    has_us = any(kw in text for kw in US_KEYWORDS)
    has_cn = any(kw in text for kw in CN_KEYWORDS)

    if has_us and has_cn:
        return "Both"
    if has_cn:
        return "CN"
    return "US"


def calculate_relevance(article):
    """Score 0.0-1.0 based on keyword matching."""
    text = " ".join([
        article.get("title") or "",
        article.get("description") or "",
    ]).lower()

    score = 0.0
    for kw in RELEVANCE_KEYWORDS_HIGH:
        if kw in text:
            score += 0.15
    for kw in RELEVANCE_KEYWORDS_MEDIUM:
        if kw in text:
            score += 0.08
    return min(score, 1.0)


def make_article_id(article):
    """Generate a dedup ID from URL + pubDate."""
    raw = (article.get("link") or "") + (article.get("pubDate") or "")
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def clean_headline(title):
    """Truncate and clean headline."""
    if not title:
        return ""
    title = title.strip()
    if len(title) > MAX_HEADLINE_LENGTH:
        title = title[: MAX_HEADLINE_LENGTH - 3].rsplit(" ", 1)[0] + "..."
    return title


def transform_article(raw):
    """Transform a raw NewsData.io article into our schema."""
    return {
        "id": make_article_id(raw),
        "headline": clean_headline(raw.get("title") or ""),
        "url": raw.get("link") or "",
        "source": raw.get("source_name") or "Unknown",
        "country": determine_country(raw),
        "publishedAt": raw.get("pubDate") or "",
        "relevanceScore": round(calculate_relevance(raw), 2),
    }


def deduplicate(articles):
    """Remove duplicates by ID and similar titles."""
    seen_ids = set()
    seen_titles = set()
    unique = []
    for a in articles:
        aid = a["id"]
        title_key = a["headline"].lower().strip()[:60]
        if aid in seen_ids or title_key in seen_titles:
            continue
        seen_ids.add(aid)
        seen_titles.add(title_key)
        unique.append(a)
    return unique


def _parse_published(article):
    """Parse publishedAt to a datetime. Returns None on failure."""
    raw = article.get("publishedAt") or ""
    if not raw:
        return None
    # Try ISO 8601 first (most common), then a naive string parse.
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        pass
    if _parse_iso_date is not None:
        try:
            return _parse_iso_date(raw)
        except (ValueError, TypeError):
            return None
    return None


def _is_fresh(article, cutoff):
    """Whether an article is newer than the age cutoff."""
    dt = _parse_published(article)
    if dt is None:
        return False  # drop unparseable dates — they're almost always junk
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt >= cutoff


def merge_with_existing(new_articles, news_path):
    """Merge new articles with existing news.json, keeping top articles.

    Sort order: newest first (primary), relevance desc (secondary). A hard
    age cap drops anything older than MAX_ARTICLE_AGE_DAYS so the feed can't
    accumulate stale headlines. Without the age cap, high-relevance old
    articles were permanently outranking newly-published ones.
    """
    existing = []
    if news_path.exists():
        try:
            with open(news_path) as f:
                data = json.load(f)
                existing = data.get("items") or []
        except (json.JSONDecodeError, KeyError):
            pass

    combined = new_articles + existing
    deduped = deduplicate(combined)

    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_ARTICLE_AGE_DAYS)
    fresh = [a for a in deduped if _is_fresh(a, cutoff)]

    # Primary sort: publishedAt descending (newest first).
    # Secondary sort: relevance descending (break ties by quality).
    fresh.sort(
        key=lambda a: (
            _parse_published(a) or datetime.min.replace(tzinfo=timezone.utc),
            a.get("relevanceScore", 0),
        ),
        reverse=True,
    )
    return fresh[:MAX_ARTICLES]


def main():
    api_key = os.environ.get("NEWSDATA_API_KEY", "")
    if not api_key:
        print("WARNING: NEWSDATA_API_KEY not set. Skipping news scrape.")
        sys.exit(0)

    workspace = Path(__file__).resolve().parent.parent
    news_path = workspace / "news.json"

    print("Fetching AI news from NewsData.io...")
    raw_articles = fetch_news(api_key)
    print(f"  Got {len(raw_articles)} articles")

    if not raw_articles:
        print("No articles fetched. Keeping existing news.json if present.")
        sys.exit(0)

    # Transform and filter
    transformed = [transform_article(a) for a in raw_articles]
    transformed = [a for a in transformed if a["headline"] and a["url"]]
    print(f"  Transformed {len(transformed)} valid articles")

    # Filter out clearly irrelevant articles (relevance score 0)
    relevant = [a for a in transformed if a["relevanceScore"] > 0]
    if relevant:
        transformed = relevant
        print(f"  {len(transformed)} articles passed relevance filter")

    # Merge with existing
    final = merge_with_existing(transformed, news_path)

    # Write news.json
    output = {
        "lastUpdated": datetime.now(timezone.utc).isoformat(),
        "items": final,
    }
    with open(news_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(final)} articles to news.json")


if __name__ == "__main__":
    main()
