"""Versioned inputs for Avg IQ; unrelated benchmark records stay untouched."""
import json
import math
from functools import lru_cache
from pathlib import Path
from benchmark_names import canonicalize_benchmark_name as canonical

CONFIG_PATH = Path(__file__).resolve().parents[1] / 'data/core_benchmarks.json'


@lru_cache(maxsize=1)
def load_config():
    config = json.loads(CONFIG_PATH.read_text())
    benchmarks = config['benchmarks']
    if len(benchmarks) != 19 or not math.isclose(sum(b['weight'] for b in benchmarks), 100, rel_tol=0, abs_tol=1e-9) or any(not math.isfinite(b['weight']) or b['weight'] <= 0 for b in benchmarks) or config.get('denominator') != 1.0 or config.get('missingContribution') != 0:
        raise ValueError('Avg IQ requires nineteen benchmark weights totaling 100%')
    aliases = {}
    for b in benchmarks:
        for alias in b['aliases']:
            key = canonical(alias)
            if key in aliases and aliases[key] != b['id']:
                raise ValueError('Ambiguous benchmark alias: '+alias)
            aliases[key] = b['id']
    return config


def selected_weights(headers, config=None):
    config = config or load_config()
    aliases = {canonical(a): b['weight'] for b in config['benchmarks'] for a in b['aliases']}
    # Ingestion's established canonicalization identifies punctuation aliases.
    # Do not invent generic/version equivalences here.
    return {header: aliases[canonical(header)]/100 for header in headers if canonical(header) in aliases}


@lru_cache(maxsize=128)
def component_aliases(header):
    for component in load_config()['benchmarks']:
        keys = frozenset(canonical(a) for a in component['aliases'])
        if canonical(header) in keys:
            return keys
    return frozenset()


def selected_value(columns, header):
    """Resolve one configured component using ingestion's first-present rule."""
    from scoring import MISSING_VALUE_MARKERS
    value = columns.get(header, '')
    if value not in MISSING_VALUE_MARKERS:
        return value
    keys = component_aliases(header)
    for key, value in columns.items():
        if canonical(key) in keys and value not in MISSING_VALUE_MARKERS:
            return value
    return ''


# Model identity, pricing and descriptive fields needed by the existing UI.
# Benchmark/category/composite scores are deliberately absent.
MODEL_FIELDS = frozenset({
    'model', 'organization', 'link', 'origin', 'description', 'created',
    'Model', 'Country', 'License', 'Context', 'Input$/M', 'Output$/M',
    'Input $/M', 'Output $/M', 'Speed', 'Parameters(B)', 'Parameters (B)',
    'KnowledgeCutoff', 'Knowledge Cutoff', 'Multimodal', 'Released',
    'Organization', 'Latency', 'llm-stats ranking',
})
DERIVED_FIELDS = frozenset({'avgIq', 'value', 'unified', 'coverage', 'provisional', '_coverage'})


def selected_columns(columns, *, rebuild=False):
    """Drop legacy benchmark inputs; optionally clear all scores for rebuilding."""
    result = {k: v for k, v in columns.items() if k in MODEL_FIELDS}
    if rebuild:
        return result
    result.update({k: v for k, v in columns.items() if k in DERIVED_FIELDS})
    provenance = columns.get('_provenance') or {}
    kept_provenance = {}
    for component in load_config()['benchmarks']:
        header = component['aliases'][0].replace(' ', '')
        result[header] = selected_value(columns, header) or '—'
        aliases = {canonical(a) for a in component['aliases']}
        for key, details in provenance.items():
            if canonical(key) in aliases:
                kept_provenance[header] = details
                break
    if kept_provenance:
        result['_provenance'] = kept_provenance
    return result
