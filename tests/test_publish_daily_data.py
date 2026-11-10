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
HEAD, DEVELOP, MAIN = 'a' * 40, 'b' * 40, 'c' * 40


class FakeGitHub:
    """Answers the gh calls the publisher makes and records every mutation."""

    def __init__(self, **options):
        self.options = dict(data_checks='pass', promotion_checks='pass', review_head=HEAD,
                            reviewer='copilot-pull-request-reviewer[bot]', threads=0,
                            base='develop', promotion_head=DEVELOP)
        self.options.update(options)
        self.merged, self.created = [], []

    def pull(self, number):
        if number == 7:
            return dict(number=7, state='MERGED' if 7 in self.merged else 'OPEN', headRefOid=HEAD,
                        baseRefName=self.options['base'], headRefName=BRANCH, isCrossRepository=False,
                        mergeCommit={'oid': DEVELOP} if 7 in self.merged else None)
        return dict(number=8, state='MERGED' if 8 in self.merged else 'OPEN',
                    headRefOid=self.options['promotion_head'], baseRefName='main', headRefName='develop',
                    isCrossRepository=False, mergeCommit={'oid': MAIN} if 8 in self.merged else None)

    def __call__(self, args, check=True):
        if args[:2] == ['pr', 'view']:
            return 0, json.dumps(self.pull(7 if args[2] in (BRANCH, '7') else 8))
        if args[:2] == ['pr', 'checks']:
            bucket = self.options['data_checks' if args[2] == '7' else 'promotion_checks']
            return 0, json.dumps([{'name': 'test', 'bucket': bucket}, {'name': 'verify_build', 'bucket': 'pass'}])
        if args[0] == 'api' and 'graphql' not in args:
            return 0, json.dumps([{'commit_id': self.options['review_head'],
                                   'user': {'login': self.options['reviewer']}},
                                  {'commit_id': HEAD, 'user': {'login': 'claude[bot]'}}])
        if args[:2] == ['api', 'graphql']:
            nodes = [{'isResolved': False}] * self.options['threads'] + [{'isResolved': True}]
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
             patch.object(sys, 'argv', ['publish', '--repo', REPO, '--branch', BRANCH]), patch('builtins.print') as out:
            code = publish.main()
        return code, github, ' '.join(str(call.args[0]) for call in out.call_args_list)

    def test_clean_data_is_merged_then_promoted_through_pull_requests(self):
        code, github, log = self.run_publish()
        self.assertEqual((code, github.merged), (0, [7, 8]))
        created = github.created[0]
        self.assertEqual((created[created.index('--base') + 1], created[created.index('--head') + 1]), ('main', 'develop'))

    def test_failed_or_pending_checks_leave_the_pull_request_open(self):
        for bucket in ('fail', 'pending', 'cancel'):
            code, github, log = self.run_publish(data_checks=bucket)
            self.assertEqual((code, github.merged), (1, []), bucket)
            self.assertIn('::error::Daily data was not published automatically', log)

    def test_review_must_cover_the_exact_head_by_the_automatic_reviewer(self):
        for options in (dict(review_head='d' * 40), dict(reviewer='someone')):
            code, github, log = self.run_publish(**options)
            self.assertEqual((code, github.merged), (1, []))
            self.assertIn('automatic review did not finish', log)

    def test_open_review_thread_needs_a_person(self):
        code, github, log = self.run_publish(threads=1)
        self.assertEqual((code, github.merged), (1, []))
        self.assertIn('review thread is open', log)

    def test_only_a_daily_data_pull_request_into_develop_is_published(self):
        code, github, _ = self.run_publish(base='main')
        self.assertEqual((code, github.merged, github.created), (1, [], []))

    def test_promotion_stops_when_its_checks_fail_or_develop_moved(self):
        for options in (dict(promotion_checks='fail'), dict(promotion_head='e' * 40)):
            code, github, _ = self.run_publish(**options)
            self.assertEqual((code, github.merged), (1, [7]), 'data stays on develop; main is untouched')


if __name__ == '__main__':
    unittest.main()
