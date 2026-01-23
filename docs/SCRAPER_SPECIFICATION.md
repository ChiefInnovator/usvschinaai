# Specification: Automated Leaderboard Scraper and Scoring

**Project**: aiolympics  
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
  "AIME 2025": "string (raw score)",
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

## 5. Derived Score Calculations (Current)

All derived scores are computed from raw strings at display/persist time.

1) Per-benchmark normalization (0–100):
- For each benchmark with participation ≥ 2, compute min/max across the cohort and normalize: `(score − min) / (max − min) × 100`.
- Benchmarks with a single participant are excluded from scoring.

2) Participation weighting:
- Weight for a benchmark b: `w_b = participation[b] / max_participation`.

3) AvgIQ (capability):
- `avgIq = sum(norm_b × w_b) / sum(w_b)` over benchmarks with valid scores.

4) Value (cost efficiency):
- `value = avgIq / (Input $/M + Output $/M)` (0 if total cost ≤ 0).

5) Cohort normalization (0–100):
- Compute min/max of `avgIq` and `value` across the cohort, then min–max normalize both to 0–100.

6) Unified (0–1000):
- `unified = 10 × (0.7 × norm(avgIq) + 0.3 × norm(value))`.

Sorting: All leaderboards are ordered by Unified (descending).
---

## 6. Outputs

Stage 2 writes the following files in the repository root:
- `stage2_combined.csv` — All columns and derived scores, in Unified‑desc order
- `stage2_combined.json` — Same rows/ordering as CSV
- `stage2_country_aggregates.csv` — Per‑country totals/averages of Unified
- `stage2_summary.json` — Aggregates + top‑3 models per country by Unified

Console table reads more comfortably via a slightly wider Model column.

---

## 5. Validation Rules

Run post-calculation before committing to models.json:

| Rule | Details | Action on Fail |
|------|---------|--------|
| JSON Valid | Parse output as JSON | Log error + exit |
| Link HTTP Checks | GET each `companyLink`; expect 200/3xx | Warn (don't block) |
| Benchmark Count | 10 benchmarks per model | Error + exit |
| IQ Math | Verify IQ = sum / 10 | Error + exit |
| Value Math | Verify Value formula against scores | Error + exit |
| Unified Math | Verify Unified = IQ × (1 + Value/100) | Error + exit |
| Rank Uniqueness | Ranks 1–20 (no duplicates/gaps) | Error + exit |
| Team Totals | Sum of 10 scores per team | Error + exit |
| Origin Count | Exactly 10 "US" + 10 "CN" | Error + exit |
| Required Fields | name, company, origin, iq, value, unified, benchmarks, costs | Error + exit |

---

## 6. File Organization

```
/Users/rich/Documents/aiolympics/
├── models.json                          # Primary data file
├── models.backup-2025-12-30.json        # Safety backup (created manually)
├── newday.md                            # Manual prompt template (reference)
├── scripts/                             # NEW: Automation scripts
│   ├── scrape_models.py                # Main scraper + calculator + validator
│   └── requirements.txt                 # Python dependencies
├── .github/workflows/
│   └── update-models.yml                # NEW: CI/CD workflow
└── [other project files]
```

---

## 7. Dependencies

**Python 3.11+**  
**scripts/requirements.txt**:
```
playwright>=1.40.0
```


**CLI**:
```bash
# Stage 1: Basic leaderboard (rank, name, country, URL) - table output only
python scripts/scrape_models.py --leaderboard-basic

# Stage 2: Full leaderboard (all columns + derived scores; writes CSV/JSON)
python scripts/scrape_models.py --leaderboard-full

# Stage 3: Full scrape with metadata (default, always writes JSON)
python scripts/scrape_models.py

# Custom column width for tables (default 36)
python scripts/scrape_models.py --leaderboard-full --max-col-width 50
```

**Output Behavior**:
- Default: Console table (Unified‑desc) + CSV/JSON summaries in repo root
- Table: Max column width (default 36), with +5 width for Model column in Stage 2

**Manual Steps**:
1. Run with desired stage flag
2. Review console output and CSV/JSON summaries
3. If using Stage 3, review the `models.json` update before committing

### B. GitHub Actions (Optional)
- Triggers and cadence configurable per repository
- Set up Python, install deps, run Stage 2/3, and commit on success

---

## 9. Error Handling

| Scenario | Behavior |
|----------|----------|
| **Playwright timeout** | Retry 2× with exponential backoff; fail after 3 attempts |
| **Missing benchmark data** | Skip in AvgIQ if no valid score; log warning |
| **Invalid JSON generated** | Roll back; log parse error; exit 1 |
| **Validation failure** | Log rule name + details; exit 1; no commit |
| **Network error (llm-stats.com down)** | Retry 3×; fail after 3 attempts; notify operator |
| **GitHub Actions env missing** | Graceful fallback to stdout logging |

---

## 10. Decisions Finalized

All open questions have been resolved:

| Decision | Selection | Status |
|----------|-----------|---------|
| **Benchmark Handling** | Auto-detected; per-benchmark min–max normalization; skip single-participation | ✅ FINAL |
| **Cron Schedule** | Twice daily: 12:00 UTC (noon) AND 00:00 UTC (midnight) | ✅ FINAL |
| **Failure Notifications** | Silent—no Slack/email/GitHub alerts; errors logged to Actions output only | ✅ FINAL |

---

## 11. Success Criteria

- ✅ Scraper runs autonomously daily without manual intervention
- ✅ Stage 2 CSV/JSON summaries generated and sorted by Unified
- ✅ All calculations verified during run
- ✅ Historical audit trail preserved (all previous entries intact)
- ✅ Azure Static Web Apps auto-deploys updated site within 2 minutes of push
- ✅ Local execution works for testing: `python scripts/scrape_models.py`
- ✅ Validation catches 100% of calculation errors before commit
