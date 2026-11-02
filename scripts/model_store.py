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
from datetime import datetime, timezone
from pathlib import Path

from avg_iq_benchmarks import MODEL_FIELDS, load_config
from benchmark_names import canonicalize_benchmark_name as canonical

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / 'data/model_catalog.json'
SCORES = {'avgIq', 'value', 'unified', 'coverage', 'provisional'}


@preconditions(timestamp='timestamp')
def utc_day(timestamp):
    parsed = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).date().isoformat()


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
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
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
                    cache[mid] = benchmark_columns(model, utc_day(snapshot['timestamp']))
                expanded.append({**copy.deepcopy(profile), **copy.deepcopy(cache[mid]),
                                 'modelId': mid, 'profileId': ref['profileId'],
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
        day = utc_day(snapshot['timestamp'])
        for country, rows in snapshot['teams'].items():
            refs = []
            for row in rows:
                if 'modelId' in row and 'model' not in row:
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


@preconditions(data='mapping')
def roster_identity(data):
    """Ordered snapshot membership and exact metadata, excluding computed cells."""
    return [(snapshot['timestamp'], [(country, [
        {key: copy.deepcopy(value) for key, value in row.items()
         if key in MODEL_FIELDS or key in ('modelId', 'profileId')}
        for row in rows]) for country, rows in snapshot['teams'].items()])
        for snapshot in data['history']]


@preconditions(data='mapping', path='path', catalog='?mapping')
def save_data(data, path, *, catalog=None):
    path = Path(path)
    catalog_path = path.parent / 'data/model_catalog.json'
    catalog = read_catalog(catalog_path) if catalog is None else catalog
    components = catalog.setdefault('components', [])
    known_components = {component['id'] for component in components}
    components.extend(dict(id=b['id'], name=b['name'], column=b['aliases'][0].replace(' ', ''))
                      for b in load_config()['benchmarks'] if b['id'] not in known_components)
    # Oldest first ensures an observation is stored once at its earliest retained date.
    ordered = copy.deepcopy(data)
    ordered['history'] = sorted(ordered['history'], key=lambda s: utc_day(s['timestamp']))
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


@preconditions(root='path', relative='nonempty')
def safe_store_path(root, relative):
    if relative not in ('.model-store-pending.json', 'data/model_catalog.json', 'models.json', 'current.json'):
        raise ValueError('Invalid model-store transaction path')
    root = Path(root).absolute()
    target = root / relative
    cursor = target
    while True:
        if cursor.is_symlink():
            raise ValueError('Model-store transaction path is a symlink: '+str(cursor))
        if cursor == root:
            break
        cursor = cursor.parent
    return target


@preconditions(transaction='mapping')
def validate_pending(transaction):
    if set(transaction) != {'catalog', 'history', 'current', 'historyFile'} or transaction['historyFile'] != 'models.json':
        raise ValueError('Invalid model-store pending transaction destinations')
    catalog, history, current = (transaction[key] for key in ('catalog', 'history', 'current'))
    if not all(isinstance(value, dict) for value in (catalog, history, current)):
        raise ValueError('Invalid model-store pending transaction payloads')
    if catalog.get('schemaVersion') != 1 or not isinstance(catalog.get('models'), dict) or not isinstance(catalog.get('evidenceMetadata'), dict):
        raise ValueError('Invalid pending model catalog')
    if history.get('schemaVersion') != 2 or history.get('modelCatalog') != 'data/model_catalog.json' or not isinstance(history.get('history'), list):
        raise ValueError('Invalid pending model history')
    if current != {**history, 'history': history['history'][:1]}:
        raise ValueError('Pending current roster disagrees with history')
    for model in catalog['models'].values():
        if not isinstance(model, dict) or not isinstance(model.get('profiles'), dict) or not isinstance(model.get('benchmarks'), dict):
            raise ValueError('Invalid pending catalog model')
        if any(not isinstance(profile, dict) for profile in model['profiles'].values()):
            raise ValueError('Invalid pending catalog profile')
        for records in model['benchmarks'].values():
            if not isinstance(records, dict) or any(not isinstance(record, dict) for record in records.values()):
                raise ValueError('Invalid pending benchmark observations')
    seen = set()
    for snapshot in history['history']:
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get('teams'), dict):
            raise ValueError('Invalid pending snapshot')
        timestamp = snapshot.get('timestamp')
        utc_day(timestamp)
        if timestamp in seen:
            raise ValueError('Duplicate pending snapshot timestamp')
        seen.add(timestamp)
        for rows in snapshot['teams'].values():
            if not isinstance(rows, list):
                raise ValueError('Invalid pending snapshot roster')
            for ref in rows:
                if not isinstance(ref, dict):
                    raise ValueError('Invalid pending model reference')
                model = catalog['models'].get(ref.get('modelId'))
                if model is None or ref.get('profileId') not in model['profiles']:
                    raise ValueError('Dangling pending model/profile reference')
    json.dumps(transaction, allow_nan=False)


@preconditions(root='path')
def recover_pending(root):
    root = Path(root)
    pending = safe_store_path(root, '.model-store-pending.json')
    if not pending.exists():
        return
    # Validate all destinations and the complete transaction before the first write.
    targets = [safe_store_path(root, name) for name in
               ('data/model_catalog.json', 'models.json', 'current.json')]
    transaction = json.loads(pending.read_text())
    if not isinstance(transaction, dict):
        raise ValueError('Invalid model-store pending transaction')
    validate_pending(transaction)
    for path, key in zip(targets, ('catalog', 'history', 'current')):
        atomic_json(path, transaction[key])
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
