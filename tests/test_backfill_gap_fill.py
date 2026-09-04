#!/usr/bin/env python3
"""Tests for the history gap-fill backfill adapter.

The backfill's whole risk surface is the translation between two shapes: the
models.json history row (space-stripped keys, flat) and the LeaderboardEntry
the gap-fill pass expects (original spaced headers, .columns). Get that wrong
and the pass either misses every cached multi-word benchmark or writes cells
under keys the site never reads.
"""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import backfill_gap_fill as bf


def _row(model, origin, **cols):
    row = {
        "model": model, "organization": "Org", "link": f"https://x/{model}",
        "origin": origin, "description": "", "created": "Jan. 2026",
        "avgIq": 50.0, "value": 1.0, "unified": 500.0,
        "coverage": "3/8", "provisional": False,
        "Model": model, "Country": "🇺🇸", "License": "Closed",
        "Context": "1.0M", "Input$/M": "$1.00", "Output$/M": "$2.00",
        "Speed": "10c/s", "Latency": "5s", "LLMStats": "50.0",
        "CodeArena": "1500", "Reasoning": "50.0",
    }
    row.update(cols)
    return row


def _snapshot(ts, us_rows, cn_rows):
    return {"timestamp": ts, "teams": {"US": us_rows, "CN": cn_rows}}


class SnapshotKeysTest(unittest.TestCase):
    def test_metadata_and_aggregates_are_not_benchmarks(self):
        snap = _snapshot("2026-09-01T00:00:00+00:00",
                         [_row("A", "US", GPQA="90.0%")], [])
        keys = bf.snapshot_benchmark_keys(snap)
        self.assertIn("GPQA", keys)
        for excluded in ("Model", "Country", "License", "Context", "Input$/M",
                         "Speed", "Latency", "LLMStats", "CodeArena", "Reasoning",
                         "avgIq", "unified", "coverage", "origin", "link"):
            self.assertNotIn(excluded, keys, f"{excluded} must not be scored")

    def test_underscore_bookkeeping_keys_excluded(self):
        snap = _snapshot("2026-09-01T00:00:00+00:00",
                         [_row("A", "US", GPQA="90.0%", _provenance={"GPQA": {}})], [])
        self.assertNotIn("_provenance", bf.snapshot_benchmark_keys(snap))


class DisplayNameTest(unittest.TestCase):
    def test_spaced_header_recovered_from_cache(self):
        """A squashed row key maps back to the spelling the cache is keyed by.

        Without this the pass looks up "SWE-benchVerified", the cache holds
        "SWE-bench Verified", and every cached multi-word fill is missed.
        """
        original = bf.gf.load_cache
        bf.gf.load_cache = lambda: {"M": {"SWE-bench Verified": {"score": "70%"}}}
        original_audit = bf.gf.AUDIT_FILE
        bf.gf.AUDIT_FILE = Path("/nonexistent")
        try:
            display = bf.build_display_names({"SWE-benchVerified", "GPQA"})
        finally:
            bf.gf.load_cache = original
            bf.gf.AUDIT_FILE = original_audit
        self.assertEqual(display["SWE-benchVerified"], "SWE-bench Verified")
        self.assertEqual(display["GPQA"], "GPQA")

    def test_unknown_header_keeps_its_row_key(self):
        original = bf.gf.load_cache
        original_audit = bf.gf.AUDIT_FILE
        bf.gf.load_cache = lambda: {}
        bf.gf.AUDIT_FILE = Path("/nonexistent")
        try:
            display = bf.build_display_names({"NL2Repo"})
        finally:
            bf.gf.load_cache = original
            bf.gf.AUDIT_FILE = original_audit
        self.assertEqual(display["NL2Repo"], "NL2Repo")


