"""Small, disposable projection of canonical rosters and computed scores."""
import copy
import hashlib
from datetime import datetime, timezone
from avg_iq_benchmarks import load_config
from model_store import SCORES, hydrate
from preconditions import preconditions
from scoring_revision import canonical_bytes, require_revision


@preconditions(timestamp='timestamp')
def timestamp_order(timestamp):
    parsed = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


@preconditions(snapshot='mapping')
def national_scores(snapshot):
    board = [(country, row) for country in ('US', 'CN')
             for row in snapshot['teams'].get(country, [])]
    board.sort(key=lambda pair: -float(pair[1]['unified']))
    result = {}
    for country in ('US', 'CN'):
        rows = [row for origin, row in board[:10] if origin == country]
        result[country] = {'total': sum(row['unified'] for row in rows), 'count': len(rows),
                           'avgIq': sum(row['avgIq'] for row in rows)/len(rows) if rows else 0,
                           'avgValue': sum(row['value'] for row in rows)/len(rows) if rows else 0}
    return result


@preconditions(raw='mapping', catalog='mapping', revision='nonempty', generation_id='nonempty')
def build_summary(raw, catalog, revision, generation_id):
    require_revision(raw, revision)
    if raw.get('schemaVersion') != 2:
        raise ValueError('Summary requires normalized model references')
    hydrated = hydrate(raw, catalog)
    ordered = sorted(zip(raw['history'], hydrated['history']), key=lambda pair: timestamp_order(pair[0]['timestamp']), reverse=True)
    latest, current = ordered[0]
    teams = {}
    for country in ('US', 'CN'):
        teams[country] = []
        for ref in latest['teams'].get(country, []):
            profile = catalog['models'][ref['modelId']]['profiles'][ref['profileId']]
            teams[country].append({**copy.deepcopy(profile), 'modelId': ref['modelId'],
                                   'profileId': ref['profileId'],
                                   **{key: copy.deepcopy(ref[key]) for key in SCORES if key in ref}})
    return {'schemaVersion': 1, 'scoringRevision': revision, 'generationId': generation_id,
            'catalogFingerprint': hashlib.sha256(canonical_bytes(catalog)).hexdigest(),
            'metadata': copy.deepcopy(raw.get('metadata', {})),
            'teams': copy.deepcopy(raw.get('teams', {})), 'columns': copy.deepcopy(raw.get('columns', [])),
            'benchmarks': [dict(id=b['id'], name=b['name'], column=b['aliases'][0].replace(' ', ''),
                                weight=b['weight']) for b in load_config()['benchmarks']],
            'current': {'timestamp': latest['timestamp'], 'scoring': copy.deepcopy(latest['scoring']), 'teams': teams},
            'history': [{'timestamp': snapshot['timestamp'], 'scoringRevision': revision,
                         'scores': national_scores(snapshot)} for _, snapshot in ordered]}
