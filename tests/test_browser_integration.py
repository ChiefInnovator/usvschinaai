"""Real Chromium tests against application HTML, Chart.js and shared JSON storage.

Only benchmark data and transport failures are fixtures. Application renderers
and Chart.js are real. No API keys, model research, or publishing is involved.
"""
import copy
import functools
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import requests
from playwright.sync_api import sync_playwright
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from model_store import load_data, save_data

ROOT=Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass


class BrowserIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.addClassCleanup(cls.temp.cleanup)
        for name in ('index.html','history.html','about.html','privacy.html','terms.html','js/model-store.js','js/preconditions.js'):
            dest=cls.root/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((ROOT/name).read_bytes())
        # Keep the real UI configuration, but use a small deterministic roster.
        base=load_data(ROOT/'current.json');base.pop('schemaVersion',None);base.pop('modelCatalog',None)
        sample=copy.deepcopy(base['history'][0]);sample['teams']={'US':[],'CN':[]}
        for i in range(12):
            country='US' if i%2==0 else 'CN'
            sample['teams'][country].append(dict(model=f'Test Model {i}',origin=country,organization='Test',
                link=f'https://example.org/model-{i}',**{'Input$/M':'$1','Output$/M':'$2','GPQADiamond':'70%',
                'avgIq':70,'value':23.33,'unified':900-i*50,'coverage':'1/18','provisional':False}))
        base['history']=[]
        # Two observations on the same UTC day, an exact daily boundary and an older point.
        for stamp in ('2026-09-07T12:00:00-04:00','2026-09-06T20:30:00Z',
                      '2026-09-06T00:30:00-04:00','2026-08-09T00:00:00Z','2026-08-08T23:59:59Z'):
            s=copy.deepcopy(sample);s['timestamp']=stamp;base['history'].append(s)
        base['history'][1]['teams']['CN'][0]['unified']=990
        cls.input=copy.deepcopy(base)
        save_data(base,cls.root/'models.json')
        cls.valid={name:(cls.root/name).read_bytes() for name in ('models.json','current.json','data/model_catalog.json')}
        cls.assets={}
        for url in ('https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js',
                    'https://cdn.tailwindcss.com/3.4.16'):
            response=requests.get(url,timeout=30);response.raise_for_status();cls.assets[url]=response.content
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(QuietHandler,directory=cls.temp.name))
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.addClassCleanup(cls.server.server_close);cls.addClassCleanup(cls.server.shutdown)
        cls.url=f'http://127.0.0.1:{cls.server.server_port}'
        cls.pw=sync_playwright().start();cls.addClassCleanup(cls.pw.stop)
        cls.browser=cls.pw.chromium.launch();cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        self.context=self.browser.new_context(service_workers='block',timezone_id='America/Los_Angeles')
        self.addCleanup(self.context.close)
        self.page=self.context.new_page();self.failures={};self.errors=[]
        self.page.on('pageerror',lambda error:self.errors.append(str(error)))
        def route(request):
            url=request.request.url
            relative=url.removeprefix(self.url+'/')
            if relative in self.failures:
                status,body=self.failures[relative]
                request.fulfill(status=status,body=body,content_type='application/json');return
            if url in self.assets:
                request.fulfill(status=200,body=self.assets[url],content_type='application/javascript');return
            if url.startswith(self.url):request.continue_();return
            # Nonessential icons/news are not the subject of these tests.
            request.fulfill(status=200,body='',content_type='application/javascript')
        self.context.route('**/*',route)

    def ready(self):
        self.page.wait_for_function('window.Chart && Chart.getChart("trendChart") && document.getElementById("trend-status").textContent.includes("daily snapshots")')

    def test_graph_uses_latest_snapshot_per_utc_day_and_preserves_archive(self):
        self.page.goto(self.url+'/index.html');self.ready()
        datasets=self.page.evaluate('Chart.getChart("trendChart").data.datasets')
        ordered=[self.input['history'][i] for i in (3,1,0)]
        self.assertEqual([d['label'] for d in datasets],['USA','China'])
        for dataset,country in zip(datasets,('US','CN')):
            self.assertEqual(len(dataset['data']),3)
            self.assertEqual(len({p['x'] for p in dataset['data']}),3)
            self.assertEqual([p['snapshotTimestamp'] for p in dataset['data']],[s['timestamp'] for s in ordered])
            self.assertTrue(all(p['x'] % 86400000 == 0 for p in dataset['data']))
            for point,snapshot in zip(dataset['data'],ordered):
                ranked=sorted([(r['unified'],c) for c,rows in snapshot['teams'].items() for r in rows],reverse=True)[:10]
                self.assertEqual(point['y'],sum(score for score,c in ranked if c==country))
        rendered=self.page.evaluate('''() => {const c=Chart.getChart('trendChart');return c.data.datasets.map((d,i)=>c.getDatasetMeta(i).data.every(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)));}''')
        self.assertEqual(rendered,[True,True]);self.assertGreater(len(self.page.locator('#trendChart').screenshot()),5000)
        self.assertEqual(self.page.locator('#benchmarks-section').get_attribute('open'),None)
        self.assertEqual(self.page.locator('nav[aria-label="Page sections"] a').count(),7)
        self.assertTrue(self.page.locator('#matrixChart').is_visible());self.assertFalse(self.errors)
        self.page.goto(self.url+'/history.html')
        self.page.wait_for_function('historyData.length === 5')
        # Every archived observation remains available, including the intraday one.
        for i,snapshot in enumerate(self.input['history'][:4]):
            top=sorted([(r['unified'],c) for c,rows in snapshot['teams'].items() for r in rows],reverse=True)[:10]
            text=self.page.locator('#history-container > div').nth(i).inner_text()
            for country in ('US','CN'):
                self.assertIn(f'{sum(score for score,c in top if c==country):.1f}',text.replace(',',''))

    def test_catalog_http_failure_recovers_with_leaderboard_retry(self):
        self.failures['data/model_catalog.json']=(503,'{}')
        self.page.goto(self.url+'/index.html');self.page.get_by_role('button',name='Retry',exact=True).wait_for()
        self.failures.clear();self.page.get_by_role('button',name='Retry',exact=True).click();self.ready()
        self.assertEqual(self.page.locator('#models-table-body tr').count(),10)

    def test_malformed_catalog_json_recovers_with_retry(self):
        self.failures['data/model_catalog.json']=(200,'{broken')
        self.page.goto(self.url+'/index.html');self.page.get_by_role('button',name='Retry',exact=True).wait_for()
        self.failures.clear();self.page.get_by_role('button',name='Retry',exact=True).click();self.ready()

    def test_invalid_catalog_structure_does_not_poison_retry_cache(self):
        self.failures['data/model_catalog.json']=(200,'{"models":{},"components":[]}')
        self.page.goto(self.url+'/index.html');self.page.get_by_role('button',name='Retry',exact=True).wait_for()
        self.failures.clear();self.page.get_by_role('button',name='Retry',exact=True).click();self.ready()

    def test_history_http_failure_and_malformed_json_recover_on_reload(self):
        for status,body in ((503,'{}'),(200,'{broken')):
            with self.subTest(status=status):
                self.failures['models.json']=(status,body)
                self.page.goto(self.url+'/index.html')
                self.page.get_by_text('Historical comparison could not load.',exact=False).wait_for()
                self.failures.clear();self.page.reload();self.ready()

    def test_archive_failure_recovers_using_its_retry_button(self):
        self.failures['models.json']=(503,'{}')
        self.page.goto(self.url+'/history.html');self.page.get_by_role('button',name='Retry',exact=True).wait_for()
        self.failures.clear();self.page.get_by_role('button',name='Retry',exact=True).click()
        self.page.wait_for_function('historyData.length === 5')

    def test_public_page_actions_have_positive_and_negative_precondition_cases(self):
        import re
        for filename in ('index.html','history.html','about.html','privacy.html','terms.html'):
            with self.subTest(page=filename):
                self.page.goto(self.url+'/'+filename)
                source=(ROOT/filename).read_text()
                contracts=re.findall(r'AppContract\.check\("(\w+)", arguments, (\[[^;]*\])\);',source)
                declared=re.findall(r'function (\w+)\([^()]*\)\s*\{',source)
                self.assertEqual(sorted(declared),sorted(name for name,_ in contracts))
                for name,raw in contracts:
                    rules=json.loads(raw)
                    result=self.page.evaluate('''async ({name,rules}) => {
                        const values=rules.map(r=>r==='mapping'?{}:r==='index'?0:r.startsWith('enum:')?r.slice(5).split('|')[0]:'sample');
                        AppContract.check(name,values,rules);
                        let rejected=0;
                        for (let i=0;i<rules.length;i++) {
                            const bad=values.slice();bad[i]=rules[i]==='mapping'?[]:rules[i]==='index'?-1:rules[i]==='?json'?(()=>{}):42;
                            try { await window[name](...bad); } catch(e) { if(e instanceof TypeError) rejected++; }
                        }
                        try {await window[name](...values, 'unexpected argument');} catch(e) {if(e instanceof TypeError) rejected++;}
                        return rejected===rules.length+1;
                    }''',dict(name=name,rules=rules))
                    self.assertTrue(result,name)

    def test_archive_index_precondition_rejects_out_of_range_without_changing_state(self):
        self.page.goto(self.url+'/history.html');self.page.wait_for_function('historyData.length === 5')
        self.page.evaluate('toggleEntry(0)')
        self.assertTrue(self.page.get_by_text('Test Model 0',exact=False).first.is_visible())
        result=self.page.evaluate('''() => {
            const before=JSON.stringify(expandedEntries);
            for(const i of [-1,5,1.5]) {
                try {toggleEntry(i);return false;} catch(e) {if(!(e instanceof TypeError || e instanceof RangeError))return false;}
            }
            return before===JSON.stringify(expandedEntries);
        }''')
        self.assertTrue(result)

    def test_chart_uses_roster_scores_without_expanding_entire_catalog(self):
        self.page.goto(self.url+'/index.html');self.ready()
        calls=self.page.evaluate('''async () => {
            const original=ModelStore.expand;let calls=0;
            ModelStore.expand=(...args)=>{calls++;return original(...args);};
            try {await renderThirtyDayTrend();return calls;} finally {ModelStore.expand=original;}
        }''')
        self.assertEqual(calls,0)
        self.assertEqual(self.page.evaluate('Chart.getChart("trendChart").data.datasets[0].data.length'),3)
