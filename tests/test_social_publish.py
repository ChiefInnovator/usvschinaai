#!/usr/bin/env python3
"""social_publish.py: the day's carousel as the daily scrape produces it and
post_to_instagram.py consumes it. Rendering and the caption model are stubbed;
what is under test is naming, pruning, plan.json and the day's story."""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import social_publish as sp
from test_social_formats import row, snapshot, data


def _data(ts="2026-09-05T03:30:00+00:00"):
    us = [row(f"US{i}", "US", 900 - i * 20) for i in range(10)]
    cn = [row(f"CN{i}", "CN", 850 - i * 20) for i in range(10)]
    prev = snapshot("2026-09-04T03:30:00+00:00", us, cn)
    return data(snapshot(ts, us, cn), prev)


class NamingAndPruneTests(unittest.TestCase):
    def test_slide_names_are_date_stamped_and_ordered(self):
        self.assertEqual(sp.slide_filename("2026-09-05", 1, "head_to_head", "midnight"),
                         "2026-09-05-1-head_to_head-midnight.png")
        self.assertEqual(sp.slides_for("head_to_head", "midnight"),
                         [("head_to_head", "midnight"), ("leaderboard", "midnight")])
        self.assertEqual(sp.slides_for("leaderboard", "graphite"), [("leaderboard", "graphite")],
                         "the leaderboard is never its own second slide")

    def test_prune_keeps_only_todays_slides_and_the_plan(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            for name in ("2026-09-04-1-x-y.png", "2026-09-04-2-leaderboard-y.png",
                         "2026-09-05-1-x-y.png", "plan.json"):
                (out / name).write_bytes(b"x")
            removed = sp.prune(out, "2026-09-05")
            self.assertEqual(removed, ["2026-09-04-1-x-y.png", "2026-09-04-2-leaderboard-y.png"])
            self.assertEqual(sorted(p.name for p in out.iterdir()), ["2026-09-05-1-x-y.png", "plan.json"])


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.rendered = []
        self.addCleanup(setattr, sp.sr, "render_png", sp.sr.render_png)
        self.addCleanup(setattr, sp, "generate_caption", sp.generate_caption)

        def fake_render(html_text, out):
            Path(out).write_bytes(b"png"); self.rendered.append(Path(out).name); return out
        sp.sr.render_png = fake_render
        sp.generate_caption = lambda facts, fmt, weight, api_key=None, use_cache=True: {
            "hook": f"HOOK {fmt}", "bullets": ["a", "b"], "question": "Q?", "hashtags": ["#AI"], "_source": "stub"}

    def test_plan_has_two_slides_urls_and_caption(self):
        with tempfile.TemporaryDirectory() as d:
            plan, removed = sp.publish(_data(), Path(d), today=datetime(2026, 9, 5, 4, tzinfo=timezone.utc), history=[])
            self.assertEqual(plan["date"], "2026-09-05")
            self.assertEqual(len(plan["slides"]), 2 if plan["format"] != "leaderboard" else 1)
            self.assertTrue(all(u.startswith("https://usvschina.ai/social/2026-09-05-") for u in plan["urls"]))
            self.assertEqual(plan["slides"], self.rendered)
            self.assertIn(f"HOOK {plan['format']}", plan["caption"])
            self.assertEqual(plan["caption_source"], "stub")
            written = json.loads((Path(d) / "plan.json").read_text())
            self.assertEqual(written["urls"], plan["urls"])
            self.assertEqual(removed, [])

    def test_rerun_same_day_keeps_the_story_and_replaces_older_slides(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "2026-09-04-1-old-old.png").write_bytes(b"x")
            today = datetime(2026, 9, 5, 4, tzinfo=timezone.utc)
            first, removed = sp.publish(_data(), Path(d), today=today, history=[])
            self.assertEqual(removed, ["2026-09-04-1-old-old.png"])
            hist = [sp.history_record(first)]
            second, _ = sp.publish(_data(), Path(d), today=today, history=hist)
            self.assertEqual((first["format"], first["palette"]), (second["format"], second["palette"]),
                             "a same-day rerun must not rotate the story")

    def test_next_day_rotates_away_from_yesterdays_palette(self):
        with tempfile.TemporaryDirectory() as d:
            day1 = datetime(2026, 9, 5, 4, tzinfo=timezone.utc)
            first, _ = sp.publish(_data(), Path(d), today=day1, history=[])
            day2 = datetime(2026, 9, 6, 4, tzinfo=timezone.utc)
            second, _ = sp.publish(_data("2026-09-06T03:30:00+00:00"), Path(d), today=day2,
                                   history=[sp.history_record(first)])
            self.assertNotEqual(first["palette"], second["palette"])

    def test_history_record_is_minimal(self):
        rec = sp.history_record({"date": "d", "timestamp": "t", "format": "f", "palette": "p",
                                 "caption": "long", "urls": ["u"], "benchmark": "HLE"})
        self.assertEqual(rec, {"date": "d", "timestamp": "t", "format": "f", "palette": "p", "benchmark": "HLE"})


if __name__ == "__main__":
    unittest.main()
