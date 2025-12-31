# US vs CHINA AI — Project Specification

## 1. Project Overview

| Field | Value |
|-------|-------|
| **Project Name** | US vs CHINA AI Dashboard |
| **Domain** | usvschina.ai |
| **Date** | December 30, 2025 |
| **Purpose** | Rank frontier AI models by intelligence and cost efficiency, tracking the US-China AI competition |
| **Benchmarks** | 10 Frontier Benchmarks |

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

### Unified Power Score (Max ~180)

$$\text{Unified} = I \times \left(1 + \frac{V_{\text{norm}}}{100}\right)$$

**Intelligence gates everything.** A model with low intelligence cannot score high, regardless of how cheap it is. Value acts as a multiplier boost, not an equal component.

| Component | Range | Role |
|-----------|-------|------|
| Intelligence (I) | 0–100 | Gates the score (multiplicative) |
| Value (V_norm) | 50–100 | Boosts the score (1.5× to 2.0× multiplier) |

**Examples:**
- IQ 80, Value 75 (avg cost) → Unified = 80 × 1.75 = **140**
- IQ 60, Value 100 (free) → Unified = 60 × 2.0 = **120** (can't overcome low IQ)
- IQ 40, Value 100 (free) → Unified = 40 × 2.0 = **80** (low IQ ceiling)

### Intelligence Index — Raw Score (0–100)

**Raw IQ:** Unweighted average of available benchmark scores (only benchmarks with data count).

$$I = \frac{\sum_{i=1}^{n} \text{Benchmark}_i}{n} \quad \text{where } n = \text{benchmarks with data}$$

#### 10 Frontier Benchmarks

| # | Benchmark | Category | Source |
|---|-----------|----------|--------|
| 1 | AIME 2025 | Math Olympiad | [llm-stats](https://llm-stats.com/benchmarks/aime-2025) |
| 2 | HMMT 2025 | Math Tournament | [llm-stats](https://llm-stats.com/benchmarks/hmmt) |
| 3 | GPQA Diamond | PhD Science | [llm-stats](https://llm-stats.com/benchmarks/gpqa) |
| 4 | BrowseComp | Web Agents | [llm-stats](https://llm-stats.com/benchmarks/browsecomp) |
| 5 | ARC-AGI v2 | Advanced Reasoning | [arcprize.org](https://arcprize.org/) |
| 6 | HLE | Multidisciplinary | [llm-stats](https://llm-stats.com/benchmarks/hle) |
| 7 | MMLU-Pro | Knowledge | [llm-stats](https://llm-stats.com/benchmarks/mmlu-pro) |
| 8 | LiveCodeBench | Coding | [llm-stats](https://llm-stats.com/benchmarks/livecodebench) |
| 9 | SWE-Bench Verified | Software Engineering | [llm-stats](https://llm-stats.com/benchmarks/swe-bench-verified) |
| 10 | CodeForces | Competitive Programming | [llm-stats](https://llm-stats.com/benchmarks/codeforces) |

### Value Index — Normalized to 50–100

**Raw Value:** Log-normalized efficiency based on blended cost per 1M tokens:

$$V_{\text{raw}} = 100 \times \left(1 - \frac{\log(C / 0.25)}{\log(60.00 / 0.25)}\right)$$

**Blended Cost:**

$$C = \frac{3 \times \text{Input} + 1 \times \text{Output}}{4}$$

**Normalized Value:** (ensures minimum 50 even for expensive models)

$$V_{\text{norm}} = 50 + \frac{V_{\text{raw}}}{100} \times 50$$

| Threshold | Cost | Raw Value | Normalized |
|-----------|------|-----------|------------|
| Floor (Best) | $0.25 | 100 | 100 |
| Ceiling (Worst) | $60.00 | 0 | 50 |

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

## 7. Current Rankings (Dec 31, 2025)

| Rank | Model | Origin | Unified | IQ (0-100) | Value (50-100) |
|------|-------|--------|---------|-----------|----------------|
| 1 | Gemini 3 Flash | 🇺🇸 | 166.5 | 89.4 | 86.3 |
| 2 | Gemini 3 Pro | 🇺🇸 | 155.2 | 89.4 | 73.6 |
| 3 | Grok-4 Heavy | 🇺🇸 | 152.7 | 89.3 | 71.0 |
| 4 | GPT-5.1 | 🇺🇸 | 151.7 | 86.1 | 76.1 |
| 5 | Grok-4 | 🇺🇸 | 147.2 | 86.1 | 71.0 |
| 6 | DeepSeek-V3.2-Exp | 🇨🇳 | 143.5 | 72.4 | 98.2 |
| 7 | Kimi K2-Thinking | 🇨🇳 | 142.1 | 75.3 | 88.8 |
| 8 | DeepSeek-V3.2 | 🇨🇳 | 141.7 | 71.6 | 97.9 |
| 9 | Qwen3-235B-Thinking | 🇨🇳 | 138.9 | 74.1 | 87.6 |
| 10 | MiMo-V2-Flash | 🇨🇳 | 138.8 | 69.4 | 100.0 |

### National Totals (Top 10 Method)

| Team | Score | Models in Top 10 |
|------|-------|------------------|
| 🇺🇸 USA | 773.3 | 5 |
| 🇨🇳 China | 705.0 | 5 |

**Leader:** Team USA 🇺🇸 by 68.3 points

---

*Last Updated: December 31, 2025*

