"""Publication durability, path boundaries, and staging failures."""
import base64
import hashlib
import json
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import prepare_publication as publication
from model_store import atomic_json


class PublicationTests(unittest.TestCase):
    def journal(self, root, payloads):
        digests = {path: hashlib.sha256(content).hexdigest() for path, content in payloads.items()}
        manifest = {'schemaVersion': 1, 'generationId': 'generation', 'scoringRevision': 'revision', 'artifacts': digests}
        payloads = {**payloads, publication.MANIFEST: json.dumps(manifest).encode()}
        entries = {path: {'sha256': hashlib.sha256(content).hexdigest(),
                          'bytes': base64.b64encode(content).decode()} for path, content in payloads.items()}
        atomic_json(root / publication.JOURNAL, {'schemaVersion': 1, 'artifacts': entries})
        return entries

    def test_interrupted_installation_recovers_exact_bytes_and_installs_manifest_last(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entries = self.journal(root, {'models.json': b'{"new":1}\n', 'current.json': b'{"new":1}\n'})
            original = publication.atomic_bytes
            installed = []
            def interrupt(path, payload):
                installed.append(Path(path).relative_to(root).as_posix())
                if len(installed) == 2:
                    raise OSError('simulated crash')
                original(path, payload)
            with patch.object(publication, 'atomic_bytes', side_effect=interrupt), self.assertRaises(OSError):
                publication.recover_publication(root)
            self.assertTrue((root / publication.JOURNAL).exists())
            self.assertFalse((root / publication.MANIFEST).exists())
            installed.clear()
            def observe(path, payload):
                installed.append(Path(path).relative_to(root).as_posix())
                original(path, payload)
            with patch.object(publication, 'atomic_bytes', side_effect=observe):
                publication.recover_publication(root)
            self.assertEqual(installed[-1], publication.MANIFEST)
            self.assertFalse((root / publication.JOURNAL).exists())
            for path, record in entries.items():
                self.assertEqual((root / path).read_bytes(), base64.b64decode(record['bytes']))

    def test_invalid_journal_paths_digests_or_symlinks_fail_before_first_write(self):
        for invalid in ('path', 'digest', 'symlink'):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                entries = self.journal(root, {'models.json': b'new'})
                if invalid == 'path':
                    entries['../outside.json'] = entries.pop('models.json')
                elif invalid == 'digest':
                    entries['models.json']['sha256'] = 'bad'
                else:
                    outside = root / 'outside'
                    outside.write_text('original')
                    (root / 'models.json').symlink_to(outside)
                atomic_json(root / publication.JOURNAL, {'schemaVersion': 1, 'artifacts': entries})
                with patch.object(publication, 'atomic_bytes') as write, self.assertRaises(ValueError):
                    publication.recover_publication(root)
                write.assert_not_called()

    def test_renderer_subprocess_failure_leaves_checkout_bytes_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'scripts').mkdir()
            (root / 'scripts/prepare_publication.py').write_text('# stage fixture\n')
            for path in publication.SOURCE_PATHS:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('{}\n')
            baseline = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with patch.object(publication.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, ['renderer'])), self.assertRaises(subprocess.CalledProcessError):
                publication.prepare(root, write=True)
            self.assertEqual(baseline, {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()})
            self.assertFalse((root / publication.JOURNAL).exists())

    def test_unpublished_paths_and_traversal_are_rejected(self):
        for path in ('/tmp/file', '../file', 'social/../models.json', 'scripts/scoring.py', './models.json', 'social/plan.json/extra'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                publication.allowed_path(path)

    def test_independent_full_replay_catches_forged_fresh_score_and_manifest(self):
        from test_model_store_integration import fixture
        from model_store import save_data
        from scoring_revision import generation_id
        from site_summary import build_summary
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(source / 'scripts', root / 'scripts', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            (root / 'data').mkdir()
            shutil.copyfile(source / 'data/core_benchmarks.json', root / 'data/core_benchmarks.json')
            data = fixture()
            for snapshot in data['history']:
                for rows in snapshot['teams'].values():
                    for row in rows:
                        row['created'] = '2026-01-01'
            save_data(data, root / 'models.json')
            (root / 'social').mkdir()
            plan = {'slides': ['2026-01-01-1-leaderboard-midnight.png']}
            atomic_json(root / 'social/plan.json', plan)
            atomic_json(root / 'data/social_caption_cache.json', {})
            for path in ('og-image.png', 'ig-image.png', 'social/'+plan['slides'][0]):
                shutil.copyfile(source / 'og-image.png', root / path)
            with patch.object(publication.subprocess, 'run', wraps=subprocess.run):
                publication.build_staged(root, False)
            # Alter an old computed result and forge every cheap identity/hash gate.
            raw = json.loads((root / 'models.json').read_text())
            raw['history'][-1]['teams']['US'][0]['unified'] += 7
            atomic_json(root / 'models.json', raw)
            manifest = json.loads((root / publication.MANIFEST).read_text())
            generation = generation_id(root, raw['scoringRevision'])
            catalog = json.loads((root / 'data/model_catalog.json').read_text())
            atomic_json(root / 'data/site_summary.json', build_summary(raw, catalog, raw['scoringRevision'], generation))
            manifest['generationId'] = generation
            manifest['artifacts'] = {path: publication.file_digest(root, path) for path in manifest['artifacts']}
            atomic_json(root / publication.MANIFEST, manifest)
            publication.verify_installed(root)
            before = (root / 'models.json').read_bytes()
            with self.assertRaisesRegex(ValueError, 'Full replay differs') as failure:
                publication.prepare(root)
            report = Path(str(failure.exception).split('diff: ')[1])
            self.assertTrue(report.exists())
            self.assertIn('unified', report.read_text())
            self.assertEqual((root / 'models.json').read_bytes(), before)
            report.unlink()

    def test_staging_excludes_secret_files_and_rejects_symlink_inputs(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as output:
            root, stage = Path(temporary), Path(output)
            (root / 'scripts').mkdir()
            (root / 'scripts/scorer.py').write_text('VALUE = 1')
            (root / 'scripts/.env.private').write_text('SECRET=hidden')
            (root / 'scripts/session.key').write_text('private')
            (root / 'scripts/leak.tmp').write_text('temporary secret')
            for path in publication.SOURCE_PATHS:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('{}')
            publication.copy_inputs(root, stage, True)
            self.assertEqual([p.name for p in (stage / 'scripts').iterdir()], ['scorer.py'])
            (root / 'models.json').unlink()
            (root / 'models.json').symlink_to(root / 'current.json')
            with tempfile.TemporaryDirectory() as another, self.assertRaisesRegex(ValueError, 'symlink'):
                publication.copy_inputs(root, Path(another), True)
