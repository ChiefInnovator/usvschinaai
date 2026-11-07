"""Crawler resources must match the canonical pages and current methodology."""
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from scrape_models import update_llms_metadata, update_sitemap_lastmod


class SearchDiscoveryTests(unittest.TestCase):
    def test_sitemap_matches_canonical_indexable_pages(self):
        ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        entries = ET.parse(ROOT / 'sitemap.xml').findall('s:url', ns)
        urls = [entry.findtext('s:loc', namespaces=ns) for entry in entries]
        expected = []
        for name in ('index.html', 'history.html', 'about.html', 'privacy.html', 'terms.html'):
            html = (ROOT / name).read_text()
            expected.append(re.search(r'rel="canonical" href="([^"]+)"', html).group(1))
            self.assertNotIn('noindex', html)
        self.assertCountEqual(urls, expected)
        self.assertEqual(len(urls), len(set(urls)))
        for entry in entries:
            self.assertRegex(entry.findtext('s:lastmod', namespaces=ns), r'^\d{4}-\d{2}-\d{2}$')
        self.assertIn('Sitemap: https://usvschina.ai/sitemap.xml', (ROOT / 'robots.txt').read_text())

    def test_ai_map_covers_current_benchmarks_and_published_resources(self):
        text = (ROOT / 'llms.txt').read_text()
        for benchmark in json.loads((ROOT / 'data/core_benchmarks.json').read_text())['benchmarks']:
            self.assertIn('- ' + benchmark['name'] + '\n', text)
        self.assertNotIn('two-pass', text)
        self.assertNotIn('%', text)
        for path in re.findall(r'https://usvschina.ai/([^\s)"<>]+)', text):
            self.assertTrue((ROOT / path).is_file(), path)

    def test_refresh_moves_only_dynamic_dates_and_keeps_ai_map_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            sitemap = Path(tmp) / 'sitemap.xml'
            sitemap.write_text((ROOT / 'sitemap.xml').read_text())
            original = ET.parse(sitemap)
            self.assertTrue(update_sitemap_lastmod(sitemap, '2027-01-02'))
            ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
            for before, after in zip(original.findall('s:url', ns), ET.parse(sitemap).findall('s:url', ns)):
                url = after.findtext('s:loc', namespaces=ns)
                expected = '2027-01-02' if url in ('https://usvschina.ai/', 'https://usvschina.ai/history.html') else before.findtext('s:lastmod', namespaces=ns)
                self.assertEqual(after.findtext('s:lastmod', namespaces=ns), expected)
            self.assertFalse(update_sitemap_lastmod(sitemap, '2026-01-01'))
            llms = Path(tmp) / 'llms.txt'
            llms.write_text((ROOT / 'llms.txt').read_text().replace('- Toolathlon\n', '- Retired benchmark\n'))
            self.assertTrue(update_llms_metadata(llms, '2027-01-02'))
            self.assertIn('Updated: 2027-01-02', llms.read_text())
            self.assertIn('- Toolathlon\n', llms.read_text())
            self.assertNotIn('Retired benchmark', llms.read_text())
            self.assertFalse(update_llms_metadata(llms, '2027-01-02'))
