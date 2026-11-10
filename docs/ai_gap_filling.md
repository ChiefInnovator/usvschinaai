# AI benchmark gap filling

The research pass fills missing results for exactly the eighteen Avg IQ benchmarks
in `data/core_benchmarks.json`. That file is the single source for benchmark
selection, aliases and scoring weights. The pass does not accept the old Value
benchmark list.

## Routine research workflow

The daily scraper now runs `refresh_benchmark_sources.py` before AI research.
This API-key-independent stage refreshes every retained historical llm-stats model
plus the current scraped roster, with six concurrent source requests:

- llm-stats model detail pages, matched against all eighteen configured components.
- Artificial Analysis embedded evaluation data and Epoch benchmark CSV exports.
- The operator's original Toolathlon table, separated from Toolathlon-Verified.
- CharXiv's operator CSV, using reasoning accuracy rather than descriptive accuracy.
- Vals embedded benchmark data: MMLU-Pro, LiveCodeBench v6,
  SWE-bench Verified, GPQA Diamond, and Terminal-Bench 2.1. Select the exact task:
  adapters use overall accuracy, never a subject/difficulty subset.
  AIME 2025 is no longer configured and its source refresh is disabled.
- Agents’ Last Exam's official API, full-split pass rate across effort settings;
  partial-credit `avgScore`, sub-splits, and fallback configurations are excluded.

Vals source row counts, matches, and unmatched model IDs are retained in the
refresh report. Unknown release/date/preview aliases remain unmatched for review;
recognized effort suffixes do not block an exact underlying model match.
Page-level update dates never establish historical applicability for every row.

The AI research prompt uses the same audit findings when direct adapters leave
gaps: inspect benchmark pages and pagination, embedded evaluator data, archived
results, and dated source revisions. It explicitly distinguishes combined AIME
scores, subject/difficulty subsets, ALE partial credit, OfficeQA oracle-page
results, and similarly named benchmark versions. Missing-result explanations
identify source access, incomplete pagination, release identity, or protocol
issues rather than claiming a model was never evaluated.

Historical rescoring continues to use the dated evidence replay workflow below;
the legacy `backfill_gap_fill.py` writer refuses revised scoring history. Newly
researched undated results remain applicable from retrieval. Old provenance
ambiguities identified by an audit are not silently assigned publication dates.

Individual source failures are recorded in `data/benchmark_source_refresh.json`
and do not prevent other sources from being processed. Requests retry throttled
and transient responses (403, 408, 425, 429, 5xx, timeouts) three times with
jittered backoff, and at most three llm-stats detail pages are fetched at once.

### Source health

A source that changes its page silently looks identical to "no new results",
so every adapter fails closed when its payload stops parsing: a missing Vals
view, a renamed Artificial Analysis field, a missing Epoch table, unreadable
Toolathlon rows or an absent ALE full split are all recorded as failures.

The same report carries a `sourceHealth` record per source, rolled forward from
the previous run: `status` (`ok`, `failed`, or `empty` when the source answers
but matches no tracked model), `findings`, `since` (the day that status began)
and `lastOk` (the last day it produced results). llm-stats detail pages are one
source; it is `failed` only when most pages are unavailable.

`scripts/check_source_health.py` reads that record. The daily workflow adds its
summary to the data pull request, then runs it again as the final step, after
the pull request is open. A source that is `failed` on consecutive refreshes,
or `empty` after previously producing results, fails the run. Publication is
never blocked; the failure exists to trigger the workflow-failure email. A
source that has never matched a tracked model is listed without alerting.

```sh
python scripts/check_source_health.py --markdown   # summary only
python scripts/check_source_health.py              # exit 1 on a sustained outage
```

Accepted results enter
`data/model_catalog.json` and fill current gaps before paid research.
A dry run applies results in memory without writing source evidence or the audit.
The model roster is never expanded from these external benchmark tables.

