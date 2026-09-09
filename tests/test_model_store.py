"""Shared observations update all applicable rosters without copying benchmark cells."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from model_store import (empty_catalog, merge_evidence, save_data, load_data, read_catalog,
                         load_evidence, save_evidence, hydrate, benchmark_columns)
from rescore_history import replay


class ModelStoreTests(unittest.TestCase):
    def test_unsupported_benchmarks_are_dropped_without_losing_supported_results(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'models.json'
            data = self.fixture()
            for snapshot in data['history']:
                row = snapshot['teams']['US'][0]
                row['Obsolete Benchmark'] = '99%'
                row['_provenance'] = {
                    'Obsolete Benchmark': {'url': 'https://example.org/obsolete'},
                    'GPQADiamond': {'url': 'https://example.org/gpqa'},
                }
            save_data(data, path)
            catalog = read_catalog(path.parent / 'data/model_catalog.json')
            model = next(iter(catalog['models'].values()))
            self.assertEqual(set(model['benchmarks']), {'gpqa-diamond'})
            self.assertNotIn('Obsolete Benchmark', json.dumps(catalog))
            result = next(iter(model['benchmarks']['gpqa-diamond'].values()))
            self.assertEqual(result['source'], 'https://example.org/gpqa')
            for snapshot in load_data(path)['history']:
                row = snapshot['teams']['US'][0]
                self.assertEqual(row['GPQADiamond'], '70%')
                self.assertEqual(row['Input$/M'], '$1.00')
                self.assertNotIn('Obsolete Benchmark', row)

    def fixture(self):
        row = {'model': 'Test Model', 'link': 'https://example.org/model', 'origin': 'US',
               'Input$/M': '$1.00', 'Output$/M': '$2.00', 'GPQADiamond': '70%',
               'avgIq': 1, 'value': 1, 'unified': 1}
        return {'history': [dict(timestamp=day+'T12:00:00Z', teams={'US': [copy.deepcopy(row)], 'CN': []})
                            for day in ['2026-03-03', '2026-02-02', '2026-01-01']]}

    def test_normalization_preserves_rosters_prices_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'models.json'
            data=self.fixture();data['history'][0]['teams']['US'][0]['Input$/M']='$0.50'
            stored=save_data(data,path)
            catalog=read_catalog(path.parent/'data/model_catalog.json')
            self.assertEqual(len(catalog['models']),1)
            model=next(iter(catalog['models'].values()))
            self.assertEqual(len(model['profiles']),2)
            self.assertEqual(len(model['benchmarks']['gpqa-diamond']),1)
            for snapshot in stored['history']:
                self.assertEqual(set(snapshot['teams']['US'][0]),{'modelId','profileId','avgIq','value','unified'})
            hydrated=load_data(path)
            self.assertEqual([s['timestamp'] for s in hydrated['history']],[s['timestamp'] for s in data['history']])
            self.assertEqual([s['teams']['US'][0]['Input$/M'] for s in hydrated['history']],['$0.50','$1.00','$1.00'])
            original=path.read_bytes();original_catalog=(path.parent/'data/model_catalog.json').read_bytes()
            save_data(hydrated,path)
            self.assertEqual(path.read_bytes(),original)
            self.assertEqual((path.parent/'data/model_catalog.json').read_bytes(),original_catalog)

    def test_one_gap_fill_updates_all_applicable_dates_and_rescores_idempotently(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'models.json';catalog_path=path.parent/'data/model_catalog.json'
            save_data(self.fixture(),path)
            evidence=load_evidence(catalog_path)
            evidence['results'].append(dict(id='new',model='Test Model',component='gpqa-diamond',
                benchmark='GPQA Diamond',score=90,unit='percent',source='https://example.org/result',
                availableFrom='2026-02-01',retrievedAt='2026-03-03',configuration='xhigh'))
            save_evidence(evidence,catalog_path)
            data=load_data(path)
            self.assertEqual([s['teams']['US'][0]['GPQADiamond'] for s in data['history']],['90%','90%','70%'])
            replay(data,load_evidence(catalog_path));save_data(data,path)
            first=path.read_bytes()
            data=load_data(path);replay(data,load_evidence(catalog_path));save_data(data,path)
            self.assertEqual(path.read_bytes(),first)
            self.assertGreater(data['history'][0]['teams']['US'][0]['avgIq'], data['history'][-1]['teams']['US'][0]['avgIq'])
            self.assertEqual(len(load_evidence(catalog_path)['results']),2)
            # Source correction replaces the one central observation.
            evidence=load_evidence(catalog_path)
            next(r for r in evidence['results'] if r['id']=='new')['excludedReason']='Wrong benchmark version'
            save_evidence(evidence,catalog_path)
            self.assertEqual(load_data(path)['history'][0]['teams']['US'][0]['GPQADiamond'],'70%')

    def test_browser_and_python_hydrate_identically_and_reject_dangling_refs(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'models.json';stored=save_data(self.fixture(),path)
            catalog=read_catalog(path.parent/'data/model_catalog.json')
            script=Path(__file__).resolve().parents[1]/'js/model-store.js'
            actual=subprocess.check_output(['node','-e',
                'const fs=require("fs"),s=require(process.argv[1]),v=JSON.parse(fs.readFileSync(0,"utf8"));process.stdout.write(JSON.stringify(s.hydrate(v.data,v.catalog)));',str(script)],
                input=json.dumps(dict(data=stored,catalog=catalog)).encode())
            self.assertEqual(json.loads(actual),hydrate(stored,catalog))
            stored['history'][0]['teams']['US'][0]['modelId']='missing'
            with self.assertRaises(KeyError):hydrate(stored,catalog)


if __name__=='__main__':unittest.main()
