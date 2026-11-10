"""The scrape waits for the country filter, and the news feed tells an empty answer from a failed one."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import scrape_models
import scrape_news

COUNTRIES = {'us-a': {'organization_country': 'US'}, 'us-b': {'organization_country': 'US'},
             'cn-a': {'organization_country': 'CN'}}


class Row:
    def __init__(self, slug):
        self.slug = slug

    def query_selector(self, selector):
        return self if self.slug else None

    def get_attribute(self, name):
        return '/models/' + self.slug


class Page:
    """A table that re-renders: each read of the rows returns the next frame."""

    def __init__(self, *frames):
        self.frames = list(frames)
        self.reads = 0

    def query_selector_all(self, selector):
        self.reads += 1
        frame = self.frames[0] if len(self.frames) == 1 else self.frames.pop(0)
        if isinstance(frame, Exception):
            raise frame
        return [Row(slug) for slug in frame]


class CountryFilterWaitTests(unittest.TestCase):
    def wait(self, page, timeout=5.0):
        with patch.object(scrape_models, 'extract_leaderboard_metadata', return_value=COUNTRIES), \
             patch.object(scrape_models.time, 'sleep'):
            return scrape_models.wait_for_country_rows(page, 'US', timeout)

    def test_succeeds_only_once_every_row_is_the_filtered_country(self):
        page = Page(['us-a', 'cn-a'], ['us-a', 'cn-a'], ['us-a', 'us-b'])
        self.assertTrue(self.wait(page))
        self.assertEqual(page.reads, 3)

    def test_transient_render_error_and_empty_table_are_retried(self):
        page = Page(RuntimeError('detached'), [], ['us-a'])
        self.assertTrue(self.wait(page))
        self.assertEqual(page.reads, 3)

    def test_unknown_or_other_country_rows_never_confirm_the_filter(self):
        for rows in (['us-a', 'cn-a'], ['us-a', 'not-in-dataset'], []):
            with patch.object(scrape_models.time, 'monotonic', side_effect=[0, 1, 2, 99, 99]):
                self.assertFalse(self.wait(Page(rows)), rows)

    def test_row_without_a_rendered_link_does_not_confirm_the_filter(self):
        with patch.object(scrape_models.time, 'monotonic', side_effect=[0, 1, 2, 99, 99]):
            self.assertFalse(self.wait(Page(['us-a', ''])))

    def test_unreadable_metadata_falls_back_to_the_fixed_pause(self):
        with patch.object(scrape_models, 'extract_leaderboard_metadata', side_effect=ValueError('missing')):
            self.assertFalse(scrape_models.wait_for_country_rows(Page(['us-a']), 'US', 5.0))


class NewsFreshnessTests(unittest.TestCase):
    OLD = '2026-11-01T00:00:00+00:00'

    def run_main(self, fetched):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'scripts').mkdir()
            (root / 'news.json').write_text(json.dumps({'lastUpdated': self.OLD, 'items': []}))
            with patch.object(scrape_news, '__file__', str(root / 'scripts' / 'scrape_news.py')), \
                 patch.dict(scrape_news.os.environ, {'NEWSDATA_API_KEY': 'key'}), \
                 patch.object(scrape_news, 'fetch_news', return_value=fetched), patch('builtins.print'):
                scrape_news.main()
            return json.loads((root / 'news.json').read_text())['lastUpdated']

    def test_successful_empty_fetch_counts_as_fresh_but_a_failed_one_does_not(self):
        self.assertNotEqual(self.run_main([]), self.OLD, 'the API answered: nothing new')
        self.assertEqual(self.run_main(None), self.OLD, 'the request failed: keep the last successful time')

    def test_fetch_reports_failure_separately_from_no_results(self):
        class Response:
            def __init__(self, payload): self.payload = payload
            def raise_for_status(self): pass
            def json(self): return self.payload
        with patch('builtins.print'):
            with patch.object(scrape_news.requests, 'get', return_value=Response({'status': 'success', 'results': []})):
                self.assertEqual(scrape_news.fetch_news('key'), [])
            with patch.object(scrape_news.requests, 'get', return_value=Response({'status': 'error', 'results': {}})):
                self.assertIsNone(scrape_news.fetch_news('key'))
            with patch.object(scrape_news.requests, 'get', side_effect=OSError('offline')):
                self.assertIsNone(scrape_news.fetch_news('key'))


if __name__ == '__main__':
    unittest.main()
