#!/usr/bin/env python3
"""The daily post must vary by story and by colour, driven by the data."""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from social_formats import (FORMAT_PALETTES, NO_REPEAT_DAYS, PALETTES, build_day_facts,
                            choose_format, choose_palette, detect_events, plan_today)


def row(model, origin, unified, iq=50.0, value=1.0, price_in=1.0):
    return {"model": model, "organization": "x", "unified": unified, "avgIq": iq,
            "value": value, "Input$/M": f"${price_in}", "Output$/M": "$1.00", "coverage": "5/8"}


def snapshot(ts, us, cn):
    return {"timestamp": ts, "teams": {"US": us, "CN": cn}}


def data(*entries):
    return {"history": list(entries)}


US = [row(f"US{i}", "US", 900 - i * 20) for i in range(10)]   # 900..720
CN = [row(f"CN{i}", "CN", 890 - i * 20) for i in range(10)]   # 890..710
T = "2026-09-04T09:31:36+00:00"
Y = "2026-09-03T03:30:00+00:00"


class FactsTests(unittest.TestCase):
    def test_totals_mirror_the_frontend_top10_rule(self):
        f = build_day_facts(data(snapshot(T, US, CN)))
        # combined top 10 alternates US/CN: 900,890,...,810
        self.assertEqual(f["totals"]["US"], 900 + 880 + 860 + 840 + 820)
        self.assertEqual(f["totals"]["CN"], 890 + 870 + 850 + 830 + 810)
        self.assertEqual(f["leader"], "US")

    def test_previous_day_is_a_prior_date_not_an_earlier_run_today(self):
        earlier_today = snapshot("2026-09-04T05:10:00+00:00", US, CN)
        f = build_day_facts(data(snapshot(T, US, CN), earlier_today, snapshot(Y, CN, US)))
        self.assertIsNotNone(f["prev_totals"])
        self.assertEqual(f["prev_leader"], "CN")  # from Y, where teams were swapped

    def test_new_entrants_and_mover_detected(self):
        # US9 (720, rank 19 yesterday) jumps to 999 today: it enters the top 10
        # AND is the biggest mover. Everyone else shifts by at most one place.
        today_us = US[:9] + [row("US9", "US", 999)]
        f = build_day_facts(data(snapshot(T, today_us, CN), snapshot(Y, US, CN)))
        self.assertEqual(f["new_entrants"], ["US9"])
        self.assertEqual(f["biggest_mover"]["model"], "US9")
        self.assertEqual(f["biggest_mover"]["places"], 18)

    def test_brand_new_is_absent_from_the_whole_previous_board(self):
        # "Riser" was #19 yesterday and is #1 today: in the top 10 for the first
        # time, but NOT brand new. "Fresh" was nowhere yesterday: brand new.
        today_us = [row("Fresh", "US", 999), row("Riser", "US", 998)] + US[:8]
        prev_us = US + [row("Riser", "US", 500)]
        f = build_day_facts(data(snapshot(T, today_us, CN), snapshot(Y, prev_us, CN)))
        self.assertEqual(f["brand_new"], ["Fresh"])
        self.assertEqual(set(f["new_entrants"]), {"Fresh", "Riser"})

    def test_facts_are_small(self):
        import json
        f = build_day_facts(data(snapshot(T, US, CN), snapshot(Y, US, CN)))
        self.assertLess(len(json.dumps(f)), 6000, "facts dict is the caption token budget")


class EventTests(unittest.TestCase):
    def test_lead_change_outranks_everything(self):
        f = {"leader": "CN", "prev_leader": "US", "new_entrants": ["x"], "biggest_mover": {"places": 5}}
        self.assertEqual(detect_events(f)[0][1], "lead_change")

    def test_small_moves_are_not_a_story(self):
        f = {"leader": "US", "prev_leader": "US", "new_entrants": [], "biggest_mover": {"places": 1}}
        self.assertEqual(detect_events(f), [])


class ChooserTests(unittest.TestCase):
    quiet = {"leader": "US", "prev_leader": "US", "new_entrants": [], "biggest_mover": None}

    def test_no_format_repeats_within_window(self):
        recent = []
        for _ in range(12):
            fmt = choose_format(self.quiet, recent, today=datetime(2026, 9, 2, tzinfo=timezone.utc))
            self.assertNotIn(fmt, recent[-NO_REPEAT_DAYS:][-3:] if len(recent) >= 3 else [])
            recent.append(fmt)
        # Over 12 quiet days, at least 3 distinct formats appear.
        self.assertGreaterEqual(len(set(recent)), 3)

    def test_event_used_recently_falls_back_to_rotation(self):
        f = dict(self.quiet, new_entrants=["x"])
        fmt = choose_format(f, ["new_challenger"], today=datetime(2026, 9, 2, tzinfo=timezone.utc))
        self.assertNotEqual(fmt, "new_challenger")

    def test_sunday_is_the_trend(self):
        fmt = choose_format(self.quiet, [], today=datetime(2026, 9, 6, tzinfo=timezone.utc))  # a Sunday
        self.assertEqual(fmt, "trend_30d")


class PaletteTests(unittest.TestCase):
    def test_every_format_has_two_palettes_that_exist(self):
        for fmt, opts in FORMAT_PALETTES.items():
            self.assertEqual(len(opts), 2, fmt)
            for p in opts:
                self.assertIn(p, PALETTES)

    def test_never_yesterdays_palette(self):
        for fmt in FORMAT_PALETTES:
            for yesterday in PALETTES:
                p = choose_palette(fmt, {"leader": "US"}, [yesterday])
                self.assertNotEqual(p, yesterday, f"{fmt} repeated {yesterday}")

    def test_lead_change_colour_follows_the_leader(self):
        self.assertEqual(choose_palette("lead_change", {"leader": "US"}, []), "cobalt")
        self.assertEqual(choose_palette("lead_change", {"leader": "CN"}, []), "signal")

    def test_consecutive_days_differ_in_colour(self):
        recent_p = []
        for day in range(10):
            fmt = choose_format(ChooserTests.quiet, [], today=datetime(2026, 9, 1 + day, tzinfo=timezone.utc))
            p = choose_palette(fmt, ChooserTests.quiet, recent_p)
            if recent_p:
                self.assertNotEqual(p, recent_p[-1])
            recent_p.append(p)


class PlanTests(unittest.TestCase):
    def test_plan_is_stable_across_reruns_on_the_same_day(self):
        d = data(snapshot(T, US, CN), snapshot(Y, US, CN))
        first = plan_today(d, history=[], today=datetime(2026, 9, 4, tzinfo=timezone.utc))
        again = plan_today(d, history=[{"date": "2026-09-04", "format": first["format"], "palette": first["palette"]}],
                           today=datetime(2026, 9, 4, tzinfo=timezone.utc))
        self.assertEqual(first["format"], again["format"])
        self.assertEqual(first["palette"], again["palette"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
