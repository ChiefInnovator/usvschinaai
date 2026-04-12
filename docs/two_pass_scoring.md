# Two-Pass Scoring

**Status:** Implemented.
**First shipped:** 2026-04-12

## Motivation

The original IQ Index was a participation-weighted average of normalized benchmarks across the full US+CN cohort. Because models self-select which benchmarks they publish, a model could rank lower than its peers simply by omitting the "easy win" benchmarks the others reported.

Concrete example from the 2026-04-12 snapshot before the change:

| Model | Unified | IQ | Benchmarks Reported |
| --- | ---: | ---: | ---: |
| GPT-5.2 | 773.27 | 54.85 | 14 / 19 |
| GPT-5.4 | 683.08 | 49.77 | 9 / 19 |

On the 9 benchmarks both reported, GPT-5.4 swept 9–0:

| Benchmark | GPT-5.2 | GPT-5.4 | Winner |
| --- | ---: | ---: | --- |
| CodeArena | 1,502 | 1,626 | GPT-5.4 |
| GPQA | 92.4% | 92.8% | GPT-5.4 |
| ARC-AGIv2 | 52.9% | 73.3% | GPT-5.4 |
| BrowseComp | 65.8% | 82.7% | GPT-5.4 |
| MMMU-Pro | 79.5% | 81.2% | GPT-5.4 |
| MCPAtlas | 60.6% | 67.2% | GPT-5.4 |
| HLE | 34.5% | 39.8% | GPT-5.4 |
| Toolathlon | 46.3% | 54.6% | GPT-5.4 |
| FrontierMath | 40.3% | 47.6% | GPT-5.4 |

GPT-5.4 was still ranked lower because it never reported 5 benchmarks GPT-5.2 did — AIME2025 (100%), SWE-bench Verified (80%), MMMLU (89.6%), CharXiv-R (82.1%), ScreenSpotPro (86.3%) — all near-perfect scores that pulled GPT-5.2's weighted average up. Participation weighting didn't fully compensate.

The two-pass approach restricts IQ to a benchmark set where head-to-head comparison is actually meaningful.

## Algorithm (as shipped)

### Pass 1 — Initial Top 10 selection

Compute `avgIq`, `value`, `unified` using participation-weighted normalized benchmarks across the full cohort. Sort combined US+CN by `unified` descending. The top 10 become the **Initial Top 10**.

### Qualified benchmark set

For each benchmark, count how many of the Initial Top 10 reported a non-missing value. Keep benchmarks where that count is **≥ 8**. If fewer than 3 benchmarks qualify, fall back to Pass 1 silently.

### Pass 2 — rescore every model

For every model in the cohort (not just the top 10):

1. `avgIq_2` = **flat average** of normalized scores over qualified benchmarks only. Flat, not participation-weighted — per-model averages only count benchmarks the model actually reported, and each qualified benchmark contributes with weight 1.
2. Each benchmark's normalization range is chosen via the precedence rule below.
3. `value = avgIq_2 / (Input $/M + Output $/M)`.
4. Rebuild `min/max_avg_iq` and `min/max_value` across the full cohort from the Pass 2 outputs.
5. `unified = 10 × (0.9 × norm(avgIq_2) + 0.1 × norm(value))`.

Pass 2 values are what get written to `models.json` and shown on the site. Pass 1 exists only to pick the qualified benchmark set.

### Normalization precedence

For each qualified benchmark, determine the `(min, max)` normalization range via:

1. **Known absolute range** — `BENCHMARK_KNOWN_RANGES` lookup. Currently only `CodeArena: (1000, 2000)` — LMArena Elo with documented starting value 1000 and a defensible empirical ceiling of 2000.
2. **Percentage auto-detect** — if every non-missing cell ends with `%`, the range is `(0, 100)` and raw values pass through unchanged. This applies to GPQA, MMMU-Pro, HLE, AIME2025, and most qualified benchmarks.
3. **Cohort min/max fallback** — for unknown-scale benchmarks with no `%` suffix and no hardcoded range.

