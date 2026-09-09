# Historical benchmark rebuild

Run `.venv/bin/python scripts/rescore_history.py --rebuild --write --refresh-images`.
The rebuild retains historical timestamps, exact model cohorts and model
metadata/pricing. It clears every old benchmark and calculated score, applies
dated evidence for the configured eighteen benchmarks, and recalculates Avg IQ,
Value, Unified Score, coverage, badges and graph inputs. Without `--rebuild`,
replay retains selected raw results but still removes all legacy benchmark fields.

Evidence is stored separately in `data/model_catalog.json`, with
exact model/component, percentage, source, configuration and earliest supported
date. Stable retained observations for selected benchmarks are usable only from
their recorded observation date. Published evidence cannot be backdated before
its recorded availability. Records marked `excludedReason` are not used: this
includes known incompatible benchmark variants and model fallback configurations.

The result is written to `models.json` and `current.json`. Remaining missing
model/component/date combinations are recorded in
`data/historical_benchmark_gaps.json`. Missing results contribute zero within
the fixed 100% denominator. Value is recalculated from the new Avg IQ and retained
prices; no old Value inputs or frozen calculated scores remain.

Existing web graphs read the rebuilt history directly. `--refresh-images` also
renders OG/IG and local carousel exports through existing templates; it does not
publish posts or call a caption API. No UI layout changes are required.

The old undated cache backfill must not be used for historical evidence. Use the
rebuild command above. Verification checks exact model/date preservation, only
nineteen benchmark columns, removal of legacy scoring inputs, fixed-weight math,
evidence dates, unchanged UI files and replay idempotence.

## Rebuild verification (2026-09-06)

Rebuilt 233 snapshots spanning 225 dates (2026-01-23 through 2026-09-06),
retaining all 4,639 model rows in their original cohorts and order. Populated
25,934 date-applicable benchmark cells. Every row contains exactly nineteen
benchmark columns and no legacy Value input block. There remain 656 distinct
model/component pairs missing evidence on at least one historical date; those
cells contribute zero. Existing image exports were regenerated. The browser
loaded ten default leaderboard rows and the nineteen-benchmark summary without
JavaScript errors. The test suite ran 194 tests, with one existing skip.

## Expanded source research (2026-09-06)

Refreshed llm-stats detail pages for all 90 distinct retained models (zero fetch
failures), inspected Artificial Analysis model payloads and IFBench tables,
Toolathlon's original and Verified series, CharXiv's operator CSV, Databricks'
OfficeQA Pro figures, and official Qwen/NVIDIA model reports.

Nine additional evidence pairs were accepted, filling 64 cells across five
model/component pairs in retained history. Four findings have no applicable
retained snapshot on or after their verifiable availability date, so they are
kept as source evidence without backdating. Kimi K3 now has 12/12 results. Astra
remains 8/12: no usable exact Toolathlon, CharXiv-R, OfficeQA Pro or IFBench
result was verified in this pass. Current data, all historical scores and image
exports were regenerated through existing code and templates.

The audit is `data/benchmark_research_refresh.json`; accepted source findings
are `data/benchmark_research_findings.json`. The source harvester now reads
GPQA Diamond when matching configurations. Excluded evidence no longer blocks
ingestion of independently valid findings for the same pair, and low-confidence
cache entries are researched again instead of suppressing retries for 30 days.

The configured automated research API returned HTTP 401. Direct source
research succeeded; unattended API gap filling requires valid credentials.
Validation: 196 tests run (195 passed, one existing skip), zero data-validator
errors/warnings, and exactly nineteen benchmark columns across all 233 snapshots.

### Automated source refresh

The daily scraper now refreshes llm-stats details, Artificial Analysis, Epoch,
original Toolathlon and CharXiv reasoning data before AI gap research. Newly
accepted evidence is retained with dates and configuration, then the daily
workflow rescores historical snapshots before generating the existing visuals.
See [AI gap filling](ai_gap_filling.md#routine-research-workflow) for source
coverage, failure handling and the limits of automated research.

Shared model records, dated roster references, and full-history recalculation are documented in [Model storage](model_storage.md).
