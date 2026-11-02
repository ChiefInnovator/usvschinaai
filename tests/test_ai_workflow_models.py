"""Task routes use current cheaper models without changing evidence validation."""
import inspect
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import ai_models as policy
import backfill_gap_fill as legacy
import check_openai_billing as billing
import gap_fill_benchmarks as gap
import research_history as history
import social_caption as caption


class ModelPolicyTests(unittest.TestCase):
    def test_task_defaults_and_workflows_agree(self):
        self.assertEqual(gap.DEFAULT_MODEL_CHAIN, list(policy.RESEARCH_MODEL_CHAIN))
        self.assertEqual(gap.DEFAULT_MODEL_CHAIN[0], policy.RESEARCH_MODEL)
        self.assertEqual(inspect.signature(history.research_history).parameters['model'].default,
                         policy.ECONOMY_MODEL)
        self.assertEqual(legacy.BACKFILL_MODEL, policy.ECONOMY_MODEL)
        self.assertEqual(billing.DEFAULT_MODEL, policy.ECONOMY_MODEL)
        daily = (ROOT / '.github/workflows/daily-scrape.yml').read_text()
        backfill = (ROOT / '.github/workflows/backfill-gap-fill.yml').read_text()
        self.assertIn('AI_GAP_FILL_MODEL: ' + policy.RESEARCH_MODEL, daily)
        self.assertIn('--model ' + policy.ECONOMY_MODEL, daily)
        self.assertIn("default: '" + policy.ECONOMY_MODEL + "'", backfill)

    def test_default_availability_fallback_cannot_raise_token_rates(self):
        primary = policy.TOKEN_PRICES[policy.RESEARCH_MODEL]
        self.assertEqual(len(set(gap.DEFAULT_MODEL_CHAIN)), len(gap.DEFAULT_MODEL_CHAIN))
        for model in gap.DEFAULT_MODEL_CHAIN:
            self.assertNotIn(model, ('gpt-6-astra', 'gpt-6.1-sol', 'gpt-5.6-sol', 'gpt-5.4'))
            self.assertTrue(all(a <= b for a, b in zip(policy.TOKEN_PRICES[model], primary)))

    def test_optional_caption_routes_and_real_token_cost(self):
        with patch.dict(os.environ, {'SOCIAL_CAPTION_MODEL': ''}):
            self.assertEqual(caption.choose_caption_model(1), policy.ECONOMY_MODEL)
            self.assertEqual(caption.choose_caption_model(4), policy.RESEARCH_MODEL)
        usage = {'input_tokens': 1000, 'input_tokens_details': {'cached_tokens': 400},
                 'output_tokens': 200}
        self.assertAlmostEqual(caption.cost_usd(policy.ECONOMY_MODEL, usage), 0.000164)
        self.assertAlmostEqual(caption.cost_usd(policy.RESEARCH_MODEL, usage), 0.001620)
        self.assertLess(caption.cost_usd(policy.RESEARCH_MODEL, usage),
                        caption.cost_usd('gpt-5.6-terra', usage))

    def test_preflight_uses_tiny_nonreasoning_nonstored_request(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def read(self): return b'{}'
        with patch.object(billing.urllib.request, 'urlopen', return_value=Response()) as request:
            self.assertTrue(billing.check('test-only-key', policy.ECONOMY_MODEL)[0])
        payload = json.loads(request.call_args.args[0].data)
        self.assertEqual(payload['model'], policy.ECONOMY_MODEL)
        self.assertEqual(payload['reasoning'], {'effort': 'none'})
        self.assertEqual(payload['max_output_tokens'], 16)
        self.assertFalse(payload['store'])
