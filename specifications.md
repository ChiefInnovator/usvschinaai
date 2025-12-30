# US vs CHINA AI — Project Specification

## 1. Project Overview

| Field | Value |
|-------|-------|
| **Project Name** | US vs CHINA AI Dashboard |
| **Domain** | usvschina.ai |
| **Date** | December 30, 2025 |
| **Purpose** | Rank frontier AI models by intelligence and cost efficiency, tracking the US-China AI competition |

## 2. Technical Stack

- **Architecture:** Static HTML5 frontend with JSON data source
- **Styling:** Tailwind CSS (CDN)
- **Icons:** Lucide (CDN)
- **Charts:** Chart.js (CDN)
- **JavaScript:** Vanilla ES6+

### Design System

| Element | Value |
|---------|-------|
| Background | `bg-slate-950` |
| USA Accent | `#3b82f6` (Electric Blue) |
| China Accent | `#ef4444` (Crimson Red) |
| Glass Effect | `rgba(30, 41, 59, 0.4)` with backdrop blur |

## 3. File Structure

```
├── index.html        # Main leaderboard (loads latest history entry)
├── history.html      # Historical archives (loads all history entries)
├── about.html        # Methodology, assumptions, benchmarks
├── models.json       # Single source of truth for all data
├── specifications.md # This file
└── README.md         # Quick start guide
```

## 4. Data Schema

### models.json Structure

```json
{
  "metadata": {
    "title": "US vs CHINA AI",
    "subtitle": "...",
    "footerText": "..."
  },
  "teams": {
    "usa": { "name": "Team USA", "flag": "🇺🇸", "description": "...", "badge": "..." },
    "china": { "name": "Team China", "flag": "🇨🇳", "description": "...", "badge": "..." }
  },
  "benchmarks": ["AIME 2025", "HMMT 2025", ...],
  "columns": [
    { "key": "rank", "label": "Rank" },
    { "key": "name", "label": "Model" },
    ...
  ],
  "history": [
    {
      "timestamp": "2025-12-30T12:00:00-05:00",
      "leader": "china",
      "scores": {
        "usa": { "total": 662.5, "avgIq": 89.5, "avgValue": 83.5 },
        "china": { "total": 1009.6, "avgIq": 89.4, "avgValue": 91.2 }
      },
      "benchmarks": [...],
      "models": [...]
    }
  ]
}
```

### Model Object

```json
{
  "rank": 1,
  "name": "DeepSeek-V3.2",
  "company": "DeepSeek",
  "companyLink": "https://...",
  "origin": "CN",
  "description": "...",
  "unified": 184.8,
  "iq": 92.4,
  "value": 100,
  "createdDate": "2025-12-15",
  "link": "https://...",
  "costPer1M": 0.25,
  "benchmarkScores": {
    "AIME 2025": { "score": 99.1, "source": "https://..." },
    ...
  }
}
```

## 5. Scoring Methodology

### Unified Power Score (Max 200)

$$\text{Unified} = I \times \left(1 + \frac{V}{100}\right)$$

*Intelligence gates everything. A model with zero intelligence scores zero, no matter how cheap.*

### Intelligence Index (I) — Max 100

Unweighted average of 11 frontier benchmarks:

