"""Migration, daily updates, identity boundaries, and interrupted disk writes."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import model_store as store
from refresh_benchmark_sources import accept_findings, finding
with patch('dotenv.load_dotenv'):
    from scrape_models import prepend_history
from rescore_history import replay


def fixture():
    def row(name, country, price):
        return dict(model=name, link='https://example.org/'+name.replace(' ', '-'),
                    origin=country, organization='Test', **{'Input$/M': price, 'Output$/M': '$2',
                    'GPQADiamond': '70%', 'avgIq': 1, 'value': 1, 'unified': 1})
    teams={'US':[row('Muse Spark 1.3','US','$1'),row('Muse Spark 1.2','US','$3')],
           'CN':[row('Other model','CN','$1')]}
    return {'metadata':{},'teams':{'usa':{},'china':{}},'history':[
        dict(timestamp=day+'T12:00:00Z',teams=copy.deepcopy(teams))
        for day in ['2026-03-03','2026-02-02','2026-01-01']]}


class StoreIntegrationTests(unittest.TestCase):
    def test_migration_preserves_all_rows_profiles_evidence_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'models.json';legacy=root/'data/historical_benchmark_evidence.json'
            data=fixture();data['history'][0]['teams']['US'][0]['Input$/M']='$0.50'
            store.atomic_json(path,data)
            evidence={'benchmarkAvailability':{},'results':[]}
            accept_findings(evidence,[finding('Muse Spark 1.3','gpqa-diamond',70,'https://example.org/result','max','2026-01-01')],
                            {'Muse Spark 1.3':'2026-01-01'},'2026-03-03')
            store.atomic_json(legacy,evidence)
            store.migrate(path)
            self.assertFalse(legacy.exists())
            migrated=store.load_data(path)
            for old,new in zip(data['history'],migrated['history']):
                self.assertEqual(old['timestamp'],new['timestamp'])
                for country in old['teams']:
                    self.assertEqual(len(old['teams'][country]),len(new['teams'][country]))
                    for a,b in zip(old['teams'][country],new['teams'][country]):
                        self.assertTrue(all(b[k]==v for k,v in a.items()))
            actual={r['id']:r for r in store.load_evidence(root/'data/model_catalog.json')['results']}
            for r in evidence['results']:self.assertEqual(actual[r['id']],r)
            files=[path,root/'current.json',root/'data/model_catalog.json']
            before=[p.read_bytes() for p in files];store.migrate(path)
            self.assertEqual(before,[p.read_bytes() for p in files])

    def test_daily_update_ingests_once_rescores_old_dates_and_keeps_current_in_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'models.json';catalog=root/'data/model_catalog.json'
            old=fixture();store.save_data(old,path)
            replay(old,store.load_evidence(catalog));store.save_data(old,path)
            baseline=store.load_data(path)
            evidence=store.load_evidence(catalog)
            accepted,rejected=accept_findings(evidence,[finding('Muse Spark 1.3','gpqa-diamond',90,
                'https://example.org/new-result','xhigh','2026-02-01')],{'Muse Spark 1.3':'2026-01-01'},'2026-03-04')
            self.assertEqual((len(accepted),len(rejected)),(1,0));store.save_evidence(evidence,catalog)
            new=copy.deepcopy(baseline['history'][0]);new['timestamp']='2026-03-04T12:00:00Z'
            prepend_history(path,new)
            after=store.load_data(path)
            self.assertEqual(len(after['history']),4)
            self.assertEqual(store.load_data(root/'current.json')['history'],after['history'][:1])
            self.assertEqual([s['timestamp'] for s in after['history'][1:]],[s['timestamp'] for s in baseline['history']])
            self.assertEqual([s['teams']['US'][0]['GPQADiamond'] for s in after['history']],['90%','90%','90%','70%'])
            self.assertGreater(after['history'][1]['teams']['US'][0]['avgIq'],baseline['history'][0]['teams']['US'][0]['avgIq'])
            for a,b in zip(after['history'][1:],baseline['history']):
                for country in a['teams']:
                    self.assertEqual([r['model'] for r in a['teams'][country]],[r['model'] for r in b['teams'][country]])
                    for x,y in zip(a['teams'][country],b['teams'][country]):
                        if x['model']!='Muse Spark 1.3':self.assertEqual(x['avgIq'],y['avgIq'])
            self.assertEqual(sum(r['id']==accepted[0]['id'] for r in store.load_evidence(catalog)['results']),1)
            self.assertTrue((root/'data/historical_benchmark_gaps.json').exists())

    def test_model_release_and_benchmark_versions_never_share_fills(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'models.json';catalog=path.parent/'data/model_catalog.json'
            store.save_data(fixture(),path);evidence=store.load_evidence(catalog)
            accepted,rejected=accept_findings(evidence,[
                finding('Muse Spark 1.3','deepswe-1.1',85,'https://example.org/deepswe','low','2026-02-01'),
                finding('Muse Spark 1.3','gpqa-diamond',90,'https://example.org/gpqa','xhigh','2026-02-01'),
                finding('Muse Spark 1.3 preview','gpqa-diamond',99,'https://example.org/preview','max','2026-02-01')],
                {'Muse Spark 1.3':'2026-01-01','Muse Spark 1.2':'2026-01-01'},'2026-03-03')
            self.assertEqual((len(accepted),len(rejected)),(2,1))
            store.save_evidence(evidence,catalog);rows=store.load_data(path)['history'][0]['teams']['US']
            self.assertEqual(rows[0]['GPQADiamond'],'90%');self.assertEqual(rows[1]['GPQADiamond'],'70%')
            self.assertEqual(rows[0]['GPQA'],'—');self.assertEqual(rows[0]['DeepSWE'],'—')
            self.assertEqual(rows[0]['DeepSWE1.1'],'85%');self.assertEqual(rows[1]['DeepSWE1.1'],'—')

    def test_interrupted_multi_file_save_recovers_without_losing_rosters(self):
        for failing_file in ('model_catalog.json','models.json','current.json'):
            with self.subTest(failing_file=failing_file),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);path=root/'models.json';data=fixture();store.save_data(data,path)
                new=copy.deepcopy(data['history'][0]);new['timestamp']='2026-03-04T12:00:00Z'
                new['teams']['US'][0]['model']='New exact release'
                data['history'].insert(0,new)
                real=store.atomic_json
                def interrupted(target,value):
                    if Path(target).name==failing_file:raise OSError('simulated disk interruption')
                    return real(target,value)
                with patch.object(store,'atomic_json',side_effect=interrupted):
                    with self.assertRaises(OSError):store.save_data(data,path)
                restored=store.load_data(path)
                self.assertEqual([s['timestamp'] for s in restored['history']],[s['timestamp'] for s in data['history']])
                self.assertEqual(restored['history'][0]['teams']['US'][0]['model'],'New exact release')
                self.assertEqual(store.load_data(root/'current.json')['history'],restored['history'][:1])
                self.assertFalse((root/'.model-store-pending.json').exists())

    def test_partial_json_write_keeps_previous_complete_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'data.json';store.atomic_json(path,{'old':True});before=path.read_bytes()
            def fail_mid_write(data, stream, **kwargs):
                stream.write('{partial')
                raise TypeError('simulated serialization failure')
            with patch.object(store.json,'dump',side_effect=fail_mid_write):
                with self.assertRaises(TypeError):store.atomic_json(path,{'new':True})
            self.assertEqual(before,path.read_bytes())
            self.assertEqual(list(path.parent.glob('*.tmp')),[])

    def test_invalid_evidence_is_rejected_before_overwriting_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'models.json';catalog=path.parent/'data/model_catalog.json'
            store.save_data(fixture(),path);evidence=store.load_evidence(catalog)
            before=catalog.read_bytes()
            for bad_score in (-1,101,float('inf'),float('nan')):
                invalid=copy.deepcopy(evidence);invalid['results'][0]['score']=bad_score
                with self.subTest(score=bad_score),self.assertRaises(ValueError):store.save_evidence(invalid,catalog)
                self.assertEqual(before,catalog.read_bytes())
            valid=copy.deepcopy(evidence);valid['results'][0]['score']=71
            store.save_evidence(valid,catalog)
            self.assertEqual(store.load_evidence(catalog)['results'][0]['score'],71)

    def test_replay_builds_evidence_index_once_for_all_snapshots(self):
        import rescore_history
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'models.json';store.save_data(fixture(),path)
            data=store.load_data(path);evidence=store.load_evidence(path.parent/'data/model_catalog.json')
            with patch.object(rescore_history,'index_evidence',wraps=rescore_history.index_evidence) as index:
                replay(data,evidence)
            self.assertEqual(index.call_count,1)
            expected=copy.deepcopy(data)
            replay(data,evidence)
            self.assertEqual(data,expected)
