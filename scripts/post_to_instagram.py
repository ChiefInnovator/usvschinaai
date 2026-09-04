#!/usr/bin/env python3
"""
Post ig-image.png to Instagram via the Graph API.

Requires environment variables:
  INSTAGRAM_ACCESS_TOKEN - Never-expiring Page Access Token
  IG_USER_ID             - Instagram Business Account ID

Instagram Graph API two-step process:
  1. Create media container: POST /{ig-user-id}/media?image_url=...&caption=...
  2. Publish: POST /{ig-user-id}/media_publish?creation_id=...
"""
import json
import os
import sys
import time
from pathlib import Path

import requests
from dateutil.parser import parse as parse_date


def load_caption_data(models_path):
    """Extract data for the Instagram caption from models.json."""
    with open(models_path) as f:
        data = json.load(f)
    entry = data["history"][0]
    timestamp = entry.get("timestamp", "")

    all_models = []
    for team_key in ["US", "CN"]:
        for m in entry["teams"][team_key]:
            all_models.append({
                "name": m["model"],
                "origin": team_key,
                "unified": float(m.get("unified", 0)),
            })
    all_models.sort(key=lambda m: m["unified"], reverse=True)
    top10 = all_models[:10]

    us_total = sum(m["unified"] for m in top10 if m["origin"] == "US")
    cn_total = sum(m["unified"] for m in top10 if m["origin"] == "CN")
    us_count = sum(1 for m in top10 if m["origin"] == "US")
    cn_count = sum(1 for m in top10 if m["origin"] == "CN")

    leader = "US" if us_total > cn_total else "China"
    margin = abs(us_total - cn_total)

    date_str = ""
    if timestamp:
        try:
            dt = parse_date(timestamp)
            date_str = dt.strftime("%B %d, %Y").replace(" 0", " ")
        except Exception:
            date_str = timestamp

    top_model = top10[0]["name"] if top10 else "Unknown"
    top_flag = "\U0001F1FA\U0001F1F8" if top10[0]["origin"] == "US" else "\U0001F1E8\U0001F1F3"

    return {
        "date_str": date_str,
        "us_total": f"{us_total:.2f}",
        "cn_total": f"{cn_total:.2f}",
        "us_count": us_count,
        "cn_count": cn_count,
        "leader": leader,
        "margin": f"{margin:.2f}",
        "top_model": top_model,
        "top_flag": top_flag,
    }


def build_caption(data):
    """Build the Instagram post caption."""
    return (
        f"\U0001F1FA\U0001F1F8 US vs \U0001F1E8\U0001F1F3 China AI Scoreboard\n"
        f"\U0001F4C5 {data['date_str']}\n"
        f"\n"
        f"Team {data['leader']} leads by {data['margin']} points!\n"
        f"\n"
        f"\U0001F1FA\U0001F1F8 USA: {data['us_total']} ({data['us_count']} models in Top 10)\n"
        f"\U0001F1E8\U0001F1F3 China: {data['cn_total']} ({data['cn_count']} models in Top 10)\n"
        f"\n"
        f"\U0001F3C6 #1 Model: {data['top_flag']} {data['top_model']}\n"
        f"\n"
        f"Full rankings at usvschina.ai\n"
        f"\n"
        f"#AI #ArtificialIntelligence #USvsChinaAI #AIrace "
        f"#MachineLearning #LLM #AIbenchmarks #FrontierAI "
        f"#TechCompetition #AIleaderboard"
    )


# Graph API version. v21.0 (Oct 2024) is at/near its ~2-year sunset window;
# keep this current when Meta announces deprecations.
GRAPH_API_BASE = "https://graph.facebook.com/v23.0"


def _raise_with_body(resp, context):
    """raise_for_status, but print the Graph error JSON first.

    The error body (code/subcode/message) is the only way to distinguish an
    expired token from a rate limit from a media error — don't swallow it.
    """
    if not resp.ok:
        print(f"ERROR during {context}: HTTP {resp.status_code}")
        print(resp.text[:2000])
    resp.raise_for_status()


def check_token_expiry(access_token):
    """Warn when the access token expires within 30 days. Soft-fail."""
    try:
        resp = requests.get(
            f"{GRAPH_API_BASE}/debug_token",
            params={"input_token": access_token, "access_token": access_token},
            timeout=30,
        )
        info = resp.json().get("data", {})
        expires_at = info.get("expires_at")
        if not expires_at:  # 0 / absent = never expires
            print("Token check: no expiry (never-expiring token confirmed)")
            return
        from datetime import datetime, timezone
        remaining = datetime.fromtimestamp(expires_at, tz=timezone.utc) - datetime.now(timezone.utc)
        if remaining.days < 30:
            print(f"WARNING: Instagram access token expires in {remaining.days} day(s) — rotate it soon")
        else:
            print(f"Token check: expires in {remaining.days} day(s)")
    except Exception as e:
        print(f"Token check skipped ({e})")


