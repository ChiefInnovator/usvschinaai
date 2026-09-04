# Gap-fill backfill — state and handoff

**Date:** 2026-09-04 (updated later the same day)
**Scope:** retroactively run the AI gap-filling pass over the last **45** days of
stored history snapshots, then re-score them. Extending back to 2026-04-25 is
the follow-on, run in the background.

## 1. What the gap actually was

The 35-day window is **not** missing days — `models.json` has a snapshot for
every date in it. What was missing is the gap-filling pass itself.
`data/ai_fill_history.jsonl` shows it ran 2026-04-12 .. 2026-04-25, then went
dark until 2026-09-03:

```text
2026-04-12  30 fills
2026-04-13   1
2026-04-15   1
2026-04-17   1
2026-04-18   2
2026-04-22   1
2026-04-25   1
   ← four-month hole; every snapshot in here was scored un-enriched
2026-09-03  22
2026-09-04   7
```

The pass runs live, before Pass 1, so it only ever enriches the day it runs on
(`docs/ai_gap_filling.md` §2). Days it did not run on stay sparse forever
unless something replays it. That is what `scripts/backfill_gap_fill.py` does.

## 2. Decision on record: fill cells, then re-score (owner, 2026-09-04)

The first version of this doc recorded "cells only, no rescoring". The owner
reversed that the same day: **backfilled cells are written to the history
rows and each snapshot in the window is then re-scored** with the same
implementation the daily run uses (`scripts/scoring.py`, extracted from
`scrape_models.py` for exactly this purpose so the two cannot drift).

Rules of the re-score:

- **The cohort is untouched.** No deduping, no additions, no drops. Each past
  day keeps exactly the models it had; only their numbers change, and the top
  10 falls out of the filled data.
- **Originals are kept.** The first time a row is re-scored its published
  `avgIq` / `value` / `unified` / `coverage` are copied to `_prior`; later
  re-scores never overwrite `_prior`.
- **Today's scorer, not that day's.** Full-cohort qualified set, coverage
  floor, `Latency` / `LLM Stats` / `Code Arena` excluded. A re-scored day will
  differ from what was published then even where no cell was filled. That is
  what makes the 30-day trend comparable end to end.
- **Pool-scored days re-score on the pool's scale, or not at all.** Since
  2026-09-03 the daily run scores a pool of 15 per country and publishes the
  top 10 per country; the published rows cannot recover the bounds or the
  qualified set of the pool they were normalised against. The first live
  backfill re-derived them from the 20 published rows and crushed the bottom
  of the live board (Claude Sonnet 5: 579 → 1, Muse Spark 1.3: 948 → 1000,
  qualified set 8 → 9). So `rescore_snapshot` now has three cases:
  - snapshot carries a `scoring` block (the daily run stores
    `ScoringResult.to_snapshot()` — qualified set, bounds, benchmark ranges —
    from 2026-09-04 on): re-score with `score_cohort(..., fixed=block)`. An
    unchanged snapshot reproduces its published numbers exactly; a filled cell
    moves only its own row, capped at 1000.
  - pool-scored (rows carry `coverage`) but no block, never re-scored (no
    `_prior`): **kept as published.** 2026-09-03 and 2026-09-04 were restored
    from `_prior` and fall in here.
  - legacy (top-10-per-country cohort, pre-pool): qualified set and bounds
    derived from the 20 rows — which is how those days were scored anyway.
- `--no-rescore` restores the cells-only behaviour; `--rescore-only` re-scores
  the window without filling anything.

## 3. What has been done

1. `--cache-only` (no API calls): 116 cells filled across 33 days from the
   existing cache, 12 distinct (model, column) pairs, each with `_provenance`.
2. **First live run in CI** (workflow run 33867753511, `gpt-5.6-luna`,
   `--days 45 --max-calls 80`, 2026-09-04 ~11:15 UTC):
   - the whole 80-call budget went on the five newest days — 8 cells filled,
     27 luna answers dropped as low-confidence, then
     `call budget exhausted; stopping before 2026-08-30`. Cause: the pass
     never caches a null answer, so each day re-asked the same ~18 models.
     Fixed by the asked-pairs memory below; the 95 pairs that run asked are
     seeded into `data/ai_gap_backfill_asked.json` from its log.
   - all 45 days re-scored — correctly for the 43 legacy days, destructively
     for 2026-09-03/04 (see §2). Those two were restored from `_prior` in the
     follow-up commit; the 43 legacy days re-derive deterministically.
   - `validate_models.py`: 0 errors, 0 warnings; suite: 170 tests OK.

