#!/usr/bin/env python3
"""Replay all selected historical cohorts from evidence, without score archives.

    python3 scripts/rescore_history.py --write

Without --write, validates and reports without modifying application data.
"""
from preconditions import preconditions
import argparse
import copy
from model_store import load_data, load_evidence, save_data
import json
from datetime import date, datetime
from pathlib import Path

from avg_iq_benchmarks import load_config, selected_columns
from benchmark_names import canonicalize_benchmark_name as canonical
from backfill_gap_fill import ScoreEntry, scoring_headers, recompute_badges
from scoring import (MISSING_VALUE_MARKERS, MIN_COHORT_PARTICIPATION,
                     build_benchmark_participation, score_avg_iq_cohort)

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = ROOT / 'data/model_catalog.json'


@preconditions(snapshot='mapping')
def rows(snapshot):
    return [(country, row) for country, team in snapshot['teams'].items() for row in team]


@preconditions(row='mapping', component='mapping')
def component_key(row, component):
    aliases = {canonical(a) for a in component['aliases']}
    keys = [k for k in row if canonical(k) in aliases]
    # Same ingestion rule: existing reported cell wins; never maximize results.
    return next((k for k in keys if row[k] not in MISSING_VALUE_MARKERS),
                keys[0] if keys else component['aliases'][0].replace(' ', ''))


@preconditions(evidence='mapping')
def validate_evidence(evidence):
    ids = {b['id'] for b in load_config()['benchmarks']}
    seen = set()
    for record in evidence['results']:
        if record['id'] in seen:
            raise ValueError('Duplicate evidence ID: '+record['id'])
        seen.add(record['id'])
        if record['component'] not in ids or not record['model'] or not record['source'] or not record['configuration']:
            raise ValueError('Incomplete benchmark evidence')
        if not isinstance(record['score'], (int, float)) or not 0 <= record['score'] <= 100 or record['unit'] != 'percent':
            raise ValueError('Invalid percentage result')
        available = date.fromisoformat(record['availableFrom'])
        if available > date.fromisoformat(record['retrievedAt']):
            raise ValueError('Evidence predates retrieval')
        for key in ('publishedAt', 'benchmarkAvailableFrom', 'modelAvailableFrom'):
            if record.get(key) and available < date.fromisoformat(record[key]):
                raise ValueError('Historical applicability precedes '+key)


@preconditions(evidence='mapping')
def index_evidence(evidence):
    indexed = {}
    for record in sorted(evidence['results'], key=lambda r: (-r['score'], r['availableFrom'], r['id'])):
        if not record.get('excludedReason'):
            indexed.setdefault(record['model'], []).append(record)
    return indexed


@preconditions(snapshot='mapping', evidence='mapping', indexed='?mapping')
def apply_evidence(snapshot, evidence, *, indexed=None):
    components = {b['id']: b for b in load_config()['benchmarks']}
    added = []
    day = snapshot['timestamp'][:10]
    indexed = index_evidence(evidence) if indexed is None else indexed
    for _, row in rows(snapshot):
        for record in indexed.get(row['model'], ()):
            if record.get('excludedReason') or row['model'] != record['model'] or day < record['availableFrom']:
                continue
            key = component_key(row, components[record['component']])
            current = row.get(key, '')
            if current not in MISSING_VALUE_MARKERS and float(str(current).rstrip('%')) >= record['score']:
                continue
            # Highest date-applicable verified score, regardless of effort.
            row[key] = f"{record['score']:g}%"
            row.setdefault('_provenance', {})[key] = {
                'type': 'historical-evidence', 'url': record['source'],
                'evidenceId': record['id'], 'configuration': record['configuration'],
                'availableFrom': record['availableFrom'], 'retrievedAt': record['retrievedAt'],
            }
            added.append((row['model'], record['component']))
    return added


