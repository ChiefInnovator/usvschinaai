# US vs CHINA AI Dashboard

A leaderboard that ranks the world's best AI models by both **intelligence** and **cost efficiency**—then shows you which country is winning.

**Use it to:** Compare models side-by-side, find the best value for your use case, and see how the US-China AI race is unfolding in real time.

## Features

- **Unified Power Score**: Ranks models by Intelligence × Value (max 200)
- **National Scoreboard**: Real-time aggregation for Team USA 🇺🇸 vs Team China 🇨🇳
- **Interactive Filters**: View Top 10, All models, or filter by country
- **Historical Archives**: Track how the balance of power shifts over time
- **About Page**: Full methodology, assumptions, and benchmark explanations

## Pages

| Page | Description |
|------|-------------|
| `index.html` | Main leaderboard with current rankings |
| `history.html` | Historical snapshots over time |
| `about.html` | Scoring methodology and assumptions |

## Data Structure

All data lives in a single `models.json` file:

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

The main page displays the **latest** history entry. The archives page displays **all** entries sorted by date.

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

## Scoring Methodology

**Unified Power Score** (Max 200) = Intelligence × (1 + Value/100)

### Intelligence Index (I) — Max 100

Unweighted average of 10 frontier benchmarks:

| Category | Benchmarks |
|----------|------------|
| Math | AIME 2025, HMMT 2025 |
| Science | GPQA Diamond |
| Reasoning | ARC-AGI v2, HLE |
| Agents | BrowseComp |
| Knowledge | MMLU-Pro |
| Coding | LiveCodeBench, SWE-Bench Verified, CodeForces |

### Value Index (V) — Max 100

Log-normalized cost efficiency based on blended cost per 1M tokens.

- **Floor:** $0.25 (best value = 100)
- **Ceiling:** $60.00 (worst value = 0)

### National Score

Sum of Unified Scores for models in the **Global Top 10** belonging to each nation.

## Tech Stack

- **Core**: HTML5, Vanilla JavaScript
- **Styling**: [Tailwind CSS](https://tailwindcss.com/) (CDN)
- **Icons**: [Lucide](https://lucide.dev/) (CDN)
- **Charts**: [Chart.js](https://www.chartjs.org/) (CDN)

## File Structure

```
├── index.html        # Main leaderboard
├── history.html      # Historical archives
├── about.html        # Methodology & assumptions
├── models.json       # All data (current + history)
├── specifications.md # Detailed project spec
└── README.md         # This file
```

---

*Data Audited: December 30, 2025*
