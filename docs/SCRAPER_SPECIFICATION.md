# Specification: Automated Models.json Update Scraper

**Project**: aiolympics  
**Feature**: Python-based automation for updating AI model leaderboard rankings  
**Status**: Active Development (Staged Architecture)

---

## 1. Overview

Automate daily data collection and aggregation for the US vs China AI leaderboard by scraping model rankings, benchmark scores, and pricing from [llm-stats.com/leaderboards/llm-leaderboard](https://llm-stats.com/leaderboards/llm-leaderboard), calculating competitive metrics (total, avgIq, value, unified scores), and prepending new history entries to `models.json`. The scraper uses a **staged architecture** with table-based debugging output at each stage.

---

## 2. Staged Architecture

The scraper operates in three distinct stages, each building upon the previous:

### Stage 1: Basic Leaderboard Extraction (`--leaderboard-basic`)
- **Purpose**: Extract top-10 models per country with essential identification data
- **Output**: Console tables (China/US) showing rank, name, country, model URL
- **Data Captured**: Minimal columns for verification and Stage 2 input
- **JSON Write**: Optional via `--write-json` flag

### Stage 2: Full Leaderboard Extraction (`--leaderboard-full`)
- **Purpose**: Capture all visible table columns from llm-stats leaderboard
- **Output**: Console tables (China/US) with all columns + derived scores at end
- **Data Captured**: 
  - Auto-detected headers in original column order
  - All cell values as raw strings (including "-", "n/a", empty strings)
  - Rank (1-10 per country, after filtering)
  - Name, URL, and every leaderboard column verbatim
  - Derived scores (total, avgIq, value, unified) appended at end
- **JSON Write**: Optional via `--write-json` flag

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
- **Derived scores only**: Computed fields (total, avgIq, value, unified) calculated from raw strings at display/persist time

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
  "total": number,
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

**Note**: All benchmark columns auto-detected; the 10 benchmarks listed above are current as of Jan 2026 but may change based on llm-stats table updates "HLE": number or 0,
   5. Derived Score Calculations

All derived scores are computed from raw string values at display/persist time. Non-numeric values (empty, "-", "n/a", etc.) are treated as **0** for calculation purposes.

**Total** (Sum of All Benchmarks):
```
total = Score_1 + Score_2 + ... + Score_N
```
- Non-numeric benchmark values = 0
- Captures breadth across all auto-detected benchmarks

**Average IQ** (Mean Benchmark Performance):
```
avgIq = total / number_of_benchmarks
```
- Non-numeric benchmarks counted as 0 in sum
- Denominator = total number of benchmark columns detected

**Value** (Cost-Adjusted Performance):
```
value = avgIq / costIn (if costIn > 0)
value = 0 (if costIn is 0, non-numeric, or missing)
```
- Measures performance per unit of input cost
- Non-numeric costIn treated as 0 → value = 0

**Unified Score** (Combined Metric):
```
unified = avgIq × 0.7 + value × 0.3
```
- Weighted blend: 70% capability, 30% cost efficiency
- Non-numeric inputs propagate through as 0
---

## 4. Calculations

**IQ Index** (Reward Breadth Across All Benchmarks):
```
IQ = (Score_1 + Score_2 + ... + Score_10) / 10
```
- Missing benchmarks = 0 (penalized)
- Range: 0–100

**Value Index** (Cost-Adjusted Performance):
```
BlendedCost = (3 × Input + 1 × Output) / 4
Value = 100 × (1 - log(BlendedCost / 0.25) / log(60.00 / 0.25))
```
- Floor: $0.25/1M tokens = Value 100
- Ceiling: $60.00/1M tokens = Value 0
- Range: 0–100

**Unified Power Score** (Overall Competitiveness):
```
Unified = IQ × (1 + Value/100)
```
- Captures both raw capability (IQ) and cost efficiency (Value)

**Team Aggregates** (per team):
- **Total**: Sum of 10 model Unified scores
- **avgIq**: Mean of 10 model IQ values
- **avgValue**: Mean of 10 model Value values

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

**Python 3.8+**  
**scripts/requirements.txt**:
```
playwright==1.40.0
requests==2.31.0
python-dateutil==2.8.2
```


**Stage Flags**:
```bash
# Stage 1: Basic leaderboard (rank, name, country, URL) - table output only
python scripts/scrape_models.py --leaderboard-basic

# Stage 2: Full leaderboard (all columns) - table output only
python scripts/scrape_models.py --leaderboard-full

# Stage 2 with JSON write
python scripts/scrape_models.py --leaderboard-full --write-json

# Stage 3: Full scrape with metadata (default, always writes JSON)
python scripts/scrape_models.py

# Custom column width for tables (default 36)
python scripts/scrape_models.py --leaderboard-full --max-col-width 50
```

**Output Behavior**:
- **Default**: Console tables showing China and US data with derived scores at end
- **--write-json**: Creates timestamped backup, prepends history entry to models.json
- **Table Format**: Max column width (default 36 chars), ellipsis for truncation, preserves column order

**Manual Steps**:
1. Run stage with desired flag
2. Review console table output
3. Optionally add --write-json to persist
4. Review updated models.json (git diff)
5 ✅ Valid: Prepends new entry to models.json; prints "SUCCESS: New entry prepended"
- ❌ Invalid: Rolls back changes; prints error with details; exits code 1

**Manual Steps**:
1. Backup `models.json` → `models.backup-YYYY-MM-DDTHHMMSS.json`
2. Run scraper
3. Review updated models.json (git diff)
4. Commit + push to GitHub

### B. GitHub Actions Scheduled
**.github/workflows/update-models.yml**:
- **Trigger**: Twice daily at 12:00 UTC (noon) and 00:00 UTC (midnight)
  - Cron 1: `0 12 * * *` (12:00 UTC)
  - Cron 2: `0 0 * * *` (00:00 UTC)
- **Runtime**: ~5–10 minutes per execution
- **Step 1**: Check out main branch
- **Step 2**: Set up Python 3.11
- **Step 3**: Install dependencies
- **Step 4**: Backup `models.json` → `models.backup-YYYY-MM-DDTHHMMSS.json` (UTC)
- **Step 5**: Run scraper with validation
- **Step 6**: Commit + push if successful

**On Success**:
- Auto-commits: `[Auto] Update models.json: Jan 21, 2026`
- Pushes to main
- Triggers Azure Static Web Apps deploy

**On Failure**:
- Logs error details to Actions output
- No commit
- Silent (no Slack/email/GitHub notifications)

---

## 9. Error Handling

| Scenario | Behavior |
|----------|----------|
| **Playwright timeout** | Retry 2× with exponential backoff; fail after 3 attempts |
| **Missing benchmark data** | Fill with 0; log warning |
| **Invalid JSON generated** | Roll back; log parse error; exit 1 |
| **Validation failure** | Log rule name + details; exit 1; no commit |
| **Network error (llm-stats.com down)** | Retry 3×; fail after 3 attempts; notify operator |
| **GitHub Actions env missing** | Graceful fallback to stdout logging |

---

## 10. Decisions Finalized

All open questions have been resolved:

| Decision | Selection | Status |
|----------|-----------|---------|
| **Benchmark Count** | 10 benchmarks (no 11th benchmark addition) | ✅ FINAL |
| **Cron Schedule** | Twice daily: 12:00 UTC (noon) AND 00:00 UTC (midnight) | ✅ FINAL |
| **Failure Notifications** | Silent—no Slack/email/GitHub alerts; errors logged to Actions output only | ✅ FINAL |

---

## 11. Success Criteria

- ✅ Scraper runs autonomously daily without manual intervention
- ✅ models.json updated with new 20-model entry prepended to history
- ✅ All calculations verified before commit
- ✅ Historical audit trail preserved (all previous entries intact)
- ✅ Azure Static Web Apps auto-deploys updated site within 2 minutes of push
- ✅ Local execution works for testing: `python scripts/scrape_models.py`
- ✅ Validation catches 100% of calculation errors before commit
