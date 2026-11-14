#!/usr/bin/env python3
"""Publish the daily data pull request when nothing in it needs a person.

    python scripts/publish_daily_data.py --repo OWNER/REPO --branch feature/daily-scrape-... \
        --head SHA --develop SHA

Merges the data pull request into develop, then opens and merges the
develop -> main promotion. Both are ordinary merge-commit pull requests; nothing
is pushed to develop or main. The data pull request must be the exact commit
this run pushed and may change only generated data files, so a later push to
the branch, or anything that is not data, is never merged here. The one
exception is Copilot's own fix: when the automatic review leaves a thread open,
Copilot is asked once to address it, and commits it adds on top of the run's
commit are accepted when they too change only generated data. Each merge
requires that:

- the required checks have passed on the exact head commit,
- for develop, the automatic review has finished on that commit,
- no review thread is open,
- develop is still the commit the run started from, so the promotion carries
  this run's data and nothing a person has not promoted.

Any other outcome leaves the pull request open and exits 1, so the run fails
and the workflow-failure email tells a person to merge it by hand.
"""
from preconditions import preconditions
import argparse
import json
import re
import subprocess
import sys
import time

POLL_SECONDS = 20
CHECK_TIMEOUT = 20 * 60
REVIEW_TIMEOUT = 20 * 60
FIX_TIMEOUT = 45 * 60
# The account GitHub's automatic review posts as. A substring match would let
# any account with a similar name satisfy the review gate.
REVIEWER = 'copilot-pull-request-reviewer[bot]'
# How a Copilot fix commit is recognised: GitHub commits and signs it on the
# agent's behalf, authored by the account that asked, with this trailer. Any
# other commit on the branch after the run's commit needs a person.
FIXER_TRAILER = 'Co-authored-by: copilot-swe-agent[bot] <'
# Posted with the write-capable token: Copilot acts only on a comment from an
# account with write access. What a fix may touch is spelled out in AGENTS.md.
FIX_REQUEST = ('@copilot Address every open review thread on this pull request by committing to this branch. '
               'Follow "Review findings on daily data pull requests" in AGENTS.md: check each finding against '
               'the cited source before changing anything, change only generated data, and regenerate and '
               'verify the publication.')
# The files a daily scrape generates. Code, workflows and pages are not data.
GENERATED = re.compile(r'(models\.json|current\.json|news\.json|og-image\.png|ig-image\.png|sitemap\.xml|llms\.txt'
                       r'|data/[^/]+\.jsonl?|social/[^/]+\.(png|json))')
THREADS = '''query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) { pullRequest(number: $number) {
    reviewThreads(first: 100, after: $cursor) { nodes { isResolved } pageInfo { hasNextPage endCursor } } } } }'''


class NeedsPerson(Exception):
    """Publication stopped; `recovery` says what a person has to do."""

    @preconditions(reason='text', recovery='?text')
    def __init__(self, reason, recovery=None):
        super().__init__(reason)
        self.recovery = recovery


@preconditions(args='sequence', check='bool')
def gh(args, check=True):
    """Run the GitHub CLI; returns (exit code, stdout)."""
    done = subprocess.run(['gh', *args], capture_output=True, text=True)
    if check and done.returncode:
        raise NeedsPerson(f"gh {' '.join(args[:3])} failed: {done.stderr.strip()[:200]}")
    return done.returncode, done.stdout


