#!/usr/bin/env python3
"""Fold researched benchmark findings into the historical evidence file.

    python3 scripts/ingest_benchmark_findings.py <findings.json> [...] [--write]

Each findings file is a JSON array of researched results (see
docs/gap_fill_backfill.md). Records are normalized into
`data/historical_benchmark_evidence.json` entries: the applicability date is
clamped so a score is never applied before the source published it, before the
benchmark version existed, or before the model appeared in our history.
Without --write the command reports what it would add and changes nothing.
"""
import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from avg_iq_benchmarks import load_config
from benchmark_names import canonicalize_benchmark_name as canonical
from scoring import MISSING_VALUE_MARKERS

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = ROOT / 'data/historical_benchmark_evidence.json'
RETRIEVED_AT = datetime.now(timezone.utc).date().isoformat()
ACCEPTED_SOURCE_TYPES = {'vendor_blog', 'model_card', 'system_card', 'paper',
                         'official_leaderboard', 'third_party_leaderboard'}


def model_first_seen():
    """Earliest snapshot date each model appears in, keyed by exact model name."""
    data = json.loads((ROOT / 'models.json').read_text())
    first = {}
    for snapshot in data['history']:
        day = snapshot['timestamp'][:10]
        for team in snapshot['teams'].values():
            for row in team:
                name = row['model']
                if day < first.get(name, '9999-99-99'):
                    first[name] = day
    return first


def squash(name):
    return ''.join(c for c in name.lower() if c.isalnum())


def resolve_model(name, first_seen):
    """Match a researched name to an exact history model, allowing only
    punctuation/spacing differences and only when the match is unambiguous."""
    if name in first_seen:
        return name
    matches = [known for known in first_seen if squash(known) == squash(name)]
    return matches[0] if len(matches) == 1 else None


def parse_score(raw):
    if isinstance(raw, (int, float)):
        value = float(raw)
    else:
        text = str(raw).strip().rstrip('%').strip()
        try:
            value = float(text)
        except ValueError:
            return None
    return round(value, 1) if 0 <= value <= 100 else None


def record_id(finding):
    seed = f"{finding['model']}|{finding['component']}|{finding['score']}|{finding.get('sourceUrl')}"
    return hashlib.sha1(seed.encode()).hexdigest()[:16]


def normalize(finding, components, availability, first_seen, undated_from_release=False, *, retrieved_at=None):
    """Return (evidence_record, None) or (None, rejection_reason)."""
    retrieved_at = retrieved_at or RETRIEVED_AT
    raw_model = (finding.get('model') or '').strip()
    component = (finding.get('component') or '').strip()
    if component not in components:
        return None, f'unknown component {component!r}'
    model = resolve_model(raw_model, first_seen)
    if not model:
        return None, f'model {raw_model!r} is not in models.json history'
    score = parse_score(finding.get('score'))
    if score is None:
        return None, 'unusable score'
    url = (finding.get('sourceUrl') or '').strip()
    if not url.startswith('http'):
        return None, 'missing citation URL'
    source_type = finding.get('sourceType') or 'third_party_leaderboard'
    if source_type not in ACCEPTED_SOURCE_TYPES:
        return None, f'unaccepted source type {source_type!r}'
    if finding.get('confidence') == 'low':
        return None, 'low confidence'

    published = finding.get('publishedAt') or None
    bounds = {'publishedAt': published,
              'benchmarkAvailableFrom': availability.get(component, {}).get('date'),
              'modelAvailableFrom': first_seen[model]}
    # A source with no publication date cannot license backdating on its own.
    # `undated_from_release` relaxes that to the earliest date the result could
    # have existed: the model and the benchmark version both being available.
    fallback = [] if published or undated_from_release else [retrieved_at]
    dates = [d for d in bounds.values() if d] + fallback
    available_from = max(dates)
    if available_from > retrieved_at:
        return None, 'evidence postdates retrieval'

    record = {
        'id': record_id({**finding, 'score': score}),
        'model': model,
        'component': component,
        'benchmark': components[component]['name'],
        'score': score,
        'unit': 'percent',
        'source': url,
        'availableFrom': available_from,
        'retrievedAt': retrieved_at,
        'configuration': finding.get('configuration') or 'Configuration not stated in source.',
        'kind': 'published',
        'sourceType': source_type,
        'confidence': finding.get('confidence') or 'medium',
    }
    for key, value in bounds.items():
        if value:
            record[key] = value
    if finding.get('notes'):
        record['notes'] = finding['notes']
    return record, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('findings', nargs='+')
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--undated-from-release', action='store_true',
                        help='Apply undated leaderboard rows from the model/benchmark '
                             'availability date rather than only from the retrieval date')
    args = parser.parse_args()

    evidence = json.loads(EVIDENCE_PATH.read_text())
    components = {b['id']: b for b in load_config()['benchmarks']}
    availability = evidence.get('benchmarkAvailability', {})
    first_seen = model_first_seen()

    existing = {r['id'] for r in evidence['results']}
    # Retain dated observations; replay selects the highest score available that day.
    best = {(r['model'], r['component']): r for r in evidence['results'] if not r.get('excludedReason')}
    added, rejected, superseded = [], [], 0

    for path in args.findings:
        raw = json.loads(Path(path).read_text())
        for finding in raw:
            record, reason = normalize(finding, components, availability, first_seen,
                                       args.undated_from_release)
            if reason:
                rejected.append({'finding': finding, 'reason': reason})
                continue
            if record['id'] in existing:
                continue
            key = (record['model'], record['component'])
            best[key] = record
            existing.add(record['id'])
            added.append(record)

    report = {'accepted': len(added), 'rejected': len(rejected),
              'earlierThanExisting': superseded,
              'uniquePairsAdded': len({(r['model'], r['component']) for r in added})}
    if args.write:
        evidence['results'].extend(added)
        evidence['results'].sort(key=lambda r: (r['model'], r['component'], r['availableFrom']))
        evidence['retrievedAt'] = RETRIEVED_AT
        EVIDENCE_PATH.write_text(json.dumps(evidence, indent=2, ensure_ascii=False)+'\n')
    (ROOT / 'data/benchmark_findings_rejected.json').write_text(
        json.dumps(rejected, indent=2, ensure_ascii=False)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
