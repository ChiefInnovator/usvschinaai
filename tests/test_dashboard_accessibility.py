"""Phone, keyboard, and recoverable interaction acceptance using real page assets."""
import unittest
import test_browser_integration as integration


class DashboardAccessibilityTests(unittest.TestCase):
    setUpClass = classmethod(integration.BrowserIntegrationTests.setUpClass.__func__)
    setUp = integration.BrowserIntegrationTests.setUp
    ready = integration.BrowserIntegrationTests.ready

    def test_phone_keeps_rank_name_and_unified_in_one_view(self):
        self.page.set_viewport_size({'width':390,'height':844})
        self.page.goto(self.url+'/index.html');self.ready()
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= 390'))
        for cell in self.page.locator('#models-table-body > tr').first.locator(':scope > td').all():
            if cell.is_visible():
                box=cell.bounding_box();self.assertGreaterEqual(box['x'],0);self.assertLessEqual(box['x']+box['width'],390)
        self.assertIn('900.00',self.page.locator('#models-table-body > tr').first.inner_text())
        for selector in ('#team-usa-badge','#team-china-badge','#scoreboard .items-end > span'):
            for label in self.page.locator(selector).all():
                self.assertGreaterEqual(label.evaluate('node => parseFloat(getComputedStyle(node).fontSize)'),11)
        self.assertLess(self.page.locator('#scoreboard').bounding_box()['y'],self.page.locator('nav[aria-label="Page sections"]').bounding_box()['y'])

    def test_keyboard_sort_filter_url_and_back(self):
        self.page.goto(self.url+'/index.html?filter=US&sort=name&direction=asc');self.ready()
        self.assertEqual(self.page.locator('#filter-us').get_attribute('aria-pressed'),'true')
        sort=self.page.get_by_role('button',name='Unified (0-1000)',exact=False)
        sort.focus();self.page.keyboard.press('Enter')
        self.assertEqual(self.page.locator('th[data-sort="unified"]').get_attribute('aria-sort'),'descending')
        self.page.locator('#filter-cn').click()
        self.assertIn('filter=CN',self.page.url)
        self.page.go_back()
        self.assertEqual(self.page.locator('#filter-us').get_attribute('aria-pressed'),'true')
        self.assertEqual(self.page.locator('#models-table-body > tr').count(),6)

    def test_chart_values_and_share_failure_are_accessible(self):
        self.page.goto(self.url+'/index.html');self.ready()
        self.assertTrue(self.page.get_by_role('img',name='USA and China Top 10 sums',exact=False).is_visible())
        self.page.get_by_text('Exact historical values',exact=True).click()
        self.assertEqual(self.page.locator('#trend-values tbody tr').count(),3)
        self.page.evaluate("Object.defineProperty(navigator,'clipboard',{value:{writeText:()=>Promise.reject(new Error('Denied'))},configurable:true})")
        self.page.get_by_role('button',name='Copy Link',exact=False).click()
        fallback=self.page.get_by_role('textbox',name='Copy this leaderboard link')
        fallback.wait_for();self.assertEqual(fallback.input_value(),self.page.url)
        self.assertIn('Clipboard unavailable',self.page.locator('#share-status').inner_text())
