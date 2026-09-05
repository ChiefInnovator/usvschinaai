#!/usr/bin/env python3
"""The Instagram post must happen at most once per UTC day.

The workflow fires on every successful deploy, and a deploy follows every
push to main. On 2026-09-03 the same board was posted several times in a
few hours. The guard asks Instagram for its latest media and skips if it was
posted today; it also refuses to post a snapshot that is not from today.
"""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

try:
    import post_to_instagram as pti
except ImportError:  # requests not installed
    pti = None

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


class FakeResp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")
    def json(self):
        return self._p


@unittest.skipIf(pti is None, "requests not installed")
class AlreadyPostedTodayTests(unittest.TestCase):
    def _with(self, payload, status=200):
        self.addCleanup(setattr, pti.requests, "get", pti.requests.get)
        pti.requests.get = lambda *a, **k: FakeResp(payload, status)

    def test_post_earlier_today_blocks(self):
        self._with({"data": [{"id": "1", "timestamp": "2026-09-04T03:35:00+0000"}]})
        self.assertTrue(pti.already_posted_today("t", "u", now=NOW))

    def test_post_yesterday_allows(self):
        self._with({"data": [{"id": "1", "timestamp": "2026-09-03T23:59:00+0000"}]})
        self.assertIsNone(pti.already_posted_today("t", "u", now=NOW))

    def test_timezone_is_respected(self):
        # 23:30 on the 3rd in UTC-5 is 04:30 on the 4th UTC -> today.
        self._with({"data": [{"id": "1", "timestamp": "2026-09-03T23:30:00-0500"}]})
        self.assertTrue(pti.already_posted_today("t", "u", now=NOW))

    def test_several_posts_today_still_blocks_and_reports_newest(self):
        self._with({"data": [
            {"id": "3", "timestamp": "2026-09-04T09:22:57+0000"},
            {"id": "2", "timestamp": "2026-09-04T05:14:00+0000"},
            {"id": "1", "timestamp": "2026-09-03T23:00:00+0000"},
        ]})
        self.assertEqual(pti.already_posted_today("t", "u", now=NOW), "2026-09-04T09:22:57+0000")

    def test_only_older_posts_in_the_window_allows(self):
        self._with({"data": [
            {"id": "2", "timestamp": "2026-09-03T09:00:00+0000"},
            {"id": "1", "timestamp": "2026-09-02T09:00:00+0000"},
        ]})
        self.assertIsNone(pti.already_posted_today("t", "u", now=NOW))

    def test_no_media_allows(self):
        self._with({"data": []})
        self.assertIsNone(pti.already_posted_today("t", "u", now=NOW))

    def test_api_failure_fails_closed(self):
        """A missed post is recoverable; a duplicate is not."""
        self._with({}, status=500)
        self.assertTrue(pti.already_posted_today("t", "u", now=NOW))


@unittest.skipIf(pti is None, "requests not installed")
class SnapshotIsTodayTests(unittest.TestCase):
    def _models(self, ts):
        d = tempfile.mkdtemp()
        p = Path(d) / "models.json"
        p.write_text(json.dumps({"history": [{"timestamp": ts}]}))
        return p

    def test_today_allows(self):
        self.assertTrue(pti.snapshot_is_today(self._models("2026-09-04T03:30:00+00:00"), now=NOW))

    def test_yesterday_blocks(self):
        self.assertFalse(pti.snapshot_is_today(self._models("2026-09-03T03:30:00+00:00"), now=NOW))


if __name__ == "__main__":
    unittest.main(verbosity=2)


