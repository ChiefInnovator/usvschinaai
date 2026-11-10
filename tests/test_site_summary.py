"""Summary is a small projection of reference identity and global top-ten scores."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from site_summary import build_summary


class SiteSummaryTests(unittest.TestCase):
    def fixture(self):
        catalog = {'models': {}}
        teams = {'CN': [], 'US': []}
        for country in ('CN', 'US'):
            for i in range(8):
                mid, pid = country+str(i), 'profile'+str(i)
                catalog['models'][mid] = {'profiles': {pid: {'model': mid, 'origin': country, 'Input$/M': '$1'}}, 'benchmarks': {}}
                teams[country].append({'modelId': mid, 'profileId': pid, 'unified': 1,
                                       'avgIq': i, 'value': i*2, 'coverage': '0/17', 'provisional': False})
        snapshots = [{'timestamp': day+'T12:00:00Z', 'scoring': {'revision': 'test'}, 'teams': copy.deepcopy(teams)}
                     for day in ('2026-01-01', '2026-01-03', '2026-01-02')]
        raw = {'schemaVersion': 2, 'scoringRevision': 'test', 'metadata': {'title': 'Title'},
               'teams': {'usa': {'badge': 'TIED'}}, 'columns': [{'key': 'model'}], 'history': snapshots}
        return raw, catalog

    def test_summary_preserves_profiles_excludes_evidence_and_sorts_latest_first(self):
        raw, catalog = self.fixture()
        summary = build_summary(raw, catalog, 'test', 'generation')
        self.assertEqual(summary['schemaVersion'], 1)
        self.assertEqual(summary['generationId'], 'generation')
        self.assertEqual(summary['current']['timestamp'], raw['history'][1]['timestamp'])
        self.assertEqual([s['timestamp'] for s in summary['history']], sorted((s['timestamp'] for s in raw['history']), reverse=True))
        self.assertEqual(summary['current']['teams']['US'][0]['modelId'], 'US0')
        self.assertEqual(summary['current']['teams']['US'][0]['profileId'], 'profile0')
        self.assertEqual(summary['current']['teams']['US'][0]['Input$/M'], '$1')
        self.assertNotIn('_provenance', summary['current']['teams']['US'][0])
        self.assertNotIn('GPQADiamond', summary['current']['teams']['US'][0])
        self.assertEqual(sum(b['weight'] for b in summary['benchmarks']), 100)
        self.assertTrue(all(set(b) == {'id', 'name', 'column', 'weight'} for b in summary['benchmarks']))

    def test_equal_scores_at_cutoff_keep_us_then_cn_order_and_country_means(self):
        raw, catalog = self.fixture()
        summary = build_summary(raw, catalog, 'test', 'generation')
        scores = summary['history'][0]['scores']
        self.assertEqual(scores['US'], {'total': 8, 'count': 8, 'avgIq': 3.5, 'avgValue': 7})
        self.assertEqual(scores['CN'], {'total': 2, 'count': 2, 'avgIq': 0.5, 'avgValue': 1})

    def test_mixed_revisions_and_dangling_refs_are_rejected(self):
        raw, catalog = self.fixture()
        raw['history'][-1]['scoring']['revision'] = 'old'
        with self.assertRaises(ValueError):
            build_summary(raw, catalog, 'test', 'generation')
        raw['history'][-1]['scoring']['revision'] = 'test'
        raw['history'][0]['teams']['US'][0]['profileId'] = 'missing'
        with self.assertRaises(KeyError):
            build_summary(raw, catalog, 'test', 'generation')

    def test_summary_orders_offset_timestamps_by_actual_instant(self):
        raw, catalog = self.fixture()
        timestamps = ['2026-01-03T01:00:00+03:00', '2026-01-02T23:00:00Z', '2026-01-02T20:00:00-04:00']
        for snapshot, timestamp in zip(raw['history'], timestamps):
            snapshot['timestamp'] = timestamp
        summary = build_summary(raw, catalog, 'test', 'generation')
        self.assertEqual(summary['current']['timestamp'], timestamps[2])
        self.assertEqual([s['timestamp'] for s in summary['history']], [timestamps[2], timestamps[1], timestamps[0]])
