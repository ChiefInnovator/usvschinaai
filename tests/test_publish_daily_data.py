"""The daily scrape publishes its own data only when nothing in it needs a person."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import publish_daily_data as publish

REPO = 'owner/repo'
BRANCH = 'feature/daily-scrape-1-1'
HEAD, DEVELOP, MAIN, STARTED, FIXED = 'a' * 40, 'b' * 40, 'c' * 40, 'f' * 40, '5' * 40


class FakeGitHub:
    """Answers the gh calls the publisher makes and records every mutation."""

    def __init__(self, **options):
        self.options = dict(data_checks='pass', promotion_checks='pass', review_head=HEAD,
                            reviewer='copilot-pull-request-reviewer[bot]', threads=0,
                            base='develop', promotion_head=DEVELOP, develop_tip=STARTED,
                            merge_parents=[STARTED, HEAD], review_state='COMMENTED', earlier_state='COMMENTED',
                            data_head=HEAD, files=['models.json', 'current.json', 'data/model_catalog.json',
                                                   'data/ai_fill_history.jsonl', 'social/2026-11-10-1-x.png',
                                                   'social/plan.json', 'og-image.png', 'sitemap.xml', 'llms.txt'])
        self.options.update(options)
        self.merged, self.created, self.views, self.asked, self.deleted = [], [], 0, [], []

    def pull(self, number):
        if number == 7:
            head = self.options.get('fix_head') if self.asked else None
            return dict(number=7, state='MERGED' if 7 in self.merged else 'OPEN',
                        headRefOid=head or self.options['data_head'],
                        baseRefName=self.options['base'], headRefName=BRANCH, isCrossRepository=False,
                        mergeCommit={'oid': DEVELOP} if 7 in self.merged else None)
        return dict(number=8, state='MERGED' if 8 in self.merged else 'OPEN',
                    headRefOid=self.options['promotion_head'], baseRefName='main', headRefName='develop',
                    isCrossRepository=False, mergeCommit={'oid': MAIN} if 8 in self.merged else None)

    def __call__(self, args, check=True):
        if args[:2] == ['pr', 'view']:
            self.views += 1
            pull = self.pull(7 if args[2] in (BRANCH, '7') else 8)
            # Something changed the pull request while the checks and review ran.
            if pull['number'] == 7 and self.views > self.options.get('stable_views', 99):
                pull.update(self.options['later'])
            return 0, json.dumps(pull)
        if args[:2] == ['pr', 'checks']:
            bucket = self.options['data_checks' if args[2] == '7' else 'promotion_checks']
            return 0, json.dumps([{'name': 'test', 'bucket': bucket}, {'name': 'verify_build', 'bucket': 'pass'}])
        if args[0] == 'api' and '/files?' in args[1]:
            files = self.options.get('fix_files') if self.asked else None
            return 0, json.dumps([{'filename': name} for name in files or self.options['files']])
        if args[:2] == ['pr', 'comment']:
            self.asked.append(args[args.index('--body') + 1])
            return 0, ''
        if args[:3] == ['api', '-X', 'DELETE']:
            self.deleted.append(args[3])
            return 0, ''
        if args[0] == 'api' and '/compare/' in args[1]:
            return 0, json.dumps({'status': self.options.get('fix_status', 'ahead'), 'commits': [
                {'author': {'login': login}} for login in self.options.get('fix_authors', ['Copilot'])]})
        if args[0] == 'api' and args[1].endswith('/git/ref/heads/develop'):
            self.tips = getattr(self, 'tips', 0) + 1
            moved = self.options.get('develop_moves_after')
            tip = '9' * 40 if moved is not None and self.tips > moved else self.options['develop_tip']
            return 0, json.dumps({'object': {'sha': tip}})
        if args[0] == 'api' and '/commits/' in args[1]:
            return 0, json.dumps({'parents': [{'sha': sha} for sha in self.options['merge_parents']]})
        if args[0] == 'api' and 'graphql' not in args:
            return 0, json.dumps([
                {'commit_id': self.options.get('fix_reviewed', FIXED), 'user': {'login': self.options['reviewer']},
                 'state': 'COMMENTED', 'submitted_at': '2026-11-10T04:10:00Z'},
                {'commit_id': self.options['review_head'], 'user': {'login': self.options['reviewer']},
                 'state': self.options['earlier_state'], 'submitted_at': '2026-11-10T03:40:00Z'},
                {'commit_id': self.options['review_head'], 'user': {'login': self.options['reviewer']},
                 'state': self.options['review_state'], 'submitted_at': '2026-11-10T03:45:00Z'},
                {'commit_id': HEAD, 'user': {'login': 'claude[bot]'}, 'state': 'APPROVED',
                 'submitted_at': '2026-11-10T03:50:00Z'}])
        if args[:2] == ['api', 'graphql']:
            # Copilot's fix, once asked for, leaves `threads_after_fix` threads open.
            count = self.options.get('threads_after_fix', self.options['threads']) if self.asked else self.options['threads']
            nodes = [{'isResolved': False}] * count + [{'isResolved': True}]
            return 0, json.dumps({'data': {'repository': {'pullRequest': {'reviewThreads': {
                'nodes': nodes, 'pageInfo': {'hasNextPage': False, 'endCursor': None}}}}}})
        if args[:2] == ['pr', 'merge']:
            self.assert_merge(args)
            self.merged.append(int(args[2]))
            return 0, ''
        if args[:2] == ['pr', 'create']:
            self.created.append(args)
            return 0, 'https://github.com/owner/repo/pull/8\n'
        raise AssertionError('unexpected gh call: ' + ' '.join(args))

    def assert_merge(self, args):
        assert '--merge' in args and '--match-head-commit' in args, args
        assert not {'--admin', '--squash', '--rebase', '--auto'} & set(args), args


class PublishDailyDataTests(unittest.TestCase):
    def run_publish(self, **options):
        github = FakeGitHub(**options)
        with patch.object(publish, 'gh', github), patch.object(publish.time, 'sleep'), \
             patch.object(publish, 'CHECK_TIMEOUT', 0), patch.object(publish, 'REVIEW_TIMEOUT', 0), \
             patch.object(publish, 'FIX_TIMEOUT', 0), \
             patch.object(sys, 'argv', ['publish', '--repo', REPO, '--branch', BRANCH, '--head', HEAD,
                                        '--develop', STARTED]), \
             patch('builtins.print') as out:
            code = publish.main()
        return code, github, ' '.join(str(call.args[0]) for call in out.call_args_list)

    def test_clean_data_is_merged_then_promoted_through_pull_requests(self):
        code, github, log = self.run_publish()
        self.assertEqual((code, github.merged), (0, [7, 8]))
        created = github.created[0]
        self.assertEqual((created[created.index('--base') + 1], created[created.index('--head') + 1]), ('main', 'develop'))
        self.assertEqual((github.asked, github.deleted), ([], [f'repos/{REPO}/git/refs/heads/{BRANCH}']))

    def test_failed_or_pending_checks_leave_the_pull_request_open(self):
        for bucket in ('fail', 'pending', 'cancel'):
            code, github, log = self.run_publish(data_checks=bucket)
            self.assertEqual((code, github.merged), (1, []), bucket)
            self.assertIn('::error::Daily data was not published automatically', log)

    def test_review_must_cover_the_exact_head_by_the_automatic_reviewer(self):
        # A look-alike account must not satisfy the gate.
        for options in (dict(review_head='d' * 40), dict(reviewer='someone'), dict(reviewer='copilot-reviewer'),
                        dict(reviewer='Copilot-Pull-Request-Reviewer[bot]x')):
            code, github, log = self.run_publish(**options)
            self.assertEqual((code, github.merged), (1, []))
            self.assertIn('automatic review did not finish', log)

    def test_blocking_or_dismissed_review_needs_a_person(self):
        # A body-only review leaves no thread, so its state has to be read.
        for state in ('CHANGES_REQUESTED', 'DISMISSED', 'PENDING'):
            code, github, log = self.run_publish(review_state=state)
            self.assertEqual((code, github.merged), (1, []), state)
            self.assertIn('automatic review is', log)
        # Only the latest review on the commit counts.
        code, github, _ = self.run_publish(earlier_state='CHANGES_REQUESTED', review_state='APPROVED')
        self.assertEqual((code, github.merged), (0, [7, 8]))

    def test_open_review_thread_is_handed_to_copilot_once(self):
        # Copilot is asked; a thread it leaves open still needs a person.
        code, github, log = self.run_publish(threads=1)
        self.assertEqual((code, github.merged, len(github.asked)), (1, [], 1))
        self.assertTrue(github.asked[0].startswith('@copilot '))
        self.assertIn('did not clear the open review threads', log)

    def test_copilot_fix_is_merged_when_it_is_only_data_reviewed_and_clean(self):
        fixed = dict(threads=2, threads_after_fix=0, fix_head=FIXED, merge_parents=[STARTED, FIXED])
        code, github, log = self.run_publish(**fixed)
        self.assertEqual((code, github.merged, len(github.asked)), (0, [7, 8], 1))
        self.assertIn('Copilot fixed #7', log)
        # Threads cleared with no commit: the run's own commit is merged.
        code, github, _ = self.run_publish(threads=1, threads_after_fix=0)
        self.assertEqual((code, github.merged), (0, [7, 8]))
        for refused, reason in ((dict(fix_authors=['Copilot', 'someone']), 'not Copilot fixes'),
                                (dict(fix_authors=[]), 'not Copilot fixes'),
                                (dict(fix_status='diverged'), 'not Copilot fixes'),
                                (dict(fix_files=['models.json', 'scripts/scoring.py']), 'not generated data'),
                                (dict(fix_reviewed='d' * 40), 'automatic review did not finish')):
            code, github, log = self.run_publish(**fixed, **refused)
            self.assertEqual((code, github.merged), (1, []), refused)
            self.assertIn(reason, log)

    def test_only_a_daily_data_pull_request_into_develop_is_published(self):
        code, github, _ = self.run_publish(base='main')
        self.assertEqual((code, github.merged, github.created), (1, [], []))

    def test_only_the_commit_this_run_pushed_and_only_data_files_are_merged(self):
        # Someone pushed to the branch after the run: not the generated commit.
        code, github, log = self.run_publish(data_head='d' * 40)
        self.assertEqual((code, github.merged), (1, []))
        self.assertIn('not the commit this run pushed', log)
        for extra in ('scripts/scoring.py', '.github/workflows/daily-scrape.yml', 'index.html', 'AGENTS.md',
                      'data/social_preview/x.png', 'social/nested/x.png', 'models.json.bak'):
            code, github, log = self.run_publish(files=['models.json', extra])
            self.assertEqual((code, github.merged), (1, []), extra)
            self.assertIn('not generated data: ' + extra, log)

    def test_pull_request_and_base_are_read_again_just_before_merging(self):
        # Retargeted, closed or pushed to while the checks and review ran.
        for later in (dict(baseRefName='main'), dict(state='CLOSED'), dict(headRefOid='d' * 40)):
            code, github, log = self.run_publish(stable_views=3, later=later)
            self.assertEqual((code, github.merged), (1, []), later)
            self.assertIn('changed while its checks and review ran', log)
        # develop moved after the first check but before the merge.
        code, github, log = self.run_publish(develop_moves_after=1)
        self.assertEqual((code, github.merged), (1, []))
        self.assertIn('develop changed while the checks and review ran', log)

    def test_recovery_message_matches_how_far_publication_got(self):
        _, _, log = self.run_publish(threads=1)
        self.assertIn('Review the open data pull request', log)
        # The data is merged; only the promotion is left.
        _, github, log = self.run_publish(promotion_checks='fail')
        self.assertEqual(github.merged, [7])
        self.assertIn('#7 is already merged into develop', log)
        self.assertIn('Promotion #8 is open', log)
        self.assertNotIn('Review the open data pull request', log)
        _, github, log = self.run_publish(merge_parents=['9' * 40, HEAD])
        self.assertIn('#7 is already merged into develop', log)
        self.assertIn('promote it to main by hand', log)

    def test_develop_must_be_the_commit_the_run_started_from(self):
        # Something else landed on develop during the run: do not merge at all.
        code, github, log = self.run_publish(develop_tip='9' * 40)
        self.assertEqual((code, github.merged, github.created), (1, [], []))
        self.assertIn('develop changed while the scrape ran', log)
        # It landed between the check and the merge: the data is in develop, but main is not touched.
        code, github, log = self.run_publish(merge_parents=['9' * 40, HEAD])
        self.assertEqual((code, github.merged, github.created), (1, [7], []))
        self.assertIn('did not start from', log)

    def test_promotion_stops_when_its_checks_fail_or_develop_moved(self):
        for options in (dict(promotion_checks='fail'), dict(promotion_head='e' * 40)):
            code, github, _ = self.run_publish(**options)
            self.assertEqual((code, github.merged), (1, [7]), 'data stays on develop; main is untouched')


if __name__ == '__main__':
    unittest.main()
