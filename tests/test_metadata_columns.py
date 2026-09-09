"""Import only configured benchmarks; never discover new scoring inputs implicitly."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
with patch('dotenv.load_dotenv'):
    from scrape_models import extract_detail_benchmarks, scrape_country_leaderboard
from avg_iq_benchmarks import load_config


class MetadataColumnTests(unittest.TestCase):
    def test_detail_import_keeps_every_supported_benchmark_and_drops_others(self):
        names = [b['aliases'][0] for b in load_config()['benchmarks']]
        extras = ['Obsolete Benchmark', 'SimpleVQA', 'LLM Stats', 'Code Arena']
        payload = ''.join(json.dumps(json.dumps(dict(benchmark_id=i, name=name,
            normalized_score=0.75), separators=(',', ':'))) for i, name in enumerate(names + extras))
        page = MagicMock()
        page.content.return_value = payload
        self.assertEqual(extract_detail_benchmarks(page), {name: '75.0%' for name in names})

    def test_table_import_drops_unsupported_columns_without_shifting_cells(self):
        names = [b['aliases'][0] for b in load_config()['benchmarks']]
        headers = ['Model', 'Obsolete Benchmark', 'Released', 'Input $/M',
                   'LLM Stats', 'Latency', 'Code Arena'] + names
        values = ['Test Model', '99%', '2026-01-01', '$1', '90', '3', '1500'] + ['75%'] * len(names)
        page, row, link = MagicMock(), MagicMock(), MagicMock()
        link.inner_text.return_value = 'Test Model'
        link.get_attribute.return_value = '/models/test'
        row.query_selector.return_value = link
        cells = []
        for value in values:
            cell = MagicMock(); cell.inner_text.return_value = value; cells.append(cell)
        row.query_selector_all.return_value = cells
        ths = []
        for name in headers:
            th = MagicMock(); th.inner_text.return_value = name; ths.append(th)
        page.query_selector_all.side_effect = lambda selector: ths if selector == 'thead th' else [row]
        with patch('scrape_models.time.sleep'):
            entries, imported_headers, benchmarks = scrape_country_leaderboard(page, 'United States', 'US', max_models=1)
        self.assertEqual(benchmarks, names)
        self.assertEqual(len(entries), 1)
        for excluded in ('Obsolete Benchmark', 'LLM Stats', 'Code Arena'):
            self.assertNotIn(excluded, imported_headers)
            self.assertNotIn(excluded, entries[0].columns)
        self.assertEqual(entries[0].columns['Released'], '2026-01-01')
        self.assertEqual(entries[0].columns['Input $/M'], '$1')
        self.assertEqual(entries[0].columns['Latency'], '3')
        for name in names:
            self.assertEqual(entries[0].columns[name], '75%')
