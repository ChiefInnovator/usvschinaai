#!/usr/bin/env python3
"""The two hooks the history backfill relies on in gap_fill_benchmarks:
`skip_pairs` keeps already-researched (model, benchmark) pairs out of the
batches, and `on_batch` fires once per validated answer so the caller can
remember what was asked."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import gap_fill_benchmarks as gf


class Entry:
    def __init__(self, name, country, columns):
        self.name, self.country, self.url, self.columns = name, country, "", columns


class PassHookTests(unittest.TestCase):
    def setUp(self):
        self.saved = {k: getattr(gf, k) for k in ("resolve_openai_key", "discover_available_model", "load_cache",
                                                   "save_cache", "append_audit_entry", "query_openai_responses",
                                                   "extract_json_from_response", "validate_batch_response",
                                                   "build_candidates", "time", "load_first_seen",
                                                   "negative_is_fresh")}
        self.calls = []
        gf.resolve_openai_key = lambda: "key"
        gf.discover_available_model = lambda key, chain=None: "stub-model"
        gf.load_first_seen = lambda: {"M": "2026-01-01", "K": "2026-01-01"}   # neither is new
        gf.load_cache = lambda: {}
        gf.save_cache = lambda cache: None
        gf.append_audit_entry = lambda entry: None
        gf.query_openai_responses = lambda *a, **k: self.calls.append(k.get("user", a[1] if len(a) > 1 else "")) or {}
        gf.extract_json_from_response = lambda raw: {"results": []}
        gf.validate_batch_response = lambda parsed, expected: {}      # every benchmark omitted -> nulls

        class T:
            @staticmethod
            def sleep(_):
                pass
        gf.time = T
        gf.build_candidates = lambda entries: [
            gf.GapCandidate(e.name, e.country, e.url, "Org", b)
            for e in entries for b in ("HLE", "GPQA") if e.columns.get(b, "") in ("", "—")]

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(gf, k, v)

    def _entries(self):
        return [Entry("M", "US", {"HLE": "—", "GPQA": "—"}), Entry("K", "CN", {"HLE": "—", "GPQA": "50%"})]

    def test_skip_pairs_removes_candidates_before_batching(self):
        seen = []
        gf.run_gap_filling_pass(self._entries(), max_calls=5,
                                skip_pairs={("M", "HLE"), ("M", "GPQA")},
                                on_batch=lambda model, benchmarks: seen.append((model, sorted(benchmarks))))
        self.assertEqual(seen, [("K", ["HLE"])], "M had nothing left to ask; K still asks HLE")
        self.assertEqual(len(self.calls), 1)

    def test_on_batch_fires_only_for_validated_answers(self):
        seen = []
        gf.validate_batch_response = lambda parsed, expected: None    # malformed answer
        gf.run_gap_filling_pass(self._entries(), max_calls=5,
                                on_batch=lambda model, benchmarks: seen.append(model))
        self.assertEqual(seen, [], "a malformed answer must not be remembered as asked")
        self.assertEqual(len(self.calls), 2)

    def test_low_confidence_cache_is_researched_again(self):
        from datetime import datetime, timezone
        gf.load_cache = lambda: {'M': {'GPQA': {'score': '90%', 'confidence': 'medium',
            'cached_at': datetime.now(timezone.utc).isoformat()}}}
        seen = []
        gf.run_gap_filling_pass(self._entries(), max_calls=5,
            on_batch=lambda model, benchmarks: seen.append((model, sorted(benchmarks))))
        self.assertIn(('M', ['GPQA', 'HLE']), seen)

    def test_null_answers_are_cached(self):
        saved = {}
        gf.save_cache = lambda cache: saved.update(cache)
        gf.run_gap_filling_pass(self._entries(), max_calls=5)
        self.assertEqual(sorted(saved["M"]), ["GPQA", "HLE"])
        self.assertIsNone(saved["M"]["HLE"]["score"])
        self.assertIn("cached_at", saved["K"]["HLE"])

    def test_recent_null_is_not_asked_again(self):
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=gf.NEGATIVE_CACHE_TTL_DAYS + 1)).isoformat()
        gf.load_cache = lambda: {'M': {'HLE': {'score': None, 'cached_at': now.isoformat()},
                                       'GPQA': {'score': None, 'cached_at': old}}}
        seen = []
        gf.run_gap_filling_pass(self._entries(), max_calls=5,
            on_batch=lambda model, benchmarks: seen.append((model, sorted(benchmarks))))
        self.assertEqual(seen, [('M', ['GPQA']), ('K', ['HLE'])], "fresh null skipped, expired null re-asked")

    def test_zero_budget_still_applies_cached_fills(self):
        from datetime import datetime, timezone
        gf.load_cache = lambda: {'K': {'HLE': {'score': '40%', 'confidence': 'high',
            'cached_at': datetime.now(timezone.utc).isoformat()}}}
        applied = []
        saved_apply = gf._apply_fill
        gf._apply_fill = lambda entries, cand, entry, model: applied.append((cand.model_name, cand.benchmark)) or True
        try:
            gf.run_gap_filling_pass(self._entries(), max_calls=0)
        finally:
            gf._apply_fill = saved_apply
        self.assertEqual(self.calls, [])
        self.assertEqual(applied, [('K', 'HLE')])

    def test_malformed_answer_does_not_cache_nulls(self):
        saved = {}
        gf.save_cache = lambda cache: saved.update(cache)
        gf.validate_batch_response = lambda parsed, expected: None
        gf.run_gap_filling_pass(self._entries(), max_calls=5)
        self.assertEqual(saved, {}, "a failed call must not suppress re-asking for the TTL window")

    def test_budget_hit_mid_pass_still_applies_later_cached_fills(self):
        from datetime import datetime, timezone
        gf.load_cache = lambda: {'K': {'HLE': {'score': '40%', 'confidence': 'high',
            'cached_at': datetime.now(timezone.utc).isoformat()}}}
        applied = []
        saved_apply = gf._apply_fill
        gf._apply_fill = lambda entries, cand, entry, model: applied.append(cand.model_name) or True
        try:
            gf.run_gap_filling_pass(self._entries(), max_calls=1)
        finally:
            gf._apply_fill = saved_apply
        self.assertEqual(len(self.calls), 1, "M spends the only call")
        self.assertEqual(applied, ['K'], "K's cached fill applies after the budget is spent")

    def test_negative_is_fresh_edges(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        self.assertFalse(gf.negative_is_fresh({'score': None}, now), "no timestamp -> re-ask")
        self.assertFalse(gf.negative_is_fresh({'score': None, 'cached_at': 'bad'}, now))
        self.assertFalse(gf.negative_is_fresh({'score': '50%', 'cached_at': now.isoformat()}, now))
        self.assertTrue(gf.negative_is_fresh({'score': None, 'cached_at': now.isoformat()}, now))
        naive = now.replace(tzinfo=None).isoformat()
        self.assertTrue(gf.negative_is_fresh({'score': None, 'cached_at': naive}, now), "naive timestamp read as UTC")

    def test_null_answer_replaces_unaccepted_low_confidence_lead(self):
        from datetime import datetime, timezone
        gf.load_cache = lambda: {'M': {'GPQA': {'score': '90%', 'confidence': 'medium',
            'cached_at': datetime.now(timezone.utc).isoformat()}}}
        saved = {}
        gf.save_cache = lambda cache: saved.update(cache)
        gf.run_gap_filling_pass(self._entries(), max_calls=5)
        self.assertIsNone(saved['M']['GPQA']['score'], "research found nothing; the stale lead is dropped")

    def test_scraper_cli_budget_defaults_to_ten_and_accepts_zero(self):
        src = (Path(__file__).parent.parent / "scripts" / "scrape_models.py").read_text(encoding="utf-8")
        self.assertIn('getattr(args, "gap_fill_max_calls", 10)', src)
        self.assertEqual(gf.DEFAULT_MAX_CALLS, 10)
        gf.run_gap_filling_pass(self._entries(), max_calls=0)
        self.assertEqual(self.calls, [], "max_calls=0 makes no API calls")

    def _make_new(self, *names):
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()
        seen = {"M": "2026-01-01", "K": "2026-01-01"}
        seen.update({n: today for n in names})
        gf.load_first_seen = lambda: seen

    def test_new_model_is_asked_on_a_cache_only_night(self):
        self._make_new("K")
        seen = []
        gf.run_gap_filling_pass(self._entries(), max_calls=0,
            on_batch=lambda model, benchmarks: seen.append(model))
        self.assertEqual(seen, ["K"], "only the new model is researched when max_calls=0")

    def test_new_model_ignores_recent_nulls_and_does_not_cache_them(self):
        from datetime import datetime, timezone
        self._make_new("K")
        stamp = "2026-01-01T00:00:00+00:00"
        gf.load_cache = lambda: {'K': {'HLE': {'score': None, 'cached_at': stamp}}}
        gf.negative_is_fresh = lambda entry, now: True   # a recent null, for any clock
        saved = {}
        gf.save_cache = lambda cache: saved.update(cache)
        seen = []
        gf.run_gap_filling_pass(self._entries(), max_calls=0,
            on_batch=lambda model, benchmarks: seen.append((model, sorted(benchmarks))))
        self.assertEqual(seen, [('K', ['HLE'])])
        self.assertEqual(saved['K']['HLE']['cached_at'], stamp, "the new null was not written over it")

    def test_model_missing_from_history_counts_as_new(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        self.assertTrue(gf.is_new_model("Brand New", {"M": "2026-01-01"}, now))
        self.assertFalse(gf.is_new_model("M", {"M": "2026-01-01"}, now))
        self.assertFalse(gf.is_new_model("M", None, now), "unreadable history -> nothing is new")

    def test_new_model_window_is_two_weeks(self):
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        day = lambda n: (now - timedelta(days=n)).date().isoformat()
        self.assertTrue(gf.is_new_model("X", {"X": day(13)}, now))
        self.assertFalse(gf.is_new_model("X", {"X": day(14)}, now))

    def test_new_model_budget_is_separate_then_falls_back(self):
        self._make_new("M", "K")
        gf.run_gap_filling_pass(self._entries(), max_calls=0, new_model_max_calls=1)
        self.assertEqual(len(self.calls), 1, "one new-model call, no general budget")
        self.calls.clear()
        gf.run_gap_filling_pass(self._entries(), max_calls=1, new_model_max_calls=1)
        self.assertEqual(len(self.calls), 2, "second new model falls back to the general budget")

    def test_without_hooks_nothing_changes(self):
        seen = []
        gf.run_gap_filling_pass(self._entries(), max_calls=5)
        self.assertEqual(seen, [])
        self.assertEqual(len(self.calls), 2)


if __name__ == "__main__":
    unittest.main()
