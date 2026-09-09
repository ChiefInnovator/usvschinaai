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
