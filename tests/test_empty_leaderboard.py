"""Regression coverage for the September 10 upstream table change."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
with patch('dotenv.load_dotenv'):
    from scrape_models import scrape_country_leaderboard, prepend_history
import validate_models


class EmptyLeaderboardTests(unittest.TestCase):
    def modern_page(self, records):
        page = MagicMock()
        headers = ['#', 'Model', 'LLM Stats', 'Reasoning', 'Coding', 'Agents',
                   'Context', 'Price $/M', 'Speed', 'License']
        ths = [MagicMock() for _ in headers]
        for th, name in zip(ths, headers):
            th.inner_text.return_value = name
        rows = []
        for record in records:
            row, link = MagicMock(), MagicMock()
            link.inner_text.return_value = record['name']
            link.get_attribute.return_value = '/models/' + record['model_id']
            row.query_selector.return_value = link
            cells = [MagicMock() for _ in headers]
            for cell, value in zip(cells, ['1', record['name'], '60', '58', '48', '46', '1M', '$10 / $50', '19c/s', '']):
                cell.inner_text.return_value = value
            row.query_selector_all.return_value = cells
            rows.append(row)
        page.query_selector_all.side_effect = lambda selector: ths if selector == 'thead th' else rows
        payload = '34:' + json.dumps(['$', '$L36', None, {'initialData': records}]) + '\n'
        # Flight frames may split in the middle of a model record.
        page.content.return_value = ''.join('<script>self.__next_f.push(' + json.dumps([1, part]) + ')</script>'
                                            for part in (payload[:120], payload[120:]))
        return page

    def test_modern_table_uses_embedded_release_and_prices(self):
        record = dict(model_id='released', name='Released Model', organization='Test Org',
                      organization_country='US', release_date='2026-09-04', input_price=0, output_price=50)
        preview = dict(record, model_id='preview', name='Preview Model', release_date=None)
        page = self.modern_page([preview, record])
        with patch('scrape_models.time.sleep'):
            entries, headers, benchmarks = scrape_country_leaderboard(page, 'United States', 'US', max_models=1)
        self.assertEqual([e.name for e in entries], ['Released Model'])
        self.assertEqual(entries[0].columns['Released'], '2026-09-04')
        self.assertEqual(entries[0].columns['Input $/M'], '0')
        self.assertEqual(entries[0].columns['Output $/M'], '50')
        self.assertEqual(entries[0].columns['Organization'], 'Test Org')
        self.assertIn('Released', headers)
        self.assertEqual(benchmarks, [])
        self.assertNotIn('LLM Stats', entries[0].columns)

    def test_missing_embedded_metadata_fails_instead_of_publishing_empty(self):
        page = self.modern_page([])
        page.content.return_value = '<html></html>'
        with patch('scrape_models.time.sleep'), self.assertRaisesRegex(ValueError, 'metadata'):
            scrape_country_leaderboard(page, 'United States', 'US')

    def test_prepend_rejects_empty_or_missing_country_before_writing(self):
        for teams in ({}, {'US': [], 'CN': []}, {'US': [{}], 'CN': []}, {'CN': [{}]}):
            with self.subTest(teams=teams), patch('scrape_models.load_data') as load:
                with self.assertRaisesRegex(ValueError, 'empty|missing'):
                    prepend_history(Path('/tmp/unused-models.json'), {'teams': teams})
                load.assert_not_called()

    def test_validator_fails_on_empty_or_missing_teams(self):
        for teams in ({}, {'US': [], 'CN': []}):
            with self.subTest(teams=teams), patch.object(validate_models, 'load_data',
                    return_value={'history': [{'teams': copy.deepcopy(teams)}]}):
                self.assertEqual(validate_models.main(), 1)
