"""Research selection must match the configured Avg IQ scoring inputs."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from avg_iq_benchmarks import load_config
from gap_fill_benchmarks import build_candidates, _group_by_model


def entry(i, columns=None):
    return SimpleNamespace(name=f'Model {i}', country='US' if i < 10 else 'CN',
                           url='', columns=columns or {})


class ResearchSelectionTests(unittest.TestCase):
    def test_every_missing_component_at_every_participation_count(self):
        names = [b['name'] for b in load_config()['benchmarks']]
        for count in (0, 1, 7, 8, 15, 16, 19):
            with self.subTest(participants=count):
                entries = [entry(i, {b: '80%' for b in names} if i < count else {})
                           for i in range(20)]
                candidates = build_candidates(entries)
                self.assertEqual(len(candidates), (20-count)*len(names))
                for _, group in _group_by_model(candidates):
                    self.assertEqual([c.benchmark for c in group], names)

    def test_aliases_count_but_unrelated_or_newer_benchmarks_do_not(self):
        e = entry(0, {'GPQA': '96%', 'DeepSWE1.1': '74.1%',
                      'ARC-AGIv2': '95%', 'Terminal-Bench4.0': '57%', 'HLE': '65%'})
        names = {c.benchmark for c in build_candidates([e])}
        self.assertEqual(len(names), 14)
        self.assertIn('GPQA Diamond', names)
        self.assertIn('Terminal-Bench 2.1', names)
        self.assertNotIn('DeepSWE 1.1', names)
        self.assertNotIn('ARC-AGI-2', names)
        self.assertNotIn('Humanity’s Last Exam', names)

    def test_missing_markers_and_zero_results(self):
        e = entry(0, {'Toolathlon': '0%', 'IFBench': '—', 'MMMU-Pro': '–'})
        names = {c.benchmark for c in build_candidates([e])}
        self.assertNotIn('Toolathlon', names)
        self.assertIn('IFBench', names)
        self.assertIn('MMMU-Pro', names)


class SourceFingerprintTests(unittest.TestCase):
    def test_fingerprint_reads_selected_gpqa_diamond_column(self):
        from unittest.mock import patch
        from harvest_benchmark_sources import observed_values
        payload = '{"history":[{"teams":{"US":[{"model":"M","GPQADiamond":"96%","GPQA":"70%"}]}}]}'
        with patch('pathlib.Path.read_text', return_value=payload):
            self.assertEqual(observed_values()['M']['gpqa'], 96)
