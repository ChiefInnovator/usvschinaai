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
            self.assertEqual(path.read_text(),original)
            self.assertEqual(selected_value(entry.columns,'GPQA Diamond'),'80%')

if __name__=='__main__': unittest.main()
