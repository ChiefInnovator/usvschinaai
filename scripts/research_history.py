"""Research exact retained models without the legacy historical-score writer."""
import argparse
import copy
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from types import SimpleNamespace

from gap_fill_benchmarks import run_gap_filling_pass
from model_store import load_data
from preconditions import preconditions
from refresh_benchmark_sources import persist_ai_findings
from ai_models import ECONOMY_MODEL

ROOT = Path(__file__).resolve().parents[1]


@preconditions(data='mapping', days='positive_int')
def research_entries(data, days):
    """Take the newest dated profile of each exact model inside the research window."""
    history = sorted(data.get('history', []), key=lambda item:
        datetime.fromisoformat(item['timestamp'].replace('Z', '+00:00')).astimezone(timezone.utc), reverse=True)
    if not history:
        return []
    latest = datetime.fromisoformat(history[0]['timestamp'].replace('Z', '+00:00')).astimezone(timezone.utc)
    cutoff = latest.date() - timedelta(days=days - 1)
    selected = {}
    for snapshot in history:
        instant = datetime.fromisoformat(snapshot['timestamp'].replace('Z', '+00:00')).astimezone(timezone.utc)
        if instant.date() < cutoff:
            continue
        for country in ('US', 'CN'):
            for row in snapshot['teams'].get(country, []):
                name = row['model']
                if name not in selected:
                    selected[name] = SimpleNamespace(name=name, country=country,
                        url=row.get('link', ''), columns=copy.deepcopy(row))
    return list(selected.values())


@preconditions(days='positive_int', max_calls='nonnegative_int', model='nonempty', write='bool')
def research_history(days=45, max_calls=80, model=ECONOMY_MODEL, *, write=False):
    entries = research_entries(load_data(ROOT / 'models.json'), days)
    if not write:
        return {'models': len(entries), 'maxCalls': max_calls, 'writes': False}
    previous = os.environ.get('AI_GAP_FILL_MODEL')
    os.environ['AI_GAP_FILL_MODEL'] = model
    try:
        # Disable the independent new-model budget: the manual ceiling is total.
        if max_calls and entries:
            run_gap_filling_pass(entries, max_calls=max_calls, new_model_max_calls=0,
                                 min_confidence='high', scraper_run_ts=datetime.now(timezone.utc).isoformat())
            accepted, rejected = persist_ai_findings(entries)
        else:
            accepted, rejected = [], []
    finally:
        if previous is None:
            os.environ.pop('AI_GAP_FILL_MODEL', None)
        else:
            os.environ['AI_GAP_FILL_MODEL'] = previous
    return {'models': len(entries), 'accepted': len(accepted), 'rejected': len(rejected),
            'maxCalls': max_calls, 'writes': True}


@preconditions()
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days', type=int, default=45)
    parser.add_argument('--max-calls', type=int, default=80)
    parser.add_argument('--model', default=ECONOMY_MODEL)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    print(research_history(args.days, args.max_calls, args.model, write=args.write))


if __name__ == '__main__':
    main()
