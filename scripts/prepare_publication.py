#!/usr/bin/env python3
"""Prepare an isolated, reproducible publication (--write), or verify by full replay."""
import argparse
import base64
import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
from preconditions import preconditions
from scoring_revision import SOURCE_PATHS, canonical_bytes, generation_id, require_revision, scoring_revision

ROOT = Path(__file__).resolve().parents[1]
JOURNAL = '.publication-pending.json'
MANIFEST = 'data/publication.json'
JSON_OUTPUTS = (*SOURCE_PATHS, 'data/scoring_revision.json', 'data/historical_benchmark_gaps.json',
                'data/site_summary.json', 'data/social_caption_cache.json', 'social/plan.json')
FIXED_OUTPUTS = frozenset((*JSON_OUTPUTS, 'og-image.png', 'ig-image.png', MANIFEST))
INPUTS = (*SOURCE_PATHS, 'news.json', 'data/social_history.jsonl', 'social/plan.json')


@preconditions(path='nonempty')
def allowed_path(path):
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or '..' in parsed.parts or str(parsed) != path or '\\' in path:
        raise ValueError('Invalid publication path: '+path)
    if path not in FIXED_OUTPUTS and not re.fullmatch(r'social/\d{4}-\d{2}-\d{2}-[A-Za-z0-9_-]+\.png', path):
        raise ValueError('Path is outside publication allowlist: '+path)
    return path


@preconditions(root='path', path='nonempty')
def source_path(root, path):
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or '..' in parsed.parts or str(parsed) != path or '\\' in path:
        raise ValueError('Invalid staging input path: '+path)
    root = Path(root)
    target = root / path
    cursor = target
    while cursor != root:
        if cursor.is_symlink():
            raise ValueError('Publication destination is a symlink: '+str(cursor))
        cursor = cursor.parent
    return target


@preconditions(root='path', path='nonempty')
def destination(root, path):
    allowed_path(path)
    return source_path(root, path)


@preconditions(root='path', path='nonempty')
def file_digest(root, path):
    return hashlib.sha256(destination(root, path).read_bytes()).hexdigest()


