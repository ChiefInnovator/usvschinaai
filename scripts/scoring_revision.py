"""Content identity for the scoring program and dated publication inputs."""
import ast
import hashlib
import json
from pathlib import Path
from preconditions import preconditions

ROOT = Path(__file__).resolve().parents[1]
SCORING_ROOTS = ('scoring.py', 'avg_iq_benchmarks.py', 'benchmark_names.py',
                 'rescore_history.py', 'model_store.py', 'backfill_gap_fill.py', 'preconditions.py')
SOURCE_PATHS = ('models.json', 'current.json', 'data/model_catalog.json', 'data/core_benchmarks.json')


@preconditions(value='json')
def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


@preconditions(root='path')
def scoring_sources(root=ROOT):
    """Inventory imports at every nesting level, including deferred imports."""
    root = Path(root)
    scripts = root / 'scripts'
    pending = [scripts / name for name in (*SCORING_ROOTS, 'scoring_revision.py')]
    found = set()
    while pending:
        path = pending.pop()
        if path in found:
            continue
        if not path.is_file():
            raise ValueError('Missing scoring dependency: '+str(path))
        found.add(path)
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                local = scripts / (name.replace('.', '/')+'.py')
                package = scripts / name.replace('.', '/') / '__init__.py'
                if local.is_file():
                    pending.append(local)
                elif package.is_file():
                    pending.extend(package.parent.rglob('*.py'))
    found.add(scripts / 'requirements.txt')
    return sorted(path.relative_to(root).as_posix() for path in found)


@preconditions(root='path')
def revision_record(root=ROOT):
    root = Path(root)
    paths = ['data/core_benchmarks.json', *scoring_sources(root)]
    sources = {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths}
    return {'schemaVersion': 1, 'scoringRevision': hashlib.sha256(canonical_bytes(sources)).hexdigest(),
            'sources': sources}


@preconditions(root='path')
def scoring_revision(root=ROOT):
    return revision_record(root)['scoringRevision']


@preconditions(root='path', revision='nonempty')
def generation_id(root, revision):
    root = Path(root)
    sources = {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in SOURCE_PATHS}
    return hashlib.sha256(canonical_bytes({'scoringRevision': revision, 'sources': sources})).hexdigest()


@preconditions(data='mapping', revision='nonempty')
def require_revision(data, revision):
    if data.get('scoringRevision') != revision or not data.get('history'):
        raise ValueError('Missing or stale scoring revision; run prepare_publication.py --write')
    if any((s.get('scoring') or {}).get('revision') != revision for s in data['history']):
        raise ValueError('History contains missing or stale scoring revisions; full replay required')