class HydrateWriteBackTest(unittest.TestCase):
    def test_roundtrip_writes_under_the_stripped_key(self):
        """A fill on the spaced header lands on the key the site reads."""
        row = _row("A", "US", **{"SWE-benchVerified": "—", "GPQA": "90.0%"})
        snap = _snapshot("2026-09-01T00:00:00+00:00", [row], [])
        display = {"SWE-benchVerified": "SWE-bench Verified", "GPQA": "GPQA"}
        entries = bf.hydrate(snap, display)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].columns["SWE-bench Verified"], "—")
        entries[0].columns["SWE-bench Verified"] = "71.4%"
        written = bf.write_back(entries)
        self.assertEqual(written, 1)
        self.assertEqual(row["SWE-benchVerified"], "71.4%")
        self.assertNotIn("SWE-bench Verified", row)

    def test_provenance_keys_are_stripped_on_the_way_back(self):
        row = _row("A", "US", **{"SWE-benchVerified": "—"})
        snap = _snapshot("2026-09-01T00:00:00+00:00", [row], [])
        entries = bf.hydrate(snap, {"SWE-benchVerified": "SWE-bench Verified"})
        entries[0].columns["_provenance"] = {"SWE-bench Verified": {"source": "ai_filled"}}
        bf.write_back(entries)
        self.assertIn("SWE-benchVerified", row["_provenance"])

    def test_identity_and_cohort_order_preserved(self):
        """get_top_cohort reads the first 10 per country, so US must precede CN."""
        snap = _snapshot("2026-09-01T00:00:00+00:00",
                         [_row("US1", "US"), _row("US2", "US")], [_row("CN1", "CN")])
        entries = bf.hydrate(snap, {})
        self.assertEqual([e.name for e in entries], ["US1", "US2", "CN1"])
        self.assertEqual([e.country for e in entries], ["US", "US", "CN"])
        self.assertEqual(entries[0].url, "https://x/US1")
        self.assertEqual(entries[0].columns["Organization"], "Org")

    def test_unchanged_cells_are_not_counted_as_writes(self):
        row = _row("A", "US", GPQA="90.0%")
        snap = _snapshot("2026-09-01T00:00:00+00:00", [row], [])
        entries = bf.hydrate(snap, {})
        self.assertEqual(bf.write_back(entries), 0)


class DailySnapshotsTest(unittest.TestCase):
    def _history(self):
        return [
            _snapshot("2026-09-04T09:00:00+00:00", [], []),
            _snapshot("2026-09-04T05:00:00+00:00", [], []),
            _snapshot("2026-09-03T05:00:00+00:00", [], []),
            _snapshot("2026-07-01T05:00:00+00:00", [], []),
        ]

    def test_latest_snapshot_per_day_wins(self):
        days = bf.daily_snapshots(self._history(), days=35)
        self.assertEqual([d for d, _ in days], ["2026-09-04", "2026-09-03"])
        self.assertEqual(days[0][1]["timestamp"], "2026-09-04T09:00:00+00:00")

    def test_window_excludes_older_than_cutoff(self):
        # The cutoff is newest-timestamp minus N days, not N calendar dates:
        # at days=1 the boundary is Sep 3 09:00, so the Sep 3 05:00 snapshot
        # falls outside it and only Sep 4 survives.
        self.assertEqual([d for d, _ in bf.daily_snapshots(self._history(), days=1)],
                         ["2026-09-04"])
        self.assertEqual([d for d, _ in bf.daily_snapshots(self._history(), days=2)],
                         ["2026-09-04", "2026-09-03"])
        # July 1 is far outside any sane window.
        self.assertNotIn("2026-07-01",
                         [d for d, _ in bf.daily_snapshots(self._history(), days=35)])

    def test_empty_history(self):
        self.assertEqual(bf.daily_snapshots([], days=35), [])


class CacheOnlyTest(unittest.TestCase):
    def test_stale_cache_entry_is_not_applied(self):
        """The 30-day TTL is the pass's own freshness rule; honour it here too."""
        stale = (datetime.now(timezone.utc) - timedelta(days=99)).isoformat()
        row = _row("A", "US", GPQA="—")
        snap = _snapshot("2026-09-01T00:00:00+00:00", [row], [])
        original = bf.gf.load_cache
        bf.gf.load_cache = lambda: {
            "A": {"GPQA": {"score": "90%", "confidence": "high", "cached_at": stale}}
        }
        try:
            bf.apply_cached([("2026-09-01", snap)], {}, "high")
        finally:
            bf.gf.load_cache = original
        self.assertEqual(row["GPQA"], "—")

    def test_low_confidence_dropped_when_high_required(self):
        fresh = datetime.now(timezone.utc).isoformat()
        row = _row("A", "US", GPQA="—")
        snap = _snapshot("2026-09-01T00:00:00+00:00", [row], [])
        original = bf.gf.load_cache
        bf.gf.load_cache = lambda: {
            "A": {"GPQA": {"score": "90%", "confidence": "medium", "cached_at": fresh}}
        }
        try:
            bf.apply_cached([("2026-09-01", snap)], {}, "high")
        finally:
            bf.gf.load_cache = original
        self.assertEqual(row["GPQA"], "—")