AI research then searches the remaining components across vendor releases, PDF
system cards, operator archives, comparative tables and evaluator model cards.
The prompt explicitly checks original-model baselines in reports about quantized
models, fallback-model footnotes, benchmark versions and subsets. This is a
web-research route, not a dedicated parser for every vendor or image-only chart;
unreadable numeric evidence remains unresolved. Configuration notes are retained
with accepted AI results and copied into the dated evidence store.

Undated results start at retrieval, not model release. Epoch evaluation start
dates are not treated as publication dates by the routine refresh. Existing evidence is preserved; higher verified results can upgrade populated
scores on or after their availability date.
The daily workflow replays evidence across retained history before validation and
existing graph/image generation. An AI billing check failure is reported but no
longer blocks this direct-source workflow. AI web research still needs a working
API key; the key tested locally on September 6 returned HTTP 401.

To run the direct refresh and historical replay locally:

```sh
python scripts/refresh_benchmark_sources.py --write
python scripts/rescore_history.py --write --refresh-images
```

## Candidate selection

Every retained llm-stats model is eligible for every missing configured component.
There are no participation thresholds, qualification tiers, country/vendor locks,
minimum model coverage rules or participation-based priorities. A reported result
for another benchmark version does not block research for the selected version.
Already populated exact components, including configured aliases, are not gaps.
Generic GPQA does not automatically establish GPQA Diamond.

Candidates are batched by model in incoming model order, with all its missing
components requested together. Eligibility is unchanged, but the call budgets are
spent in that order, so the daily scraper sets it with
`scripts/research_priority.py`:

1. models on the latest published board, heaviest missing benchmark weight first;
2. new models, newest first;
3. every other model, in scrape order.

Each tier alternates between the United States and China; in scrape order every
US model precedes every Chinese one, so no Chinese model was reached.

A model is new for 14 days from the day it was first published on the board.
A model that has never been published is new for 14 days from its release date,
and is not new when that date is unknown. New models draw on their own nightly
budget and their null answers are not cached. Until this rule used the release
date, every release that never reached the board stayed new indefinitely and
took that budget every night.

`--gap-fill-max-calls` (default 40) limits API calls,
not eligibility. `--no-gap-fill` disables both source refresh and AI research; an unavailable API
only disables the AI stage and leaves its unresolved cells missing.

## Evidence requirements

The Responses API research prompt requires a public source URL, exact model,
benchmark version, subset, metric and compatible evaluation protocol. It must not
copy sibling-version scores, combine incompatible configurations, or estimate
missing scores. Configuration details belong in the evidence notes. Normal
acceptance requires high confidence; unsupported results remain missing.

Positive results are cached in `data/ai_gap_cache.json` for 30 days. Cached results below the acceptance confidence are researched again for better evidence; they do not block retries. Null results
are researched again on later runs. Accepted results carry source URL, research
model and confidence in `_provenance`; the append-only audit is
`data/ai_fill_history.jsonl`. Historical replay must additionally enforce the
dated-evidence rules in [gap_fill_backfill.md](gap_fill_backfill.md).

## Scoring boundary

Gap filling runs after detail enrichment and before scoring. Only the configured
eighteen benchmark columns are saved. Avg IQ uses their fixed weights and a 100%
denominator, with missing results contributing zero. Value uses that same Avg IQ
divided by input plus output price. Model selection uses Unified Score without a
coverage cutoff. No legacy participation or Value input path is used.

## Effort settings (September 6 correction)

Effort is not an eligibility filter. For each exact model and benchmark, use the
highest verified score across all reasoning-effort levels independently. A model
can use xhigh for one benchmark and max for another. Store the winning source and
effort in provenance. The source refresh checks all published effort rows, and
historical replay upgrades existing scores as well as filling missing values.
Higher results apply only on or after their evidence availability date; undated
results begin at retrieval. Exact model release, benchmark version/subset and
mixed-model fallback exclusions remain enforced. The eighteen fixed weights and
missing-as-zero denominator are unchanged. Historical calibration reports describe
the evidence available when the weights were fitted; scores can change as new
verified evidence arrives, without automatically refitting the weights.

Shared model records, dated roster references, and full-history recalculation are documented in [Model storage](model_storage.md).
