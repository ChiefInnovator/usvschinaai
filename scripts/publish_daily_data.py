#!/usr/bin/env python3
"""Publish the daily data pull request when nothing in it needs a person.

    python scripts/publish_daily_data.py --repo OWNER/REPO --branch feature/daily-scrape-... --develop SHA

Merges the data pull request into develop, then opens and merges the
develop -> main promotion. Both are ordinary merge-commit pull requests; nothing
is pushed to develop or main. Each merge requires that:

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
import subprocess
import sys
import time

POLL_SECONDS = 20
CHECK_TIMEOUT = 20 * 60
REVIEW_TIMEOUT = 20 * 60
# The account GitHub's automatic review posts as. A substring match would let
# any account with a similar name satisfy the review gate.
REVIEWER = 'copilot-pull-request-reviewer[bot]'
THREADS = '''query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) { pullRequest(number: $number) {
    reviewThreads(first: 100, after: $cursor) { nodes { isResolved } pageInfo { hasNextPage endCursor } } } } }'''


class NeedsPerson(Exception):
    """The pull request was left open for a manual merge."""


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
        _, out = gh(['api', f'repos/{repo}/pulls/{pr}/reviews?per_page=100'])
        reviews = json.loads(out)
        if any(review.get('commit_id') == head and (review.get('user') or {}).get('login') == REVIEWER
               for review in reviews):
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


@preconditions(repo='nonempty', pr='json')
def pull_request(repo, pr):
    _, out = gh(['pr', 'view', str(pr), '--repo', repo, '--json',
                 'number,state,headRefOid,baseRefName,headRefName,mergeCommit,isCrossRepository'])
    return json.loads(out)


@preconditions(repo='nonempty', pr='positive_int', head='nonempty', review='bool')
def merge_when_clean(repo, pr, head, review):
    """Merge with a merge commit once the gates hold; returns the merge commit."""
    wait_for_checks(repo, pr, head, CHECK_TIMEOUT)
    if review:
        wait_for_review(repo, pr, head, REVIEW_TIMEOUT)
    if open_threads(repo, pr):
        raise NeedsPerson('a review thread is open')
    gh(['pr', 'merge', str(pr), '--repo', repo, '--merge', '--match-head-commit', head])
    merged = pull_request(repo, pr)
    if merged['state'] != 'MERGED' or merged['headRefOid'] != head or not merged.get('mergeCommit'):
        raise NeedsPerson('GitHub did not report the merge')
    return merged['mergeCommit']['oid']


@preconditions(repo='nonempty', branch='nonempty')
def branch_tip(repo, branch):
    _, out = gh(['api', f'repos/{repo}/git/ref/heads/{branch}'])
    return json.loads(out)['object']['sha']


@preconditions(repo='nonempty', branch='nonempty', started_from='nonempty')
def publish(repo, branch, started_from):
    data = pull_request(repo, branch)
    if (data['state'] != 'OPEN' or data['baseRefName'] != 'develop' or data['isCrossRepository']
            or not data['headRefName'].startswith('feature/daily-scrape-')):
        raise NeedsPerson('this is not an open daily data pull request into develop')
    # Anything merged into develop during the run would ride along to main.
    if branch_tip(repo, 'develop') != started_from:
        raise NeedsPerson('develop changed while the scrape ran')
    develop = merge_when_clean(repo, data['number'], data['headRefOid'], review=True)
    print(f"Merged data pull request #{data['number']} into develop at {develop[:7]}.")
    _, out = gh(['api', f'repos/{repo}/commits/{develop}'])
    parents = [parent['sha'] for parent in json.loads(out)['parents']]
    if parents != [started_from, data['headRefOid']]:
        raise NeedsPerson('the data merged onto a develop commit this run did not start from; promote by hand')
    _, url = gh(['pr', 'create', '--repo', repo, '--base', 'main', '--head', 'develop',
                 '--title', f"Publish daily data from #{data['number']}",
                 '--body', f"Promotes #{data['number']}. Opened and merged by the daily scrape after its "
                           'required checks passed and its automatic review left no open thread.'])
    promotion = int(url.strip().rsplit('/', 1)[-1])
    if pull_request(repo, promotion)['headRefOid'] != develop:
        raise NeedsPerson(f'develop moved before promotion #{promotion} was opened')
    main = merge_when_clean(repo, promotion, develop, review=False)
    print(f'Promoted develop to main at {main[:7]} through #{promotion}.')


@preconditions()
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--branch', required=True)
    parser.add_argument('--develop', required=True, help='The develop commit the run started from')
    args = parser.parse_args()
    try:
        publish(args.repo, args.branch, args.develop)
    except NeedsPerson as reason:
        print(f'::error::Daily data was not published automatically: {reason}. '
              'Merge the open pull request and promote develop by hand.')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