| # | Benchmark | Category | Source |
|---|-----------|----------|--------|
| 1 | AIME 2025 | Math Olympiad | [llm-stats](https://llm-stats.com/benchmarks/aime-2025) |
| 2 | HMMT 2025 | Math Tournament | [llm-stats](https://llm-stats.com/benchmarks/hmmt) |
| 3 | GPQA Diamond | PhD Science | [llm-stats](https://llm-stats.com/benchmarks/gpqa) |
| 4 | ARC-AGI | Reasoning | [arcprize.org](https://arcprize.org/) |
| 5 | BrowseComp | Web Agents | [llm-stats](https://llm-stats.com/benchmarks/browsecomp) |
| 6 | ARC-AGI v2 | Advanced Reasoning | [arcprize.org](https://arcprize.org/) |
| 7 | HLE | Multidisciplinary | [llm-stats](https://llm-stats.com/benchmarks/hle) |
| 8 | MMLU-Pro | Knowledge | [llm-stats](https://llm-stats.com/benchmarks/mmlu-pro) |
| 9 | LiveCodeBench | Coding | [llm-stats](https://llm-stats.com/benchmarks/livecodebench) |
| 10 | SWE-Bench Verified | Software Engineering | [llm-stats](https://llm-stats.com/benchmarks/swe-bench-verified) |
| 11 | CodeForces | Competitive Programming | [llm-stats](https://llm-stats.com/benchmarks/codeforces) |

### Value Index (V) — Max 100

Log-normalized efficiency based on blended cost per 1M tokens:

$$V = 100 \times \left(1 - \frac{\log(C / 0.25)}{\log(60.00 / 0.25)}\right)$$

| Threshold | Cost | Value |
|-----------|------|-------|
| Floor (Best) | $0.25 | 100 |
| Ceiling (Worst) | $60.00 | 0 |

### National Score

**Rule:** Sum of Unified Scores for models in the **Global Top 10** belonging to each nation.

- Only Top 10 models contribute to the national score
- Rewards both peak performance (#1 model) and depth (multiple models in Top 10)

## 6. UI Components

### Pages

| Page | Title Format | Data Source |
|------|--------------|-------------|
| index.html | `US vs CHINA AI` | Latest `history[]` entry |
| history.html | `Historical Archives` | All `history[]` entries (desc by date) |
| about.html | `About This Project` | Static content |

### Filters (index.html & history.html)

| Filter | Behavior |
|--------|----------|
| Top 10 (default) | Global Top 10 by Unified score |
| All | All models in dataset |
| USA | All US-origin models |
| China | All China-origin models |

### Benchmark Badge Colors

| Color | Benchmarks |
|-------|------------|
| Blue | AIME 2025, HMMT 2025, GPQA Diamond |
| Red | ARC-AGI, BrowseComp, ARC-AGI v2 |
| Purple | HLE, MMLU-Pro, LiveCodeBench |
| Yellow | SWE-Bench Verified, CodeForces |

## 7. Current Rankings (Dec 30, 2025)

| Rank | Model | Origin | Unified | IQ | Value |
|------|-------|--------|---------|-----|-------|
| 1 | DeepSeek-V3.2 | 🇨🇳 | 184.8 | 92.4 | 100.0 |
| 2 | DeepSeek-V3.2-Speciale | 🇨🇳 | 176.1 | 90.1 | 95.5 |
| 3 | Gemini 3 Pro | 🇺🇸 | 171.7 | 96.2 | 78.5 |
| 4 | Gemini 3 Flash | 🇺🇸 | 170.0 | 88.5 | 92.0 |
| 5 | DeepSeek-V3.2-Exp | 🇨🇳 | 168.1 | 88.0 | 91.0 |
| 6 | Qwen 3 Max | 🇨🇳 | 165.2 | 89.1 | 85.3 |
| 7 | Qwen3-235B-Thinking | 🇨🇳 | 161.0 | 87.5 | 84.0 |
| 8 | Grok Code Fast 1 | 🇺🇸 | 161.7 | 86.0 | 88.0 |
| 9 | GPT-5 mini | 🇺🇸 | 159.1 | 82.0 | 94.0 |
| 10 | GPT-5.1 | 🇺🇸 | 153.5 | 93.0 | 65.0 |

### National Totals

| Team | Score | Models in Top 10 |
|------|-------|------------------|
| 🇨🇳 China | 1009.6 | 5 |
| 🇺🇸 USA | 662.5 | 5 |

**Leader:** Team China 🇨🇳

---

*Last Updated: December 30, 2025*