@preconditions(entries='sequence', timestamp='timestamp', evidence='?mapping')
def fill_current_entries(entries, timestamp, evidence=None):
    """Reuse validated findings for exact models on or after their evidence dates."""
    if evidence is None:
        evidence = load_evidence(EVIDENCE_PATH)
    validate_evidence(evidence)
    proxies = [{**entry.columns, 'model': entry.name} for entry in entries]
    snapshot = {'timestamp': timestamp, 'teams': {'cohort': proxies}}
    apply_evidence(snapshot, evidence)
    new_headers = []
    for entry, row in zip(entries, proxies):
        for key, value in row.items():
            if key == 'model':
                continue
            if key not in entry.columns and not key.startswith('_'):
                new_headers.append(key)
            entry.columns[key] = value
    return list(dict.fromkeys(new_headers))


@preconditions(parameters='mapping', headers='sequence')
def normalize_parameters(parameters, headers):
    """Daily serialization removes spaces from row keys, but not parameter keys."""
    by_canonical = {canonical(h): h for h in headers}
    def key(name):
        if name in headers:
            return name
        squashed = name.replace(' ', '')
        return squashed if squashed in headers else by_canonical.get(canonical(name), squashed)
    result = copy.deepcopy(parameters)
    result['qualified'] = [key(b) for b in parameters['qualified']] if parameters.get('qualified') else None
    result['benchmarkRanges'] = {key(b): rng for b, rng in parameters.get('benchmarkRanges', {}).items()}
    return result


@preconditions(snapshot='mapping', evidence='mapping', indexed='?mapping')
def rescore_snapshot(snapshot, evidence, *, indexed=None):
    for _, row in rows(snapshot):
        clean = selected_columns(row)
        row.clear()
        row.update(clean)
    added = apply_evidence(snapshot, evidence, indexed=indexed)
    entries = [ScoreEntry(row, country) for country, row in rows(snapshot)]
    result = score_avg_iq_cohort(entries, log=lambda *a: None)
    for entry in entries:
        entry.row.update(result.scores_for(entry))
        n, q = result.coverage(entry)
        entry.row['coverage'] = f'{n}/{q}' if q else ''
        # Coverage remains informational; no model is provisional for sparse data.
        entry.row['provisional'] = False
        entry.row.pop('_prior', None)
    snapshot['scoring'] = result.to_snapshot()
    return added


@preconditions(history='sequence')
def audit_gaps(history):
    gaps = {}
    components = load_config()['benchmarks']
    for snapshot in history:
        for _, row in rows(snapshot):
            for component in components:
                key = component_key(row, component)
                if row.get(key, '') in MISSING_VALUE_MARKERS:
                    pair = (row['model'], component['id'])
                    gaps.setdefault(pair, set()).add(snapshot['timestamp'][:10])
    return gaps


@preconditions(model='text', component='text', days='set', evidence='mapping')
def unresolved_record(model, component, days, evidence):
    known = [r['availableFrom'] for r in evidence['results']
             if r['model'] == model and r['component'] == component]
    first_evidence = min(known) if known else None
    release = evidence.get('benchmarkAvailability', {}).get(component, {}).get('date')
    before_release = sum(day < release for day in days) if release else 0
    before_evidence = sum(day < first_evidence for day in days) if first_evidence else 0
    reason = ('Available evidence starts on '+first_evidence+'; earlier applicability is unverified.'
              if first_evidence else 'No exact, date-applicable result verified in retained evidence or bounded primary-source research.')
    if before_release:
        reason += f' Benchmark version unavailable on {before_release} of these days (released {release}).'
    return {'model': model, 'component': component, 'days': len(days),
            'firstDate': min(days), 'lastDate': max(days), 'reason': reason,
            'beforeBenchmarkReleaseDays': before_release, 'beforeAvailableEvidenceDays': before_evidence}


