# US vs CHINA AI Dashboard

A leaderboard that ranks the world's best AI models by both **intelligence** and **cost efficiency**—then shows you which country is winning.

Use it to compare models side-by-side, find the best value for your use case, and see how the US–China AI race is unfolding in near real time.

## Features

- **Unified Score (0–1000)**: 90% capability + 10% value, cohort-normalized
- **National Scoreboard**: Aggregation for Team USA 🇺🇸 vs Team China 🇨🇳
- **Auto-Sorted**: Rankings sorted by Unified descending
- **Historical Archives**: Track how the balance of power shifts over time with expandable entries
- **About Page**: Full methodology, assumptions, and benchmark explanations
- **Daily Automation**: GitHub Actions runs the scraper automatically every day at 00:00 UTC

## Pages

| Page | Description |
|------|-------------|
| `index.html` | Main leaderboard with current rankings |
| `history.html` | Historical snapshots over time |
| `about.html` | Scoring methodology and assumptions |

## Data Structure

All site data lives in a single `models.json` file:

```json
{
  "metadata": { "title": "...", "subtitle": "...", "footerText": "..." },
  "teams": { "usa": {...}, "china": {...} },
  "benchmarks": ["AIME 2025", "HMMT 2025", ...],
  "columns": [...],
  "history": [
    {
      "timestamp": "2025-12-30T12:00:00-05:00",
      "leader": "china",
      "scores": { "usa": {...}, "china": {...} },
      "benchmarks": [...],
      "models": [...]
    }
  ]
}
```

The main page displays the latest history entry. The archives page displays all entries sorted by date.

## Setup & Usage

This project uses `fetch()` to load JSON data, so it requires a local web server.

### Python (Recommended)

```bash
python3 -m http.server
```

Then open `http://localhost:8000`

### VS Code Live Server

1. Install the **Live Server** extension
2. Right-click `index.html` → **Open with Live Server**

### Node.js

```bash
npx http-server .
```

## Scoring Methodology (Current)

- **Per-benchmark normalization (0–100):** For each benchmark with ≥2 participating models, scores are min–max normalized across the cohort. Benchmarks with a single participant are excluded from scoring.
- **Participation weighting:** Each benchmark is weighted by its participation fraction (models reporting that benchmark ÷ max participation across benchmarks).
- **AvgIQ:** Weighted average of the per-benchmark normalized scores.
- **Value:** `AvgIQ / (Input $/M + Output $/M)`.
- **Cohort normalization:** Both AvgIQ and Value are min–max normalized to 0–100 across the cohort.
- **Unified (0–1000):** `10 × (0.9 × norm(AvgIQ) + 0.1 × norm(Value))`.
- **Sorting:** Leaderboards are sorted by Unified (descending).

Notes:
- Multimodal parsing is detected from table icons (green check = Yes; grey X = No).
- Benchmarks are auto-detected from the source table; the exact set may change over time.
- The 90/10 weighting emphasizes capability (AvgIQ) over value, reflecting industry focus on model performance.

## Tech Stack

- **Core**: HTML5, Vanilla JavaScript
- **Styling**: Tailwind CSS (CDN)
- **Icons**: Lucide (CDN)
- **Charts**: Chart.js (CDN)

## File Structure

```
├── index.html             # Main leaderboard
├── history.html           # Historical archives
├── about.html             # Methodology & assumptions
├── models.json            # All data (current + history)
├── scripts/
│   └── scrape_models.py   # Scraper (Stage 1–3)
├── docs/
│   └── SCRAPER_SPECIFICATION.md
└── README.md              # This file
```

## Scraper Quickstart

Requires Python 3.11+ and Playwright.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r scripts/requirements.txt
playwright install chromium

# Full scrape with metadata enrichment (default)
python scripts/scrape_models.py
```

The scraper runs through 3 stages:
1. **Stage 1**: Fetches raw leaderboard data from source
2. **Stage 2**: Generates CSV exports and summary JSON
3. **Stage 3**: Enriches with metadata (company, release date, parameters, etc.) and prepends a new history entry to `models.json`

## Automated Daily Runs

The project includes a GitHub Actions workflow (`.github/workflows/daily-scrape.yml`) that:
- Runs automatically every day at **00:00 UTC** (8:00 AM UTC+8)
- Installs dependencies and Playwright browsers
- Executes the scraper
- Automatically commits and pushes results to the main branch
- Can be manually triggered from the **Actions** tab on GitHub

To view workflow runs and logs:
1. Go to your GitHub repository
2. Click the **Actions** tab
3. Select "Daily AI Model Scrape"
4. Click any run to see detailed logs

---

Last updated: January 2026

