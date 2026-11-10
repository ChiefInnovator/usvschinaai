"""Real Chromium tests against application HTML, Chart.js and shared JSON storage.

Only benchmark data and transport failures are fixtures. Application renderers
and Chart.js are real. No API keys, model research, or publishing is involved.
"""
import copy
from datetime import datetime, timezone
import functools
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import hashlib
import shutil
from playwright.sync_api import sync_playwright
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from model_store import load_data, save_data
from site_summary import build_summary

ROOT=Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass


class BrowserIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.addClassCleanup(cls.temp.cleanup)
        shutil.copyfile(ROOT/'inventing-fire-mark.png',cls.root/'inventing-fire-mark.png')
        for name in ('index.html','history.html','about.html','privacy.html','terms.html','js/model-store.js','js/preconditions.js','js/site-data.js'):
            dest=cls.root/name;dest.parent.mkdir(parents=True,exist_ok=True)
            content=(ROOT/name).read_text()
            if name.endswith('.html'):
                # Expose the actual closure-scoped functions only in test fixtures.
                # Declarations remain intact, so application calls keep their scope.
                import re
                content=re.sub(r'((?:async )?function (\w+)\([^()]*\)\s*\{)',
                    lambda match: f'(window.__contractFunctions ||= {{}})["{match[2]}"] = {match[2]};\n'+match[1],content)
            dest.write_text(content)
        # Keep the real UI configuration, but use a small deterministic roster.
        base=load_data(ROOT/'current.json');base.pop('schemaVersion',None);base.pop('modelCatalog',None)
        sample=copy.deepcopy(base['history'][0]);sample['teams']={'US':[],'CN':[]}
        for i in range(12):
            country='US' if i%2==0 else 'CN'
            sample['teams'][country].append(dict(model=f'Test Model {i}',origin=country,organization='Test',
                link=f'https://example.org/model-{i}',**{'Input$/M':'$1','Output$/M':'$2','GPQADiamond':'70%',
                'avgIq':70,'value':23.33,'unified':900-i*50,'coverage':'1/17','provisional':False}))
        base['history']=[]
        # Two observations on the same UTC day, an exact daily boundary and an older point.
        for stamp in ('2026-09-07T12:00:00-04:00','2026-09-06T20:30:00Z',
                      '2026-09-06T00:30:00-04:00','2026-08-09T00:00:00Z','2026-08-08T23:59:59Z'):
            s=copy.deepcopy(sample);s['timestamp']=stamp;base['history'].append(s)
        base['history'][1]['teams']['CN'][0]['unified']=990
        cls.input=copy.deepcopy(base)
        save_data(base,cls.root/'models.json')
        revision='browser-test-revision'
        for name in ('models.json','current.json'):
            data=json.loads((cls.root/name).read_text());data['scoringRevision']=revision
            for snapshot in data['history']:snapshot.setdefault('scoring',{})['revision']=revision
            (cls.root/name).write_text(json.dumps(data))
        raw=json.loads((cls.root/'models.json').read_text())
        catalog=json.loads((cls.root/'data/model_catalog.json').read_text())
        summary=build_summary(raw,catalog,revision,'browser-test-generation')
        (cls.root/'data/site_summary.json').write_text(json.dumps(summary))
        cls.valid={name:(cls.root/name).read_bytes() for name in ('models.json','current.json','data/model_catalog.json','data/site_summary.json')}
        manifest={'schemaVersion':1,'scoringRevision':revision,'generationId':'browser-test-generation',
                  'artifacts':{name:hashlib.sha256(body).hexdigest() for name,body in cls.valid.items()}}
        (cls.root/'data/publication.json').write_text(json.dumps(manifest))
        shutil.copytree(ROOT/'assets',cls.root/'assets')
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
            if url.startswith(self.url):request.continue_();return
            # Nonessential icons/news are not the subject of these tests.
            request.fulfill(status=200,body='',content_type='application/javascript')
        self.context.route('**/*',route)

    def ready(self):
        self.page.wait_for_function('window.Chart && Chart.getChart("trendChart") && document.getElementById("trend-status").textContent.includes("daily snapshots")')

    def test_visible_updated_timestamp_uses_local_calendar_days_and_time(self):
        for zone,expected in (('America/New_York','YESTERDAY AT 10:37 PM'),
                              ('America/Los_Angeles','YESTERDAY AT 7:37 PM'),
                              ('Asia/Tokyo','TODAY AT 12:37 PM')):
            with self.subTest(timezone=zone):
                context=self.browser.new_context(service_workers='block',timezone_id=zone)
                try:
                    page=context.new_page()
                    page.clock.install(time=datetime(2026,11,8,11,52,tzinfo=timezone.utc))
                    page.route('**/data/site_summary.json',lambda route: route.fulfill(
                        status=200,body=self.valid['data/site_summary.json'],content_type='application/json'))
                    page.goto(self.url+'/index.html',wait_until='domcontentloaded')
                    page.wait_for_function("document.querySelector('#page-subtitle').textContent.startsWith('Updated ')")
                    page.evaluate("currentEntry.timestamp='2026-11-08T03:37:41+00:00'; populateStaticContent()")
                    self.assertEqual(page.locator('#page-subtitle').inner_text(),
                                     'UPDATED '+expected)
                    self.assertNotIn('UTC',page.locator('#page-subtitle').inner_text())
                    title=page.locator('#page-subtitle').get_attribute('title')
                    self.assertIn({'America/New_York':'EST','America/Los_Angeles':'PST','Asia/Tokyo':'GMT+9'}[zone],title)
                    self.assertIn({'America/New_York':'10:37:41 PM','America/Los_Angeles':'7:37:41 PM','Asia/Tokyo':'12:37:41 PM'}[zone],title)
                    page.clock.set_system_time(datetime(2026,11,10,11,52,tzinfo=timezone.utc))
                    page.clock.fast_forward(60000)
                    self.assertNotIn('TODAY',page.locator('#page-subtitle').inner_text())
                    self.assertNotIn('YESTERDAY',page.locator('#page-subtitle').inner_text())
                    page.clock.set_system_time(datetime(2026,11,8,11,52,tzinfo=timezone.utc))
                    page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:true}); document.dispatchEvent(new Event('visibilitychange'))")
                    self.assertNotIn('UPDATED '+expected,page.locator('#page-subtitle').inner_text())
                    page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:false}); document.dispatchEvent(new Event('visibilitychange'))")
                    self.assertEqual(page.locator('#page-subtitle').inner_text(),'UPDATED '+expected)
                finally:
                    context.close()

    def test_failed_refresh_keeps_error_after_timer_and_visibility_updates(self):
        self.page.clock.install(time=datetime(2026,11,8,11,52,tzinfo=timezone.utc))
        self.page.goto(self.url+'/index.html');self.ready()
        self.failures['data/site_summary.json']=(503,'{}')
        self.page.evaluate('fetchModels()')
        subtitle=self.page.locator('#page-subtitle')
        self.assertEqual(subtitle.inner_text(),'DATA TEMPORARILY UNAVAILABLE')
        self.page.clock.fast_forward(60000)
        self.page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        self.assertEqual(subtitle.inner_text(),'DATA TEMPORARILY UNAVAILABLE')
        self.assertIsNone(subtitle.get_attribute('title'))

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
        self.page.get_by_text('Explore sections', exact=True).click()
        self.assertTrue(self.page.get_by_role('navigation',name='Page sections').get_by_role('link',name='Leaderboard').is_visible())
        self.assertTrue(self.page.locator('#matrixChart').is_visible());self.assertFalse(self.errors)
    def test_initial_home_never_downloads_raw_catalog_or_archive(self):
        requested=[];self.page.on('request',lambda req:requested.append(req.url))
        self.page.goto(self.url+'/index.html');self.ready()
        for path in ('models.json','current.json','data/model_catalog.json'):
            self.assertNotIn(self.url+'/'+path,requested)
        self.assertEqual(self.page.locator('#models-table-body > tr').count(),10)

        benchmarks=json.loads(self.valid['data/site_summary.json'])['benchmarks']
        self.assertTrue(any(b['weight'] > 0 for b in benchmarks))
        names=[b['name'] for b in benchmarks]
        preview=self.page.locator('#benchmarks-preview')
        self.assertEqual(preview.text_content(),' · '.join(names))
        self.assertEqual(preview.get_attribute('title'),' · '.join(names))
        self.assertEqual(self.page.locator('#benchmarks-container > span').all_text_contents(),names)

    def test_summary_failure_recovers_with_retry(self):
        self.failures['data/site_summary.json']=(503,'{}')
        self.page.goto(self.url+'/index.html');self.page.get_by_role('button',name='Retry',exact=True).wait_for()
        self.failures.clear();self.page.get_by_role('button',name='Retry',exact=True).click();self.ready()

    def test_generation_mismatch_explains_refresh_and_recovers(self):
        summary=json.loads(self.valid['data/site_summary.json']);summary['current']['teams']={'US':[],'CN':[]}
        self.failures['data/site_summary.json']=(200,json.dumps(summary))
        self.page.goto(self.url+'/index.html');self.page.get_by_text('Published data changed',exact=False).wait_for()
        self.failures.clear();self.page.get_by_role('button',name='Retry',exact=True).click();self.ready()

    def test_deferred_evidence_failure_keeps_ranking_and_retries(self):
        self.failures['data/model_catalog.json']=(503,'{}')
        self.page.goto(self.url+'/index.html');self.ready()
        self.page.locator('#models-table-body details summary').first.click()
        self.page.get_by_role('button',name='Retry evidence').wait_for()
        self.assertEqual(self.page.locator('#models-table-body > tr').count(),10)
        self.failures.clear();self.page.get_by_role('button',name='Retry evidence').click()
        self.page.locator('#models-table-body .evidence-content').first.get_by_text(
            'Missing results contribute zero',exact=False).wait_for()
        names=[b['name'] for b in json.loads(self.valid['data/site_summary.json'])['benchmarks']]
        self.assertEqual(self.page.locator('#models-table-body .evidence-content').first.locator('tbody th').all_text_contents(),names)

    def test_chart_constructor_failure_preserves_rankings_and_tables(self):
        self.page.goto(self.url+'/index.html');self.ready()
        self.page.evaluate("() => {window.Chart = class {constructor(){throw new Error('Chart render failed')}};}")
        self.page.evaluate('fetchModels()')
        self.page.get_by_text('Intelligence vs. Value chart unavailable.',exact=False).wait_for()
        self.assertEqual(self.page.locator('#models-table-body > tr').count(),10)
        self.assertEqual(self.page.locator('#matrix-values tbody tr').count(),12)
        self.assertEqual(self.page.locator('#trend-values tbody tr').count(),3)
        self.assertNotEqual(self.page.locator('#page-subtitle').inner_text(),'Data temporarily unavailable')
        self.assertFalse(self.errors)

    def test_future_summary_timestamp_has_explicit_warning(self):
        from datetime import datetime, timedelta, timezone
        future=(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()
        summary=json.loads(self.valid['data/site_summary.json'])
        summary['current']['timestamp']=future;summary['history'][0]['timestamp']=future
        body=json.dumps(summary)
        manifest=json.loads((self.root/'data/publication.json').read_text())
        manifest['artifacts']['data/site_summary.json']=hashlib.sha256(body.encode()).hexdigest()
        self.failures['data/site_summary.json']=(200,body)
        self.failures['data/publication.json']=(200,json.dumps(manifest))
        self.page.goto(self.url+'/index.html');self.ready()
        self.assertIn('more than five minutes in the future',self.page.locator('#snapshot-freshness-warning').inner_text())
        self.assertEqual(self.page.locator('#models-table-body > tr').count(),10)

    def test_loaded_snapshot_is_labeled_while_offline_and_updates_online(self):
        self.page.goto(self.url+'/index.html');self.ready()
        self.context.set_offline(True)
        self.page.wait_for_function("document.getElementById('connection-status').textContent.includes('Offline')")
        status=self.page.locator('#connection-status')
        self.assertTrue(status.is_visible())
        self.assertIn(self.input['history'][0]['timestamp'],status.inner_text())
        self.assertEqual(self.page.locator('#models-table-body > tr').count(),10)
        self.context.set_offline(False)
        self.page.wait_for_function("document.getElementById('connection-status').hidden")

    def test_service_worker_cached_response_is_labeled_even_when_online(self):
        self.page.route('**/data/site_summary.json',lambda route:route.fulfill(status=200,
            body=self.valid['data/site_summary.json'],headers={'Content-Type':'application/json','X-Site-Cache':'offline'}))
        self.page.goto(self.url+'/index.html');self.ready()
        self.assertTrue(self.page.evaluate('navigator.onLine'))
        self.assertIn('Cached data',self.page.locator('#connection-status').inner_text())
        self.assertTrue(self.page.locator('#connection-status').is_visible())

    def test_hydrate_evidence_cutoff_uses_utc_day_for_offset_timestamps(self):
        self.page.goto(self.url+'/index.html');self.ready()
        values=self.page.evaluate("""() => {
            const catalog={components:[{id:'test',column:'Test'}],models:{m:{profiles:{p:{model:'Offset model'}},benchmarks:{test:{early:{score:50,availableFrom:'2026-09-06'},next:{score:90,availableFrom:'2026-09-07'}}}}}};
            const hydrate=timestamp=>ModelStore.hydrate({schemaVersion:2,history:[{timestamp,teams:{US:[{modelId:'m',profileId:'p'}],CN:[]}}]},catalog).history[0].teams.US[0].Test;
            return [hydrate('2026-09-07T00:30:00+04:00'),hydrate('2026-09-06T23:30:00-04:00')];
        }""")
        self.assertEqual(values,['50%','90%'])

    def test_hydrate_uses_active_component_columns_and_keeps_zero_weights(self):
        self.page.goto(self.url+'/index.html');self.ready()
        row=self.page.evaluate("""() => {
            const catalog={components:[{id:'old',column:'Retired'},{id:'new',column:'Active'}],models:{m:{profiles:{p:{model:'Changed definition'}},benchmarks:{old:{e:{score:99,availableFrom:'2026-01-01'}},new:{e:{score:80,availableFrom:'2026-01-01'}}}}}};
            return ModelStore.hydrate({schemaVersion:2,history:[{timestamp:'2026-09-07T00:00:00Z',scoring:{avgIqWeights:{Active:0}},teams:{US:[{modelId:'m',profileId:'p'}],CN:[]}}]},catalog).history[0].teams.US[0];
        }""")
        self.assertEqual(row['Active'],'80%')
        self.assertNotIn('Retired',row)
        self.assertEqual(row['modelId'],'m')

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
                        const action=window[name] || window.__contractFunctions[name];
                        if (typeof action !== 'function') throw new Error('Missing callable: ' + name);
                        const values=rules.map(r=>r==='mapping'?{}:r==='index'?0:r.startsWith('enum:')?r.slice(5).split('|')[0]:'sample');
                        AppContract.check(name,values,rules);
                        let rejected=0;
                        for (let i=0;i<rules.length;i++) {
                            const bad=values.slice();bad[i]=rules[i]==='mapping'?[]:rules[i]==='index'?-1:rules[i]==='?json'?(()=>{}):42;
                            try { await action(...bad); } catch(e) { if(e instanceof TypeError && e.message.startsWith(name + ':')) rejected++; }
                        }
                        try {await action(...values, 'unexpected argument');} catch(e) {if(e instanceof TypeError && e.message.startsWith(name + ':')) rejected++;}
                        return rejected===rules.length+1;
                    }''',dict(name=name,rules=rules))
                    self.assertTrue(result,name)

    def test_json_contract_rejects_nonfinite_and_cyclic_values(self):
        self.page.goto(self.url+'/index.html');self.ready()
        result=self.page.evaluate('''() => {
            const cycle={};cycle.self=cycle;
            const invalid=[NaN,Infinity,-Infinity,{score:NaN},[Infinity],cycle];
            for (const value of invalid) {
                try {AppContract.check('jsonTest',[value],['json']);return false;}
                catch(error) {if(!(error instanceof TypeError) || !error.message.startsWith('jsonTest:'))return false;}
            }
            for(const value of [null,0,84.5,'score',true,{scores:[1,2,null]}]) AppContract.check('jsonTest',[value],['json']);
            return true;
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
