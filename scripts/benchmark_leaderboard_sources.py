"""Exact-version leaderboard adapters for the selected benchmark audit/refresh."""
from preconditions import preconditions
import json
import math
from html.parser import HTMLParser
from ingest_benchmark_findings import resolve_model
from harvest_benchmark_sources import strip_effort


@preconditions(payload='mapping', models='mapping')
def ale_results(payload, models):
    """Use the full ALE pass rate, never partial-credit avgScore or a sub-split."""
    findings = []
    for row in payload['rows']:
        if row.get('split') != 'full':
            continue
        model = resolve_model(row.get('model', ''), models)
        score = row.get('passRate')
        if not model or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
            continue
        config = f"Full ALE pass rate; {row.get('harness')}; {row.get('harnessVariant')}; {row.get('splitTasks')} split tasks."
        if 'fallback' in config.lower():
            continue
        findings.append(dict(model=model, component='agents-last-exam', score=100*score,
            sourceUrl='https://agents-last-exam.org/api/demo/leaderboard',
            sourceType='official_leaderboard', confidence='high', publishedAt=None,
            configuration=config, notes='Undated API observation; partial-credit avgScore excluded.'))
    return findings

VALS_SOURCES = {
    'mmlu_pro': ('mmlu-pro', 'MMLU Pro', 'overall', '5-shot chain-of-thought; overall mean across 14 subjects'),
    'aime': ('aime-2025', 'AIME', 'aime_2025', '2025 questions only; pass@1 averaged over eight runs'),
    'lcb': ('livecodebench-v6', 'LiveCodeBench', 'overall', 'v6 code generation; overall accuracy, not an easy/medium/hard subset'),
    'swebench': ('swe-bench-verified', 'SWE-bench', 'overall', '500 Verified tasks; minimal bash-only agent harness'),
    'gpqa': ('gpqa-diamond', 'GPQA Diamond', 'overall', 'Diamond subset; overall accuracy'),
    'terminal-bench-2-1': ('terminal-bench-2.1', 'Terminal-Bench 2.1', 'overall', 'version 2.1; overall accuracy'),
}


@preconditions(value='json')
def decode_astro(value):
    if isinstance(value, list):
        if len(value) == 2 and isinstance(value[0], int) and value[0] in (0, 1):
            return decode_astro(value[1])
        return [decode_astro(v) for v in value]
    if isinstance(value, dict):
        return {k: decode_astro(v) for k, v in value.items()}
    return value


class ValsProps(HTMLParser):
    @preconditions()
    def __init__(self):
        super().__init__(); self.view = None

    @preconditions(tag='text', attrs='sequence')
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'astro-island' and 'BenchmarkView.' in attrs.get('component-url', ''):
            self.view = decode_astro(json.loads(attrs['props']))['benchmarkView']


@preconditions(html='text', slug='text', models='mapping')
def vals_results(html, slug, models):
    component, expected, task, protocol = VALS_SOURCES[slug]
    parser = ValsProps(); parser.feed(html)
    view = parser.view
    if not view or view.get('metadata', {}).get('benchmark') != expected:
        raise ValueError('Vals benchmark identity or payload changed: ' + slug)
    if slug == 'lcb' and '(v6)' not in html:
        raise ValueError('LiveCodeBench v6 confirmation absent')
    scores = view.get('tasks', {}).get(task)
    if not isinstance(scores, dict):
        raise ValueError('Exact Vals task unavailable: ' + task)
    findings = []; unmatched = []
    for model_id, row in scores.items():
        # Exact release matching, allowing punctuation only. No stripping dates,
        # preview/variant labels, or fallback identities to force a match.
        label = model_id.split('/')[-1]
        model = resolve_model(label, models) or resolve_model(strip_effort(label), models)
        if not model:
            unmatched.append(model_id); continue
        score = row.get('accuracy')
        if not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 100:
            continue
        config = '; '.join(f'{k}={row[k]}' for k in
                          ('reasoning_effort', 'compute_effort', 'harness', 'max_output_tokens')
                          if row.get(k) is not None)
        findings.append(dict(model=model, component=component, score=score,
            sourceUrl='https://www.vals.ai/benchmarks/' + slug,
            sourceType='third_party_leaderboard', confidence='high', publishedAt=None,
            configuration=f'Vals {expected}; {protocol}; exact ID {model_id}; {config}.',
            notes='Individual publication date unknown; page update date is not used to backdate results.'))
    return findings, dict(source='vals:' + slug, component=component,
                         rows=len(scores), matched=len(findings), unmatched=unmatched)
