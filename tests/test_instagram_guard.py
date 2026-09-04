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
