"""Production discovery must not be limited to the source's displayed rows."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
with patch('dotenv.load_dotenv'):
    from scrape_models import LeaderboardEntry, discover_released_models


def record(name, released='2026-09-22', country='US'):
    return dict(name=name, release_date=released, organization_country=country,
                organization='Anthropic', input_price=4, output_price=20)


class ModelDiscoveryTests(unittest.TestCase):
    def test_stale_source_cannot_remove_a_known_released_model(self):
        catalog = {'models': {'opus': {'name': 'Claude Opus 5.5',
            'profiles': {'p': {'link': 'https://llm-stats.com/models/claude-opus-5-5',
                               'origin': 'US', 'organization': 'Anthropic', 'Output$/M': '$20'}},
            'benchmarks': {'arc': {'e': {'modelAvailableFrom': '2026-09-23'}}}}}}
        metadata = {'claude-opus-5': record('Claude Opus 5', '2026-07-24')}
        result = discover_released_models([], metadata, 'US', '2026-09-26', catalog)
        self.assertEqual([e.name for e in result], ['Claude Opus 5.5'])
        self.assertEqual(result[0].columns['Output $/M'], '$20')
        earlier = discover_released_models([], metadata, 'US', '2026-09-22', catalog)
        self.assertEqual([e.name for e in earlier], ['Claude Opus 5'])

    def test_hidden_new_release_replaces_older_visible_version(self):
        old = LeaderboardEntry(1, 'Claude Opus 5', 'US',
                               'https://llm-stats.com/models/claude-opus-5', {})
        metadata = {'claude-opus-5': record(old.name, '2026-07-24'),
                    'claude-opus-5-5': record('Claude Opus 5.5')}
        result = discover_released_models([old], metadata, 'US', '2026-09-26')
        self.assertEqual([e.name for e in result], ['Claude Opus 5.5'])
        self.assertEqual(result[0].columns['Released'], '2026-09-22')
        self.assertEqual(result[0].columns['Input $/M'], '4')

    def test_full_dataset_has_no_table_or_pool_cutoff(self):
        metadata = {f'model-{i}.1': record(f'Family {chr(65+i//26)}{chr(65+i%26)}') for i in range(40)}
        self.assertEqual(len(discover_released_models([], metadata, 'US', '2026-09-26')), 40)

    def test_future_undated_and_foreign_models_do_not_replace_released_model(self):
        metadata = {'opus-5': record('Claude Opus 5', '2026-07-24'),
                    'opus-6': record('Claude Opus 6', '2026-10-01'),
                    'opus-7': record('Claude Opus 7', None),
                    'foreign': record('Foreign model', country='CN')}
        result = discover_released_models([], metadata, 'US', '2026-09-26')
        self.assertEqual([e.name for e in result], ['Claude Opus 5'])

    def test_visible_benchmarks_are_preserved_with_current_metadata(self):
        entry = LeaderboardEntry(1, 'Claude Opus 5.5', 'US',
                                 'https://llm-stats.com/models/opus-5-5', {'GPQA': '95%'})
        result = discover_released_models([entry], {'opus-5-5': record(entry.name)}, 'US', '2026-09-26')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].columns['GPQA'], '95%')

    def test_invalid_or_empty_source_fails(self):
        for metadata in ({}, {'bad': record('Bad', 'not-a-date')}):
            with self.assertRaises(ValueError):
                discover_released_models([], metadata, 'US', '2026-09-26')
