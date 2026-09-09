import html
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from benchmark_leaderboard_sources import vals_results, ale_results


def page(tasks, name='AIME'):
    def encode(x):
        if isinstance(x, dict): return [0, {k:encode(v) for k,v in x.items()}]
        return [0,x]
    props={'benchmarkView':encode({'metadata':{'benchmark':name},'tasks':tasks})}
    return '<astro-island component-url="/_astro/BenchmarkView.test.js" props="'+html.escape(json.dumps(props),quote=True)+'"></astro-island>'


class LeaderboardSourceTests(unittest.TestCase):
    def test_aime_uses_2025_not_combined_or_2024(self):
        raw=page({'overall':{'gpt-5.5':{'accuracy':99}},'aime_2024':{'gpt-5.5':{'accuracy':100}},'aime_2025':{'gpt-5.5':{'accuracy':92,'reasoning_effort':'max'},'gpt-5.5-preview':{'accuracy':100}}})
        results,audit=vals_results(raw,'aime',{'GPT-5.5':'2026-04-01'})
        self.assertEqual([r['score'] for r in results],[92])
        self.assertIsNone(results[0]['publishedAt'])
        self.assertIn('gpt-5.5-preview',audit['unmatched'])
        self.assertIn('max',results[0]['configuration'])

    def test_missing_subtest_fails_closed(self):
        with self.assertRaises(ValueError):
            vals_results(page({'overall':{}}),'aime',{})

    def test_effort_suffix_matches_without_merging_release_variants(self):
        raw=page({'overall':{'meta/muse_spark_1_3_max':{'accuracy':90},
                             'meta/muse_spark_1_2_max':{'accuracy':99}}}, 'Terminal-Bench 2.1')
        results,audit=vals_results(raw,'terminal-bench-2-1',{'Muse Spark 1.3':'2026-09-02'})
        self.assertEqual([r['score'] for r in results],[90])
        self.assertEqual(audit['unmatched'],['meta/muse_spark_1_2_max'])

    def test_ale_full_pass_rate_and_efforts(self):
        rows=[{'model':'gpt-5.5','split':split,'passRate':rate,'avgScore':0.99,'harnessVariant':effort} for split,rate,effort in [('full',0.3,'high'),('full',0.4,'max'),('last_exam',0.9,'max'),('full',0.8,'fallback')]]
        results=ale_results({'rows':rows},{'GPT-5.5':'2026-04-01'})
        self.assertEqual([r['score'] for r in results],[30,40])
        self.assertTrue(all(r['publishedAt'] is None for r in results))
