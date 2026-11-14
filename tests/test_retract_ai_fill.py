"""Retracting an AI fill removes its evidence and stops the same answer returning."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import retract_ai_fill as retract

URL = 'https://example.com/card'


class RetractAiFillTests(unittest.TestCase):
    def run_retract(self, cache):
        evidence = {'results': [
            {'id': '1', 'model': 'M', 'component': 'gpqa', 'benchmark': 'GPQA', 'score': 77.0, 'source': URL},
            {'id': '2', 'model': 'M', 'component': 'gpqa', 'benchmark': 'GPQA', 'score': 70.0, 'source': 'https://example.com/own'},
            {'id': '3', 'model': 'K', 'component': 'gpqa', 'benchmark': 'GPQA', 'score': 77.0, 'source': URL}]}
        saved, audit = {}, []
        with patch.object(retract.gap_fill, 'load_cache', lambda: cache), \
             patch.object(retract.gap_fill, 'save_cache', saved.update), \
             patch.object(retract.gap_fill, 'append_audit_entry', audit.append), \
             patch.object(retract.model_store, 'load_evidence', lambda: evidence), \
             patch.object(retract.model_store, 'save_evidence', lambda kept: saved.update(evidence=kept)):
            removed = retract.retract('M', 'GPQA', 'the page reports another model')
        return removed, saved, audit

    def test_only_the_cited_evidence_is_removed_and_the_answer_is_remembered(self):
        removed, saved, audit = self.run_retract({'M': {'GPQA': {'score': '77.0%', 'source_url': URL,
                                                                 'llm_model': 'stub'}}})
        self.assertEqual(removed, 1)
        self.assertEqual([record['id'] for record in saved['evidence']['results']], ['2', '3'])
        entry = saved['M']['GPQA']
        self.assertIsNone(entry['score'])
        self.assertEqual(entry['rejected'], {'score': '77.0%', 'source_url': URL,
                                             'reason': 'the page reports another model'})
        self.assertEqual((audit[0]['retracted'], audit[0]['model'], audit[0]['benchmark']), (True, 'M', 'GPQA'))

    def test_nothing_changes_without_a_cached_fill(self):
        for cache in ({}, {'M': {'GPQA': {'score': None}}}):
            with self.assertRaises(ValueError):
                self.run_retract(cache)


if __name__ == '__main__':
    unittest.main()
