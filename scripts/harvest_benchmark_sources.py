#!/usr/bin/env python3
"""Harvest cross-vendor benchmark tables into researched-findings JSON.

    python3 scripts/harvest_benchmark_sources.py --out data/harvested_findings.json

Two machine-readable sources carry most models at once:

* Epoch AI's public dump (`https://epoch.ai/data/benchmark_data.zip`), whose
  GPQA Diamond and FrontierMath Tiers 1-3 v2 tables record the evaluation
  start timestamp; this is not a publication date and does not permit backdating.
* Artificial Analysis' model pages, which embed every model AA tracks in the
  Next.js payload with `gpqa`, `ifbench`, `mmmuPro` and `terminalbenchV21`.

For each exact model and selected benchmark, use the highest verified score
across reasoning-effort settings. Different components may use different effort
levels. Preserve release identity and reject mixed-model fallback configurations.
"""
from preconditions import preconditions
import argparse
import csv
import io
from model_store import load_data
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from benchmark_names import canonicalize_benchmark_name as canonical
from scoring import MISSING_VALUE_MARKERS

ROOT = Path(__file__).resolve().parents[1]
EPOCH_ZIP = 'https://epoch.ai/data/benchmark_data.zip'
AA_PAGE = 'https://artificialanalysis.ai/models/qwen3-6-plus'
USER_AGENT = 'Mozilla/5.0 (compatible; usvschinaai-benchmark-harvest/1.0)'

# AA payload field -> our component id. AA's `gpqa` is the Diamond subset.
AA_FIELDS = {'gpqa': 'gpqa-diamond', 'ifbench': 'ifbench',
             'mmmuPro': 'mmmu-pro', 'terminalbenchV21': 'terminal-bench-2.1'}
# Epoch CSV -> (component id, score column, evaluation-date column or None).
EPOCH_TABLES = {
    'gpqa_diamond.csv': ('gpqa-diamond', 'mean_score', 'Started at'),
    'frontiermath_tiers_1_3_v2.csv': ('frontiermath-1-3-v2', 'mean_score', 'Started at'),
    'arc_agi_2_external.csv': ('arc-agi-2', 'Score', None),
    'deepswe_external.csv': ('deepswe-1.1', 'Pass@1', None),
}
# Columns already scraped into models.json that can fingerprint an effort tier.
FINGERPRINT_COLUMNS = {'GPQA Diamond': 'gpqa', 'MMMU-Pro': 'mmmuPro', 'HLE': 'hle',
                       'IFBench': 'ifbench', 'Terminal-Bench 2.1': 'terminalbenchV21'}
MIN_FINGERPRINT_OVERLAP = 2
MAX_FINGERPRINT_DELTA = 1.5
EFFORT_TOKENS = ('minimal', 'low', 'medium', 'xhigh', 'high', 'max')


@preconditions(name='text')
def squash(name):
    return ''.join(c for c in name.lower() if c.isalnum())


@preconditions(name='text')
def strip_effort(name):
    """Strip only recognized effort settings, preserving release/variant identity."""
    qualifier = re.search(r'\s*\(([^)]*)\)\s*$', name)
    allowed = r'(?:(?:adaptive |non-)?reasoning|(?:minimal|low|medium|high|xhigh|max)(?: effort)?)'
    if qualifier and re.fullmatch(allowed + r'(?:,\s*' + allowed + r')*',
                                  qualifier[1], re.I):
        name = name[:qualifier.start()].strip()
    return re.sub(r'_(?:minimal|low|medium|high|xhigh|max)$', '', name)


@preconditions(label='text')
def effort_of(label):
    """The reasoning-effort token a source encodes in its variant label."""
    text = label.lower()
    qualifier = re.search(r'\(([^)]*)\)\s*$', text)
    text = qualifier.group(1) if qualifier else text.rsplit('_', 1)[-1]
    return next((token for token in EFFORT_TOKENS if token in text), None)


@preconditions(url='text', binary='bool')
def fetch(url, binary=False):
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = response.read()
    return payload if binary else payload.decode('utf-8', 'replace')


@preconditions()
def observed_values():
    """Benchmark values already recorded per model, keyed by canonical name."""
    data = load_data(ROOT / 'models.json')
    wanted = {canonical(name): field for name, field in FINGERPRINT_COLUMNS.items()}
    observed = {}
    for snapshot in data['history']:
        for team in snapshot['teams'].values():
            for row in team:
                seen = observed.setdefault(row['model'], {})
                for key, value in row.items():
                    field = wanted.get(canonical(key))
                    if not field or field in seen or value in MISSING_VALUE_MARKERS:
                        continue
                    try:
                        seen[field] = float(str(value).rstrip('%'))
                    except ValueError:
                        pass
    return observed


