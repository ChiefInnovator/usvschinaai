"""Modern backfill researches dated evidence, never uses the obsolete score writer."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import research_history as research


class DatedResearchTests(unittest.TestCase):
    def fixture(self):
        return {'history': [
            {'timestamp': '2026-01-03T01:00:00+03:00', 'teams': {'US': [
                {'model': 'A', 'link': 'https://example.org/a', 'Input$/M': '$2'}], 'CN': []}},
            {'timestamp': '2026-01-02T23:00:00Z', 'teams': {'US': [
                {'model': 'A', 'link': 'https://example.org/a', 'Input$/M': '$3'}], 'CN': [
                {'model': 'B', 'link': 'https://example.org/b'}]}},
            {'timestamp': '2026-01-01T23:00:00Z', 'teams': {'US': [
                {'model': 'Older', 'link': 'https://example.org/old'}], 'CN': []}}]}

    def test_utc_window_keeps_latest_exact_profile_without_mutating_rosters(self):
        data = self.fixture()
        before = copy.deepcopy(data)
        rows = research.research_entries(data, 1)
        self.assertEqual([row.name for row in rows], ['A', 'B'])
        self.assertEqual(rows[0].columns['Input$/M'], '$3')
        rows[0].columns['Input$/M'] = '$900'
        self.assertEqual(data, before)

    def test_preview_never_calls_network_research_or_writes(self):
        with patch.object(research, 'load_data', return_value=self.fixture()), \
                patch.object(research, 'run_gap_filling_pass') as run, \
                patch.object(research, 'persist_ai_findings') as persist:
            result = research.research_history(1, 7, 'research-model')
        self.assertFalse(result['writes'])
        run.assert_not_called()
        persist.assert_not_called()

    def test_manual_research_has_one_total_budget_and_persists_dated_findings(self):
        with patch.object(research, 'load_data', return_value=self.fixture()), \
                patch.object(research, 'run_gap_filling_pass') as run, \
                patch.object(research, 'persist_ai_findings', return_value=([{}], [])) as persist:
            result = research.research_history(1, 7, 'research-model', write=True)
        self.assertEqual(run.call_args.kwargs['max_calls'], 7)
        self.assertEqual(run.call_args.kwargs['new_model_max_calls'], 0)
        persist.assert_called_once()
        self.assertEqual(result['accepted'], 1)

    def test_zero_budget_never_calls_research(self):
        with patch.object(research, 'load_data', return_value=self.fixture()), \
                patch.object(research, 'run_gap_filling_pass') as run:
            research.research_history(1, 0, 'research-model', write=True)
        run.assert_not_called()
