#!/usr/bin/env python3
"""
Mint a never-expiring Instagram Page token that can post link comments,
store it in GitHub secrets, and add the link comment to recent posts missing it.

  .venv/bin/python scripts/fix_instagram_token.py --ig-user-id ID  # browser login
  .venv/bin/python scripts/fix_instagram_token.py --token --ig-user-id ID  # token pasted from Graph API Explorer

Needs FB_APP_ID / FB_APP_SECRET (env, or prompted). The one step Meta keeps
dashboard-only is adding instagram_manage_comments to the app (App Review >
Permissions and Features); if it is not granted, this opens that page and stops.
"""
from preconditions import preconditions
from post_to_instagram import GRAPH_API_BASE, repair_recent_comments
import argparse
import getpass
import os
import secrets
import subprocess
import sys
import urllib.parse
import webbrowser

import requests

SCOPES = ["pages_show_list", "pages_read_engagement", "business_management",
          "instagram_basic", "instagram_content_publish", "instagram_manage_comments"]
REQUIRED = {"instagram_basic", "instagram_content_publish", "instagram_manage_comments", "pages_read_engagement"}
REDIRECT_URI = "https://usvschina.ai/"
GH = "/opt/homebrew/bin/gh" if os.path.exists("/opt/homebrew/bin/gh") else "gh"


@preconditions(path='nonempty', params='mapping')
def graph(path, params):
    try:
        resp = requests.get(f"{GRAPH_API_BASE}/{path}", params=params, timeout=30)
    except requests.RequestException:
        raise RuntimeError(f"Meta request failed during {path}") from None
    if not resp.ok:
        error = resp.json().get("error", {})
        raise RuntimeError(f"Meta rejected {path}: HTTP {resp.status_code}, code {error.get('code')}")
    return resp.json()



@preconditions(app_id='nonempty')
def browser_login(app_id):
    """Run the OAuth dialog and return the authorization code from the pasted redirect URL.

    The app enforces HTTPS redirect URIs, so localhost can't receive the redirect;
    REDIRECT_URI must be listed in Facebook Login > Settings > Valid OAuth Redirect URIs.
    """
    state = secrets.token_urlsafe(16)
    url = "https://www.facebook.com/v23.0/dialog/oauth?" + urllib.parse.urlencode({
        "client_id": app_id, "redirect_uri": REDIRECT_URI, "state": state,
        "scope": ",".join(SCOPES), "auth_type": "rerequest", "response_type": "code",
    })
    print("Opening Facebook login. Select your Page AND its Instagram account in the dialog.")
    webbrowser.open(url)
    landed = input(f"Paste the full URL of the {REDIRECT_URI} page you land on: ").strip()
    result = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(landed).query).items()}
    if "code" not in result:
        sys.exit(f"Login refused: {result.get('error_description') or result.get('error_message') or 'no code in URL'}\n"
                 "If this is \"Can't load URL\", the app lacks Advanced Access to public_profile; rerun with "
                 f"--token from https://developers.facebook.com/tools/explorer/{app_id}/ instead.")
    if result.get("state") != state:
        sys.exit("That URL is from a different login attempt; rerun.")
    return result["code"]


@preconditions(app_id='nonempty', app_secret='nonempty')
def user_token(app_id, app_secret, pasted=None):
    if pasted:
        short = pasted
    else:
        short = graph("oauth/access_token", dict(client_id=app_id, client_secret=app_secret,
                      redirect_uri=REDIRECT_URI, code=browser_login(app_id)))["access_token"]
    return graph("oauth/access_token", dict(grant_type="fb_exchange_token", client_id=app_id,
                 client_secret=app_secret, fb_exchange_token=short))["access_token"]


@preconditions(token='nonempty', app_id='nonempty')
def require_comment_permission(token, app_id):
    granted = {p["permission"] for p in graph("me/permissions", dict(access_token=token))["data"]
               if p["status"] == "granted"}
    missing = REQUIRED - granted
    if missing:
        webbrowser.open(f"https://developers.facebook.com/apps/{app_id}/app-review/permissions/")
        sys.exit(f"Not granted: {', '.join(sorted(missing))}. If the page that just opened lists "
                 "them as Ready to use, rerun and leave every permission checked in the login "
                 "dialog; otherwise add them there (you must be an app Admin, or have Advanced Access).")


@preconditions(token='nonempty')
def pick_page(token):
    pages = [p for p in graph("me/accounts", dict(access_token=token,
                              fields="name,access_token,instagram_business_account"))["data"]
             if p.get("instagram_business_account")]
    if not pages:
        sys.exit("No Page with a linked Instagram account was granted; rerun and select both.")
    if len(pages) > 1:
        for i, p in enumerate(pages):
            print(f"  [{i}] {p['name']}")
        pages = [pages[int(input("Page number: "))]]
    return pages[0]


@preconditions(page_token='nonempty', app_id='nonempty', app_secret='nonempty')
def verify_page_token(page_token, app_id, app_secret):
    info = graph("debug_token", dict(input_token=page_token,
                 access_token=f"{app_id}|{app_secret}"))["data"]
    if not info.get("is_valid") or info.get("expires_at", 1) != 0:
        sys.exit("Page token is not a valid never-expiring token")
    if REQUIRED - set(info.get("scopes", [])):
        sys.exit(f"Page token scopes missing: {sorted(REQUIRED - set(info['scopes']))}")


@preconditions(name='nonempty', value='nonempty')
def set_secret(name, value):
    subprocess.run([GH, "secret", "set", name], input=value, text=True, check=True)


@preconditions()
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--token", action="store_true", help="prompt privately for a Graph API Explorer user token")
    ap.add_argument("--ig-user-id", required=True, help="expected Instagram account ID; refuse another account")
    ap.add_argument("--days", type=int, default=14, help="backfill link comments on posts this recent")
    args = ap.parse_args()

    app_id = os.environ.get("FB_APP_ID") or input("FB_APP_ID: ").strip()
    app_secret = os.environ.get("FB_APP_SECRET") or getpass.getpass("FB_APP_SECRET: ").strip()

    token = user_token(app_id, app_secret, getpass.getpass("User token: ") if args.token else None)
    require_comment_permission(token, app_id)
    page = pick_page(token)
    ig_user_id = page["instagram_business_account"]["id"]
    if str(ig_user_id) != args.ig_user_id:
        sys.exit("Selected Page is linked to a different Instagram account; no secrets changed")
    verify_page_token(page["access_token"], app_id, app_secret)
    # Verify real comment access and recovery before replacing the working token.
    repair_recent_comments(page["access_token"], ig_user_id, args.days)

    set_secret("INSTAGRAM_ACCESS_TOKEN", page["access_token"])
    print(f"Updated INSTAGRAM_ACCESS_TOKEN and IG_USER_ID for {page['name']} (IG {ig_user_id}).")


if __name__ == "__main__":
    main()
