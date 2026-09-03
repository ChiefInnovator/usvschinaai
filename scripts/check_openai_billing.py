#!/usr/bin/env python3
"""Preflight: is the OpenAI key valid AND funded?

The gap-filling pass researches missing benchmark scores, and without it the
cohort is scored on whatever llm-stats happens to publish. On 2026-09-03 that
meant 523 empty cells and models being ranked on 2 of 7 benchmarks. The pass
had been failing since 2026-04-25 because the key ran out of quota, and
nothing surfaced it: the scrape ran for 45 minutes, aborted gap-fill on its
first batch, and published thin data as if nothing were wrong.

This runs before the scrape and distinguishes the two failure modes, because
they need different fixes:

  401 invalid_api_key  -> the key is wrong/revoked; rotate the secret
  429 insufficient_quota -> the key is fine; the account needs funding

Exit 0 = usable. Exit 1 = do not run.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.4"


def check(api_key: str, model: str) -> tuple[bool, str]:
    """Smallest possible billable call — enough to prove quota exists."""
    body = json.dumps({"model": model, "input": "ping", "max_output_tokens": 16}).encode()
    req = urllib.request.Request(
        RESPONSES_URL,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            r.read()
        return True, f"OpenAI billing OK ({model} reachable and funded)"
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode()).get("error", {})
        except Exception:
            err = {}
        code = err.get("code") or err.get("type") or f"http_{e.code}"
        msg = (err.get("message") or "").strip()
        if e.code == 401:
            return False, f"API key rejected ({code}). Rotate the OPENAI_API_KEY secret.\n  {msg[:200]}"
        if e.code == 429 or "quota" in code or "quota" in msg.lower():
            return False, f"API key valid but OUT OF QUOTA ({code}). Fund the account at platform.openai.com.\n  {msg[:200]}"
        return False, f"OpenAI preflight failed ({code}, HTTP {e.code}).\n  {msg[:200]}"
    except Exception as e:  # network, DNS, timeout
        return False, f"Could not reach OpenAI: {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default=os.environ.get("AI_GAP_FILL_MODEL", DEFAULT_MODEL))
    ap.add_argument(
        "--warn-only",
        action="store_true",
        help="report the problem but exit 0 (publish thin data rather than nothing)",
    )
    args = ap.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        print("::error::OPENAI_API_KEY is not set — gap-filling cannot run")
        return 0 if args.warn_only else 1

    ok, message = check(api_key, args.model)
    if ok:
        print(f"✅ {message}")
        return 0

    level = "warning" if args.warn_only else "error"
    print(f"::{level}::{message}")
    print(
        "\nWithout gap-filling, missing benchmark scores are never researched and "
        "models get ranked on a fraction of the benchmark set."
    )
    return 0 if args.warn_only else 1


if __name__ == "__main__":
    sys.exit(main())