@unittest.skipIf(pti is None, "requests not installed")
class CarouselTests(unittest.TestCase):
    """Child containers with is_carousel_item, one CAROUSEL parent, one publish."""

    def _capture(self):
        calls = []
        class R:
            ok, status_code, text = True, 200, ""
            def __init__(self, payload): self._p = payload
            def json(self): return self._p
            def raise_for_status(self): pass
        def post(url, data=None, timeout=None):
            calls.append((url.rsplit("/", 1)[-1], dict(data)))
            n = len(calls)
            return R({"id": f"c{n}"})
        self.addCleanup(setattr, pti.requests, "post", pti.requests.post)
        self.addCleanup(setattr, pti, "wait_for_container", pti.wait_for_container)
        self.addCleanup(setattr, pti, "check_token_expiry", pti.check_token_expiry)
        pti.requests.post = post
        pti.wait_for_container = lambda *a, **k: None
        pti.check_token_expiry = lambda *a, **k: None
        return calls

    def test_call_sequence(self):
        calls = self._capture()
        post_id = pti.post_carousel(["https://x/1.png", "https://x/2.png"], "cap", "tok", "user")
        kinds = [c[0] for c in calls]
        self.assertEqual(kinds, ["media", "media", "media", "media_publish"])
        self.assertEqual(calls[0][1]["is_carousel_item"], "true")
        self.assertEqual(calls[1][1]["image_url"], "https://x/2.png")
        self.assertEqual(calls[2][1]["media_type"], "CAROUSEL")
        self.assertEqual(calls[2][1]["children"], "c1,c2")
        self.assertEqual(calls[2][1]["caption"], "cap")
        self.assertEqual(calls[3][1]["creation_id"], "c3")
        self.assertEqual(post_id, "c4")

    def test_rejects_wrong_slide_counts(self):
        self._capture()
        with self.assertRaises(ValueError):
            pti.post_carousel(["only-one"], "cap", "tok", "user")
        with self.assertRaises(ValueError):
            pti.post_carousel([f"s{i}" for i in range(11)], "cap", "tok", "user")


@unittest.skipIf(pti is None, "requests not installed")
class TaggingTests(unittest.TestCase):
    def setUp(self):
        import os
        for k in ("IG_TAG_USERNAME", "IG_COLLABORATORS"):
            self.addCleanup(os.environ.pop, k, None)
            os.environ.pop(k, None)

    def test_default_handle_is_richcrane(self):
        self.assertEqual(pti.tag_username(), "richcrane")

    def test_mention_added_once_and_not_duplicated(self):
        c = pti.with_mention("Hook\n\n#AI")
        self.assertTrue(c.endswith("\n\n@richcrane"))
        self.assertEqual(pti.with_mention(c), c)

    def test_user_tags_field_shape(self):
        t = json.loads(pti.tag_fields()["user_tags"])
        self.assertEqual(t, [{"username": "richcrane", "x": 0.92, "y": 0.96}])
        self.assertTrue(0 <= t[0]["x"] <= 1 and 0 <= t[0]["y"] <= 1)

    def test_collaborators_opt_in_and_capped(self):
        import os
        self.assertEqual(pti.collaborator_fields(), {})
        os.environ["IG_COLLABORATORS"] = "@richcrane, mill5, a, b"
        self.assertEqual(json.loads(pti.collaborator_fields()["collaborators"]), ["richcrane", "mill5", "a"])

    def test_carousel_tags_every_child_and_collaborators_on_parent(self):
        import os
        os.environ["IG_COLLABORATORS"] = "richcrane"
        calls = []
        class R:
            ok, status_code, text = True, 200, ""
            def __init__(self, p): self._p = p
            def json(self): return self._p
            def raise_for_status(self): pass
        def post(url, data=None, timeout=None):
            calls.append((url.rsplit("/", 1)[-1], dict(data))); return R({"id": f"c{len(calls)}"})
        self.addCleanup(setattr, pti.requests, "post", pti.requests.post)
        self.addCleanup(setattr, pti, "wait_for_container", pti.wait_for_container)
        self.addCleanup(setattr, pti, "check_token_expiry", pti.check_token_expiry)
        pti.requests.post = post; pti.wait_for_container = lambda *a, **k: None; pti.check_token_expiry = lambda *a, **k: None
        pti.post_carousel(["https://x/1.png", "https://x/2.png"], "cap", "tok", "user")
        self.assertIn("user_tags", calls[0][1]); self.assertIn("user_tags", calls[1][1])
        self.assertNotIn("user_tags", calls[2][1])
        self.assertEqual(json.loads(calls[2][1]["collaborators"]), ["richcrane"])


