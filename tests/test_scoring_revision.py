"""Scoring program identity and mandatory all-history migration."""
import ast
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from scoring_revision import (SCORING_ROOTS, SOURCE_PATHS, canonical_bytes, generation_id,
                              require_revision, revision_record, scoring_sources)
from model_store import load_data, load_evidence, read_catalog, roster_identity, save_data
import rescore_history

ROOT = Path(__file__).resolve().parents[1]


class ScoringRevisionTests(unittest.TestCase):
    def test_inventory_recurses_into_new_local_imports_and_tracks_dependency_pins(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(ROOT / 'scripts', root / 'scripts')
            (root / 'data').mkdir()
            shutil.copyfile(ROOT / 'data/core_benchmarks.json', root / 'data/core_benchmarks.json')
            initial = revision_record(root)
            for name in SCORING_ROOTS:
                self.assertIn('scripts/'+name, initial['sources'])
            for path in scoring_sources(root):
                if not path.endswith('.py'):
                    continue
                for node in ast.walk(ast.parse((root / path).read_text())):
                    names = [a.name for a in node.names] if isinstance(node, ast.Import) else ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
                    for name in names:
                        local = 'scripts/'+name.replace('.', '/')+'.py'
                        if (root / local).exists():
                            self.assertIn(local, initial['sources'])
            helper = root / 'scripts/new_score_dependency.py'
            helper.write_text('VALUE = 1\n')
            scorer = root / 'scripts/scoring.py'
            scorer.write_text(scorer.read_text()+'\nimport new_score_dependency\n')
            added = revision_record(root)
            self.assertIn('scripts/new_score_dependency.py', added['sources'])
            helper.write_text('VALUE = 2\n')
            self.assertNotEqual(added['scoringRevision'], revision_record(root)['scoringRevision'])
            pins = root / 'scripts/requirements.txt'
            prior = revision_record(root)['scoringRevision']
            pins.write_text(pins.read_text()+'\n# changed dependency pins\n')
            self.assertNotEqual(prior, revision_record(root)['scoringRevision'])

    def test_generation_uses_exact_named_path_bytes_and_framing(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for path in SOURCE_PATHS:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('{"sample":1}\n')
            sources = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in SOURCE_PATHS}
            expected = hashlib.sha256(canonical_bytes({'scoringRevision': 'revision', 'sources': sources})).hexdigest()
            self.assertEqual(generation_id(root, 'revision'), expected)
            (root / 'models.json').write_text('{ "sample": 1 }\n')
            self.assertNotEqual(generation_id(root, 'revision'), expected)

    def test_missing_snapshot_stamp_forces_rebuild_of_every_snapshot_without_identity_changes(self):
        from test_model_store_integration import fixture
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'models.json'
            original = save_data(fixture(), path)
            catalog = read_catalog(path.parent / 'data/model_catalog.json')
            data = load_data(path)
            evidence = load_evidence(path.parent / 'data/model_catalog.json')
            data['scoringRevision'] = 'test-revision'
            for snapshot in data['history']:
                snapshot['scoring'] = {'revision': 'test-revision'}
                snapshot['teams']['US'][0]['GPQADiamond'] = '99%'
            del data['history'][-1]['scoring']['revision']
            with patch.object(rescore_history, 'scoring_revision', return_value='test-revision'), patch.object(rescore_history, 'rescore_snapshot', wraps=rescore_history.rescore_snapshot) as scorer:
                rescore_history.replay(data, evidence)
            self.assertEqual(scorer.call_count, 3)
            self.assertEqual([s['teams']['US'][0]['GPQADiamond'] for s in data['history']], ['70%']*3)
            normalized = save_data(data, path)
            self.assertEqual(roster_identity(normalized), roster_identity(original))
            self.assertEqual(catalog, read_catalog(path.parent / 'data/model_catalog.json'))
            require_revision(normalized, 'test-revision')
            del normalized['history'][-1]['scoring']['revision']
            with self.assertRaisesRegex(ValueError, 'full replay'):
                require_revision(normalized, 'test-revision')

    def test_replacing_active_benchmark_retains_inactive_evidence_without_scoring_it(self):
        from contextlib import ExitStack
        import avg_iq_benchmarks
        import model_store
        from test_model_store_integration import fixture
        config = copy.deepcopy(avg_iq_benchmarks.load_config())
        component = next(b for b in config['benchmarks'] if b['id'] == 'gpqa-diamond')
        component.update(id='replacement-benchmark', name='Replacement Benchmark', aliases=['Replacement Benchmark'])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'models.json'
            original = save_data(fixture(), path)
            catalog_path = path.parent / 'data/model_catalog.json'
            original_catalog = read_catalog(catalog_path)
            with ExitStack() as patches:
                for module in (avg_iq_benchmarks, model_store, rescore_history):
                    patches.enter_context(patch.object(module, 'load_config', return_value=config))
                data = load_data(path)
                evidence = load_evidence(catalog_path)
                rescore_history.validate_evidence(evidence)
                self.assertEqual(rescore_history.index_evidence(evidence), {})
                rescore_history.replay(data, evidence, rebuild=True)
                self.assertTrue(all(row['avgIq'] == 0 for snapshot in data['history'] for rows in snapshot['teams'].values() for row in rows))
                result = save_data(data, path)
            updated = read_catalog(catalog_path)
            self.assertEqual(updated['models'], original_catalog['models'])
            self.assertEqual(updated['evidenceMetadata'], original_catalog['evidenceMetadata'])
            self.assertEqual(updated['components'][:-1], original_catalog['components'])
            self.assertEqual(updated['components'][-1]['id'], 'replacement-benchmark')
            self.assertEqual(roster_identity(original), roster_identity(result))
            self.assertEqual(load_evidence(catalog_path), evidence)

    def test_offset_applicability_uses_utc_day_in_hydration_replay_and_retention(self):
        from test_model_store_integration import fixture
        from model_store import benchmark_columns, normalize, utc_day
        data = fixture()
        data['history'] = data['history'][:1]
        snapshot = data['history'][0]
        snapshot['timestamp'] = '2026-01-03T01:00:00+03:00'
        self.assertEqual(utc_day(snapshot['timestamp']), '2026-01-02')
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'models.json'
            original = save_data(data, path)
            catalog = read_catalog(path.parent / 'data/model_catalog.json')
            evidence = load_evidence(path.parent / 'data/model_catalog.json')
            self.assertTrue(all(r['availableFrom'] == '2026-01-02' for r in evidence['results']))
            future = copy.deepcopy(evidence['results'][0])
            future.update(id='utc-boundary-future', score=99, availableFrom='2026-01-03', retrievedAt='2026-01-03')
            evidence['results'].append(future)
            model = next(iter(catalog['models'].values()))
            model['benchmarks']['gpqa-diamond'][future['id']] = {k: v for k, v in future.items() if k not in ('id', 'model', 'component')}
            from model_store import hydrate
            hydrated = hydrate(original, catalog)
            self.assertEqual(hydrated['history'][0]['teams']['US'][0]['GPQADiamond'], '70%')
            rescore_history.replay(hydrated, evidence, rebuild=True)
            self.assertEqual(hydrated['history'][0]['teams']['US'][0]['GPQADiamond'], '70%')
            self.assertEqual(hydrated['history'][0]['timestamp'], snapshot['timestamp'])