def wait_for_container(creation_id, access_token, timeout_seconds=60):
    """Poll the media container until Instagram reports FINISHED.

    Replaces a blind fixed sleep — the classic source of intermittent
    'Media ID is not available' publish failures.
    """
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        resp = requests.get(
            f"{GRAPH_API_BASE}/{creation_id}",
            params={"fields": "status_code", "access_token": access_token},
            timeout=30,
        )
        _raise_with_body(resp, "container status poll")
        status = resp.json().get("status_code", "")
        print(f"  container status: {status}")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"Media container {creation_id} failed processing")
        time.sleep(5)
    raise RuntimeError(f"Media container {creation_id} not ready after {timeout_seconds}s")


def post_to_instagram(image_url, caption, access_token, ig_user_id):
    """Two-step Instagram Graph API publish."""
    check_token_expiry(access_token)

    # Step 1: Create media container
    print(f"Creating media container for {image_url}...")
    create_resp = requests.post(
        f"{GRAPH_API_BASE}/{ig_user_id}/media",
        data={
            "image_url": image_url,
            "caption": caption,
            "access_token": access_token,
            **tag_fields(),
            **collaborator_fields(),
        },
        timeout=60,
    )
    _raise_with_body(create_resp, "media container creation")
    creation_id = create_resp.json()["id"]
    print(f"Media container created: {creation_id}")

    # Wait for Instagram to download and process the image
    print("Waiting for container processing...")
    wait_for_container(creation_id, access_token)

    # Step 2: Publish
    print("Publishing...")
    publish_resp = requests.post(
        f"{GRAPH_API_BASE}/{ig_user_id}/media_publish",
        data={
            "creation_id": creation_id,
            "access_token": access_token,
        },
        timeout=60,
    )
    _raise_with_body(publish_resp, "media publish")
    post_id = publish_resp.json()["id"]
    print(f"Published! Post ID: {post_id}")
    return post_id



def post_carousel(image_urls, caption, access_token, ig_user_id):
    """Publish a carousel: one child container per slide, then a parent.

    Every slide must be the same aspect ratio (the renderer emits 4:5 for all
    of them). Carousels get the most reach and saves on Instagram, and the
    grid shows only the first slide, so the cover carries the day's story and
    the full leaderboard still ships as a later slide.
    """
    check_token_expiry(access_token)
    if not 2 <= len(image_urls) <= 10:
        raise ValueError(f"carousel needs 2-10 slides, got {len(image_urls)}")

    child_ids = []
    for i, url in enumerate(image_urls, 1):
        print(f"Creating carousel item {i}/{len(image_urls)} for {url}...")
        resp = requests.post(
            f"{GRAPH_API_BASE}/{ig_user_id}/media",
            data={"image_url": url, "is_carousel_item": "true", "access_token": access_token, **tag_fields()},
            timeout=60,
        )
        _raise_with_body(resp, f"carousel item {i}")
        cid = resp.json()["id"]
        wait_for_container(cid, access_token)
        child_ids.append(cid)

    print("Creating carousel container...")
    parent = requests.post(
        f"{GRAPH_API_BASE}/{ig_user_id}/media",
        data={"media_type": "CAROUSEL", "children": ",".join(child_ids),
              "caption": caption, "access_token": access_token, **collaborator_fields()},
        timeout=60,
    )
    _raise_with_body(parent, "carousel container")
    creation_id = parent.json()["id"]
    wait_for_container(creation_id, access_token)

    print("Publishing carousel...")
    publish = requests.post(
        f"{GRAPH_API_BASE}/{ig_user_id}/media_publish",
        data={"creation_id": creation_id, "access_token": access_token},
        timeout=60,
    )
    _raise_with_body(publish, "carousel publish")
    post_id = publish.json()["id"]
    print(f"Published carousel! Post ID: {post_id}")
    return post_id


# ---------------------------------------------------------------------------
# Tagging
# ---------------------------------------------------------------------------
# IG_TAG_USERNAME (default richcrane): mentioned in the caption and tagged on
# every image via user_tags (public accounts only; x/y are fractions of the
# image, placed bottom-right beside the site URL). IG_COLLABORATORS (opt-in,
# comma-separated, max 3) adds the post to those accounts' own grids via the
# collaborators field; the invited account has to accept.

DEFAULT_TAG_USERNAME = "richcrane"
TAG_POSITION = {"x": 0.92, "y": 0.96}


def tag_username():
    return os.environ.get("IG_TAG_USERNAME", DEFAULT_TAG_USERNAME).strip().lstrip("@")


def collaborators():
    raw = os.environ.get("IG_COLLABORATORS", "")
    names = [n.strip().lstrip("@") for n in raw.split(",") if n.strip()]
    return names[:3]


