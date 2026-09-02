# Specification: Fresh Model Statistics Federation

**Status:** Proposed
**Date:** 2026-04-25
**Owner:** usvschinaai

## 1. Problem

`scripts/scrape_models.py` currently treats llm-stats as the upstream authority for the tracked cohort, visible benchmark columns, model metadata, pricing, and initial ranking. `scripts/gap_fill_benchmarks.py` improves missing cells only after llm-stats has already supplied the model row and the post-sparse-drop benchmark set.

That leaves two freshness gaps:

1. **New model gap:** a newly announced model can be absent from llm-stats for hours or days, so it never enters the US vs China cohort. A gap-filler cannot fill benchmarks for a row that does not exist.
2. **New benchmark gap:** release posts often publish benchmark tables before llm-stats normalizes them. Current scraping only considers benchmarks discovered from llm-stats leaderboard/detail pages, so fresh launch-table metrics are ignored unless they map to an existing column.

Recent release pages validate the need for a second lane. Anthropic announced Claude Opus 4.7 on 2026-04-16 with availability, pricing, and benchmark material at `https://www.anthropic.com/news/claude-opus-4-7`. OpenAI announced GPT-5.5 on 2026-04-23 with a benchmark table and API pricing at `https://openai.com/index/introducing-gpt-5-5/`. DeepSeek V4 coverage appeared on 2026-04-24 before a normalized llm-stats row can be assumed.

## 2. Goal

Add a source-federation layer that can ingest model statistics from fast sources, reconcile them with llm-stats, and publish a clearly attributed leaderboard entry when evidence is strong enough.

The output remains `models.json`. The public site should not need a second data API.

## 3. Non-goals

- Do not replace llm-stats. It remains the preferred normalized baseline when available.
- Do not estimate scores from marketing claims, charts without readable values, or neighboring model variants.
- Do not let weakly sourced scores silently affect national totals.
- Do not scrape paywalled or terms-hostile sources.

## 4. Source Classes

Each source adapter emits normalized `ModelStatEvidence` records. Sources are ranked by trust and freshness.

| Tier | Source class | Examples | Default trust | Use |
| --- | --- | --- | ---: | --- |
| A | Provider primary release | OpenAI release posts/system cards, Anthropic news/model pages, DeepSeek release pages/GitHub repos | 0.95 | fastest path for new models, pricing, official evals |
| B | Benchmark-owner leaderboard | SWE-bench, Terminal-Bench, LMArena/CodeArena, ARC Prize, Scale MCP Atlas | 0.90 | independent benchmark confirmation |
| C | Reputable third-party aggregator | Artificial Analysis, Papers with Code, HELM, OpenCompass, Hugging Face leaderboards | 0.80 | second source and conflict checks |
| D | llm-stats | leaderboard/detail pages | 0.85 | current baseline and normalized cohort |
| E | News/social/forum | Verge/Axios/etc., X, Reddit, Discord | 0.30 | discovery only; never scoring without corroboration |

Provider primary pages may introduce a model before third-party validation exists. That is allowed, but the row must be marked `provisional` until at least one non-provider source confirms either the model identity, pricing, or one benchmark score.

## 5. Data Model

Add two internal data files:

- `data/source_registry.json`: source definitions, crawl URLs, parser type, trust tier, country/provider ownership, and last crawl metadata.
- `data/stat_evidence.jsonl`: append-only evidence log. One JSON object per observed model-stat claim.

Evidence record:

```json
{
  "observed_at": "2026-04-25T14:00:00Z",
  "source_id": "openai_release_gpt_5_5",
  "source_tier": "A",
  "source_url": "https://openai.com/index/introducing-gpt-5-5/",
  "source_published_at": "2026-04-23",
  "claim_type": "benchmark_score",
  "model": {
    "canonical_id": "openai:gpt-5.5",
    "name": "GPT-5.5",
    "organization": "OpenAI",
    "origin": "US",
    "variant": "base"
  },
  "benchmark": {
    "canonical_id": "terminal_bench_2_0",
    "display_name": "Terminal-Bench 2.0",
    "metric": "accuracy",
    "scale": "percent_0_100"
  },
  "value": "82.7%",
  "confidence": "high",
  "extraction_method": "html_table",
  "notes": "Exact table cell from provider release page."
}
```

`models.json` rows gain a richer `_provenance` block that supports multiple evidence records per cell:

```json
"_provenance": {
  "Terminal-Bench2.0": {
    "selected": {
      "value": "82.7%",
      "source_id": "openai_release_gpt_5_5",
      "source_url": "https://openai.com/index/introducing-gpt-5-5/",
      "source_tier": "A",
      "confidence": "high"
    },
    "evidence": [
      {
        "source_id": "openai_release_gpt_5_5",
        "value": "82.7%",
        "observed_at": "2026-04-25T14:00:00Z"
      }
    ],
    "status": "accepted"
  }
}
```