if __name__ == "__main__":
    unittest.main()



class RescoreTests(unittest.TestCase):
    """Owner decision 2026-09-04: fill cells, then re-score with today's scorer."""

    def _snapshot(self):
        import backfill_gap_fill as bf
        def row(name, origin, **cells):
            r = {"model": name, "organization": "x", "origin": origin, "created": "Aug. 2026",
                 "avgIq": 1.0, "value": 1.0, "unified": 1.0, "coverage": "0/0",
                 "Input$/M": "$1.00", "Output$/M": "$2.00"}
            r.update(cells); return r
        us = [row(f"US{i}", "US", A=f"{50+i}%", B=f"{50+i}%", C=f"{50+i}%", D=f"{50+i}%") for i in range(5)]
        cn = [row(f"CN{i}", "CN", A=f"{40+i}%", B=f"{40+i}%", C=f"{40+i}%", D=f"{40+i}%") for i in range(5)]
        return bf, {"timestamp": "2026-08-20T03:00:00+00:00", "teams": {"US": us, "CN": cn}}

    def test_rescore_rewrites_scores_and_keeps_originals_once(self):
        bf, snap = self._snapshot()
        changed = bf.rescore_snapshot(snap)
        self.assertEqual(changed, 10)
        top = snap["teams"]["US"][4]
        self.assertEqual(top["_prior"], {"avgIq": 1.0, "value": 1.0, "unified": 1.0, "coverage": "0/0"})
        self.assertNotEqual(top["unified"], 1.0)
        first_prior = dict(top["_prior"])
        top["A"] = "99%"                               # a later fill
        bf.rescore_snapshot(snap)
        self.assertEqual(top["_prior"], first_prior, "_prior must never be overwritten")

    def test_cohort_membership_and_order_are_untouched(self):
        bf, snap = self._snapshot()
        before = {t: [r["model"] for r in rows] for t, rows in snap["teams"].items()}
        bf.rescore_snapshot(snap)
        after = {t: [r["model"] for r in rows] for t, rows in snap["teams"].items()}
        self.assertEqual(before, after)

    def test_a_fill_changes_the_top_ten(self):
        bf, snap = self._snapshot()
        bf.rescore_snapshot(snap)
        rank = lambda: sorted((r["model"] for t in snap["teams"].values() for r in t),
                              key=lambda m: -next(float(r["unified"]) for t in snap["teams"].values() for r in t if r["model"] == m))
        self.assertEqual(rank()[0], "US4")
        cn0 = snap["teams"]["CN"][0]
        for b in ("A", "B", "C", "D"):
            cn0[b] = "95%"                             # backfill lands strong numbers
        bf.rescore_snapshot(snap)
        self.assertEqual(rank()[0], "CN0")

    def test_coverage_is_written_and_sparse_cells_are_kept(self):
        bf, snap = self._snapshot()
        snap["teams"]["US"][0]["Rare"] = "1%"          # reported by one model only
        bf.rescore_snapshot(snap)
        self.assertEqual(snap["teams"]["US"][0]["coverage"], "4/4")
        self.assertIn("Rare", snap["teams"]["US"][0], "history cells must never be deleted")

    def test_badges_follow_the_rescored_newest_snapshot(self):
        bf, snap = self._snapshot()
        data = {"teams": {"usa": {"badge": "RUNNER UP"}, "china": {"badge": "OVERALL WINNER"}}, "history": [snap]}
        bf.rescore_snapshot(snap)
        bf.recompute_badges(data)
        self.assertEqual(data["teams"]["usa"]["badge"], "OVERALL WINNER")
        self.assertEqual(data["teams"]["china"]["badge"], "RUNNER UP")
