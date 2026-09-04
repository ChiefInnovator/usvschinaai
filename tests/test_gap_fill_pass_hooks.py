#!/usr/bin/env python3
"""The two hooks the history backfill relies on in gap_fill_benchmarks:
`skip_pairs` keeps already-researched (model, benchmark) pairs out of the
batches, and `on_batch` fires once per validated answer so the caller can
remember what was asked. Null answers are never cached by the pass itself."""
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
                                                   "build_candidates", "time")}
        self.calls = []
        gf.resolve_openai_key = lambda: "key"
        gf.discover_available_model = lambda key, chain=None: "stub-model"
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
        gf.build_candidates = lambda entries, headers, enabled_tiers=None: [
            gf.GapCandidate(e.name, e.country, e.url, "Org", b, 1, 1, 1)
            for e in entries for b in ("HLE", "GPQA") if e.columns.get(b, "") in ("", "—")]

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(gf, k, v)

    def _entries(self):
        return [Entry("M", "US", {"HLE": "—", "GPQA": "—"}), Entry("K", "CN", {"HLE": "—", "GPQA": "50%"})]

    def test_skip_pairs_removes_candidates_before_batching(self):
        seen = []
        gf.run_gap_filling_pass(self._entries(), ["HLE", "GPQA"], max_calls=5,
                                skip_pairs={("M", "HLE"), ("M", "GPQA")},
                                on_batch=lambda model, benchmarks: seen.append((model, sorted(benchmarks))))
        self.assertEqual(seen, [("K", ["HLE"])], "M had nothing left to ask; K still asks HLE")
        self.assertEqual(len(self.calls), 1)

    def test_on_batch_fires_only_for_validated_answers(self):
        seen = []
        gf.validate_batch_response = lambda parsed, expected: None    # malformed answer
        gf.run_gap_filling_pass(self._entries(), ["HLE", "GPQA"], max_calls=5,
                                on_batch=lambda model, benchmarks: seen.append(model))
        self.assertEqual(seen, [], "a malformed answer must not be remembered as asked")
        self.assertEqual(len(self.calls), 2)

    def test_without_hooks_nothing_changes(self):
        seen = []
        gf.run_gap_filling_pass(self._entries(), ["HLE", "GPQA"], max_calls=5)
        self.assertEqual(seen, [])
        self.assertEqual(len(self.calls), 2)


if __name__ == "__main__":
    unittest.main()
