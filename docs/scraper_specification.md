# Specification: Automated Leaderboard Scraper and Scoring

**Project**: usvschinaai  
**Feature**: Python-based automation for updating AI model leaderboard rankings  
**Status**: Active Development (Staged Architecture)

---

## 1. Overview

Automate data collection and aggregation for the US vs China AI leaderboard by scraping model rankings, benchmark scores, and pricing from [llm-stats.com/leaderboards/llm-leaderboard](https://llm-stats.com/leaderboards/llm-leaderboard), calculating competitive metrics (AvgIQ, Value, Unified), and optionally enriching/writing `models.json`. The scraper uses a staged architecture with clear console tables and file outputs.

---

## 2. Staged Architecture

The scraper operates in three distinct stages, each building upon the previous:

### Stage 1: Basic Leaderboard Extraction (`--leaderboard-basic`)

- **Purpose**: Extract top-10 models per country with essential identification data
- **Output**: Console tables (China/US) showing rank, name, country, model URL
- **Data Captured**: Minimal columns for verification and Stage 2 input
- **JSON Write**: Optional via `--write-json` flag

### Stage 2: Full Leaderboard Extraction (`--leaderboard-full`)

- Purpose: Capture all visible table columns from the leaderboard and compute derived scores
- Console output: Combined Top 20 table sorted by Unified (descending)
- Files written:
  - `stage2_combined.csv` — All rows/columns + derived scores
  - `stage2_combined.json` — Same ordering/fields as CSV
  - `stage2_country_aggregates.csv` — Per-country totals and averages (Unified)
  - `stage2_summary.json` — Aggregates + top-3 models per country by Unified
- Benchmarks: Auto-detected from table headers; column order preserved
- Notes: The Model column is widened in the table for readability

### Stage 3: Model Page Metadata Enrichment

- **Purpose**: Navigate to each model detail page for additional metadata
- **Output**: Enriched console tables + final models.json update
- *4. Data Structure & Schema

**Input**: Raw table data from llm-stats.com leaderboard + model page metadata  
**Output**: Single history entry object prepended to `models.json`

### Raw Data Preservation Rules

- **Store exactly as read**: All leaderboard cell values captured as raw strings
- **No inference**: Never substitute missing data with defaults or computed values
- **Null handling**: Empty cells stored as empty string; "-" stored as "-"; "n/a" stored as "n/a"
- **Column order**: Preserve original table column order from llm-stats
- **Derived scores**: Computed fields (avgIq, value, unified) calculated from raw strings at display/persist time

### Per-Model Object (20 total: 10 US + 10 CN)

```json
{
  "rank": 1-10,
  "model": "string",
  "company": "string",
  "link": "https://llm-stats.com/models/...",
  "origin": "US" | "CN",
  "description": "string",
  "created": "YYYY-MM-DD",
  "costIn": "string (raw from table)",
  "costOut": "string (raw from table)",
  "costInputPer1M": "string (raw from table)",
  "costOutputPer1M": "string (raw from table)",
  "avgIq": number,
  "value": number,
  "unified": number,
  "HMMT 2025": "string (raw score)",
  "GPQA Diamond": "string (raw score)",
  "BrowseComp": "string (raw score)",
  "ARC-AGI v2": "string (raw score)",
  "HLE": "string (raw score)",
  "MMLU-Pro": "string (raw score)",
  "LiveCodeBench": "string (raw score)",
  "SWE-Bench Verified": "string (raw score)",
  "CodeForces": "string (raw score)"
}
```

**History Entry Object**:

```json
{
  "timestamp": "YYYY-MM-DDTHH:MM:SS±HH:MM",
  "teams": {
    "US": [array of 10 model objects],
    "CN": [array of 10 model objects]
  }
}
```

**Note**: All benchmark columns are auto-detected; the concrete set may change based on llm-stats table updates.

## 5. Derived Score Calculations (Current — eighteen benchmarks)

All derived scores are computed from raw strings at display/persist time. Scoring
runs in two passes so that models aren't penalised simply for skipping benchmarks
their peers chose to publish.

### Detail-page benchmark enrichment

Before scoring, every model's detail page on llm-stats is visited and the embedded
Next.js flight payload is parsed for benchmark records. Scores are read from the
`normalized_score` field (always 0–1) and formatted as `xx.x%`. New benchmarks are
fuzzy-matched against existing leaderboard headers (alphanumeric canonicalization
plus an alias map for known abbreviations like `HLE` ↔ `Humanity's Last Exam`) so
we fill in missing cells rather than creating duplicate columns. Genuinely-new
benchmarks become new columns available to both passes.

### Missing-value markers

Missing cells are any of `""`, `"-"`, `"–"` (U+2013), `"—"` (U+2014), `"n/a"`,
`"N/A"`, `"null"`, `"None"`. Em-dash and en-dash must be included — llm-stats uses
typographic dashes, and treating them as reported-zero corrupts averages.

### Category-aggregate exclusion

The llm-stats leaderboard emits per-category rollup columns (`Reasoning`, `Math`,
`Coding`, `Search`, `Writing`, `Vision`, `Tools`, `Long Ctx`, `Finance`, `Legal`,
`Health`) which aggregate the individual benchmarks. These are preserved as raw
columns but excluded from `benchmark_headers` so they don't double-count during
scoring.

### Selected benchmark storage

Only the eighteen configured benchmark columns are persisted. Original sparse
benchmark filtering is not used for either Avg IQ, Value or gap research.

### AI gap-filling pass

Before scoring, `run_gap_filling_pass()` researches every missing component from the eighteen benchmarks in `data/core_benchmarks.json` for every retained model. It has no participation thresholds, qualification tiers, country/vendor filters or model coverage minimum. All gaps for a model are batched together in incoming model order. Existing configured aliases count as reported; sibling versions do not substitute for a requested result or prevent research.

The pass requires `OPENAI_API_KEY`, can be disabled with `--no-gap-fill`, and uses `--gap-fill-max-calls N` (default 40) as an API-call budget. Exact benchmark/model/protocol matching and source validation remain required. See [ai_gap_filling.md](ai_gap_filling.md) for caching, provenance and research behavior.

### Fresh source federation

The gap-filling pass can only enrich models and benchmark columns that llm-stats already exposed. New launch-day models and launch-page benchmark tables require an upstream ingestion lane. See [fresh_model_statistics_federation.md](fresh_model_statistics_federation.md) for the proposed source-federation layer: provider release adapters, benchmark-owner adapters, evidence logs, reconciliation, provisional rows, and a four-hour fresh-release scan.

### Scoring configuration and calculation

The authoritative methodology is [two_pass_scoring.md](two_pass_scoring.md).
`scripts/scoring.py` implements both paths; `data/core_benchmarks.json` supplies
the eighteen Avg IQ components and allocations totaling 100%.

Avg IQ includes all eighteen components at their configured weights. No
participation filter, half-cohort gate, participation multiplier, or fallback
can remove or downweight one of these components. Normalization still uses
known ranges, then percentage detection, then cohort ranges. Avg IQ divides
by a fixed 1.00 (100%); missing results contribute zero. Value retains its
original participation rules and reported-only denominator.

Avg Value uses the same eighteen-benchmark Avg IQ divided by total input and output
price. Saved scoring version 4 contains only new weights, ranges and bounds,
without legacy Value inputs. Historical rebuilding removes old benchmark scores
and regenerates scores from dated evidence while retaining model cohorts.

### Stage 2 (`--leaderboard-full`)

Writes the following files in the repository root:

- `stage2_combined.csv` — all columns and derived scores, in Unified-desc order.
- `stage2_combined.json` — same rows and ordering as the CSV.
- `stage2_country_aggregates.csv` — per-country totals and averages of Unified.
- `stage2_summary.json` — aggregates plus top-3 models per country by Unified.

Console table reads more comfortably with a slightly wider Model column.

### Stage 3 (default)

Writes only `models.json` (and updates `sitemap.xml` `lastmod` + `index.html` meta description). No stage CSVs are written in Stage 3 — they were redundant artifacts and have been removed. The pre-write backup file is auto-deleted after a successful write so the workspace stays clean.

---

## 7. CLI

```bash
# Stage 1: basic leaderboard (rank, name, country, URL) — table output only
python scripts/scrape_models.py --leaderboard-basic

# Stage 2: full leaderboard (all columns + derived scores; writes CSV/JSON)
python scripts/scrape_models.py --leaderboard-full

# Stage 3: full scrape with metadata enrichment + gap-filling + writes models.json
python scripts/scrape_models.py

# Stage 3 dry-run (no models.json modification, writes preview to stage3_dryrun.json)
python scripts/scrape_models.py --dry-run

# Skip the AI gap-filling pass entirely
python scripts/scrape_models.py --no-gap-fill

# Cap gap-fill API calls (useful for testing)
python scripts/scrape_models.py --gap-fill-max-calls 5

# Custom column width for tables
python scripts/scrape_models.py --leaderboard-full --max-col-width 50

# Run browser in visible mode for debugging
python scripts/scrape_models.py --debug
```

---

## 8. Dependencies

Python 3.11+ with `scripts/requirements.txt`:

```text
playwright==1.57.0
requests==2.31.0
python-dateutil==2.8.2
python-dotenv==1.0.1
Pillow==11.1.0
```

The OpenAI Responses API is called via plain `requests` against `https://api.openai.com/v1/responses` — no `openai` SDK dependency. `python-dotenv` is used to load `.env` at scraper startup so `OPENAI_API_KEY` is available locally; in CI the env var is injected directly via GitHub Actions secrets.

---

## 9. File Organization

```text
usvschinaai/
├── models.json                          # primary data file
├── news.json                            # secondary news feed
├── sitemap.xml                          # auto-updated lastmod on each scrape
├── index.html                           # leaderboard UI; meta description
│                                        #   month auto-updated each scrape
├── about.html / history.html            # supporting pages
├── llms.txt                             # AI knowledge map
├── scripts/
│   ├── scrape_models.py                 # main scraper + scoring
│   ├── gap_fill_benchmarks.py           # AI gap-filling pass
│   ├── scrape_news.py                   # news scraper
│   ├── post_to_instagram.py             # daily IG image
│   ├── generate_og_image.py             # social card generator
│   └── requirements.txt
├── data/
│   ├── ai_gap_cache.json                # gap-fill cache (committed)
│   └── ai_fill_history.jsonl            # gap-fill audit log (committed)
├── docs/
│   ├── scraper_specification.md         # this file
│   ├── two_pass_scoring.md
│   ├── ai_gap_filling.md
│   ├── coding_unified_score.md
│   └── seo_geo_aeo.md
├── .env                                 # local OPENAI_API_KEY (gitignored)
├── .env.example                         # template for .env
└── .github/workflows/
    ├── daily-scrape.yml                 # daily scraper run
    ├── deploy.yml                       # Azure Static Web Apps deploy
    ├── post-instagram.yml               # IG post automation
    └── bust-cache.yml                   # CDN cache bust
```

---

## 10. Error Handling

| Scenario | Behavior |
| --- | --- |
| Playwright timeout | Retry 2× with exponential backoff; fail after 3 attempts. |
| Country filter selector miss | Walk a fallback list of selectors; log loudly if all fail. |
| Missing benchmark data | Skip in AvgIQ if no valid score; log warning. |
| Detail-page enrichment failure | Skip the model's enrichment but continue with other models. |
| Sparse benchmark drop | Drop silently; print one summary line listing the dropped benchmarks. |
| Gap-fill: `OPENAI_API_KEY` missing | Skip the pass with one log line. Pass 1 / Pass 2 still run. |
| Gap-fill: OpenAI 5xx / network error | Retry 3× with exponential backoff; then skip the candidate. |
| Gap-fill: rate-limited (429) | Honor `Retry-After`; retry up to 3 times; then skip the candidate. |
| Gap-fill: schema validation failure | Drop the candidate; continue with the rest of the batch. |
| Pass 2: fewer than 3 qualified benchmarks | Fall back to Pass 1 scoring with a loud warning. |
| Invalid JSON generated | Backup file is preserved; log parse error; exit 1. |
| GitHub Actions env missing | Graceful fallback to stdout logging. |

---

## 11. Decisions Finalized

All open questions have been resolved:

| Decision | Selection |
| --- | --- |
| Benchmark handling | Auto-detected, per-benchmark range resolution (known → percentage → cohort fallback), category aggregates excluded, sparse benchmarks excluded from scoring at < 4 reporting models, with raw data retained. |
| Cron schedule | Daily via `.github/workflows/daily-scrape.yml`. |
| Failure notifications | Silent — errors logged to Actions output only, no Slack/email/GitHub alerts. |
| Two-pass scoring | Implemented over the whole scoring cohort with the configured eighteen weights for Avg IQ and Value. See [two_pass_scoring.md](two_pass_scoring.md). |
| AI gap-filling | Implemented via OpenAI Responses API + `web_search` tool. See [ai_gap_filling.md](ai_gap_filling.md). |

---

## 12. Success Criteria

- Scraper runs autonomously daily without manual intervention.
- Stage 2 CSV/JSON summaries generated and sorted by Unified.
- Stage 3 writes a clean `models.json` with no leftover stage files or backups.
- All scoring math is verified at run time (eligibility, qualified set, configured weights).
- Historical audit trail preserved (all previous entries intact, gap-fill audit appends to `data/ai_fill_history.jsonl`).
- Azure Static Web Apps auto-deploys the updated site within 2 minutes of push.
- Local execution works for testing: `python scripts/scrape_models.py`.
- The AI gap-filling pass either fills cells, returns honest `null`, or skips entirely — never corrupts existing scraped data.

### Automated source refresh

The daily scraper now refreshes llm-stats details, Artificial Analysis, Epoch,
original Toolathlon and CharXiv reasoning data before AI gap research. Newly
accepted evidence is retained with dates and configuration, then the daily
workflow rescores historical snapshots before generating the existing visuals.
See [AI gap filling](ai_gap_filling.md#routine-research-workflow) for source
coverage, failure handling and the limits of automated research.

Shared model records, dated roster references, and full-history recalculation are documented in [Model storage](model_storage.md).
