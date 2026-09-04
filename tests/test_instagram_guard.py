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