@preconditions(repo='nonempty', pr='positive_int', head='nonempty', timeout='nonnegative')
def wait_for_checks(repo, pr, head, timeout):
    """Block until every required check has passed on this head commit."""
    deadline = time.monotonic() + timeout
    while True:
        _, out = gh(['pr', 'checks', str(pr), '--repo', repo, '--required', '--json', 'name,bucket'], check=False)
        try:
            checks = json.loads(out or '[]')
        except ValueError:
            checks = []
        buckets = {check['bucket'] for check in checks}
        if buckets & {'fail', 'cancel'}:
            failed = sorted(c['name'] for c in checks if c['bucket'] in ('fail', 'cancel'))
            raise NeedsPerson('required checks failed: ' + ', '.join(failed))
        if checks and buckets <= {'pass', 'skipping'}:
            if pull_request(repo, pr)['headRefOid'] != head:
                raise NeedsPerson('the pull request head changed while its checks ran')
            return
        if time.monotonic() >= deadline:
            raise NeedsPerson('required checks did not finish in time')
        time.sleep(POLL_SECONDS)


@preconditions(repo='nonempty', pr='positive_int', head='nonempty', timeout='nonnegative')
def wait_for_review(repo, pr, head, timeout):
    """Block until the automatic reviewer has reviewed this head commit."""
    deadline = time.monotonic() + timeout
    while True:
        reviews, page = [], 1
        while True:  # every page: the decisive review may not be on the first
            _, out = gh(['api', f'repos/{repo}/pulls/{pr}/reviews?per_page=100&page={page}'])
            batch = json.loads(out)
            reviews += batch
            if len(batch) < 100:
                break
            page += 1
        mine = [review for review in reviews
                if review.get('commit_id') == head and (review.get('user') or {}).get('login') == REVIEWER]
        if mine:
            # The reviewer's latest word on this commit decides. A request for
            # changes, or a review that was dismissed, is not a finished review.
            latest = max(mine, key=lambda review: review.get('submitted_at') or '')
            if latest.get('state') not in ('COMMENTED', 'APPROVED'):
                raise NeedsPerson(f"the automatic review is {str(latest.get('state')).lower().replace('_', ' ')}")
            return
        if time.monotonic() >= deadline:
            raise NeedsPerson('the automatic review did not finish in time')
        time.sleep(POLL_SECONDS)


@preconditions(repo='nonempty', pr='positive_int')
def open_threads(repo, pr):
    """Number of unresolved review threads."""
    owner, name = repo.split('/', 1)
    count, cursor = 0, None
    while True:
        args = ['api', 'graphql', '-f', 'query=' + THREADS, '-F', f'owner={owner}', '-F', f'name={name}',
                '-F', f'number={pr}']
        if cursor:
            args += ['-F', f'cursor={cursor}']
        _, out = gh(args)
        payload = json.loads(out)
        if payload.get('errors'):
            raise NeedsPerson('review threads could not be read')
        threads = payload['data']['repository']['pullRequest']['reviewThreads']
        count += sum(not node['isResolved'] for node in threads['nodes'])
        if not threads['pageInfo']['hasNextPage']:
            return count
        cursor = threads['pageInfo']['endCursor']


@preconditions(commit='mapping')
def copilot_commit(commit):
    detail = commit.get('commit') or {}
    return ((commit.get('committer') or {}).get('login') == 'web-flow'
            and bool((detail.get('verification') or {}).get('verified'))
            and FIXER_TRAILER in (detail.get('message') or ''))


@preconditions(repo='nonempty', head='nonempty')
def release_checks(repo, head):
    """Start the workflow runs GitHub holds for approval on a Copilot push.

    Called only after the push is known to be Copilot's and to change nothing
    but generated data. A run that cannot be started leaves its check pending,
    and the wait for checks then stops for a person.
    """
    _, out = gh(['api', f'repos/{repo}/actions/runs?head_sha={head}&per_page=100'])
    for run in json.loads(out).get('workflow_runs') or []:
        if run.get('conclusion') == 'action_required':
            gh(['run', 'rerun', str(run['id']), '--repo', repo], check=False)


