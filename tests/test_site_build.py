"""Public build boundaries and content-addressed offline shell."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_site


class SiteBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'checkout'
        self.output = Path(self.temporary.name) / 'dist'
        for path in build_site.PAGES + build_site.PUBLIC + build_site.DATA:
            self.write(path, '{}')
        self.write('data/publication.json', json.dumps({'schemaVersion': 1, 'generationId': 'a' * 64}))
        self.write('social/plan.json', json.dumps({'slides': ['slide-1.png']}))
        for path in ('social/slide-1.png', 'social/previous.png', 'assets/site.css',
                     'assets/vendor/chart.umd.min.js', 'assets/vendor/lucide.min.js',
                     'js/site-data.js', 'web-app-manifest-192x192.png'):
            self.write(path, path)

    def write(self, path, contents):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents)

    def build(self):
        return build_site.build_site(self.root, self.output, verify=False)

    def test_allowlist_excludes_private_sources_and_keeps_published_slides(self):
        private = ('.agents/secret.md', '.github/workflows/deploy.yml', '.env',
                   'tests/private.py', 'scripts/private.py', 'data/ai_fill_history.jsonl',
                   'data/social_cost.jsonl', 'node_modules/package/index.js', 'social/private.json')
        for path in private:
            self.write(path, 'private')
        self.output.mkdir()
        (self.output / 'stale-secret').write_text('stale')
        self.build()
        published = {path.relative_to(self.output).as_posix() for path in self.output.rglob('*') if path.is_file()}
        self.assertFalse(published.intersection(private))
        self.assertNotIn('stale-secret', published)
        self.assertTrue({'current.json', 'models.json', 'social/plan.json', 'social/slide-1.png',
                         'social/previous.png', 'assets/site.css', 'js/site-data.js'} <= published)

    def test_manifest_hashes_exact_complete_shell_and_frontend_only_changes(self):
        first = self.build()
        manifest = json.loads((self.output / 'data/publication.json').read_text())
        required = set(build_site.PAGES) | {'assets/site.css', 'assets/vendor/chart.umd.min.js',
                    'assets/vendor/lucide.min.js', 'js/site-data.js', 'data/site_summary.json',
                    'site.webmanifest', 'favicon.svg', 'favicon.ico', 'apple-touch-icon.png',
                    'web-app-manifest-192x192.png'}
        self.assertTrue(required <= manifest['shellArtifacts'].keys())
        self.assertFalse({'models.json', 'current.json', 'data/model_catalog.json'} & manifest['shellArtifacts'].keys())
        for path, digest in manifest['shellArtifacts'].items():
            self.assertEqual(digest, hashlib.sha256((self.output / path).read_bytes()).hexdigest())
        serialized = json.dumps(manifest['shellArtifacts'], sort_keys=True, separators=(',', ':')).encode()
        self.assertEqual(manifest['shellRevision'], hashlib.sha256(serialized).hexdigest())
        self.assertEqual(first, self.build())
        self.write('assets/site.css', 'changed frontend')
        second = self.build()
        self.assertEqual(first['generationId'], second['generationId'])
        self.assertNotEqual(first['shellRevision'], second['shellRevision'])
        self.write('data/publication.json', json.dumps({'schemaVersion': 1, 'generationId': 'b' * 64}))
        third = self.build()
        self.assertNotEqual(second['generationId'], third['generationId'])

    def test_verifies_publication_by_default_before_building(self):
        with patch('prepare_publication.verify_installed', side_effect=ValueError('invalid publication')) as verify:
            with self.assertRaisesRegex(ValueError, 'invalid publication'):
                build_site.build_site(self.root, self.output)
        verify.assert_called_once_with(self.root.resolve())
        self.assertFalse(self.output.exists())

    def test_pending_writers_fail_without_replacing_existing_output(self):
        for journal in ('.publication-pending.json', '.model-store-pending.json'):
            with self.subTest(journal=journal):
                self.write(journal, '{}')
                self.output.mkdir(exist_ok=True)
                sentinel = self.output / 'sentinel'
                sentinel.write_text('keep')
                with self.assertRaisesRegex(ValueError, 'pending publication'):
                    self.build()
                self.assertEqual(sentinel.read_text(), 'keep')
                (self.root / journal).unlink()

    def test_unsafe_paths_symlinks_and_missing_files_fail_before_output_mutation(self):
        for path in ('../outside', '/tmp/outside'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                build_site.public_file(self.root, path)
        for slide in ('../outside.png', '/outside.png', 'nested/slide.png', 'private.json'):
            self.write('social/plan.json', json.dumps({'slides': [slide]}))
            with self.subTest(slide=slide), self.assertRaises(ValueError):
                self.build()
        self.write('social/plan.json', '{"slides": []}')
        target = self.root / 'assets/site.css'
        target.unlink()
        target.symlink_to(self.root / 'index.html')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.build()
        target.unlink()
        with self.assertRaisesRegex(ValueError, 'Missing required public asset'):
            build_site.public_file(self.root, 'assets/site.css')
        for output in (self.root, self.root.parent):
            with self.assertRaises(ValueError):
                build_site.build_site(self.root, output, verify=False)
