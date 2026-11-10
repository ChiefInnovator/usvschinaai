"""Order paid benchmark research by what the published board needs.

The research pass spends its budgets in the order models are handed to it.
Handed the scrape order (every US model, newest release first, then every CN
model), it never reached a Chinese model. This hands it the same models in
order of value:

1. models on the latest published board, heaviest missing benchmark weight first;
2. new models, as the research pass defines them, newest first;
3. everything else, in scrape order.

Each tier alternates between countries.
"""
from itertools import zip_longest

from avg_iq_benchmarks import selected_value
from gap_fill_benchmarks import is_new_model
from preconditions import preconditions


@preconditions(entries='sequence')
def alternate(entries):
    """Round-robin across countries, keeping each country's own order."""
    queues = {}
    for entry in entries:
        queues.setdefault(entry.country, []).append(entry)
    return [entry for group in zip_longest(*queues.values()) for entry in group if entry is not None]


@preconditions(entries='sequence', board='set', first_seen='mapping', now='datetime', benchmarks='sequence')
def plan_research(entries, board, first_seen, now, benchmarks):
    """Return the entries in research order.

    board: model names on the latest published snapshot.
    first_seen: earliest published day per model name.
    """
    def missing_weight(entry):
        return sum(b['weight'] for b in benchmarks if not selected_value(entry.columns, b['name']))

    on_board = sorted((e for e in entries if e.name in board), key=missing_weight, reverse=True)
    new, rest = [], []
    for entry in entries:
        if entry.name not in board:
            released = str(entry.columns.get('Released') or '')
            (new if is_new_model(entry.name, first_seen, now, released) else rest).append(entry)
    print(f"[gap-fill] research order: {len(on_board)} on the board, {len(new)} new releases, {len(rest)} others")
    return [*alternate(on_board), *alternate(new), *alternate(rest)]