@preconditions(repo='nonempty', pr='positive_int', head='nonempty', timeout='nonnegative')
def copilot_fix(repo, pr, head, timeout):
    """Ask Copilot to clear the open review threads; returns the head to merge.

    Copilot commits its fix to the branch and the automatic review of that push
    resolves the threads the fix addressed. Nothing here resolves a thread: one
    that is still open when the time runs out needs a person. The branch may
    only have moved forward from the run's commit, by Copilot's commits alone.
    """
    gh(['pr', 'comment', str(pr), '--repo', repo, '--body', FIX_REQUEST])
    print(f'Review threads are open on #{pr}; asked Copilot to address them.')
    deadline = time.monotonic() + timeout
    while open_threads(repo, pr):
        if time.monotonic() >= deadline:
            raise NeedsPerson('Copilot did not clear the open review threads in time')
        time.sleep(POLL_SECONDS)
    fixed = pull_request(repo, pr)['headRefOid']
    if fixed != head:
        _, out = gh(['api', f'repos/{repo}/compare/{head}...{fixed}'])
        compared = json.loads(out)
        commits = compared.get('commits') or []
        if compared.get('status') != 'ahead' or not commits or not all(map(copilot_commit, commits)):
            raise NeedsPerson('the branch gained commits that are not Copilot fixes on top of this run')
        print(f'Copilot fixed #{pr} at {fixed[:7]}.')
    return fixed


@preconditions(repo='nonempty', pr='json')
def pull_request(repo, pr):
    _, out = gh(['pr', 'view', str(pr), '--repo', repo, '--json',
                 'number,state,headRefOid,baseRefName,headRefName,mergeCommit,isCrossRepository'])
    return json.loads(out)


@preconditions(repo='nonempty', pr='positive_int', head='nonempty', base='nonempty', review='bool', base_tip='?text')
def merge_when_clean(repo, pr, head, base, review, base_tip=None):
    """Merge with a merge commit once the gates hold; returns the merge commit.

    Checks and review take minutes. The pull request and its base are read
    again immediately before merging, so one that was retargeted, closed or
    pushed to in the meantime, or a base that moved, is not merged.
    """
    wait_for_checks(repo, pr, head, CHECK_TIMEOUT)
    if review:
        wait_for_review(repo, pr, head, REVIEW_TIMEOUT)
    if open_threads(repo, pr):
        raise NeedsPerson('a review thread is open')
    current = pull_request(repo, pr)
    if (current['state'] != 'OPEN' or current['baseRefName'] != base or current['headRefOid'] != head
            or current['isCrossRepository']):
        raise NeedsPerson('the pull request changed while its checks and review ran')
    if base_tip and branch_tip(repo, base) != base_tip:
        raise NeedsPerson(f'{base} changed while the checks and review ran')
    gh(['pr', 'merge', str(pr), '--repo', repo, '--merge', '--match-head-commit', head])
    merged = pull_request(repo, pr)
    if merged['state'] != 'MERGED' or merged['headRefOid'] != head or not merged.get('mergeCommit'):
        raise NeedsPerson('GitHub did not report the merge')
    return merged['mergeCommit']['oid']


@preconditions(repo='nonempty', branch='nonempty')
def branch_tip(repo, branch):
    _, out = gh(['api', f'repos/{repo}/git/ref/heads/{branch}'])
    return json.loads(out)['object']['sha']


@preconditions(repo='nonempty', pr='positive_int')
def changed_files(repo, pr):
    """Every path the pull request changes, including the old name of a rename."""
    paths, page = [], 1
    while True:
        _, out = gh(['api', f'repos/{repo}/pulls/{pr}/files?per_page=100&page={page}'])
        files = json.loads(out)
        for item in files:
            paths.extend(name for name in (item.get('filename'), item.get('previous_filename')) if name)
        if len(files) < 100:
            return paths
        page += 1