The precedence exists to prevent the amplification artifact that bit us with MMMU-Pro: its full-cohort range was 75.6 % → 81.2 %, so a 3-point raw gap between Claude Opus 4.6 (77.3 %) and Gemini 3.1 Pro (80.5 %) became a 57-point normalized gap (30.4 vs 87.5) under naive min/max scaling.

## Related fixes shipped alongside

Three bugs and data-quality issues were found during implementation and fixed in the same change:

1. **Dash bug.** `MISSING_VALUE_MARKERS` only included ASCII hyphen `-`. llm-stats uses typographic `—` (U+2014) and `–` (U+2013) for unreported cells. The old code was treating those as reported zeros, silently corrupting averages. Fix: add both Unicode dashes to `MISSING_VALUE_MARKERS`, and reuse a single module-level constant across the file to prevent drift.
2. **Category-aggregate double-counting.** The llm-stats leaderboard emits per-category rollup columns (`Reasoning`, `Math`, `Coding`, `Search`, `Writing`, `Vision`, `Tools`, `Long Ctx`, `Finance`, `Legal`, `Health`) that aggregate the individual benchmarks. Scoring over both double-counts. Fix: add them to the `metadata_columns` exclusion so they're retained as raw columns but dropped from `benchmark_headers`.
3. **Detail-page benchmark enrichment.** The scraper was only reading the leaderboard table's fixed columns. Each model's detail page exposes additional benchmarks via llm-stats' Next.js flight payload (parsed from embedded JSON). Fix: `extract_detail_benchmarks()` now pulls the `normalized_score` field for every benchmark on each model's page, fuzzy-matched against existing headers via `canonicalize_benchmark_name()` (with an explicit alias map for known abbreviations like `HLE` ↔ `Humanity's Last Exam`).

## Observed impact on the 2026-04-12 snapshot

| Rank | Model | Country | Pass 1 Unified (before) | Pass 2 Unified (after) |
| ---: | --- | --- | ---: | ---: |
| 1 | Gemini 3.1 Pro | 🇺🇸 | 769.33 | 908.64 |
| 2 | Claude Opus 4.6 | 🇺🇸 | 904.96 | 907.58 |
| 3 | Claude Opus 4.5 | 🇺🇸 | n/a | 743.66 |
| 4 | GPT-5.4 | 🇺🇸 | 683.08 | 722.01 |
| 5 | GLM-5 | 🇨🇳 | n/a | 682.54 |
| 6 | Kimi K2.5 | 🇨🇳 | 719.68 | 625.53 |
| 7 | GLM-5.1 | 🇨🇳 | n/a | 611.70 |
| 8 | Gemini 3 Flash | 🇺🇸 | 685.18 | 592.73 |
| 9 | Claude Sonnet 4.6 | 🇺🇸 | 653.38 | 592.16 |
| 10 | GPT-5.2 | 🇺🇸 | 773.27 | 583.41 |

Key outcomes:

- **GPT-5.4 vs GPT-5.2 inversion resolved** — GPT-5.4 now ranks #4, GPT-5.2 ranks #10. The pre-change gap was GPT-5.2 ahead by 90 unified points despite losing 9–0 head-to-head on shared benchmarks.
- **Gemini 3.1 Pro and Claude Opus 4.6 are effectively tied at the top** (908.64 vs 907.58). Claude has a marginally higher IQ (79.10 vs 78.92) but Gemini's cheaper pricing nudges it ahead on Unified via the 10% value weighting.
- **China models climb.** GLM-5, Kimi K2.5, and GLM-5.1 all enter the top 7, benefiting from broad benchmark coverage under the flat-average rule.

## Files changed

- [scripts/scrape_models.py](../scripts/scrape_models.py) — `calculate_derived_scores` takes an optional `qualified_benchmarks` set that switches it to Pass 2 semantics. `resolve_benchmark_range` encodes the normalization precedence. `enrich_with_metadata` pulls detail-page benchmarks. The metadata stage in `run_scraper` computes Pass 1, picks the Initial Top 10, builds the qualified set, and re-scores.
- [models.json](../models.json) — `metadata.footerText` updated to reflect the new method. Historical entries stay untouched.
- [docs/scraper_specification.md](scraper_specification.md) — detailed step-by-step specification.