## 6. Pipeline

The daily workflow becomes:

```text
[Discover releases/news]              ← model candidates, source URLs
        │
        ▼
[Collect source evidence]             ← provider + benchmark + aggregator adapters
        │
        ▼
[Scrape llm-stats]                    ← existing scrape_models.py path
        │
        ▼
[Reconcile model identities]          ← merge/fork variants, detect aliases
        │
        ▼
[Reconcile benchmark claims]          ← source priority + conflict policy
        │
        ▼
[AI gap-fill for remaining cells]     ← existing gap_fill_benchmarks.py, now with evidence context
        │
        ▼
[Two-pass scoring]
        │
        ▼
[Write models.json + audit files]
```

This requires three new scripts:

- `scripts/discover_model_releases.py`: reads RSS, provider index pages, and existing `news.json`; emits candidate source URLs.
- `scripts/collect_stat_evidence.py`: runs source adapters and appends normalized claims to `data/stat_evidence.jsonl`.
- `scripts/reconcile_stat_evidence.py`: merges evidence with llm-stats rows before scoring.

`scripts/scrape_models.py` should call reconciliation after llm-stats detail-page enrichment and before sparse benchmark drop. That allows new source-derived benchmarks to survive the same participation filters and qualified-set logic as llm-stats benchmarks.

## 7. Source Adapters

### 7.1 Provider Release Adapter

Scope:

- OpenAI release posts and system cards under `openai.com/index/`.
- Anthropic news/model pages under `anthropic.com/news/` and `anthropic.com/claude/`.
- DeepSeek official pages, release notes, and GitHub markdown when official web pages are unavailable.

Extraction rules:

- Parse HTML tables first.
- If a table is rendered as an image, capture the image URL and send it to an extraction step only when the page is a Tier A source. Store `extraction_method: "vision_table"` and `confidence: "medium"` unless a human review approves it.
- Extract pricing, context window, availability, API model id, and release date as separate evidence records.
- Extract every benchmark row, even if the benchmark is not yet in `benchmark_headers`.

### 7.2 Benchmark-Owner Adapter

Scope:

- Benchmark leaderboards that publish model-level results directly.

Rules:

- Prefer benchmark-owner scores over provider-reported copies of the same benchmark when both exist and the benchmark-owner update is no older than 14 days.
- Keep provider-reported scores as evidence for freshness even when not selected.

### 7.3 Third-Party Aggregator Adapter

Scope:

- Artificial Analysis and similar aggregators if scraping/API access is permitted.

Rules:

- Use as a second source for model presence, pricing, and benchmark scores.
- If the source has its own composite index, store it as a non-scoring metric unless the scoring methodology is public and stable.

## 8. Canonicalization

Create `data/canonical_models.json` and `data/canonical_benchmarks.json`.

Model canonicalization:

- Canonical ID format: `{organization_slug}:{model_slug}`.
- Track aliases, API IDs, release page URLs, llm-stats URLs, and variant labels.
- Variants must not collapse by family name. `GPT-5.5`, `GPT-5.5 Pro`, and `GPT-5.5-Cyber` are separate canonical models.
- A score for a higher-effort or tool-enabled setting is accepted only if the benchmark protocol permits that setting and the model row represents that setting.

Benchmark canonicalization:

- Canonical ID format: lowercase snake case, e.g. `swe_bench_verified`, `terminal_bench_2_0`, `browsecomp`.
- Store display aliases such as `SWE-Bench Verified`, `SWE-benchVerified`, and `SWE-bench Verified`.
- Store scale metadata: `percent_0_100`, `elo`, `absolute`, or `unknown`.
- Store whether higher is better.
- Store known benchmark-owner URL and protocol notes.

## 9. Reconciliation Policy

For each model field or benchmark cell:

1. Group evidence by canonical model and canonical metric.
2. Drop evidence with low confidence, missing URL, mismatched variant, unsupported protocol, or unparseable value.
3. Normalize values to the benchmark scale.
4. Select the winner:
   - Tier B benchmark-owner evidence wins for benchmark scores when fresh.
   - Tier A provider evidence wins for newly released models when no Tier B result exists.
   - llm-stats wins when it is newer than provider evidence and agrees with at least one independent source.
   - If two high-confidence values disagree beyond tolerance, mark `status: "conflict"` and exclude the cell from scoring until reviewed.
5. Write all retained evidence into provenance.

Tolerance:

