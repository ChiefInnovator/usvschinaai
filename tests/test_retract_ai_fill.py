"""Retracting an AI fill removes its evidence and stops the same answer returning."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import retract_ai_fill as retract

URL = 'https://example.com/card'


class RetractAiFillTests(unittest.TestCase):
    def run_retract(self, cache, fill_id=None):
        fill_id = fill_id or retract.record_id({'model': 'M', 'component': 'gpqa', 'score': 77.0, 'sourceUrl': URL})
        evidence = {'results': [
            {'id': fill_id, 'model': 'M', 'component': 'gpqa', 'benchmark': 'GPQA', 'score': 77.0, 'source': URL},
            {'id': '2', 'model': 'M', 'component': 'gpqa', 'benchmark': 'GPQA', 'score': 70.0, 'source': 'https://example.com/own'},
            {'id': '3', 'model': 'K', 'component': 'gpqa', 'benchmark': 'GPQA', 'score': 77.0, 'source': URL},
            {'id': '4', 'model': 'M', 'component': 'gpqa', 'benchmark': 'GPQA', 'score': 70.0, 'source': URL},
            # The same fill as later observed in a retained snapshot.
            {'id': '5', 'model': 'M', 'component': 'gpqa', 'benchmark': 'GPQA', 'score': 77.0, 'source': URL,
             'kind': 'retained-observation', 'availableFrom': '2026-11-12'},
            # The same score observed before the fill existed is not the fill's.
            {'id': '6', 'model': 'M', 'component': 'gpqa', 'benchmark': 'GPQA', 'score': 77.0, 'source': URL,
             'kind': 'retained-observation', 'availableFrom': '2026-11-01'}]}
        self.saved, self.audit = saved, audit = {}, []
        with patch.object(retract.gap_fill, 'load_cache', lambda: cache), \
             patch.object(retract.gap_fill, 'save_cache', saved.update), \
             patch.object(retract.gap_fill, 'append_audit_entry', audit.append), \
             patch.object(retract.model_store, 'load_evidence', lambda: evidence), \
             patch.object(retract.model_store, 'save_evidence', lambda kept: saved.update(evidence=kept)):
            removed = retract.retract('M', 'GPQA', 'the page reports another model')
        return removed, saved, audit

    def test_only_the_cited_evidence_is_removed_and_the_answer_is_remembered(self):
        removed, saved, audit = self.run_retract({'M': {'GPQA': {'score': '77.0%', 'source_url': URL, 'llm_model': 'stub',
                                                                 'cached_at': '2026-11-11T03:29:41+00:00'}}})
        self.assertEqual(removed, 2)
        self.assertEqual([record['id'] for record in saved['evidence']['results']], ['2', '3', '4', '6'])
        entry = saved['M']['GPQA']
        self.assertIsNone(entry['score'])
        self.assertEqual(entry['rejected'], {'score': '77.0%', 'source_url': URL,
                                             'reason': 'the page reports another model'})
        self.assertEqual((audit[0]['retracted'], audit[0]['model'], audit[0]['benchmark']), (True, 'M', 'GPQA'))

    def test_nothing_changes_without_a_cached_fill(self):
        for cache in ({}, {'M': {'GPQA': {'score': None}}}):
            with self.assertRaises(ValueError):
                self.run_retract(cache)

    def test_evidence_not_stored_under_the_fills_id_is_kept(self):
        # Same model, benchmark, score and source, but another record: not the fill's.
        removed, saved, _ = self.run_retract({'M': {'GPQA': {'score': '77.0%', 'source_url': URL,
                                                               'cached_at': '2026-11-11T03:29:41+00:00'}}}, fill_id='other')
        self.assertEqual(removed, 1)
        self.assertEqual([record['id'] for record in saved['evidence']['results']], ['other', '2', '3', '4', '6'])

    def test_nothing_changes_when_no_evidence_came_from_the_fill(self):
        with self.assertRaises(ValueError):
            self.run_retract({'M': {'GPQA': {'score': '77.0%', 'source_url': 'https://example.com/elsewhere'}}})
        self.assertEqual((self.saved, self.audit), ({}, []))


if __name__ == '__main__':
    unittest.main()