## 4. What is left

The 40 older days of the window still need live calls. From `--dry-run`
after the fix:

```text
Days in window: 45  (2026-07-22 .. 2026-09-04)
Gap candidates across the window: 4681
  resolvable from the existing cache: 137
  already asked (null, within TTL):   4347
  needing a live lookup:              197
Distinct (model, benchmark) pairs to research: 197
Batched API calls required (one per model per day it is first seen): 59
```

The estimate is now a simulation of the pass's own budget rule — one call per
(day, model) with at least one candidate that is neither cache-fresh nor
already asked, with each call marking its pairs asked for the older days —
rather than a count of distinct models, which silently assumed nulls were
cached. Positive answers are cached by `gap_fill_benchmarks` (30-day TTL);
null answers are remembered by the backfill in
`data/ai_gap_backfill_asked.json` (same TTL) and handed to the pass as
`skip_pairs`. Both files are committed by the workflow.

## 5. The key situation — read this before trying to run it

- The `OPENAI_API_KEY` in the local `.env` is **dead**.
  `python scripts/check_openai_billing.py` returns `invalid_api_key` for it.
- The **GitHub Actions secret `OPENAI_API_KEY` is alive.** `daily-scrape.yml`
  hard-gates on `check_openai_billing.py` before the scrape, and the
  2026-09-04 daily run succeeded and produced 7 gap-fill audit entries.
- **The secret cannot be read back.** GitHub Actions secrets are write-only by
  design: `gh secret list` returns names and update timestamps only, there is
  no read endpoint, and the value is masked inside the runner. Do not spend
  time trying to extract it, and do not add a workflow step that echoes it.
- There is no file named `04112026_OPENAI_API_KEY` anywhere on the machine.
  A content search across `~/.openclaw`, `~/.claude`, `~/Documents`,
  `~/Desktop` and `~/Downloads` for `04112026` matched only this session's own
  transcript.

So there are two ways to finish the job:

**A. Run it in CI** (no key handling at all) — **this is now built:**
`.github/workflows/backfill-gap-fill.yml` (`workflow_dispatch`; inputs: days,
max_calls, model, rescore). It installs `scripts/requirements.txt`, exports
`OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}`, runs the command in §6, then
`validate_models.py`, then commits `models.json` + `current.json` +
`data/ai_gap_cache.json` + `data/ai_fill_history.jsonl`. This is the
recommended route — it reuses the key that is already known to work.
Note the backfill does **not** need Playwright, so the workflow can skip
`playwright install` and is a couple of minutes, not 45.

**B. Rotate the local key.** Owner creates a new key at platform.openai.com and
puts it in `.env` themselves. An AI instance should not be handling the
plaintext value.

## 6. How to run it

```bash
# Report only — no API calls, writes nothing.
.venv/bin/python scripts/backfill_gap_fill.py --dry-run --days 45

# Apply only what is already in data/ai_gap_cache.json — no API calls.
# (Already done for the current window; re-running is a no-op.)
.venv/bin/python scripts/backfill_gap_fill.py --cache-only --days 45

# The live run. Needs a working OPENAI_API_KEY.
.venv/bin/python scripts/backfill_gap_fill.py --days 45 --max-calls 80
```

Always run `python scripts/validate_models.py` afterwards — it is the same gate
CI uses, and it catches out-of-range percentages and >15-point jumps against
the previous snapshot.

### Flags

| Flag | Default | Notes |
| --- | --- | --- |
| `--days` | 45 | Counted back from the newest snapshot's timestamp, not calendar dates |
| `--no-rescore` | off | Fill cells only; leave scores as published |
| `--rescore-only` | off | No fills; re-score the window with today's scorer |
| `--dry-run` | off | Report candidates, cache coverage, call estimate |
| `--cache-only` | off | Apply cached fills only; never calls the API |
| `--max-calls` | 40 | Ceiling for the whole run, not per day; counts real HTTP calls |
| `--model` | `gpt-5.6-luna` | Cheap tier. `gap_fill_benchmarks.DEFAULT_MODEL_CHAIN` is still used as fallback |
| `--min-confidence` | `high` | Drops anything the research pass is not confident about |

There is no flag for the asked-pairs memory; delete
`data/ai_gap_backfill_asked.json` entries to re-ask a pair before its TTL.

## 7. Cost

