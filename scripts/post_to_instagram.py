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


def post_to_instagram(image_url, caption, access_token, ig_user_id):
    """Two-step Instagram Graph API publish."""
    base_url = "https://graph.facebook.com/v21.0"

    # Step 1: Create media container
    print(f"Creating media container for {image_url}...")
    create_resp = requests.post(
        f"{base_url}/{ig_user_id}/media",
        data={
            "image_url": image_url,
            "caption": caption,
            "access_token": access_token,
        },
    )
    create_resp.raise_for_status()
    creation_id = create_resp.json()["id"]
    print(f"Media container created: {creation_id}")

    # Wait for Instagram to download and process the image
    print("Waiting for container processing...")
    time.sleep(15)

    # Step 2: Publish
    print("Publishing...")
    publish_resp = requests.post(
        f"{base_url}/{ig_user_id}/media_publish",
        data={
            "creation_id": creation_id,
            "access_token": access_token,
        },
    )
    publish_resp.raise_for_status()
    post_id = publish_resp.json()["id"]
    print(f"Published! Post ID: {post_id}")
    return post_id


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

    data = load_caption_data(models_path)
    caption = build_caption(data)

    print(f"Caption:\n{caption}\n")

    post_to_instagram(image_url, caption, access_token, ig_user_id)
    print("Instagram post complete.")


if __name__ == "__main__":
    main()