@preconditions(html='text')
def load_aa(html):
    """Pull every model record out of the Next.js streamed payload."""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, re.S)
    blob = ''.join(chunks).encode().decode('unicode_escape', 'replace')
    models = []
    for match in re.finditer(r'\{"id":"[0-9a-f-]{36}","slug":"', blob):
        start = match.start()
        depth = 0
        for index in range(start, min(len(blob), start + 20000)):
            if blob[index] == '{':
                depth += 1
            elif blob[index] == '}':
                depth -= 1
                if depth == 0:
                    try:
                        record = json.loads(blob[start:index + 1])
                    except ValueError:
                        break
                    if 'terminalbenchV21' in record:
                        models.append(record)
                    break
    return {record['name']: record for record in models}


@preconditions(names='iterable', our_models='sequence')
def group_by_model(names, our_models):
    """Map each of our model names to the source's variant labels for it."""
    groups = {}
    for name in names:
        groups.setdefault(squash(strip_effort(name)), []).append(name)
    resolved = {}
    for model in our_models:
        labels = groups.get(squash(model)) or groups.get(squash(strip_effort(model)))
        if labels:
            resolved[model] = labels
    return resolved


@preconditions(html='text', our_models='sequence', observed='mapping')
def harvest_aa(html, our_models, observed):
    records = load_aa(html)
    findings, skipped, efforts = [], [], {}
    for model, labels in group_by_model(records, our_models).items():
        for field, component in AA_FIELDS.items():
            available = [label for label in labels if isinstance(records[label].get(field), (int, float))]
            if not available:
                continue
            label = max(available, key=lambda label: records[label][field])
            entry = records[label]
            value = entry[field]
            findings.append({
                'model': model, 'component': component, 'score': round(value * 100, 1),
                'publishedAt': None,
                'sourceUrl': f"https://artificialanalysis.ai/models/{entry['slug']}",
                'sourceType': 'third_party_leaderboard', 'confidence': 'medium',
                'configuration': f"Artificial Analysis independent evaluation of {label}.",
                'notes': (f"AA record {entry['slug']}; highest verified result across effort settings for this "
                          f"exact model and benchmark. AA publishes no "
                          f"per-result evaluation date."),
            })
    return findings, skipped, efforts


@preconditions(tables='mapping', our_models='sequence', observed='mapping', efforts='?mapping')
def harvest_epoch(tables, our_models, observed, efforts=None):
    findings, skipped = [], []
    for filename, (component, score_column, date_column) in EPOCH_TABLES.items():
        rows = tables.get(filename)
        if not rows:
            continue
        by_version = {}
        for row in rows:
            by_version.setdefault(row['Model version'], []).append(row)
        for model, labels in group_by_model(by_version, our_models).items():
            candidates = {}
            for label in labels:
                best = max(by_version[label], key=lambda r: float(r.get(score_column) or -1))
                try:
                    candidates[label] = {'value': float(best[score_column]) * 100, 'row': best}
                except (TypeError, ValueError):
                    continue
            if not candidates:
                continue
            label, chosen = max(candidates.items(), key=lambda item: item[1]['value'])
            row = chosen['row']
            started = (row.get(date_column) or '')[:10] if date_column else None
            findings.append({
                'model': model, 'component': component, 'score': round(chosen['value'], 1),
                'publishedAt': None,
                'sourceUrl': 'https://epoch.ai/data/benchmark_data.zip',
                'sourceType': 'official_leaderboard', 'confidence': 'medium',
                'configuration': (f"Epoch AI evaluation of {label}"
                                  + (f"; harness {row['Harness']}" if row.get('Harness') else '')
                                  + (f"; evaluation started {started}" if started else
                                     '; Epoch publishes no evaluation date for this table')),
                'notes': f"Epoch AI benchmark dump, {filename}, row {label}.",
            })
    return findings, skipped


@preconditions()
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='data/harvested_findings.json')
    parser.add_argument('--epoch-zip', help='Use a previously downloaded dump instead of fetching')
    parser.add_argument('--aa-html', help='Use a previously downloaded AA page instead of fetching')
    args = parser.parse_args()

    our_models = sorted(observed_values())
    observed = observed_values()

    payload = Path(args.epoch_zip).read_bytes() if args.epoch_zip else fetch(EPOCH_ZIP, binary=True)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        tables = {}
        for name in archive.namelist():
            base = Path(name).name
            if base in EPOCH_TABLES:
                text = archive.read(name).decode('utf-8', 'replace')
                tables[base] = list(csv.DictReader(io.StringIO(text)))

    html = Path(args.aa_html).read_text(errors='replace') if args.aa_html else fetch(AA_PAGE)

    aa_findings, aa_skipped, efforts = harvest_aa(html, our_models, observed)
    epoch_findings, epoch_skipped = harvest_epoch(tables, our_models, observed, efforts)
    findings = epoch_findings + aa_findings

    Path(args.out).write_text(json.dumps(findings, indent=2, ensure_ascii=False)+'\n')
    Path(args.out).with_suffix('.skipped.json').write_text(
        json.dumps(epoch_skipped + aa_skipped, indent=2, ensure_ascii=False)+'\n')
    print(json.dumps({'epoch': len(epoch_findings), 'artificialAnalysis': len(aa_findings),
                      'skippedAmbiguous': len(epoch_skipped) + len(aa_skipped)}, indent=2))


if __name__ == '__main__':
    main()
