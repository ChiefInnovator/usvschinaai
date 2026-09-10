"""Full benchmark labels and model names must fit the Instagram canvas."""
import sys
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from avg_iq_benchmarks import load_config
from model_store import load_data
from social_formats import build_day_facts
from social_render import fill

ROOT = Path(__file__).resolve().parents[1]


class BenchmarkSlideLayoutTests(unittest.TestCase):
    def test_all_configured_titles_and_long_model_names_fit(self):
        facts = build_day_facts(load_data(ROOT / 'models.json'))
        charts = dict(benchmark_reporters=14, benchmark_cohort=20, benchmark_top5=[
            dict(model='DeepSeek-V4-Flash-Vision-Exp', origin='CN', value=59.3)
            for _ in range(5)])
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width':1080, 'height':1350})
            for component in load_config()['benchmarks']:
                with self.subTest(benchmark=component['name']):
                    charts['benchmark'] = component['aliases'][0].replace(' ', '')
                    page.set_content(fill('benchmark_day', 'graphite', facts, charts), wait_until='networkidle')
                    page.evaluate('document.fonts.ready')
                    self.assertEqual(page.locator('.bench .name').text_content(), component['name'])
                    for fallback in (False, True):
                        if fallback:
                            page.add_style_tag(content='body, .display { font-family: sans-serif !important; }')
                        issues = page.evaluate('''() => {
                            const issues = [];
                            for (const el of document.querySelectorAll('.bench .name, .bar .m, .bar .v, .legend, .footer')) {
                                const r = el.getBoundingClientRect();
                                if (el.scrollWidth > el.clientWidth + 1 || r.left < 55 || r.right > 1025 || r.bottom > 1303)
                                    issues.push(el.className + ': clipped');
                            }
                            if (document.querySelector('.legend').getBoundingClientRect().bottom > document.querySelector('.footer').getBoundingClientRect().top)
                                issues.push('legend overlaps footer');
                            return issues;
                        }''')
                        self.assertEqual(issues, [], f'fallback={fallback}')