@preconditions(data='mapping', evidence='mapping', rebuild='bool')
def replay(data, evidence, *, rebuild=False):
    validate_evidence(evidence)
    if rebuild:
        for snapshot in data['history']:
            snapshot.pop('scoring', None)
            for _, row in rows(snapshot):
                clean = selected_columns(row, rebuild=True)
                row.clear()
                row.update(clean)
    before = audit_gaps(data['history'])
    filled = []
    indexed = index_evidence(evidence)
    for snapshot in data['history']:
        filled.extend(rescore_snapshot(snapshot, evidence, indexed=indexed))
    recompute_badges(data)
    data.setdefault('metadata', {})['avgIqBenchmarks'] = [b['name'] for b in load_config()['benchmarks']]
    data['metadata']['footerText'] = 'Avg IQ: eighteen configured benchmark weights; missing results count as zero. Source: llm-stats and verified benchmark evidence.'
    after = audit_gaps(data['history'])
    dates = sorted({s['timestamp'][:10] for s in data['history']})
    return {'firstDate': dates[0], 'lastDate': dates[-1], 'calendarDays': len(dates),
            'snapshots': len(data['history']), 'uniqueMissingPairsBefore': len(before),
            'uniquePairsWithFills': len(set(filled)), 'cellsFilled': len(filled),
            'uniqueMissingPairsAfter': len(after),
            'fullyResolvedPairs': len(set(before)-set(after)),
            'unresolved': [unresolved_record(model, component, days, evidence)
                           for (model, component), days in sorted(after.items())]}



@preconditions(data='mapping')
def refresh_images(data):
    """Regenerate existing image exports without editing templates or publishing."""
    from generate_og_image import (load_scores, load_top10_models, load_news_items,
                                   build_html, build_ig_html, screenshot_html, compress_png)
    from social_formats import plan_today, build_chart_facts
    from social_caption import fallback_caption, render_caption
    from social_render import fill, render_png
    from social_publish import slides_for, slide_filename, SITE
    scores = load_scores(ROOT / 'models.json')
    screenshot_html(build_html(scores, load_news_items(ROOT / 'news.json'), ROOT / 'scripts/og-template.html'),
                    ROOT / 'og-image.png', 1200, 630)
    compress_png(ROOT / 'og-image.png')
    screenshot_html(build_ig_html(scores, load_top10_models(ROOT / 'models.json'), ROOT / 'scripts/ig-template.html'),
                    ROOT / 'ig-image.png', 1080, 1350)
    compress_png(ROOT / 'ig-image.png')
    when = datetime.fromisoformat(data['history'][0]['timestamp'])
    plan = plan_today(data, today=when)
    facts = plan['facts']
    charts = build_chart_facts(data, today=when)
    path = ROOT / 'social/plan.json'
    previous = json.loads(path.read_text()) if path.exists() else {}
    names = []
    for i, (fmt, palette) in enumerate(slides_for(plan['format'], plan['palette']), 1):
        name = slide_filename(facts['date'], i, fmt, palette)
        render_png(fill(fmt, palette, facts, charts), ROOT / 'social' / name)
        names.append(name)
    record = {key: plan[key] for key in ('format', 'palette', 'weight')}
    record.update(date=facts['date'], timestamp=facts['timestamp'], slides=names,
                  urls=[f'{SITE}/social/{name}' for name in names],
                  caption=render_caption(fallback_caption(facts, plan['format'])),
                  caption_source='deterministic', generated_at=when.isoformat())
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False)+'\n')
    for name in previous.get('slides', []):
        if name not in names and Path(name).name == name:
            (ROOT / 'social' / name).unlink(missing_ok=True)
    (ROOT / 'data/social_caption_cache.json').write_text('{}\n')


@preconditions()
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--rebuild', action='store_true', help='Clear all old benchmark and derived scores, then rebuild from dated evidence')
    parser.add_argument('--refresh-images', action='store_true', help='With --write, regenerate existing image exports using installed Playwright/Pillow')
    args = parser.parse_args()
    if args.refresh_images and not args.write:
        parser.error('--refresh-images requires --write')
    data = load_data(ROOT / 'models.json')
    evidence = load_evidence(EVIDENCE_PATH)
    report = replay(data, evidence, rebuild=args.rebuild)
    if args.write:
        save_data(data, ROOT / 'models.json')
        # Audit contains missing evidence only, never old calculated scores.
        (ROOT / 'data/historical_benchmark_gaps.json').write_text(json.dumps(report['unresolved'], indent=2)+'\n')
    if args.refresh_images:
        refresh_images(data)
    print(json.dumps({k: v for k, v in report.items() if k != 'unresolved'}, indent=2))


if __name__ == '__main__':
    main()