@preconditions(path='path', payload='nonempty')
def atomic_bytes(path, payload):
    """Payload is base64 so both contracts and journal validation cover exact bytes."""
    path = Path(path)
    content = base64.b64decode(payload, validate=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.'+path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


@preconditions(root='path')
def recover_publication(root=ROOT):
    root = Path(root)
    journal = root / JOURNAL
    if journal.is_symlink():
        raise ValueError('Publication journal is a symlink')
    if not journal.exists():
        return
    transaction = json.loads(journal.read_text())
    if transaction.get('schemaVersion') != 1 or not isinstance(transaction.get('artifacts'), dict):
        raise ValueError('Invalid publication journal')
    artifacts = transaction['artifacts']
    if MANIFEST not in artifacts:
        raise ValueError('Publication journal has no manifest')
    decoded = {}
    for path, entry in artifacts.items():
        destination(root, path)
        content = base64.b64decode(entry['bytes'], validate=True)
        if hashlib.sha256(content).hexdigest() != entry['sha256']:
            raise ValueError('Publication journal digest mismatch: '+path)
        decoded[path] = content
    manifest = json.loads(decoded[MANIFEST])
    if manifest.get('schemaVersion') != 1 or set(manifest['artifacts']) != set(artifacts)-{MANIFEST}:
        raise ValueError('Publication journal manifest inventory mismatch')
    for path, digest in manifest['artifacts'].items():
        if digest != artifacts[path]['sha256']:
            raise ValueError('Publication manifest digest mismatch: '+path)
    for path in sorted(set(artifacts)-{MANIFEST})+[MANIFEST]:
        atomic_bytes(destination(root, path), artifacts[path]['bytes'])
    journal.unlink()


@preconditions(root='path')
def verify_installed(root=ROOT):
    """Cheap build gate; full replay is performed by prepare(), independently."""
    root = Path(root)
    if (root / JOURNAL).exists():
        raise ValueError('Pending publication must be recovered before building')
    manifest = json.loads(destination(root, MANIFEST).read_text())
    revision = scoring_revision(root)
    if manifest.get('schemaVersion') != 1 or manifest.get('scoringRevision') != revision:
        raise ValueError('Publication scoring revision is missing or stale')
    artifacts = manifest.get('artifacts', {})
    required = set(SOURCE_PATHS) | {'data/scoring_revision.json', 'data/site_summary.json',
                                  'data/historical_benchmark_gaps.json', 'social/plan.json',
                                  'data/social_caption_cache.json', 'og-image.png', 'ig-image.png'}
    if not required <= set(artifacts) or MANIFEST in artifacts:
        raise ValueError('Incomplete publication artifact inventory')
    for path, digest in artifacts.items():
        if file_digest(root, path) != digest:
            raise ValueError('Publication artifact digest mismatch: '+path)
    models = json.loads((root / 'models.json').read_text())
    current = json.loads((root / 'current.json').read_text())
    require_revision(models, revision)
    require_revision(current, revision)
    if current != {**models, 'history': models['history'][:1]}:
        raise ValueError('Current roster disagrees with canonical latest snapshot')
    from validate_models import score_errors
    if score_errors(models):
        raise ValueError('Invalid historical computed scores')
    record = json.loads((root / 'data/scoring_revision.json').read_text())
    from scoring_revision import revision_record
    if record != revision_record(root):
        raise ValueError('Scoring revision record does not match source inventory')
    generation = generation_id(root, revision)
    summary = json.loads((root / 'data/site_summary.json').read_text())
    if manifest.get('generationId') != generation or summary.get('generationId') != generation or summary.get('scoringRevision') != revision:
        raise ValueError('Summary and publication generation disagree')
    catalog = json.loads((root / 'data/model_catalog.json').read_text())
    if summary.get('catalogFingerprint') != hashlib.sha256(canonical_bytes(catalog)).hexdigest():
        raise ValueError('Summary catalog fingerprint mismatch')
    plan = json.loads((root / 'social/plan.json').read_text())
    for name in plan['slides']:
        if Path(name).name != name or 'social/'+name not in artifacts:
            raise ValueError('Social plan references an unpublished slide')
    return manifest


@preconditions(root='path', stage='path', render_images='bool')
def copy_inputs(root, stage, render_images):
    root, stage = Path(root), Path(stage)
    scripts = source_path(root, 'scripts')
    for path in scripts.rglob('*'):
        if path.is_symlink():
            raise ValueError('Staging script input is a symlink: '+str(path))
    shutil.copytree(scripts, stage / 'scripts', ignore=shutil.ignore_patterns(
        '.*', '__pycache__', '*.pyc', '*.tmp', '*.bak', '*.log', '*.pem', '*.key', '*.p12', '*.pfx'))
    for path in INPUTS:
        source = source_path(root, path)
        if path in SOURCE_PATHS and not source.is_file():
            raise ValueError('Missing canonical source: '+path)
        if source.exists():
            target = stage / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    (stage / 'social').mkdir(exist_ok=True)
    if not render_images:
        plan = json.loads(source_path(root, 'social/plan.json').read_text())
        for path in ('og-image.png', 'ig-image.png', *('social/'+name for name in plan['slides'])):
            target = destination(stage, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(destination(root, path), target)
        cache = source_path(root, 'data/social_caption_cache.json')
        if cache.exists():
            shutil.copyfile(cache, stage / 'data/social_caption_cache.json')


@preconditions(root='path', render_images='bool')
def build_staged(root, render_images):
    root = Path(root)
    command = [sys.executable, str(root / 'scripts/rescore_history.py'), '--write', '--rebuild']
    if render_images:
        command.append('--refresh-images')
    subprocess.run(command, cwd=root, check=True)
    # No research or publishing entry point is invoked by this command.
    subprocess.run([sys.executable, str(root / 'scripts/validate_models.py')], cwd=root, check=True)
    revision = scoring_revision(root)
    generation = generation_id(root, revision)
    plan = json.loads((root / 'social/plan.json').read_text())
    paths = set(JSON_OUTPUTS) | {'og-image.png', 'ig-image.png'} | {'social/'+name for name in plan['slides']}
    manifest = {'schemaVersion': 1, 'generationId': generation, 'scoringRevision': revision,
                'artifacts': {path: file_digest(root, path) for path in sorted(paths)}}
    from model_store import atomic_json
    atomic_json(root / MANIFEST, manifest)
    verify_installed(root)
    return manifest


@preconditions(root='path', stage='path', manifest='mapping')
def install_staged(root, stage, manifest):
    root, stage = Path(root), Path(stage)
    paths = sorted(manifest['artifacts'])+[MANIFEST]
    artifacts = {}
    for path in paths:
        destination(root, path)
        content = destination(stage, path).read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if path != MANIFEST and digest != manifest['artifacts'][path]:
            raise ValueError('Staged artifact changed before installation: '+path)
        artifacts[path] = {'sha256': digest, 'bytes': base64.b64encode(content).decode('ascii')}
    from model_store import atomic_json
    atomic_json(root / JOURNAL, {'schemaVersion': 1, 'artifacts': artifacts})
    recover_publication(root)


@preconditions(root='path', write='bool')
def prepare(root=ROOT, *, write=False):
    root = Path(root)
    recover_publication(root)
    from model_store import recover_pending
    recover_pending(root)
    with tempfile.TemporaryDirectory(prefix='usvschinaai-publication-', dir='/tmp') as temporary:
        stage = Path(temporary)
        copy_inputs(root, stage, write)
        command = [sys.executable, str(stage / 'scripts/prepare_publication.py'), '--stage']
        if write:
            command.append('--images')
        subprocess.run(command, cwd=stage, check=True)
        manifest = json.loads((stage / MANIFEST).read_text())
        if write:
            install_staged(root, stage, manifest)
        else:
            differences = []
            for path in JSON_OUTPUTS:
                installed = json.loads((root / path).read_text())
                replayed = json.loads((stage / path).read_text())
                if installed != replayed:
                    differences.extend(difflib.unified_diff(
                        json.dumps(installed, sort_keys=True, indent=2).splitlines(True),
                        json.dumps(replayed, sort_keys=True, indent=2).splitlines(True),
                        fromfile='installed/'+path, tofile='replayed/'+path))
            if differences:
                descriptor, report = tempfile.mkstemp(prefix='usvschinaai-stale-', suffix='.diff', dir='/tmp')
                with os.fdopen(descriptor, 'w') as stream:
                    stream.writelines(differences)
                raise ValueError('Full replay differs from installed publication; diff: '+report)
            verify_installed(root)
        return manifest


@preconditions()
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--stage', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--images', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    manifest = build_staged(ROOT, args.images) if args.stage else prepare(ROOT, write=args.write)
    print('Verified publication '+manifest['generationId'])


if __name__ == '__main__':
    main()
