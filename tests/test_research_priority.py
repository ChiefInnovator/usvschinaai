"""Paid research reaches the published board and both countries before anything else."""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import gap_fill_benchmarks as gf
from research_priority import alternate, plan_research

BENCHMARKS = [{'name': 'Heavy', 'weight': 16.0}, {'name': 'Light', 'weight': 0.2}]
NOW = datetime(2026, 11, 10, 3, 30, tzinfo=timezone.utc)


def entry(name, country, released='2026-01-01', **columns):
    return SimpleNamespace(name=name, country=country, url='https://example.org/' + name,
                           columns={'Released': released, **columns})


def plan(entries, board=(), first_seen=None, benchmarks=BENCHMARKS):
    with patch('builtins.print'):
        return plan_research(entries, set(board), first_seen or {}, NOW, benchmarks)


class ResearchPriorityTests(unittest.TestCase):
    def test_board_then_new_releases_then_the_rest_alternating_countries(self):
        # Scrape order: every US model newest first, then every CN model.
        entries = [entry('US old A', 'US'), entry('US new', 'US', '2026-11-05'), entry('US board', 'US'),
                   entry('US old B', 'US'), entry('CN new', 'CN', '2026-11-08'), entry('CN board', 'CN'),
                   entry('CN old', 'CN')]
        order = plan(entries, board=('US board', 'CN board'),
                     first_seen={'US board': '2026-06-01', 'CN board': '2026-06-01'})
        self.assertEqual([e.name for e in order],
                         ['US board', 'CN board', 'US new', 'CN new', 'US old A', 'CN old', 'US old B'])

    def test_board_models_missing_the_heaviest_benchmarks_come_first(self):
        entries = [entry('Light gap', 'US', Heavy='80%'), entry('Heavy gap', 'US', Light='50%'),
                   entry('Complete', 'US', Heavy='80%', Light='50%')]
        seen = {e.name: '2026-06-01' for e in entries}
        self.assertEqual([e.name for e in plan(entries, board=seen, first_seen=seen)],
                         ['Heavy gap', 'Light gap', 'Complete'])

    def test_old_release_without_history_is_not_ranked_as_new(self):
        entries = [entry('Never on board', 'US', '2026-03-01'), entry('Label only', 'US', 'Spring 2026'),
                   entry('Fresh', 'CN', '2026-11-01'), entry('Just promoted', 'CN', '2026-02-01')]
        order = plan(entries, board=('Just promoted',), first_seen={'Just promoted': '2026-11-09'})
        self.assertEqual([e.name for e in order], ['Just promoted', 'Fresh', 'Never on board', 'Label only'])

    def test_display_label_does_not_hide_a_recent_release(self):
        # A retained catalog release shows "Nov. 2026" but carries its normalized day.
        labelled = entry('Labelled', 'US', 'Nov. 2026')
        labelled.release_date = '2026-11-06'
        order = plan([entry('Old', 'US', '2026-03-01'), labelled])
        self.assertEqual([e.name for e in order], ['Labelled', 'Old'])
        self.assertEqual(gf.build_candidates([labelled])[0].released, '2026-11-06')

    def test_alternation_keeps_each_countrys_order(self):
        mixed = [entry('a', 'US'), entry('b', 'US'), entry('c', 'CN')]
        self.assertEqual([e.name for e in alternate(mixed)], ['a', 'c', 'b'])
        self.assertEqual(alternate([]), [])

    def test_pass_spends_its_budgets_in_planned_order_on_shared_entries(self):
        # Sunday with one general call: it must go to the board model, not the first US row.
        entries = [entry('US off board', 'US', '2026-03-01'), entry('CN board', 'CN', '2026-03-01')]
        asked = []
        def answer(system, user, **kwargs):
            asked.append(next(e.name for e in entries if e.name in user))
            return None
        order = plan(entries, board=('CN board',), first_seen={'CN board': '2026-06-01'},
                     benchmarks=gf.load_config()['benchmarks'])
        self.assertTrue(all(any(o is e for e in entries) for o in order), 'fills must land on the scraped entries')
        with patch.object(gf, 'resolve_openai_key', return_value='key'), \
             patch.object(gf, 'discover_available_model', return_value='stub-model'), \
             patch.object(gf, 'load_cache', return_value={}), patch.object(gf, 'save_cache'), \
             patch.object(gf, 'load_first_seen', return_value={'CN board': '2026-06-01'}), \
             patch.object(gf.time, 'sleep'), patch('builtins.print'), \
             patch.object(gf, 'query_openai_responses', side_effect=answer):
            gf.run_gap_filling_pass(order, max_calls=1)
        self.assertEqual(asked, ['CN board'])


if __name__ == '__main__':
    unittest.main()
