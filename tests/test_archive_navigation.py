"""Archive journeys against the real page and publication-bound loader."""
import copy
import functools
import hashlib
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class ArchiveNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        for path in ('history.html', 'about.html', 'privacy.html', 'terms.html', '404.html',
                     'js/site-data.js', 'js/model-store.js', 'js/preconditions.js',
                     'assets/site.css', 'assets/vendor/lucide.min.js'):
            target = directory / path
            target.parent.mkdir(parents=True, exist_ok=True)
            if (ROOT / path).exists():
                target.write_bytes((ROOT / path).read_bytes())
        cls.stamps = ['2026-09-07T12:00:00Z', '2026-09-06T20:30:00Z',
                      '2026-09-06T04:30:00Z', '2026-08-09T00:00:00Z']
        rows = {'US': [], 'CN': []}
        catalog = {'models': {}, 'components': [{'id': 'gpqa', 'column': 'GPQA'}]}
        for i in range(12):
            model_id, profile_id = f'model-{i}', f'profile-{i}'
            profile = {'model': f'Test Model {i}', 'Input$/M': '$1', 'Output$/M': '$2', 'company': 'Test'}
            row = dict(profile, modelId=model_id, profileId=profile_id, avgIq=70,
                       value=23.33, unified=900-i*50, coverage='1/18', provisional=False)
            rows['US' if i % 2 == 0 else 'CN'].append(row)
            catalog['models'][model_id] = {'profiles': {profile_id: profile}, 'benchmarks': {
                'gpqa': {'e1': {'score': 70, 'source': 'https://example.org/evidence',
                                'availableFrom': '2026-01-01', 'retrievedAt': '2026-09-01',
                                'configuration': 'Verified result'}}}}
        current = {'timestamp': cls.stamps[0], 'scoring': {'revision': 'revision'}, 'teams': rows}
        snapshots = [dict(copy.deepcopy(current), timestamp=stamp) for stamp in cls.stamps]
        # A historical roster has an absent model, not a manufactured zero row.
        snapshots[-1]['teams']['US'].pop()
        total = {'total': 2000, 'count': 5, 'avgIq': 70, 'avgValue': 23.33}
        summary = {'schemaVersion': 1, 'generationId': 'fixture', 'scoringRevision': 'revision',
                   'catalogFingerprint': 'fixture', 'metadata': {}, 'teams': {}, 'columns': [],
                   'benchmarks': [{'id': 'gpqa', 'name': 'GPQA', 'column': 'GPQA', 'weight': 15}] +
                                 [{'id': f'b{i}', 'name': f'Fixture benchmark {i}',
                                   'column': f'B{i}', 'weight': 5} for i in range(17)],
                   'current': current, 'history': [{'timestamp': s, 'scoringRevision': 'revision',
                                                   'scores': {'US': total, 'CN': total}} for s in cls.stamps]}
        payloads = {'data/site_summary.json': summary, 'data/model_catalog.json': catalog,
                    'current.json': {'schemaVersion': 2, 'scoringRevision': 'revision', 'history': [snapshots[0]]},
                    'models.json': {'schemaVersion': 2, 'scoringRevision': 'revision', 'history': snapshots}}
        artifacts = {}
        for path, data in payloads.items():
            target = directory / path
            target.parent.mkdir(parents=True, exist_ok=True)
            content = json.dumps(data).encode()
            target.write_bytes(content)
            artifacts[path] = hashlib.sha256(content).hexdigest()
        (directory / 'data/publication.json').write_text(json.dumps({
            'schemaVersion': 1, 'generationId': 'fixture', 'scoringRevision': 'revision', 'artifacts': artifacts}))
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=cls.temp.name))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.addClassCleanup(cls.server.server_close)
        cls.addClassCleanup(cls.server.shutdown)
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'
        cls.pw = sync_playwright().start()
        cls.addClassCleanup(cls.pw.stop)
        cls.browser = cls.pw.chromium.launch()
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 390, 'height': 844}, service_workers='block')
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.requests = []
        self.errors = []
        self.page.on('request', lambda request: self.requests.append(request.url))
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))

    def ready(self, sections=1):
        self.page.wait_for_function("document.querySelector('#history-container').getAttribute('aria-busy') === 'false' && document.querySelectorAll('.snapshot').length === " + str(sections))

    def test_lightweight_default_and_lazy_evidence(self):
        self.page.goto(self.url + '/history.html')
        self.ready()
        self.assertFalse(any(path in url for url in self.requests for path in ('models.json', 'current.json', 'model_catalog.json')))
        self.assertEqual(self.page.locator('tbody tr').count(), 10)
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 390)
        row = self.page.locator('tbody tr').first
        self.assertTrue(row.get_by_text('900.00', exact=True).is_visible())
        row.locator('summary').click()
        self.page.get_by_role('link', name='Source', exact=True).wait_for()
        self.assertTrue(any('current.json' in url for url in self.requests))
        self.assertIn('available 2026-01-01', row.inner_text())
        self.assertFalse(self.errors)

    def test_date_intraday_comparison_and_back(self):
        self.page.goto(self.url + '/history.html')
        self.ready()
        self.page.locator('#snapshot-date').select_option('2026-09-06')
        self.ready()
        self.assertEqual(self.page.locator('#snapshot-time').input_value(), self.stamps[1])
        self.assertEqual(self.page.locator('#snapshot-time option').count(), 2)
        self.page.locator('#snapshot-time').select_option(self.stamps[2])
        self.ready()
        self.assertIn('at=2026-09-06T04%3A30%3A00Z', self.page.url)
        self.page.locator('#comparison-date').select_option('2026-08-09')
        self.ready(2)
        self.assertIn('compare=', self.page.url)
        self.page.go_back()
        self.ready()
        self.assertEqual(self.page.locator('#snapshot-time').input_value(), self.stamps[2])
        self.page.go_back()
        self.ready()
        self.assertEqual(self.page.locator('#snapshot-time').input_value(), self.stamps[1])
        self.assertFalse(self.errors)

    def test_invalid_fallback_keyboard_sort_and_global_ranks(self):
        self.page.goto(self.url + '/history.html?at=2026-09-05T00:00:00Z')
        self.ready()
        self.assertIn('Requested snapshot is unavailable', self.page.locator('#archive-status').inner_text())
        self.page.get_by_role('button', name='China', exact=True).click()
        self.ready()
        self.assertEqual(self.page.locator('tbody tr').first.locator('td').first.inner_text(), '2')
        button = self.page.get_by_role('button', name='Model', exact=True)
        button.focus()
        self.page.keyboard.press('Enter')
        self.ready()
        self.assertEqual(self.page.locator('th[aria-sort="descending"]').inner_text(), 'Model')
        self.assertEqual(self.page.evaluate('document.activeElement.dataset.sort'), 'model')
        self.assertEqual(self.page.get_by_role('button', name='China', exact=True).get_attribute('aria-pressed'), 'true')
        self.assertFalse(self.errors)

    def test_lazy_snapshot_failure_retry_and_absent_model(self):
        self.page.goto(self.url + '/history.html')
        self.ready()
        self.page.route('**/models.json', lambda route: route.fulfill(status=503, body='{}'))
        self.page.locator('#snapshot-date').select_option('2026-08-09')
        self.page.get_by_role('button', name='Retry snapshot', exact=True).wait_for()
        self.assertIn('HTTP 503', self.page.locator('#history-container').inner_text())
        self.page.unroute('**/models.json')
        self.page.get_by_role('button', name='Retry snapshot', exact=True).click()
        self.ready()
        self.page.get_by_role('button', name='All', exact=True).click()
        self.ready()
        self.assertEqual(self.page.locator('tbody tr').count(), 11)
        self.assertEqual(self.page.get_by_text('Test Model 10', exact=True).count(), 0)
        self.assertEqual(self.page.locator('#snapshot-date option[value="2026-09-05"]').count(), 0)
        self.assertFalse(self.errors)

    def test_reading_pages_have_no_news_requests_and_one_main(self):
        for name in ('about.html', 'privacy.html', 'terms.html'):
            with self.subTest(name=name):
                self.requests.clear()
                self.page.goto(self.url + '/' + name)
                self.assertEqual(self.page.locator('main').count(), 1)
                self.assertEqual(self.page.locator('a.skip-link').get_attribute('href'), '#main-content')
                self.assertEqual(self.page.locator('#newsMarquee').count(), 0)
                self.assertFalse(any('news.json' in url for url in self.requests))
                self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 390)
