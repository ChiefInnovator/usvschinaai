// Executed only from the trusted pull_request_target base checkout.
module.exports = async ({ github, context, core }) => {
  const { owner, repo } = context.repo;
  const { data: pr } = await github.rest.pulls.get({ owner, repo, pull_number: context.issue.number });
  const repository = `${owner}/${repo}`;
  const sameRepository = pr.head.repo?.full_name === repository && pr.base.repo?.full_name === repository;
  const target = pr.base.ref;
  if (!['main', 'develop'].includes(target)) throw new Error('Unexpected target branch');
  const source = pr.head.ref;
  const valid = sameRepository && (target === 'main'
    ? source === 'develop'
    : Boolean(source) && !['main', 'develop', 'master'].includes(source));
  const description = target === 'main'
    ? 'main accepts only same-repository develop pull requests'
    : 'develop accepts only same-repository feature pull requests';
  try {
    await github.rest.repos.createCommitStatus({
    owner, repo, sha: pr.head.sha,
    context: `Branch source policy / ${target}`,
    state: valid ? 'success' : 'failure', description,
    target_url: `https://github.com/${repository}/actions/runs/${context.runId}`,
    });
  } catch (error) {
    // New fork SHAs may not exist in this repository. Fail closed; never leave
    // an accepted source without its mandatory exact-head status.
    if (valid) throw error;
    core.setFailed(`${description}; status could not be posted for the disallowed source`);
    return;
  }
  if (!valid) core.setFailed(description);
};