Per the price table in `scripts/social_caption.py` (USD per million tokens),
and the ~9K input / ~5K output per call that `gap_fill_benchmarks` documents:

| Model | In / Out | ~48 calls |
| --- | --- | --- |
| `gpt-5.6-luna` | 0.20 / 1.20 | **≈ $0.40** |
| `gpt-5.6-terra` | 2.00 / 12.00 | ≈ $3.75 |

Token cost only — any per-call `web_search` tool fee is on top. The first
live run's 80 luna calls cost roughly $0.65 in tokens plus the search fee.

The backfill defaults to `luna`, the same cheap tier `social_caption.py`
already uses for routine days. `gap_fill_benchmarks`' own comment warns that
the weak tier is likelier to hallucinate a score, which is why the daily scrape
keeps the strong chain and why the backfill pins `--min-confidence high` and
records a `_provenance` source URL on every accepted fill.

## 8. Design notes for whoever picks this up

`scripts/backfill_gap_fill.py` deliberately does **not** modify
`scrape_models.py` or `gap_fill_benchmarks.py`. It reuses
`run_gap_filling_pass` unchanged and adapts around it:

- **Row → entry adapter.** `HistoryEntry` is a duck-typed stand-in for
  `LeaderboardEntry` (the pass only touches `.name` / `.country` / `.url` /
  `.columns`). Importing `scrape_models` would drag in Playwright.
- **Header spelling.** `build_history_entry` stores columns as
  `header.replace(" ", "")`, so `SWE-bench Verified` lands in `models.json` as
  `SWE-benchVerified` — but the cache and audit log are keyed by the *spaced*
  original. Looking up the raw row key misses every cached multi-word
  benchmark. `build_display_names()` recovers the original spelling from the
  cache + audit log by canonical (alphanumeric-only) match, and `write_back()`
  re-applies the same strip on the way out. Headers never seen by the pass
  (`FinanceAgentv2`, `SWE-benchMultilingual`, `NL2Repo`, …) keep their squashed
  form; the research prompt still reads fine.
- **Which columns are benchmarks.** Taken from `validate_models.META_KEYS`, not
  a local copy — a test already keeps that set in step with the scraper's
  `metadata_columns`.
- **Cohort order.** `get_top_cohort()` takes the first 10 rows per country, so
  `hydrate()` emits US rows then CN rows to reproduce the scraper's cohort.
- **One snapshot per UTC day.** Matches what the site and
  `social_formats.per_day_series` read, so budget is not spent on also-ran rows
  from multi-run days.
- **Budget accounting.** `--max-calls` counts real HTTP calls, via a counting
  wrapper around `gf.query_openai_responses`. Counting cache growth instead
  would overcharge several-fold, since one batched call caches many cells.
- **Newest day first,** so if the ceiling bites it is the stale end of the
  window that goes unfilled.
- **Asked-pairs memory.** `run_gap_filling_pass` gained two optional hooks:
  `skip_pairs` (pairs dropped from the candidates) and `on_batch(model,
  benchmarks)` (fired after a *validated* answer, so a malformed or
  rate-limited batch is not remembered). The backfill records every answered
  batch and saves after each day, so a crash mid-window loses nothing.
- **Scale.** `ScoringResult.to_snapshot()` / `score_cohort(fixed=...)` in
  `scoring.py`; `build_history_entry(scoring_parameters=...)` writes the block
  as `snapshot["scoring"]`. `pool_scored_without_parameters()` is the guard for
  the two snapshots that predate it. `avgIq` and `value` normalisation are
  clamped to [0, 100] — a no-op when bounds come from the cohort being scored
  (beyond a ±0.2 rounding artefact at the extremes), needed once bounds are
  stored.

Tests: `tests/test_backfill_gap_fill.py` covers the row↔entry translation,
provenance key stripping, the TTL and confidence gates, the window boundary,
the three re-score cases and the asked memory; `tests/test_scoring.py`
(`StoredParametersTests`) proves a stored block reproduces pool scores for the
published rows and that re-deriving from them alone does not;
`tests/test_gap_fill_pass_hooks.py` covers `skip_pairs` / `on_batch`.

## 9. Known caveat

Backfilled scores are **anachronistic**. A number researched today is written
into a snapshot from weeks ago, and the cache does not record when the vendor
published it, so a filled cell may be a result that did not exist on that
snapshot's date. Unavoidable if we backfill at all; the alternative is leaving
the window sparse. Also noted in the script docstring.
