"""Shared model records and reference-only dated rosters.

The catalog owns benchmark observations and metadata profiles. History owns
roster membership and derived, reproducible scores. Neither effort nor coverage
changes model identity. Readers hydrate date-applicable maxima for presentation.
"""
from preconditions import preconditions
import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path

from avg_iq_benchmarks import MODEL_FIELDS, load_config
from benchmark_names import canonicalize_benchmark_name as canonical

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / 'data/model_catalog.json'
SCORES = {'avgIq', 'value', 'unified', 'coverage', 'provisional'}


@preconditions(value='json')
def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


@preconditions()
def empty_catalog():
    return {'schemaVersion': 1, 'evidenceMetadata': {}, 'models': {}}


@preconditions(path='path')
def read_catalog(path=CATALOG_PATH):
    path = Path(path)
    recover_pending(path.parent.parent)
    return json.loads(path.read_text()) if path.exists() else empty_catalog()


@preconditions(path='path', data='json')
def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.'+path.name, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@preconditions(catalog='mapping', name='nonempty')
def model_record(catalog, name):
    key = identity(name)
    record = catalog['models'].setdefault(key, {'name': name, 'profiles': {}, 'benchmarks': {}})
    if record['name'] != name:
        raise ValueError('Model identity collision')
    return key, record


@preconditions(catalog='mapping', evidence='mapping')
def merge_evidence(catalog, evidence):
    catalog['evidenceMetadata'] = {k: copy.deepcopy(v) for k, v in evidence.items() if k != 'results'}
    # Replace observations by ID so corrections and exclusions propagate once.
    for result in evidence['results']:
        _, model = model_record(catalog, result['model'])
        records = model['benchmarks'].setdefault(result['component'], {})
        records[result['id']] = {k: copy.deepcopy(v) for k, v in result.items()
                                  if k not in ('model', 'component', 'id')}


@preconditions(catalog='mapping')
def catalog_evidence(catalog):
    evidence = copy.deepcopy(catalog.get('evidenceMetadata', {}))
    evidence['results'] = [dict(record, id=rid, model=model['name'], component=component)
        for model in catalog['models'].values()
        for component, records in model['benchmarks'].items() for rid, record in records.items()]
    return evidence


@preconditions(path='path')
def load_evidence(path=CATALOG_PATH):
    path = Path(path)
    if path.name == 'model_catalog.json':
        recover_pending(path.parent.parent)
    data = json.loads(Path(path).read_text())
    return catalog_evidence(data) if 'models' in data else data


@preconditions(evidence='mapping', path='path')
def save_evidence(evidence, path=CATALOG_PATH):
    from rescore_history import validate_evidence
    validate_evidence(evidence)
    path = Path(path)
    if path.name != 'model_catalog.json':  # Legacy fixtures / explicitly supplied evidence files.
        atomic_json(path, evidence)
        return
    catalog = read_catalog(path)
    for model in catalog['models'].values():
        model['benchmarks'] = {}
    merge_evidence(catalog, evidence)
    atomic_json(path, catalog)


@preconditions(model='mapping', day='date')
def benchmark_columns(model, day):
    columns, provenance = {}, {}
    for component in load_config()['benchmarks']:
        key = component['aliases'][0].replace(' ', '')
        candidates = [(rid, r) for rid, r in model['benchmarks'].get(component['id'], {}).items()
                      if not r.get('excludedReason') and r['availableFrom'] <= day]
        columns[key] = '—'
        if candidates:
            rid, result = min(candidates, key=lambda pair: (-pair[1]['score'], pair[1]['availableFrom'], pair[0]))
            columns[key] = f"{result['score']:g}%"
            provenance[key] = dict(type='historical-evidence', url=result['source'], evidenceId=rid,
                                   configuration=result['configuration'], availableFrom=result['availableFrom'],
                                   retrievedAt=result['retrievedAt'])
    columns['_provenance'] = provenance
    return columns


@preconditions(data='mapping', catalog='mapping')
def hydrate(data, catalog):
    if data.get('schemaVersion') != 2:
        return copy.deepcopy(data)
    result = copy.deepcopy(data)
    for snapshot in result['history']:
        cache = {}
        for country, rows in snapshot['teams'].items():
            expanded = []
            for ref in rows:
                mid = ref['modelId']
                model = catalog['models'][mid]  # Dangling references must fail loudly.
                profile = model['profiles'][ref['profileId']]
                if mid not in cache:
                    cache[mid] = benchmark_columns(model, snapshot['timestamp'][:10])
                expanded.append({**copy.deepcopy(profile), **copy.deepcopy(cache[mid]),
                                 **{k: v for k, v in ref.items() if k in SCORES}})
            snapshot['teams'][country] = expanded
    return result


