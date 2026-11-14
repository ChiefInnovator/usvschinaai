#!/usr/bin/env python3
"""Retract one AI-researched benchmark result that its cited source does not support.

    python scripts/retract_ai_fill.py --model "Model Name" --benchmark "Benchmark" --reason "why"

Use only after reading the cited source: another vendor's page is a valid
source when it reports the model in its own comparison column. The retraction

- removes the evidence the fill put in data/model_catalog.json,
- replaces the cache entry with a null answer that remembers the retracted
  score and source, so the same answer is not accepted again,
- appends the retraction to data/ai_fill_history.jsonl.

It researches nothing and regenerates nothing. Afterwards run
`python scripts/prepare_publication.py --write`, then
`python scripts/prepare_publication.py` to verify.
"""
from preconditions import preconditions
import argparse
import sys
from datetime import datetime, timezone

import gap_fill_benchmarks as gap_fill
import model_store
from ingest_benchmark_findings import record_id


@preconditions(record='mapping', model='nonempty', benchmark='nonempty', entry='mapping', source='text')
def from_fill(record, model, benchmark, entry, source):
    """Whether this evidence record is the one the cached fill produced.

    The fill is stored under the ID the ingestion derives from its model,
    component, score and source, and may also have been observed in a retained
    snapshot from the day it was cached. Other evidence for the same model and
    benchmark, including an earlier observation of the same score, is left alone.
    """
    if record['model'] != model or record['benchmark'] != benchmark or record.get('source') != source:
        return False
    if not gap_fill._scores_equal(record.get('score'), entry['score']):
        return False
    stored = record_id({'model': model, 'component': record['component'], 'score': record['score'],
                        'sourceUrl': source})
    if record['id'] == stored:
        return True
    # A snapshot can only have observed the fill from the day it was cached.
    return (record.get('kind') == 'retained-observation'
            and (record.get('availableFrom') or '') >= (entry.get('cached_at') or '9999')[:10])


@preconditions(model='nonempty', benchmark='nonempty', reason='nonempty')
def retract(model, benchmark, reason):
    """Returns the number of evidence records removed."""
    cache = gap_fill.load_cache()
    entry = cache.get(model, {}).get(benchmark)
    if not entry or entry.get('score') is None:
        raise ValueError(f'No cached AI fill for {model!r} on {benchmark!r}')
    score, source = gap_fill._format_score(entry['score']), entry.get('source_url') or ''
    evidence = model_store.load_evidence()
    kept = [record for record in evidence['results'] if not from_fill(record, model, benchmark, entry, source)]
    removed = len(evidence['results']) - len(kept)
    if not removed:
        # Nothing may claim a retraction while the score is still published.
        raise ValueError(f'No evidence from the cached fill for {model!r} on {benchmark!r}; nothing was changed')
    evidence['results'] = kept
    model_store.save_evidence(evidence)
    now = datetime.now(timezone.utc).isoformat()
    cache[model][benchmark] = {
        'benchmark': benchmark, 'score': None, 'cached_at': now, 'llm_model': entry.get('llm_model', ''),
        'rejected': {'score': score, 'source_url': source, 'reason': reason},
    }
    gap_fill.save_cache(cache)
    gap_fill.append_audit_entry({'ts': now, 'model': model, 'benchmark': benchmark, 'score': score,
                                 'source_url': source, 'retracted': True, 'reason': reason})
    return removed


@preconditions()
def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--model', required=True)
    parser.add_argument('--benchmark', required=True)
    parser.add_argument('--reason', required=True, help='What the cited source actually shows')
    args = parser.parse_args()
    try:
        removed = retract(args.model, args.benchmark, args.reason)
    except ValueError as problem:
        print(f'error: {problem}', file=sys.stderr)
        return 1
    print(f'Retracted {args.benchmark} for {args.model}: {removed} evidence record(s) removed.')
    print('Now run: python scripts/prepare_publication.py --write && python scripts/prepare_publication.py')
    return 0


if __name__ == '__main__':
    sys.exit(main())
