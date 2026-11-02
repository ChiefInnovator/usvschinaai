"""Acceptance against the exact deploy artifact, without rewriting pages or data."""
import functools
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
from pathlib import Path
import threading
import unittest
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class BuiltSiteAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = Path(os.environ.get('BUILT_SITE_DIR', ROOT / 'dist')).resolve()
        if not cls.directory.exists():
            if 'BUILT_SITE_DIR' in os.environ:
                raise AssertionError('BUILT_SITE_DIR does not exist: ' + str(cls.directory))
            raise unittest.SkipTest('No dist artifact in source preflight; deploy builds before this suite')
        cls.manifest = json.loads((cls.directory / 'data/publication.json').read_text())
        cls.summary = json.loads((cls.directory / 'data/site_summary.json').read_text())
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0),
            functools.partial(QuietHandler, directory=str(cls.directory)))
        cls.addClassCleanup(cls.server.server_close)
        cls.addClassCleanup(cls.server.shutdown)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'
        cls.pw = sync_playwright().start()
        cls.addClassCleanup(cls.pw.stop)
        cls.browser = cls.pw.chromium.launch()
        cls.addClassCleanup(cls.browser.close)
        cls.ranked = sorted([row for rows in cls.summary['current']['teams'].values() for row in rows],
                            key=lambda row: -row['unified'])[:10]

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 390, 'height': 844},
                                                service_workers='allow')
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.errors = []
        self.external = []
        self.requested = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        def guard(route):
            url = route.request.url
            self.requested.append(url)
            if urlparse(url).netloc != urlparse(self.url).netloc:
                self.external.append(url)
                route.abort()
            else:
                route.continue_()
        self.context.route('**/*', guard)

    def home(self):
        self.page.goto(self.url + '/index.html')
        self.page.wait_for_function('''() => document.querySelectorAll('#models-table-body > tr').length === 10 &&
            window.Chart && Chart.getChart('trendChart') &&
            document.getElementById('trend-status').textContent.includes('daily snapshots')''')

    def test_actual_published_rankings_load_with_local_runtime_and_mobile_columns(self):
        self.home()
        for path in ('data/publication.json', 'data/site_summary.json'):
            self.assertIn(self.url + '/' + path, self.requested)
        for index, expected in enumerate(self.ranked):
            row = self.page.locator('#models-table-body > tr').nth(index)
            self.assertIn(expected['model'], row.inner_text())
            self.assertTrue(row.get_by_role('link', name=expected['model'], exact=False).first.is_visible())
            score = row.get_by_text(f"{expected['unified']:.2f}", exact=True)
            self.assertTrue(score.is_visible())
            rank = row.locator(':scope > td').first
            self.assertTrue(rank.is_visible())
            self.assertEqual(int(re.search(r'\d+', rank.inner_text()).group()), index + 1)
            for cell in row.locator(':scope > td').all():
                if cell.is_visible():
                    box = cell.bounding_box()
                    self.assertGreaterEqual(box['x'], 0)
                    self.assertLessEqual(box['x'] + box['width'], 390)
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= 390'))
        author_image = self.page.locator('#built-by img')
        author_image.scroll_into_view_if_needed()
        self.page.wait_for_function("document.querySelector('#built-by img').naturalWidth > 0")
        self.assertIn(self.url + '/inventing-fire-mark.png', self.requested)
        self.assertFalse(self.external, self.external)
        self.assertFalse(self.errors, self.errors)

    def test_every_served_shell_artifact_matches_manifest_hash(self):
        hashes = self.manifest['shellArtifacts']
        for required in ('index.html', 'history.html', 'about.html', 'privacy.html', 'terms.html',
                         '404.html', 'assets/site.css', 'assets/vendor/chart.umd.min.js',
                         'assets/vendor/lucide.min.js', 'js/site-data.js', 'data/site_summary.json',
                         'inventing-fire-mark.png', 'app-icon-1024.png'):
            self.assertIn(required, hashes)
        for path, expected in hashes.items():
            with self.subTest(path=path):
                response = self.context.request.get(self.url + '/' + path)
                self.assertTrue(response.ok)
                self.assertEqual(hashlib.sha256(response.body()).hexdigest(), expected)
        canonical = json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), self.manifest['shellRevision'])
        self.assertEqual(self.summary['generationId'], self.manifest['generationId'])
        self.assertEqual(self.summary['scoringRevision'], self.manifest['scoringRevision'])

    def test_archive_latest_and_date_navigation_use_actual_retained_data(self):
        self.page.goto(self.url + '/history.html')
        self.page.wait_for_selector('#history-container .snapshot tbody tr')
        latest = self.summary['current']['timestamp']
        self.assertEqual(parse_qs(urlparse(self.page.url).query)['at'], [latest])
        self.assertIn(self.ranked[0]['model'], self.page.locator('#history-container tbody tr').first.inner_text())
        self.assertEqual(self.page.locator('#snapshot-time').input_value(), latest)
        dates = self.page.locator('#snapshot-date option').evaluate_all('(options) => options.map(o => o.value)')
        self.assertTrue(dates)
        if len(dates) > 1:
            chosen = dates[1]
            self.page.locator('#snapshot-date').select_option(chosen)
            self.page.wait_for_function("document.querySelector('#history-container').getAttribute('aria-busy') === 'false'")
            self.assertTrue(parse_qs(urlparse(self.page.url).query)['at'][0].startswith(chosen))
            self.assertIn(chosen, self.page.locator('#history-container h2').first.inner_text())
            self.assertGreater(self.page.locator('#history-container tbody tr').count(), 0)
            self.assertIn(self.url + '/models.json', self.requested)
        self.assertFalse(self.external, self.external)
        self.assertFalse(self.errors, self.errors)

    def test_real_service_worker_activates_complete_artifact_and_reloads_offline(self):
        # Routing disables the browser HTTP cache but permits the actual service worker cache.
        self.home()
        self.page.wait_for_function('navigator.serviceWorker.controller !== null')
        self.page.wait_for_function('''async () => {
            const meta = await caches.open('usvschina-shell-meta-v2');
            return Boolean(await meta.match(location.origin + '/.offline-generation'));
        }''')
        active = self.page.evaluate('''async () => {
            const meta = await caches.open('usvschina-shell-meta-v2');
            return (await meta.match(location.origin + '/.offline-generation')).text();
        }''')
        self.assertIn(self.manifest['generationId'], active)
        self.assertIn(self.manifest['shellRevision'], active)
        self.context.set_offline(True)
        self.page.reload(wait_until='domcontentloaded')
        self.page.wait_for_function("document.querySelectorAll('#models-table-body > tr').length === 10 && document.querySelector('#models-table-body').textContent.includes(" + json.dumps(self.ranked[0]['model']) + ")")
        self.assertIn(f"{self.ranked[0]['unified']:.2f}", self.page.locator('#models-table-body > tr').first.inner_text())
        self.assertFalse(self.external, self.external)
        self.assertFalse(self.errors, self.errors)
