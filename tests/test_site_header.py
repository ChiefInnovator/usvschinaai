"""Every page carries the same header, styled once in the shared stylesheet."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ('index.html', 'news.html', 'history.html', 'about.html', 'privacy.html', 'terms.html')


class SiteHeaderTests(unittest.TestCase):
    def test_header_markup_is_identical_on_every_page(self):
        seen = set()
        for name in PAGES:
            html = (ROOT / name).read_text()
            headers = re.findall(r'<nav aria-label="Main navigation" class="site-nav">.*?</nav>', html, re.S)
            self.assertEqual(len(headers), 1, name)
            current = re.findall(r'<a href="([^"]+)" aria-current="page">', headers[0])
            self.assertEqual(current, [name] if name not in ('privacy.html', 'terms.html') else [], name)
            seen.add(re.sub(r'\s+', ' ', headers[0].replace(' aria-current="page"', '')))
        self.assertEqual(len(seen), 1)

    def test_no_page_restyles_the_header(self):
        self.assertIn('.site-nav {', (ROOT / 'css/site.css').read_text())
        for name in PAGES:
            styles = ''.join(re.findall(r'<style>(.*?)</style>', (ROOT / name).read_text(), re.S))
            for selectors in re.findall(r'([^{}]+)\{', styles):
                for selector in (part.strip() for part in selectors.split(',')):
                    with self.subTest(page=name, selector=selector):
                        # The section menu inside the page is not the site header.
                        self.assertNotRegex(selector, r'^(body\s*>\s*div\s*>\s*)?nav\b|site-nav|site-brand|site-links')


if __name__ == '__main__':
    unittest.main()