- Percent scores: exact match after one decimal place, or absolute difference <= 0.2.
- Elo scores: absolute difference <= 5.
- Pricing: exact numeric match after currency/unit normalization.

## 10. Provisional Rows

A model absent from llm-stats may enter the cohort as a provisional row when all are true:

1. A Tier A source identifies the model, organization, origin, release date, and API or product availability.
2. Pricing is available, or the row is marked `cost_unknown` and Value is set to 0 until pricing appears.
3. At least 3 scoring-eligible benchmark cells are accepted.
4. No unresolved variant conflict exists.

Provisional rows:

- Participate in Pass 1 and Pass 2 only with accepted high-confidence cells.
- Display a provenance marker in the benchmark table.
- Keep `link` pointed to the source page until llm-stats has a detail URL.
- Are demoted automatically if llm-stats later publishes a conflicting row and reconciliation cannot resolve the conflict.

## 11. Freshness Schedule

Add a second GitHub Action:

- `fresh-release-scan.yml`
- Runs every 4 hours.
- Also runs manually via `workflow_dispatch`.
- Executes discovery, evidence collection, reconciliation, dry-run scoring, and writes `models.json` only if a new model or accepted benchmark score changes the current entry.

Keep `daily-scrape.yml` as the full baseline refresh.

Release-day behavior:

- Candidate URLs discovered from provider feeds should be crawled immediately.
- Negative results are not cached for new-model discovery.
- Positive evidence is immutable in `stat_evidence.jsonl`; corrections are appended as new evidence.

## 12. Human Review Queue

Create `data/review_queue.json` for cases that should not auto-score:

- Conflicting high-confidence benchmark values.
- Image-extracted benchmark tables from provider pages.
- New benchmarks with unknown scale.
- Provider-only rows with fewer than 3 scoring-eligible benchmarks.
- Claims from Tier E discovery sources.

Manual review action:

```json
{
  "claim_id": "sha256...",
  "decision": "accept|reject|alias|conflict",
  "reviewed_at": "2026-04-25T15:00:00Z",
  "reviewer": "rich",
  "notes": "Accepted as Terminal-Bench 2.0; exact provider table value."
}
```

## 13. Site Transparency

Update the public methodology text to distinguish:

- `llm-stats`: normalized scraped baseline.
- `primary_source`: provider release/model card.
- `benchmark_owner`: benchmark’s own leaderboard.
- `third_party`: reputable aggregator.
- `ai_filled`: OpenAI web-search gap fill.
- `provisional`: source-federated row not yet present on llm-stats.

The existing sparkles marker for AI-filled cells should become a general provenance marker for any non-llm-stats source, with tooltip text showing selected source, confidence, and provisional/conflict status.

## 14. Failure Handling

- If source federation crashes, the existing llm-stats scrape still runs.
- If reconciliation produces no accepted new evidence, no `models.json` write is needed.
- If a provisional model has fewer than 3 accepted scoring cells after reconciliation, keep it in `data/review_queue.json` but do not publish it.
- If a source changes or removes a benchmark table, preserve prior evidence in `stat_evidence.jsonl` and append a `source_missing` observation.

## 15. Acceptance Criteria

1. A model published on a Tier A provider page can appear on the leaderboard before llm-stats adds it.
2. GPT-5.5-style provider tables with pricing and benchmark cells can be parsed into evidence records within one scan cycle.
3. Opus 4.7-style provider pages with mixed text, quotes, and benchmark imagery create accepted text/table claims and review-queue entries for image-derived claims.
4. DeepSeek-style official GitHub or release-note pages can create CN-origin provisional rows when benchmark evidence is sufficient.
5. Every non-llm-stats score in `models.json` has a URL-bearing provenance entry.
6. Conflicting high-confidence values are excluded from scoring until reviewed.
7. The site clearly marks provisional/source-federated data without changing the two-pass scoring math.

## 16. Implementation Phases

### Phase 1: Evidence Backbone

- Add source registry, evidence log, canonical model/benchmark files.
- Implement provider release adapters for OpenAI and Anthropic.
- Implement reconciliation into existing `LeaderboardEntry.columns`.
- Add provenance tooltip support for `primary_source`.

### Phase 2: Fresh Release Scan

- Add `fresh-release-scan.yml` on a 4-hour schedule.
- Add model discovery from provider index pages and `news.json`.
- Support provisional rows absent from llm-stats.

### Phase 3: Independent Confirmation

- Add benchmark-owner and third-party aggregator adapters.
- Add conflict detection and review queue.
- Add review decisions to reconciliation.

### Phase 4: Coverage Hardening

- Add DeepSeek official-source adapter.
- Add table-image extraction behind review.
- Add summary metrics: source lag, accepted fills by source tier, conflict count, provisional row count.

