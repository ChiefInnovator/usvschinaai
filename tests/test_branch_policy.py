"""Exercise the trusted branch gate with GitHub API fixtures, without credentials."""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BranchPolicyTests(unittest.TestCase):
    def test_source_and_repository_matrix_posts_status_to_exact_head(self):
        harness = r"""
        const check = require('./.github/scripts/branch-policy.cjs');
        (async () => {
          const results = [];
          for (const [base, head, sourceRepo, statusError] of JSON.parse(process.argv[1])) {
            let status, failed = false;
            const github = {rest: {
              pulls: {get: async () => ({data: {
                base: {ref: base, repo: {full_name: 'owner/repo'}},
                head: {ref: head, sha: 'exact-head', repo: sourceRepo ? {full_name: sourceRepo} : null},
              }})},
              repos: {createCommitStatus: async value => {
                if (statusError) throw new Error('SHA not found');
                status = value;
              }},
            }};
            await check({github, context: {repo: {owner:'owner',repo:'repo'},issue:{number:42},runId:7},
              core: {setFailed: () => {failed = true;}}});
            results.push({status: status || null, failed});
          }
          console.log(JSON.stringify(results));
        })().catch(e => {console.error(e); process.exit(1);});
        """
        cases = [
            ('main', 'develop', 'owner/repo', True),
            ('main', 'feature/work', 'owner/repo', False),
            ('main', 'main', 'owner/repo', False),
            ('main', 'develop', 'fork/repo', False),
            ('develop', 'feature/work', 'owner/repo', True),
            ('develop', 'fix/work', 'owner/repo', True),
            ('develop', 'main', 'owner/repo', False),
            ('develop', 'develop', 'owner/repo', False),
            ('develop', 'master', 'owner/repo', False),
            ('develop', '', 'owner/repo', False),
            ('develop', 'feature/work', 'fork/repo', False),
            ('develop', 'feature/work', None, False),
            ('develop', 'feature/work', 'fork/repo', False, True),
        ]
        inputs = [list(c[:3]) + [len(c) > 4 and c[4]] for c in cases]
        result = subprocess.run(['node', '-e', harness, json.dumps(inputs)],
                                cwd=ROOT, capture_output=True, text=True, check=True)
        for case, actual in zip(cases, json.loads(result.stdout), strict=True):
            with self.subTest(case=case):
                base, _, _, valid = case[:4]
                if len(case) > 4 and case[4]:
                    self.assertTrue(actual['failed'])
                    self.assertIsNone(actual['status'])
                    continue
                self.assertEqual(actual['status']['state'], 'success' if valid else 'failure')
                self.assertEqual(actual['failed'], not valid)
                self.assertEqual(actual['status']['sha'], 'exact-head')
                self.assertEqual(actual['status']['context'], 'Branch source policy / ' + base)

    def test_gate_executes_only_trusted_base_and_writers_open_develop_prs(self):
        gate = (ROOT / '.github/workflows/branch-policy.yml').read_text()
        self.assertIn('pull_request_target:', gate)
        self.assertIn('ref: refs/heads/${{ github.event.pull_request.base.ref }}', gate)
        self.assertIn('persist-credentials: false', gate)
        self.assertNotIn('secrets.', gate)
        self.assertNotIn('pull_request.head', gate)
        for filename in ('daily-scrape.yml', 'backfill-gap-fill.yml'):
            text = (ROOT / '.github/workflows' / filename).read_text()
            self.assertIn('ref: develop', text)
            self.assertIn('persist-credentials: false', text)
            self.assertIn('contents: read', text)
            self.assertNotIn('token: ${{ secrets.PAT_TOKEN }}', text)
            self.assertIn('git fetch origin develop', text)
            self.assertIn('"$(git rev-parse HEAD)" != "$(git rev-parse FETCH_HEAD)"', text)
            self.assertLess(text.index('git fetch origin develop'), text.index('git commit'))
            self.assertIn('--base develop', text)
            self.assertIn('git push origin "HEAD:refs/heads/$BRANCH"', text)
            self.assertNotIn('git pull', text)
            self.assertNotRegex(text, r'git push[^\n]*\.git main')