@preconditions(repo='nonempty', branch='nonempty', head='nonempty', started_from='nonempty')
def publish(repo, branch, head, started_from):
    data = pull_request(repo, branch)
    if (data['state'] != 'OPEN' or data['baseRefName'] != 'develop' or data['isCrossRepository']
            or not data['headRefName'].startswith('feature/daily-scrape-')):
        raise NeedsPerson('this is not an open daily data pull request into develop')
    # Only the commit this run generated, and only data. Anything pushed to
    # the branch afterwards, or any code, workflow or page change, needs review.
    if data['headRefOid'] != head:
        raise NeedsPerson('the pull request head is not the commit this run pushed')
    other = sorted(path for path in changed_files(repo, data['number']) if not GENERATED.fullmatch(path))
    if other:
        raise NeedsPerson('the pull request changes files that are not generated data: ' + ', '.join(other[:5]))
    # Anything merged into develop during the run would ride along to main.
    if branch_tip(repo, 'develop') != started_from:
        raise NeedsPerson('develop changed while the scrape ran')
    wait_for_checks(repo, data['number'], head, CHECK_TIMEOUT)
    wait_for_review(repo, data['number'], head, REVIEW_TIMEOUT)
    if open_threads(repo, data['number']):
        data['headRefOid'] = copilot_fix(repo, data['number'], head, FIX_TIMEOUT)
        other = sorted(path for path in changed_files(repo, data['number']) if not GENERATED.fullmatch(path))
        if other:
            raise NeedsPerson('the fix changes files that are not generated data: ' + ', '.join(other[:5]))
        if data['headRefOid'] != head:
            release_checks(repo, data['headRefOid'])
    develop = merge_when_clean(repo, data['number'], data['headRefOid'], 'develop', review=True,
                               base_tip=started_from)
    print(f"Merged data pull request #{data['number']} into develop at {develop[:7]}.")
    # A merged feature branch is never left behind. Failing to delete it does not undo the merge.
    gh(['api', '-X', 'DELETE', f"repos/{repo}/git/refs/heads/{data['headRefName']}"], check=False)
    try:
        promote(repo, data, develop, started_from)
    except NeedsPerson as reason:
        # The data pull request is merged; telling a person to merge it would mislead.
        raise NeedsPerson(str(reason), reason.recovery or
                          f"Data pull request #{data['number']} is already merged into develop. "
                          'Review develop and promote it to main by hand.') from reason


@preconditions(repo='nonempty', data='mapping', develop='nonempty', started_from='nonempty')
def promote(repo, data, develop, started_from):
    _, out = gh(['api', f'repos/{repo}/commits/{develop}'])
    parents = [parent['sha'] for parent in json.loads(out)['parents']]
    if parents != [started_from, data['headRefOid']]:
        raise NeedsPerson('the data merged onto a develop commit this run did not start from')
    _, url = gh(['pr', 'create', '--repo', repo, '--base', 'main', '--head', 'develop',
                 '--title', f"Publish daily data from #{data['number']}",
                 '--body', f"Promotes #{data['number']}. Opened and merged by the daily scrape after its "
                           'required checks passed and its automatic review left no open thread.'])
    promotion = int(url.strip().rsplit('/', 1)[-1])
    waiting = (f"Data pull request #{data['number']} is already merged into develop. "
               f'Promotion #{promotion} is open: review and merge it by hand.')
    if pull_request(repo, promotion)['headRefOid'] != develop:
        raise NeedsPerson(f'develop moved before promotion #{promotion} was opened', waiting)
    try:
        main = merge_when_clean(repo, promotion, develop, 'main', review=False)
    except NeedsPerson as reason:
        raise NeedsPerson(str(reason), waiting) from reason
    print(f'Promoted develop to main at {main[:7]} through #{promotion}.')


@preconditions()
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--branch', required=True)
    parser.add_argument('--head', required=True, help='The commit this run pushed to the branch')
    parser.add_argument('--develop', required=True, help='The develop commit the run started from')
    args = parser.parse_args()
    try:
        publish(args.repo, args.branch, args.head, args.develop)
    except NeedsPerson as reason:
        recovery = reason.recovery or 'Review the open data pull request, then merge it and promote develop by hand.'
        print(f'::error::Daily data was not published automatically: {reason}. {recovery}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
