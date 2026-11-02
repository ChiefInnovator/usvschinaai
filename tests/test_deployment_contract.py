"""Source-level deployment gates: tests certify the same immutable artifact sent to Azure."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / '.github/workflows'


def job(text, name):
    match = re.search(r'^  ' + re.escape(name) + r':\n(.*?)(?=^  [a-zA-Z_][\w-]*:\n|\Z)', text, re.M | re.S)
    if not match:
        raise AssertionError('Missing workflow job ' + name)
    return match.group(1)


class DeploymentContractTests(unittest.TestCase):
    def setUp(self):
        self.deploy = (WORKFLOWS / 'deploy.yml').read_text()
        self.verify = job(self.deploy, 'verify_build')
        self.delivery = job(self.deploy, 'build_and_deploy_job')

    def test_verification_build_tests_and_upload_are_ordered_without_failure_bypass(self):
        commands = ('python scripts/prepare_publication.py', 'python scripts/validate_models.py',
                    'npm run build', 'python -m unittest discover -s tests', 'actions/upload-artifact@')
        positions = [self.verify.index(command) for command in commands]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('BUILT_SITE_DIR:', self.verify)
        self.assertIn('github.workspace }}/dist', self.verify)
        self.assertNotRegex(self.verify, r'continue-on-error:\s*true|if:\s*always\(\)')
        self.assertIn('if-no-files-found: error', self.verify)
        self.assertNotIn('--write', self.verify)

    def test_deploy_consumes_exact_verified_artifact_and_sha_without_rebuild(self):
        self.assertRegex(self.delivery, r'needs:\s*verify_build\b')
        self.assertIn('ref: ${{ needs.verify_build.outputs.sha }}', self.delivery)
        self.assertIn('sha: ${{ steps.revision.outputs.sha }}', self.verify)
        self.assertIn('git rev-parse HEAD', self.verify)
        artifact = r'name:\s*(site-\$\{\{ github.run_id \}\}-\$\{\{ github.run_attempt \}\})'
        self.assertEqual(re.search(artifact, self.verify).group(1), re.search(artifact, self.delivery).group(1))
        self.assertIn('actions/download-artifact@', self.delivery)
        self.assertIn('app_location: dist', self.delivery)
        self.assertIn('skip_app_build: true', self.delivery)
        self.assertNotRegex(self.delivery, r'npm (?:run build|ci)|build_site\.py|prepare_publication\.py')
        self.assertNotRegex(self.delivery, r'if:\s*(?:always\(\)|failure\(\))')

    def test_external_forks_cannot_reach_secret_bearing_jobs(self):
        self.assertIn("github.event.action != 'closed'", self.verify)
        self.assertIn('github.event.pull_request.head.repo.full_name == github.repository', self.verify)
        self.assertNotIn('secrets.', self.verify)
        close = job(self.deploy, 'close_pull_request_job')
        self.assertIn('github.event.pull_request.head.repo.full_name == github.repository', close)
        self.assertIn("github.event.action == 'closed'", close)
        self.assertNotIn('pull_request_target:', self.deploy)

    def test_writer_workflow_completion_resolves_current_main_and_serializes_delivery(self):
        self.assertIn("github.event.workflow_run.conclusion == 'success'", self.verify)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", self.verify)
        self.assertIn("github.event_name == 'workflow_run' && 'main' || github.sha", self.verify)
        self.assertNotIn('github.event.workflow_run.head_sha', self.verify)
        self.assertIn('cancel-in-progress: false', self.deploy)
        self.assertIn("|| 'production'", self.deploy)
        self.assertIn('CANDIDATE_SHA: ${{ needs.verify_build.outputs.sha }}', self.delivery)
        self.assertIn('git/ref/heads/main', self.delivery)
        self.assertIn('"$CURRENT" = "$CANDIDATE_SHA"', self.delivery)
        self.assertIn("if: steps.current.outputs.eligible == 'true'", self.delivery)

    def test_writers_prepare_and_verify_after_generators_before_commit(self):
        for filename, generator in (('daily-scrape.yml', 'python scripts/scrape_news.py'),
                                    ('backfill-gap-fill.yml', 'python scripts/rescore_history.py --write')):
            with self.subTest(workflow=filename):
                text = (WORKFLOWS / filename).read_text()
                prepare = text.index('python scripts/prepare_publication.py --write')
                verify = text.index('python scripts/prepare_publication.py\n', prepare)
                commit = text.index('git commit')
                self.assertLess(text.index(generator), prepare)
                if filename == 'backfill-gap-fill.yml':
                    refresh = text.index('python scripts/refresh_benchmark_sources.py --write')
                    research = text.index('python scripts/research_history.py --write')
                    replay = text.index(generator)
                    self.assertLess(refresh, research)
                    self.assertLess(research, replay)
                    self.assertNotIn('python scripts/backfill_gap_fill.py', text)
                self.assertLess(prepare, verify)
                self.assertLess(verify, commit)
                for artifact in ('data/scoring_revision.json', 'data/site_summary.json', 'data/publication.json'):
                    self.assertIn(artifact, text[verify:commit])
                self.assertNotRegex(text, r'git (?:pull|merge).*--rebase(?![\w-])')

    def test_health_checks_keep_half_hour_freshness_and_revision_agreement(self):
        text = (WORKFLOWS / 'health-check.yml').read_text()
        for token in ("*/30 * * * *", 'timedelta(hours=30)', 'site_summary.json',
                      'scoring_revision.json', 'publication.json', 'generationId', 'scoringRevision'):
            self.assertIn(token, text)

    def test_build_command_never_runs_paid_research_or_social_publishing(self):
        import json
        scripts = json.loads((ROOT / 'package.json').read_text())['scripts']
        self.assertIn('build_site.py', scripts['build'])
        for command in (scripts['build'], (ROOT / 'scripts/build_site.py').read_text()):
            self.assertNotRegex(command, r'scrape_models|gap_fill|publish_social|post_instagram|OPENAI_API_KEY|PAT_TOKEN')
