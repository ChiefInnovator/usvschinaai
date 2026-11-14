# Model records and dated rosters

The shared model catalog is the source of benchmark evidence for all history.
This replaces the repeated model/benchmark rows previously stored in each snapshot.

Only benchmarks configured in `data/core_benchmarks.json` are supported for scoring and gap filling. Leaderboard and model-detail imports accept only those benchmark names and aliases. Snapshot imports also drop other benchmark columns and their provenance; they are not retained as model metadata. Evidence ingestion rejects unsupported benchmark components.

- `data/model_catalog.json` stores each exact model once, indexed by a stable ID derived from its name. Its `benchmarks` collection stores dated observations by benchmark and evidence ID, including the score, source, configuration, and availability/retrieval dates. Corrections and exclusions update that observation once.
- The model's `profiles` collection deduplicates descriptive metadata and pricing. A historical roster references the profile it observed, preserving historical prices and avoiding accidental changes to Avg Value when a model's current price changes.
- `models.json` stores all snapshot timestamps and their US/China roster references (`modelId`, `profileId`). Rows also contain reproducible `avgIq`, `value`, `unified`, `coverage`, and `provisional` outputs. Rows contain no benchmark scores or source records.
- `current.json` contains the latest reference-only snapshot for the home page.
- `data/historical_benchmark_gaps.json` is a generated audit of missing model/benchmark pairs across dated rosters. Research finding files and AI logs are intake/audit artifacts; they are not alternative scoring inputs.

The former `data/historical_benchmark_evidence.json` has been migrated into the catalog and removed. The local rollback checkpoint is commit `9c3f364` on `feature/capability-scoring`.

## Updating a benchmark once

Research can be performed in the current assistant subscription; an OpenAI API call is not required to ingest findings. Record cited findings using the existing research JSON format, then run:

```sh
.venv/bin/python scripts/ingest_benchmark_findings.py findings.json --write
.venv/bin/python scripts/rescore_history.py --write --refresh-images
.venv/bin/python scripts/validate_models.py
```

The ingester updates the model's central observations. Rescoring visits every historical roster, resolves its references, selects the highest verified score available on that snapshot's date, and refreshes the derived scores and gap report. Missing benchmarks contribute zero in the fixed denominator. Effort does not restrict score selection. Model releases, benchmark versions/subsets, and evidence availability dates still apply.

New evidence with a verified earlier publication date can fill all applicable historical dates with one update. An undated finding starts at its retrieval date; it does not silently backdate to the model's release. This preserves the existing historical applicability policy.

The daily scraper uses the same catalog and rescoring path after recording its new roster. Roster membership on earlier dates is preserved. Repeating a rescore with unchanged evidence/configuration produces the same stored data.

## Consumers and validation

Python readers use `model_store.load_data()` to hydrate model references. The browser uses `js/model-store.js` to expand the same references before passing data to the existing renderers. The leaderboard, benchmark preview, navigation, matrix, 30-day chart, archive, and image templates retain their existing UI.

Model and profile references fail loudly if missing. Tests verify deduplication, historical pricing, one evidence update affecting multiple dates, exclusion/correction handling, date boundaries, repeatable rescoring, and identical Python/browser hydration.

The migration command is `python scripts/model_store.py`. It retains all existing snapshots, imports dated benchmark evidence, and conservatively records any additional retained benchmark values at their first observed snapshot date. Git is the rollback source; no legacy score archive is created.

Writes use a durable `.model-store-pending.json` transaction. The next Python read finishes an interrupted catalog/history/current update and removes the journal. See [Testing and preconditions](testing.md) for recovery, integration, and caller-contract tests.


## Scoring revisions and complete publication

Every algorithm change requires a full rescore of all retained dates. Use
`python scripts/prepare_publication.py --write`, then run the same command without
`--write` to independently verify replay. Historical dates, roster/model/profile
identity and prices are preserved; current and historical results share the new
scoring revision. The revision inventories configuration, pins and transitive
local scoring dependencies. It does not substitute for replay.

`data/site_summary.json` is a generated lightweight public projection;
`data/scoring_revision.json` records the algorithm fingerprint;
`data/publication.json` certifies artifact hashes and the data generation.
Preparation uses a complete copied script tree in a fresh subprocess so root
constants and configuration caches cannot read the live checkout by accident.
Scores, gap audit, summary and snapshot-time image/social outputs are staged and
validated together before installation. It uses deterministic captions and never
researches or posts remotely. Verification checks installed image digests rather
than comparing PNG rendering across operating systems.

`.publication-pending.json` is the durable installation intent. Recovery verifies
paths and bytes, installs data/images, writes the publication manifest last and
removes the journal. A failed render before installation leaves the old publication
untouched. Do not deploy while either writer journal exists. Git remains the
rollback source; restore a complete verified artifact for immediate site rollback.

## Unmerged daily publications

The daily scrape publishes its own data when nothing needs a person
(`scripts/publish_daily_data.py`): it merges its pull request into develop and
promotes develop to main, both as merge-commit pull requests. It does so only
when the pull request is the exact commit the run pushed and changes only
generated data files, the required checks pass on that commit, the automatic
reviewer's latest review of it neither requests changes nor was dismissed and
left no open thread, every develop commit was already on main before the run,
develop did not move during it, and the run was not built on an unmerged daily
pull request. Otherwise the step fails, the pull request stays open, and the
failure email asks for a manual merge. Backfill pull requests and code changes
are never published automatically.

When the automatic review leaves a thread open, the step asks Copilot once, in
a pull request comment, to fix it. Copilot follows "Review findings on daily
data pull requests" in `AGENTS.md`: it checks the finding against the cited
source, retracts a wrong result with `scripts/retract_ai_fill.py` and
regenerates the publication. Its commits are accepted only on top of the run's
commit and only when they change generated data. The review of that push
resolves the threads the fix addressed; the step resolves none itself. The
same checks, review and thread gates then apply to the new commit. A thread
still open after 45 minutes fails the step as before.

A Copilot commit is recognised by how GitHub records it: committed and signed
by GitHub, with a `Co-authored-by: copilot-swe-agent[bot]` trailer. GitHub
holds the workflow runs on such a push for approval. The step starts them
itself, but only after confirming the push is Copilot's and changes nothing
but generated data, so that approval setting can stay on.

This needs the Copilot cloud agent enabled for the repository.
`.github/workflows/copilot-setup-steps.yml` prepares its environment. The
agent's firewall must allow `fonts.googleapis.com` and `fonts.gstatic.com`
(repository Settings, Copilot, Internet access): the social slides load their
fonts from there, and a blocked request renders them in fallback fonts without
failing.

A daily pull request can therefore still be open when
the next scrape starts. Building that run on develop alone would omit the
waiting snapshot and conflict with it at merge. The daily workflow therefore
builds on develop plus the newest open `feature/daily-scrape-*` branch when all
of these hold: the branch changes only generated data (JSON, JSONL, images,
sitemap, `llms.txt`), it merges into develop without conflict, and
`prepare_publication.py` verifies the result under develop's code. Otherwise it
builds on develop alone and says why in a warning. The new pull request contains
the earlier one, so merging it merges both.

The health check follows the same model. It fails when no snapshot has been
produced for 30 hours, counting develop and open daily pull requests, or when
the published snapshot is more than 72 hours old. A published snapshot older
than 30 hours with a newer one awaiting promotion is a warning. The page shows
its own notice once the published snapshot is older than 36 hours.
