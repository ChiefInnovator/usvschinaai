# US vs China AI

- Never display benchmark weight percentages in the UI; show benchmark names only.

- Branch flow is same-repository feature branch -> develop -> main. A feature
  branch is any nonempty branch other than main, develop or master.
- Never push directly to main or develop. Use merge-commit pull requests;
  main accepts only develop, and develop accepts only feature branches.
- GitHub Copilot automatically reviews pull requests targeting develop only.
- Daily scrape and backfill open feature pull requests into develop. Data goes
  live only after develop is promoted to main; do not bypass this for freshness.

- Every scoring algorithm change requires a full rescore of every retained
  historical snapshot before publication. This includes benchmark selection,
  weights, normalization, missing results, Value and evidence-selection logic.
- Preserve historical timestamps, roster membership and dated price profiles.
  History shows recalculated results under the current algorithm; never mix
  scoring revisions in a published graph or archive.
- Prepare and verify the complete publication before deployment. Never run
  paid research or remote social publishing as part of tests or a site build.
