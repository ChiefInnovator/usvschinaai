"""Source refresh preserves benchmark identity, evidence dates and dry-run behavior."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import refresh_benchmark_sources as refresh
from avg_iq_benchmarks import load_config, selected_value


class SourceRefreshTests(unittest.TestCase):
    def test_detail_refresh_parses_fetched_html_without_browser(self):
        html = json.dumps(json.dumps(dict(benchmark_id=1, name='GPQA Diamond', normalized_score=0.8), separators=(',', ':')))
        with patch.object(refresh, 'fetch', return_value=html):
            found = refresh.detail_results('Model A', 'https://example.org/model-a')
        self.assertEqual([(r['component'], r['score']) for r in found], [('gpqa-diamond', 80.0)])

    def test_blocked_host_stops_retrying_detail_pages(self):
        attempts=[]
        def blocked(url,attempts=3): attempts_seen.append(attempts); raise RuntimeError('403')
        attempts_seen=attempts
        with patch.object(refresh,'fetch',side_effect=blocked),patch.object(refresh,'llm_stats_failures',0):
            for _ in range(refresh.LLM_STATS_BLOCKED_AFTER+2):
                with self.assertRaises(RuntimeError): refresh.detail_results('Model A','https://example.org/model-a')
        self.assertEqual(attempts,[3]*refresh.LLM_STATS_BLOCKED_AFTER+[1,1])

    def test_original_toolathlon_not_verified(self):
        def table(score):
            return '<table><tr><th>Model</th></tr><tr><td>Model A-high</td><td>x</td><td>Agent</td><td>2026-08-01</td><td>'+score+'</td></tr></table>'
        found=refresh.original_toolathlon(table('99')+'Previous Toolathlon leaderboard'+table('42'),{'Model A':'2026-01-01'})
        self.assertEqual([r['score'] for r in found],[42])
        with self.assertRaises(ValueError): refresh.original_toolathlon(table('99'),{})

    def test_model_variant_and_release_qualifiers_are_preserved(self):
        from harvest_benchmark_sources import strip_effort
        self.assertEqual(strip_effort('Model A (Adaptive Reasoning, Max Effort)'), 'Model A')
        for name in ('Model A (NVFP4)', 'Model A (Jan 2026)', 'Model A_preview',
                     'Model A (Adaptive Reasoning, Max Effort, Default Fallback)'):
            self.assertEqual(strip_effort(name),name)

    def test_charxiv_reasoning_column(self):
        found=refresh.charxiv_results('Model,a,b,Overall,c,d,e,f,Overall\nModel A,x,x,42,x,x,x,x,99\n',{'Model A':'2026-01-01'})
        self.assertEqual(found[0]['score'],42)

    def test_dates_identity_and_exclusions(self):
        evidence={'results':[]}
        record=refresh.finding('Model A','gpqa-diamond',80,'https://example.org/results','standard')
        accepted,_=refresh.accept_findings(evidence,[record],{'Model A':'2026-01-01'},'2026-10-01')
        self.assertEqual(accepted[0]['availableFrom'],'2026-10-01')
        self.assertEqual(accepted[0]['retrievedAt'],'2026-10-01')
        accepted,rejected=refresh.accept_findings(evidence,[dict(record,model='Unknown'),dict(record,configuration='fallback to another model')],{'Model A':'2026-01-01'},'2026-10-01')
        self.assertEqual(len(rejected),2)
        self.assertFalse(accepted)

    def test_direct_refresh_without_api_and_dry_run_applies_in_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'models.json').write_text(json.dumps({'history':[{'teams':{'US':[{'model':'Model A','link':'https://example.org'}]}}]}))
            path=root/'evidence.json'
            path.write_text(json.dumps({'results':[], 'benchmarkAvailability':{}}))
            entry=SimpleNamespace(name='Model A',url='https://example.org',columns={})
            original=path.read_text()
            result=refresh.finding('Model A','gpqa-diamond',80,'https://example.org/results','standard')
            with patch.object(refresh,'ROOT',root),patch.object(refresh,'EVIDENCE',path),patch.object(refresh,'model_first_seen',return_value={'Model A':'2026-01-01'}),patch.object(refresh,'observed_values',return_value={}),patch.object(refresh,'fetch',side_effect=RuntimeError('offline')),patch.object(refresh,'detail_results',return_value=[result]):
                report=refresh.refresh_sources([entry],write=False)
            self.assertEqual(report['accepted'],1)
            self.assertTrue(report['failures'])
            self.assertNotIn('vals:aime', [f['source'] for f in report['failures']])
            self.assertEqual(path.read_text(),original)
            self.assertEqual(selected_value(entry.columns,'GPQA Diamond'),'80%')

    def test_toolathlon_ignores_vendor_icon_titles(self):
        row=('<tr><td><svg><title>OpenAI icon</title><path></path></svg> <a>Model-A-xhigh</a></td><td>x</td>'
             '<td>Agent</td><td>2026-08-01</td><td>55.6± 1.2</td></tr>')
        html='Previous Toolathlon leaderboard<table><tr><th>Model</th></tr>'+row+'</table>'
        found=refresh.original_toolathlon(html,{'Model A':'2026-01-01'})
        self.assertEqual([(r['model'],r['score'],r['publishedAt']) for r in found],[('Model A',55.6,'2026-08-01')])

    def test_toolathlon_unreadable_rows_fail_closed(self):
        html='Previous Toolathlon leaderboard<table><tr><th>Model</th></tr><tr><td>Model A</td><td>x</td><td>Agent</td><td>soon</td><td>n/a</td></tr></table>'
        with self.assertRaises(ValueError): refresh.original_toolathlon(html,{'Model A':'2026-01-01'})

    def test_artificial_analysis_field_rename_fails_closed(self):
        import harvest_benchmark_sources as harvest
        def aa_page(**scores):
            record=dict(id='0'*8+'-0000-0000-0000-'+'0'*12,slug='model-a',name='Model A',**scores)
            return 'self.__next_f.push([1,"'+json.dumps(json.dumps(record,separators=(',',':')))[1:-1]+'"])'
        current=dict(gpqa=0.9,ifbench=0.5,mmmuPro=0.6,terminalBench21=0.7)
        found,_,_=harvest.harvest_aa(aa_page(**current),['Model A'],{})
        self.assertEqual({r['component']:r['score'] for r in found},
                         {'gpqa-diamond':90.0,'ifbench':50.0,'mmmu-pro':60.0,'terminal-bench-2.1':70.0})
        renamed=dict(current,terminalbenchV21=current['terminalBench21']); del renamed['terminalBench21']
        for raw in (aa_page(**renamed),'<html>no payload</html>'):
            with self.assertRaisesRegex(ValueError,'terminalBench21'): harvest.load_aa(raw)

    def test_fetch_retries_throttling_but_not_missing_pages(self):
        import io
        import urllib.error
        from email.message import Message
        import harvest_benchmark_sources as harvest
        def error(code): return urllib.error.HTTPError('https://example.org',code,'x',Message(),io.BytesIO())
        with patch.object(harvest.time,'sleep') as sleep, \
             patch.object(harvest.urllib.request,'urlopen',side_effect=[error(403),TimeoutError(),io.BytesIO(b'ok')]) as opened:
            self.assertEqual(harvest.fetch('https://example.org'),'ok')
            self.assertEqual((opened.call_count,sleep.call_count),(3,2))
        with patch.object(harvest.time,'sleep') as sleep, \
             patch.object(harvest.urllib.request,'urlopen',side_effect=error(404)) as opened:
            with self.assertRaises(urllib.error.HTTPError): harvest.fetch('https://example.org')
            self.assertEqual((opened.call_count,sleep.call_count),(1,0))
        with patch.object(harvest.time,'sleep'), \
             patch.object(harvest.urllib.request,'urlopen',side_effect=error(403)) as opened:
            with self.assertRaises(urllib.error.HTTPError): harvest.fetch('https://example.org')
            self.assertEqual(opened.call_count,3)

    def test_source_health_carries_outage_start_and_last_productive_day(self):
        previous={'vals:gpqa':dict(status='failed',findings=0,since='2026-10-04',lastOk='2026-10-03'),
                  'charxiv':dict(status='empty',findings=0,since='2026-09-06',lastOk=None)}
        counts={'vals:gpqa':0,'charxiv':0,'llm-stats':40,'epoch':12}
        failures=[{'source':'vals:gpqa','error':'payload changed'},{'source':'epoch:arc.csv','error':'Table missing'}]
        failures+=[{'source':f'llm-stats:M{i}','error':'HTTP Error 403: Forbidden'} for i in range(4)]
        health=refresh.source_health(previous,counts,{'llm-stats':10},failures,'2026-11-10')
        self.assertEqual(health['vals:gpqa'],dict(status='failed',findings=0,since='2026-10-04',lastOk='2026-10-03',error='payload changed'))
        self.assertEqual(health['charxiv']['since'],'2026-09-06')
        self.assertEqual((health['epoch']['status'],health['epoch']['since']),('failed','2026-11-10'))
        self.assertEqual(health['llm-stats'],dict(status='ok',findings=40,since='2026-11-10',lastOk='2026-11-10',
                                                  pages=10,failedPages=4,error='HTTP Error 403: Forbidden'))
        failures+=[{'source':f'llm-stats:N{i}','error':'HTTP Error 403: Forbidden'} for i in range(2)]
        self.assertEqual(refresh.source_health(previous,counts,{'llm-stats':10},failures,'2026-11-10')['llm-stats']['status'],'failed')
        recovered=refresh.source_health(health,dict(counts,**{'vals:gpqa':7}),{'llm-stats':10},[],'2026-11-11')
        self.assertEqual(recovered['vals:gpqa'],dict(status='ok',findings=7,since='2026-11-11',lastOk='2026-11-11'))

    def test_outage_start_survives_a_change_of_failure_mode(self):
        # Parser exception one night, an answer with no matches the next: still one outage.
        previous={'vals:gpqa':dict(status='failed',findings=0,since='2026-11-08',lastOk='2026-11-07'),
                  'aa':dict(status='empty',findings=0,since='2026-11-08',lastOk='2026-11-07'),
                  'charxiv':dict(status='empty',findings=0,since='2026-09-06',lastOk=None)}
        counts={'vals:gpqa':0,'aa':0,'charxiv':0}
        failures=[{'source':'aa','error':'payload changed'},{'source':'charxiv','error':'timed out'}]
        health=refresh.source_health(previous,counts,{},failures,'2026-11-09')
        self.assertEqual((health['vals:gpqa']['status'],health['vals:gpqa']['since']),('empty','2026-11-08'))
        self.assertEqual((health['aa']['status'],health['aa']['since']),('failed','2026-11-08'))
        # A source that never matched is not in an outage; its first error starts the clock.
        self.assertEqual((health['charxiv']['status'],health['charxiv']['since']),('failed','2026-11-09'))
        recovered=refresh.source_health(health,dict(counts,aa=3),{},[],'2026-11-10')
        self.assertEqual((recovered['aa']['status'],recovered['aa']['since']),('ok','2026-11-10'))

    def test_refresh_reports_missing_epoch_table_and_writes_health(self):
        import io
        import zipfile
        from harvest_benchmark_sources import EPOCH_ZIP
        archive=io.BytesIO()
        with zipfile.ZipFile(archive,'w') as bundle:
            bundle.writestr('data/gpqa_diamond.csv','Model version,mean_score,Started at\nModel A,0.8,2026-09-01\n')
        def fake_fetch(url,binary=False):
            if url==EPOCH_ZIP: return archive.getvalue()
            raise RuntimeError('offline')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'models.json').write_text(json.dumps({'history':[{'teams':{'US':[{'model':'Model A','link':'https://example.org'}]}}]}))
            path=root/'evidence.json'; audit=root/'audit.json'
            path.write_text(json.dumps({'results':[], 'benchmarkAvailability':{}}))
            audit.write_text(json.dumps({'sourceHealth':{'toolathlon':dict(status='failed',findings=0,since='2026-10-01',lastOk=None)}}))
            with patch.object(refresh,'ROOT',root),patch.object(refresh,'EVIDENCE',path),patch.object(refresh,'AUDIT',audit),patch.object(refresh,'model_first_seen',return_value={'Model A':'2026-01-01'}),patch.object(refresh,'observed_values',return_value={}),patch.object(refresh,'fetch',side_effect=fake_fetch),patch.object(refresh,'detail_results',return_value=[]):
                report=refresh.refresh_sources(write=True)
            written=json.loads(audit.read_text())['sourceHealth']
        self.assertIn('epoch:frontiermath_tiers_1_3_v2.csv',[f['source'] for f in report['failures']])
        self.assertEqual((written['epoch']['status'],written['epoch']['findings']),('failed',1))
        self.assertEqual(written['toolathlon']['since'],'2026-10-01')
        self.assertEqual(written['llm-stats']['status'],'empty')

if __name__=='__main__': unittest.main()
