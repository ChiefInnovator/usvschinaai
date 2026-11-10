# US vs China AI

- Never display benchmark weight percentages in the UI; show benchmark names only.

- Always upgrade dependencies. Keep Playwright unpinned so workflows install its
  latest stable release; retain dependency freshness and compatibility checks.

- Branch flow is same-repository feature branch -> develop -> main. A feature
  branch is any nonempty branch other than main, develop or master.
- Never push directly to main or develop. Use merge-commit pull requests;
  main accepts only develop, and develop accepts only feature branches.
- GitHub Copilot automatically reviews pull requests targeting develop only.
- Daily scrape and backfill open feature pull requests into develop. Data goes
  live only after develop is promoted to main through a pull request.
- The daily scrape publishes its own data: it merges its pull request and
  promotes develop to main, both as merge-commit pull requests, only when its
  pull request is the exact commit the run pushed and changes only generated
  data, required checks pass, the automatic review is complete with no open
  thread, develop held nothing unpromoted before the run and did not move
  during it, and the run was not built on an unmerged daily pull request.
  Otherwise it stops and a person merges.
  Code changes and backfill pull requests are always merged and promoted by a
  person; do not extend automatic publication to them.

- Every scoring algorithm change requires a full rescore of every retained
  historical snapshot before publication. This includes benchmark selection,
  weights, normalization, missing results, Value and evidence-selection logic.
- Preserve historical timestamps, roster membership and dated price profiles.
  History shows recalculated results under the current algorithm; never mix
  scoring revisions in a published graph or archive.
- Prepare and verify the complete publication before deployment. Never run
  paid research or remote social publishing as part of tests or a site build.