@preconditions(path='path')
def load_data(path):
    path = Path(path)
    recover_pending(path.parent)
    data = json.loads(path.read_text())
    if data.get('schemaVersion') == 2:
        return hydrate(data, read_catalog(path.parent / data['modelCatalog']))
    return data


@preconditions(data='mapping', catalog='mapping')
def normalize(data, catalog):
    result = copy.deepcopy(data)
    result.update(schemaVersion=2, modelCatalog='data/model_catalog.json')
    components = load_config()['benchmarks']
    aliases = {canonical(a): b for b in components for a in b['aliases']}
    for snapshot in result['history']:
        day = snapshot['timestamp'][:10]
        for country, rows in snapshot['teams'].items():
            refs = []
            for row in rows:
                if 'modelId' in row:
                    raise ValueError('Normalize expects hydrated rows')
                mid, model = model_record(catalog, row['model'])
                # Unknown benchmark columns must not become permanent model metadata.
                profile = {k: v for k, v in row.items() if k in MODEL_FIELDS}
                pid = identity(profile)
                model['profiles'][pid] = profile
                for key, value in row.items():
                    component = aliases.get(canonical(key))
                    if not component:
                        continue
                    try:
                        score = float(str(value).rstrip('%'))
                    except (ValueError, TypeError):
                        continue
                    if not 0 <= score <= 100:
                        raise ValueError('Invalid benchmark percentage')
                    records = model['benchmarks'].setdefault(component['id'], {})
                    provenance = row.get('_provenance', {}).get(key, {})
                    # Already represented centrally; never duplicate it per day.
                    if any(not r.get('excludedReason') and r['score'] == score and r['availableFrom'] <= day
                           for r in records.values()):
                        continue
                    source = provenance.get('url') or row.get('link')
                    if not source:
                        raise ValueError('Retained benchmark lacks source/model URL')
                    rid = identity([mid, component['id'], score, source, day])
                    records[rid] = dict(benchmark=component['name'], score=score, unit='percent',
                        source=source, availableFrom=day, retrievedAt=day,
                        configuration=provenance.get('configuration') or 'Retained llm-stats snapshot; configuration not recorded.',
                        kind='retained-observation', sourceType='third_party_leaderboard',
                        notes='Observed in retained snapshot at '+snapshot['timestamp'])
                refs.append(dict(modelId=mid, profileId=pid, **{k: v for k, v in row.items() if k in SCORES}))
            snapshot['teams'][country] = refs
    return result


@preconditions(data='mapping', path='path', catalog='?mapping')
def save_data(data, path, *, catalog=None):
    path = Path(path)
    catalog_path = path.parent / 'data/model_catalog.json'
    catalog = read_catalog(catalog_path) if catalog is None else catalog
    catalog['components'] = [dict(id=b['id'], name=b['name'], column=b['aliases'][0].replace(' ', ''))
                             for b in load_config()['benchmarks']]
    # Oldest first ensures an observation is stored once at its earliest retained date.
    ordered = copy.deepcopy(data)
    ordered['history'] = sorted(ordered['history'], key=lambda s: s['timestamp'])
    normalized = normalize(ordered, catalog)
    by_timestamp = {s['timestamp']: s for s in normalized['history']}
    if len(by_timestamp) != len(data['history']):
        raise ValueError('Duplicate snapshot timestamp')
    normalized['history'] = [by_timestamp[s['timestamp']] for s in data['history']]
    current = {**normalized, 'history': normalized['history'][:1]}
    # A durable intent allows a later reader to finish any interrupted update.
    atomic_json(path.parent / '.model-store-pending.json', {
        'catalog': catalog, 'history': normalized, 'current': current,
        'historyFile': path.name,
    })
    recover_pending(path.parent)
    return normalized


@preconditions(root='path')
def recover_pending(root):
    root = Path(root)
    pending = root / '.model-store-pending.json'
    if not pending.exists():
        return
    transaction = json.loads(pending.read_text())
    history_name = transaction['historyFile']
    if Path(history_name).name != history_name or history_name in ('current.json', 'model_catalog.json'):
        raise ValueError('Invalid history filename in pending transaction')
    atomic_json(root / 'data/model_catalog.json', transaction['catalog'])
    atomic_json(root / history_name, transaction['history'])
    atomic_json(root / 'current.json', transaction['current'])
    pending.unlink()


@preconditions(path='path')
def migrate(path=ROOT / 'models.json'):
    path = Path(path)
    data = load_data(path)
    catalog = read_catalog(path.parent / 'data/model_catalog.json')
    legacy = path.parent / 'data/historical_benchmark_evidence.json'
    if legacy.exists():
        merge_evidence(catalog, json.loads(legacy.read_text()))
    result = save_data(data, path, catalog=catalog)
    if legacy.exists():
        legacy.unlink()
    print(f"Migrated {len(result['history'])} snapshots and {len(catalog['models'])} shared models")


if __name__ == '__main__':
    migrate()