class PlanTests(unittest.TestCase):
    """The poster publishes the carousel social_publish.py planned for today,
    and posts nothing at all without one - the legacy single tile is the
    monotonous grid the rotation replaces."""

    def _plan(self, date="2026-09-05", **over):
        p = {"date": date, "format": "head_to_head", "palette": "midnight", "caption_source": "gpt-5.6-luna",
             "urls": ["https://usvschina.ai/social/a.png", "https://usvschina.ai/social/b.png"], "caption": "Hook\n\n• a"}
        p.update(over)
        return p

    def _write(self, d, plan):
        path = Path(d) / "plan.json"
        path.write_text(json.dumps(plan))
        return path

    def test_todays_plan_loads(self):
        import tempfile
        now = datetime(2026, 9, 5, 4, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(pti.load_plan(self._write(d, self._plan()), now)["format"], "head_to_head")

    def test_stale_incomplete_or_missing_plan_is_ignored(self):
        import tempfile
        now = datetime(2026, 9, 5, 4, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(pti.load_plan(self._write(d, self._plan(date="2026-09-04")), now))
            self.assertIsNone(pti.load_plan(self._write(d, self._plan(urls=["one"])), now))
            self.assertIsNone(pti.load_plan(self._write(d, self._plan(caption="")), now))
            (Path(d) / "plan.json").write_text("{nope")
            self.assertIsNone(pti.load_plan(Path(d) / "plan.json", now))
            self.assertIsNone(pti.load_plan(Path(d) / "missing.json", now))

    def _run_main(self, plan, env, wait_ok=True):
        import os
        calls = []
        for name in ("load_plan", "already_posted_today", "snapshot_is_today", "wait_for_urls",
                     "post_carousel", "post_to_instagram", "load_caption_data", "build_caption"):
            self.addCleanup(setattr, pti, name, getattr(pti, name))
        pti.load_plan = lambda *a, **k: plan
        pti.already_posted_today = lambda *a, **k: None
        pti.snapshot_is_today = lambda *a, **k: True
        pti.wait_for_urls = lambda urls, **k: wait_ok
        pti.post_carousel = lambda slides, caption, *a: calls.append(("carousel", slides, caption))
        pti.post_to_instagram = lambda url, caption, *a: calls.append(("single", url, caption))
        pti.load_caption_data = lambda p: {}
        pti.build_caption = lambda d: "LEGACY"
        keys = ("INSTAGRAM_ACCESS_TOKEN", "IG_USER_ID", "IG_CAROUSEL_URLS", "IG_CAPTION", "IG_LEGACY_TILE", "IG_FORCE")
        saved = {k: os.environ.get(k) for k in keys}
        for k in keys:
            os.environ.pop(k, None)
        os.environ.update({"INSTAGRAM_ACCESS_TOKEN": "t", "IG_USER_ID": "u", **env})
        try:
            pti.main()
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        return calls

    def test_plan_posts_the_carousel_with_its_caption_and_mention(self):
        calls = self._run_main(self._plan(), {})
        self.assertEqual(len(calls), 1)
        kind, slides, caption = calls[0]
        self.assertEqual((kind, slides), ("carousel", self._plan()["urls"]))
        self.assertTrue(caption.startswith("Hook"))
        self.assertIn("@richcrane", caption)

    def test_no_plan_posts_nothing(self):
        self.assertEqual(self._run_main(None, {}), [])

    def test_legacy_tile_only_when_explicitly_allowed(self):
        calls = self._run_main(None, {"IG_LEGACY_TILE": "1"})
        self.assertEqual(calls[0][0], "single")
        self.assertTrue(calls[0][2].startswith("LEGACY"))

    def test_env_override_wins_over_the_plan(self):
        calls = self._run_main(self._plan(), {"IG_CAROUSEL_URLS": "https://x/1.png,https://x/2.png", "IG_CAPTION": "Manual"})
        self.assertEqual(calls[0][1], ["https://x/1.png", "https://x/2.png"])
        self.assertTrue(calls[0][2].startswith("Manual"))

    def test_unreachable_slides_abort_without_posting(self):
        with self.assertRaises(SystemExit):
            self._run_main(self._plan(), {}, wait_ok=False)
