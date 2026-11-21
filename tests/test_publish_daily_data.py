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
HEAD, DEVELOP, MAIN, STARTED, FIXED, CARRIED = 'a' * 40, 'b' * 40, 'c' * 40, 'f' * 40, '5' * 40, '6' * 40
ASKED = '2026-11-10T03:46:00Z'
FIXER = {'login': 'copilot-swe-agent', '__typename': 'Bot'}
# The superseded daily pull request whose head is one of #7's commits.
SUPERSEDED = {'number': 5, 'state': 'CLOSED', 'headRefName': 'feature/daily-scrape-0-1', 'headRefOid': CARRIED}


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
        self.merged, self.created, self.views, self.asked, self.deleted, self.released = [], [], 0, [], [], []
        self.resolved = []

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
        if args == ['api', 'user']:
            return 0, json.dumps({'login': 'owner'})
        if args[:3] == ['api', '-X', 'POST'] and args[3].endswith('/issues/7/comments'):
            self.asked.append(args[5][len('body='):])
            return 0, json.dumps({'created_at': ASKED})
        if args[0] == 'api' and '/timeline?' in args[1]:
            # The automatic reviewer's own work events, then what the fixer has reported so far.
            reviewer = {'slug': 'copilot-pull-request-reviewer'}
            events = [{'event': 'copilot_work_finished', 'created_at': '2026-11-10T03:47:00Z',
                       'performed_via_github_app': reviewer},
                      {'event': 'copilot_work_finished_failure', 'created_at': '2026-11-10T03:47:00Z',
                       'performed_via_github_app': reviewer},
                      {'event': 'copilot_work_finished', 'created_at': '2026-11-10T03:30:00Z',
                       'performed_via_github_app': {'slug': 'copilot-swe-agent'}}]
            if self.options.get('fix_event'):
                events.append({'event': self.options['fix_event'], 'created_at': '2026-11-10T03:50:00Z',
                               'performed_via_github_app': {'slug': self.options.get('fix_app', 'copilot-swe-agent')}})
            return 0, json.dumps(events)
        if args[0] == 'api' and '/pulls/7/commits?' in args[1]:
            return 0, json.dumps([{'sha': sha} for sha in self.options.get('commits', [HEAD])])
        if args[:2] == ['pr', 'list']:
            return 0, json.dumps(self.options.get('pulls', []))
        if args[:3] == ['api', '-X', 'DELETE']:
            self.deleted.append(args[3])
            return 0, ''
        if args[0] == 'api' and '/compare/' in args[1]:
            # As GitHub reports a Copilot commit: signed and committed by GitHub, with the agent's trailer.
            copilot = {'author': {'login': 'owner'}, 'committer': {'login': 'web-flow'}, 'commit': {
                'verification': {'verified': True},
                'message': 'Fix\n\nCo-authored-by: copilot-swe-agent[bot] <198982749+Copilot@users.noreply.github.com>'}}
            return 0, json.dumps({'status': self.options.get('fix_status', 'ahead'),
                                  'commits': self.options.get('fix_commits', [copilot])})
        if args[0] == 'api' and '/actions/runs?head_sha=' in args[1]:
            return 0, json.dumps({'workflow_runs': [{'id': 11, 'conclusion': 'action_required'},
                                                    {'id': 12, 'conclusion': 'success'}]})
        if args[:2] == ['run', 'rerun']:
            self.released.append(args[2])
            return 0, ''
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
        if args[:2] == ['api', 'graphql'] and args[3].startswith('query=mutation'):
            self.resolved.append(args[5][len('thread='):])
            return 0, json.dumps({'data': {'resolveReviewThread': {'thread': {'isResolved': True}}}})
        if args[:2] == ['api', 'graphql'] and 'number=5' in args:
            nodes = [{'id': 'old', 'isResolved': False}] * self.options.get('carried_threads', 0)
            return 0, json.dumps({'data': {'repository': {'pullRequest': {'reviewThreads': {
                'nodes': nodes, 'pageInfo': {'hasNextPage': False, 'endCursor': None}}}}}})
        if args[:2] == ['api', 'graphql']:
            # Copilot's fix, once asked for, leaves `threads_after_fix` threads open.
            count = self.options.get('threads_after_fix', self.options['threads']) if self.asked else self.options['threads']
            finding = {'author': {'login': 'copilot-pull-request-reviewer', '__typename': 'Bot'},
                       'createdAt': '2026-11-10T03:45:00Z', 'body': 'Fixed: this value is wrong.'}
            # `replies` are the latest comment on each thread once Copilot was asked.
            replies = self.options.get('replies', []) if self.asked else []
            nodes = [{'id': f'thread-{index}', 'isResolved': f'thread-{index}' in self.resolved, 'comments': {'nodes': [
                dict({'author': FIXER, 'createdAt': '2026-11-10T03:49:00Z'}, **replies[index])
                if index < len(replies) else finding]}} for index in range(count)] + [{'id': 'done', 'isResolved': True}]
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
        self.assertEqual(github.released, ['11'], 'only the runs held for approval are started')
        # Threads cleared with no commit: the run's own commit is merged.
        code, github, _ = self.run_publish(threads=1, threads_after_fix=0)
        self.assertEqual((code, github.merged, github.released), (0, [7, 8], []))
        trailer = 'x\n\nCo-authored-by: copilot-swe-agent[bot] <a@b>'
        signed = {'author': {'login': 'owner'}, 'committer': {'login': 'web-flow'},
                  'commit': {'verification': {'verified': True}, 'message': 'Edit'}}
        pushed = {'author': {'login': 'owner'}, 'committer': {'login': 'owner'},
                  'commit': {'verification': {'verified': False}, 'message': trailer}}
        # A web edit by someone else who added the trailer.
        other = {'author': {'login': 'someone'}, 'committer': {'login': 'web-flow'},
                 'commit': {'verification': {'verified': True}, 'message': trailer}}
        for refused, reason in ((dict(fix_commits=[signed]), 'not Copilot fixes'),
                                (dict(fix_commits=[pushed]), 'not Copilot fixes'),
                                (dict(fix_commits=[other]), 'not Copilot fixes'),
                                (dict(fix_commits=[]), 'not Copilot fixes'),
                                (dict(fix_status='diverged'), 'not Copilot fixes'),
                                (dict(fix_files=['models.json', 'scripts/scoring.py']), 'not generated data'),
                                (dict(fix_reviewed='d' * 40), 'automatic review did not finish')):
            code, github, log = self.run_publish(**fixed, **refused)
            self.assertEqual((code, github.merged), (1, []), refused)
            self.assertIn(reason, log)

    def test_threads_copilot_answered_are_resolved_and_the_data_published(self):
        # The November 16 stall: Copilot showed the finding wrong, changed nothing, and the thread stayed open.
        answered = dict(threads=2, fix_event='copilot_work_finished', replies=[
            {'body': 'No change needed: the source lists that model separately.'}, {'body': '**Fixed:** retracted.'}])
        code, github, log = self.run_publish(**answered)
        self.assertEqual((code, github.merged, github.resolved), (0, [7, 8], ['thread-0', 'thread-1']))
        self.assertIn('resolved 2', log)
        self.assertIn('"No change needed:"', github.asked[0])
        # With a fix commit the same gates apply to the new head.
        code, github, _ = self.run_publish(**answered, fix_head=FIXED, merge_parents=[STARTED, FIXED])
        self.assertEqual((code, github.merged, github.released), (0, [7, 8], ['11']))

    def test_thread_copilot_did_not_settle_needs_a_person(self):
        settled = {'body': 'Fixed: retracted.'}
        for reply in ({'body': 'Needs a person: the label is set in code.'}, {'body': 'I looked at this.'},
                      {'body': 'Fixed: x', 'createdAt': '2026-11-10T03:40:00Z'},
                      {'body': 'Fixed: x', 'author': {'login': 'copilot-swe-agent', '__typename': 'User'}},
                      {'body': 'Fixed: x', 'author': {'login': 'someone', '__typename': 'Bot'}}):
            code, github, log = self.run_publish(threads=2, fix_event='copilot_work_finished', replies=[settled, reply])
            self.assertEqual((code, github.merged, github.resolved), (1, [], []), reply)
            self.assertIn('left a review thread for a person', log)
        # A thread Copilot never reached is not settled either.
        code, github, log = self.run_publish(threads=2, fix_event='copilot_work_finished', replies=[settled])
        self.assertEqual((code, github.merged, github.resolved), (1, [], []))
        # Replies alone are not the end of the work: a commit may still follow.
        code, github, log = self.run_publish(threads=1, replies=[settled])
        self.assertEqual((code, github.merged, github.resolved), (1, [], []))
        self.assertIn('did not clear the open review threads', log)
        # Only the fixer's own events count, and its failure stops at once.
        code, github, log = self.run_publish(threads=1, replies=[settled], fix_event='copilot_work_finished',
                                             fix_app='copilot-pull-request-reviewer')
        self.assertEqual((code, github.resolved), (1, []))
        code, github, log = self.run_publish(threads=1, replies=[settled], fix_event='copilot_work_finished_failure')
        self.assertEqual((code, github.merged, github.resolved), (1, [], []))
        self.assertIn('could not finish', log)

    def test_data_carried_from_a_superseded_pull_request_publishes_unless_its_thread_is_open(self):
        carried = dict(commits=[CARRIED, HEAD], pulls=[SUPERSEDED])
        code, github, _ = self.run_publish(**carried)
        self.assertEqual((code, github.merged), (0, [7, 8]))
        code, github, log = self.run_publish(**carried, carried_threads=1)
        self.assertEqual((code, github.merged, github.asked), (1, [], []))
        self.assertIn('#5, whose data this pull request carries, has an open review thread', log)
        self.assertIn('Resolve the thread on #5', log)
        # Merged, not a daily scrape, or not among this pull request's commits: not carried.
        for other in (dict(SUPERSEDED, state='MERGED'), dict(SUPERSEDED, headRefName='feature/site'),
                      dict(SUPERSEDED, headRefOid='d' * 40)):
            code, github, _ = self.run_publish(commits=[CARRIED, HEAD], pulls=[other], carried_threads=1)
            self.assertEqual((code, github.merged), (0, [7, 8]), other)

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
