import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from harvest_benchmark_sources import harvest_aa, harvest_epoch
from rescore_history import apply_evidence
from avg_iq_benchmarks import selected_value

class EffortMaximaTests(unittest.TestCase):
    def test_each_component_uses_its_own_best_effort(self):
        records={'Muse Spark 1.3 (max)':{'slug':'max','gpqa':.938,'mmmuPro':None},
                 'Muse Spark 1.3 (xhigh)':{'slug':'xhigh','gpqa':.941,'mmmuPro':.82},
                 'Muse Spark 1.3 (low)':{'slug':'low','gpqa':.90,'mmmuPro':.83},
                 'Muse Spark 1.3 (Default Fallback)':{'slug':'fallback','gpqa':1,'mmmuPro':1},
                 'Muse Spark 1.2 (max)':{'slug':'other','gpqa':1,'mmmuPro':1}}
        with patch('harvest_benchmark_sources.load_aa',return_value=records):
            findings,skipped,_=harvest_aa('', ['Muse Spark 1.3'],{})
        values={f['component']:f for f in findings}
        self.assertEqual(values['gpqa-diamond']['score'],94.1)
        self.assertTrue(values['gpqa-diamond']['sourceUrl'].endswith('/xhigh'))
        self.assertEqual(values['mmmu-pro']['score'],83)
        self.assertFalse(skipped)

    def test_history_upgrades_but_never_backdates_or_downgrades(self):
        snap={'timestamp':'2026-09-06','teams':{'US':[{'model':'M','GPQADiamond':'93.8%'}]}}
        def record(i,score,day,**extra):
            return dict(id=i,model='M',component='gpqa-diamond',score=score,availableFrom=day,
                        source='https://example.org/'+i,configuration=i,retrievedAt=day,**extra)
        evidence={'results':[record('xhigh',94.1,'2026-09-06'),record('future',99,'2026-09-07'),
                             record('low',80,'2026-09-01'),record('mixed',100,'2026-09-01',excludedReason='Different model fallback')]}
        apply_evidence(snap,evidence)
        row=snap['teams']['US'][0]
        self.assertEqual(selected_value(row,'GPQA Diamond'),'94.1%')
        self.assertEqual(row['_provenance']['GPQADiamond']['evidenceId'],'xhigh')
        self.assertEqual(apply_evidence(snap,evidence),[])

    def test_epoch_does_not_require_matching_effort_or_backdate_evaluation(self):
        table={'gpqa_diamond.csv':[{'Model version':'M_low','mean_score':'0.8','Started at':'2026-09-01'},
                                  {'Model version':'M_max','mean_score':'0.9','Started at':'2026-08-01'}]}
        findings,skipped=harvest_epoch(table,['M'],{}, {})
        self.assertEqual(findings[0]['score'],90)
        self.assertIsNone(findings[0]['publishedAt'])
        self.assertFalse(skipped)
