#!/usr/bin/env python3
"""The caption is the only token spend in the social pipeline; keep it tiny and safe."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

try:
    import social_caption as sc
except ImportError:
    sc = None

FACTS = {
    "timestamp": "2026-09-04T09:31:36+00:00", "totals": {"US": 4836.0, "CN": 3025.0}, "leader": "US",
    "margin": 1811.0, "us_in_top10": 6, "cn_in_top10": 4,
    "top10": [{"model": "Muse Spark 1.3", "unified": 948.2}], "first_us": {"model": "Muse Spark 1.3"},
    "first_cn": {"model": "Qwen3.8 Flash"}, "brand_new": ["GPT-6 Astra"], "new_entrants": ["GPT-6 Astra"],
    "biggest_mover": {"model": "Qwen3.8 Flash", "places": 13},
}


@unittest.skipIf(sc is None, "requests not installed")
class RoutingAndCostTests(unittest.TestCase):
    def test_routine_days_use_the_cheap_model(self):
        self.assertEqual(sc.choose_caption_model(1), sc.ROUTINE_MODEL)

    def test_big_stories_escalate(self):
        self.assertEqual(sc.choose_caption_model(4), sc.STRONG_MODEL)

    def test_cost_ledger_maths(self):
        usage = {"input_tokens": 1000, "output_tokens": 200, "input_tokens_details": {"cached_tokens": 400}}
        # luna: (600*0.20 + 400*0.02 + 200*1.20) / 1e6
        self.assertAlmostEqual(sc.cost_usd("gpt-5.6-luna", usage), (120 + 8 + 240) / 1e6, places=9)

    def test_output_is_capped_and_schema_constrained(self):
        self.assertLessEqual(sc.MAX_OUTPUT_TOKENS, 400)
        self.assertEqual(sc.CAPTION_SCHEMA["properties"]["bullets"]["maxItems"], 3)


@unittest.skipIf(sc is None, "requests not installed")
class SafetyTests(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(setattr, sc, "CACHE_PATH", sc.CACHE_PATH)
        self.addCleanup(setattr, sc, "LEDGER_PATH", sc.LEDGER_PATH)
        sc.CACHE_PATH, sc.LEDGER_PATH = d / "cache.json", d / "ledger.jsonl"

    def test_no_key_means_fallback_not_failure(self):
        cap = sc.generate_caption(FACTS, "new_challenger", 3, api_key="")
        self.assertTrue(cap["_source"].startswith("fallback"))
        self.assertIn("GPT-6 Astra", cap["hook"])
        self.assertEqual(len(cap["bullets"]), 3)

    def test_api_failure_falls_back_after_one_attempt(self):
        calls = []
        self.addCleanup(setattr, sc.requests, "post", sc.requests.post)
        def boom(*a, **k):
            calls.append(1); raise RuntimeError("down")
        sc.requests.post = boom
        cap = sc.generate_caption(FACTS, "head_to_head", 1, api_key="k")
        self.assertEqual(len(calls), 1, "must not retry")
        self.assertTrue(cap["_source"].startswith("fallback"))

    def test_cache_hit_makes_no_call(self):
        calls = []
        self.addCleanup(setattr, sc.requests, "post", sc.requests.post)
        sc.requests.post = lambda *a, **k: calls.append(1)
        sc._save_cache({f"{FACTS['timestamp']}|head_to_head": {"hook": "h", "bullets": ["a", "b", "c"], "question": "q", "hashtags": ["#x"] * 6}})
        cap = sc.generate_caption(FACTS, "head_to_head", 1, api_key="k")
        self.assertEqual(calls, [])
        self.assertEqual(cap["_source"], "cache")

    def test_request_is_small_and_capped(self):
        seen = {}
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {"usage": {"input_tokens": 500, "output_tokens": 120},
                        "output": [{"content": [{"type": "output_text", "text": json.dumps(
                            {"hook": "h", "bullets": ["a", "b", "c"], "question": "q", "hashtags": ["#a"] * 6})}]}]}
        self.addCleanup(setattr, sc.requests, "post", sc.requests.post)
        def post(url, headers=None, json=None, timeout=None):
            seen.update(json); return R()
        sc.requests.post = post
        sc.generate_caption(FACTS, "head_to_head", 1, api_key="k", use_cache=False)
        self.assertEqual(seen["max_output_tokens"], sc.MAX_OUTPUT_TOKENS)
        self.assertLess(len(seen["input"]), 4000, "facts JSON must stay small")
        self.assertEqual(seen["instructions"], sc.SYSTEM_PROMPT)
        self.assertTrue(seen["text"]["format"]["strict"])
        self.assertTrue(sc.LEDGER_PATH.exists())

    def test_render_caption_shape(self):
        text = sc.render_caption(sc.fallback_caption(FACTS, "leaderboard"))
        self.assertIn("usvschina.ai", text)
        self.assertEqual(text.count("•"), 3)
        self.assertTrue(text.strip().endswith("#TechNews"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
