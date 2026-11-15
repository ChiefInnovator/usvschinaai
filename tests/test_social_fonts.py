"""Slides render from bundled fonts, with no font host to reach."""
import re
import sys
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from model_store import load_data
from social_formats import build_day_facts
from social_render import TEMPLATES, fill, font_faces

ROOT = Path(__file__).resolve().parents[1]


class SocialFontTests(unittest.TestCase):
    def test_every_bundled_font_file_is_inlined(self):
        rules = (TEMPLATES / '_fonts.css').read_text()
        names = re.findall(r'url\((fonts/[\w.-]+)\)', rules)
        self.assertEqual(sorted(names), sorted(f'fonts/{path.name}' for path in (TEMPLATES / 'fonts').glob('*.woff2')))
        inlined = font_faces()
        self.assertEqual(inlined.count('url(data:font/woff2;base64,'), len(names))
        self.assertNotIn('url(fonts/', inlined)

    def test_slide_loads_its_fonts_with_the_network_blocked(self):
        html = fill('leaderboard', 'graphite', build_day_facts(load_data(ROOT / 'models.json')))
        self.assertNotIn('{{font_faces}}', html)
        requested = []
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 1080, 'height': 1350})
                page.route('**/*', lambda route: (requested.append(route.request.url), route.abort()))
                page.set_content(html, wait_until='networkidle')
                page.evaluate('document.fonts.ready')
                loaded = page.evaluate(
                    "() => [...document.fonts].filter(face => face.status === 'loaded').map(face => face.family.replace(/[\"']/g, ''))")
            finally:
                browser.close()
        self.assertEqual(requested, [])
        self.assertIn('IBM Plex Sans', loaded)
        self.assertIn('Bebas Neue', loaded)


if __name__ == '__main__':
    unittest.main()