def with_mention(caption, username=None):
    """Append an @mention once, on its own line, if it is not already there."""
    username = username or tag_username()
    if not username or f"@{username}" in caption:
        return caption
    return f"{caption.rstrip()}\n\n@{username}"


def tag_fields(username=None):
    """Extra form fields for an image container so the account is tagged on it."""
    username = username or tag_username()
    if not username:
        return {}
    return {"user_tags": json.dumps([{"username": username, **TAG_POSITION}])}


def collaborator_fields():
    names = collaborators()
    return {"collaborators": json.dumps(names)} if names else {}


# ---------------------------------------------------------------------------
# Once-per-day guard
# ---------------------------------------------------------------------------
# The workflow fires on every successful deploy, and a deploy follows every
# push to main - code changes included. On 2026-09-03 that produced several
# posts of the same day's board within a few hours. The rule is at most one
# post per UTC day, and the source of truth for "did we post today" is
# Instagram itself, not repo state: ask the account for its latest media.

def already_posted_today(access_token, ig_user_id, now=None):
    """Return the timestamp of today's post if one exists, else None.

    Fails CLOSED: if Instagram cannot be asked, returns a sentinel string so
    the caller skips - a missed post is recoverable, a duplicate is not.
    """
    from datetime import datetime, timezone
    now = now or datetime.now(timezone.utc)
    try:
        resp = requests.get(
            f"{GRAPH_API_BASE}/{ig_user_id}/media",
            params={"fields": "id,timestamp,permalink", "limit": 10, "access_token": access_token},
            timeout=30,
        )
        resp.raise_for_status()
        items = resp.json().get("data", [])
    except Exception as exc:  # network, auth, schema - anything
        return f"UNKNOWN (could not query Instagram: {exc})"

    # Graph API timestamps look like 2026-09-03T10:07:00+0000
    def _parse(ts):
        try:
            return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z").astimezone(timezone.utc)
        except (TypeError, ValueError):
            return None

    today = []
    for item in items:
        posted = _parse(item.get("timestamp"))
        if posted is None:
            return f"UNKNOWN (unparseable timestamp {item.get('timestamp')!r})"
        if posted.date() == now.date():
            today.append(item)
    if not today:
        return None
    # List every post from today so a manual clean-up knows exactly what
    # remains; the guard only sees what Instagram reports, and "I deleted
    # today's post" can mean any one of several.
    print(f"Instagram reports {len(today)} post(s) today (UTC):")
    for item in today:
        print(f"  {item.get('timestamp')}  id={item.get('id')}  {item.get('permalink', '')}")
    return today[0].get("timestamp", "")


def snapshot_is_today(models_path, now=None):
    """Only publish a board that was scraped today - never re-post stale data."""
    from datetime import datetime, timezone
    now = now or datetime.now(timezone.utc)
    with open(models_path) as f:
        history = json.load(f).get("history") or []
    if not history:
        return False
    ts = history[0].get("timestamp", "")
    try:
        scraped = datetime.fromisoformat(ts).astimezone(timezone.utc)
    except ValueError:
        return False
    return scraped.date() == now.date()

def main():
    access_token = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
    ig_user_id = os.environ.get("IG_USER_ID")

    if not access_token or not ig_user_id:
        print("ERROR: INSTAGRAM_ACCESS_TOKEN and IG_USER_ID must be set")
        sys.exit(1)

    workspace = Path(__file__).resolve().parent.parent
    models_path = workspace / "models.json"

    if not models_path.exists():
        print("ERROR: models.json not found")
        sys.exit(1)

    image_url = "https://usvschina.ai/ig-image.png"

    force = os.environ.get("IG_FORCE", "").lower() in ("1", "true", "yes")
    if force:
        print("IG_FORCE set - bypassing the once-per-day and freshness guards")
    else:
        posted = already_posted_today(access_token, ig_user_id)
        if posted:
            print(f"Skipping: already posted today ({posted}). Maximum one post per day.")
            return
        if not snapshot_is_today(models_path):
            print("Skipping: latest snapshot is not from today - not re-posting stale data.")
            return

    data = load_caption_data(models_path)
    caption = with_mention(os.environ.get("IG_CAPTION") or build_caption(data))

    print(f"Caption:\n{caption}\n")

    # IG_CAROUSEL_URLS: comma-separated slide URLs, all 4:5. Set by the
    # workflow once the social renderer is wired in; absent, the single
    # ig-image.png post is unchanged.
    slides = [u.strip() for u in os.environ.get("IG_CAROUSEL_URLS", "").split(",") if u.strip()]
    if len(slides) >= 2:
        post_carousel(slides, caption, access_token, ig_user_id)
    else:
        post_to_instagram(image_url, caption, access_token, ig_user_id)
    print("Instagram post complete.")


if __name__ == "__main__":
    main()
