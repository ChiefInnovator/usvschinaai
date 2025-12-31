# Prompt: Generate & Add New Day's Data to models.json

Create a comprehensive JSON dataset for **TODAY'S DATE** (use the current date), to be **added to the existing models.json history array**. This will append a new day's competitive analysis of top AI models from the United States and China.

## Data Source

**IMPORTANT**: Always fetch benchmark data from **https://llm-stats.com/benchmarks/llm-leaderboard-full** to determine the model list and benchmark scores. This ensures all data is current and accurate.

## Model Selection Process

1. **Fetch the full leaderboard** from llm-stats.com
2. **Extract ALL 11 benchmark scores** for each model (see benchmark list below)
3. **Assign 0 to any missing benchmark** - models without complete data are penalized
4. **Calculate IQ Index** as the average of ALL 11 benchmarks (rewarding well-rounded performance)
5. **Rank all models** by their IQ Index (average of all benchmarks)
6. **Select Top 10 US models** (🇺🇸 flag in leaderboard) by IQ Index
7. **Select Top 10 China models** (🇨🇳 flag in leaderboard) by IQ Index

## Data Structure Requirements

### 1. Top 10 US Models and Top 10 China Models with:
- Model name and company (from llm-stats.com)
- Company website link
- Detailed model description (capabilities, parameters, architecture highlights)
- Release/creation date
- Base cost ($ per 1M input tokens) - from llm-stats.com pricing
- Cost per output ($ per 1M output tokens) - from llm-stats.com pricing

### 2. Benchmark Scores (from llm-stats.com):
Use actual benchmark data available on llm-stats.com. **ALL 11 benchmarks are REQUIRED**:

| # | Benchmark | Category | Source |
|---|-----------|----------|--------|
| 1 | AIME 2025 | Math Olympiad | llm-stats.com/benchmarks/aime-2025 |
| 2 | HMMT 2025 | Math Tournament | llm-stats.com/benchmarks/hmmt |
| 3 | GPQA Diamond | PhD Science | llm-stats.com/benchmarks/gpqa |
| 4 | ARC-AGI | Reasoning | arcprize.org |
| 5 | BrowseComp | Web Agents | llm-stats.com/benchmarks/browsecomp |
| 6 | ARC-AGI v2 | Advanced Reasoning | arcprize.org |
| 7 | HLE | Multidisciplinary | llm-stats.com/benchmarks/hle |
| 8 | MMLU-Pro | Knowledge | llm-stats.com/benchmarks/mmlu-pro |
| 9 | LiveCodeBench | Coding | llm-stats.com/benchmarks/livecodebench |
| 10 | SWE-Bench Verified | Software Engineering | llm-stats.com/benchmarks/swe-bench-verified |
| 11 | CodeForces | Competitive Programming | llm-stats.com/benchmarks/codeforces |

**IMPORTANT**: If a benchmark score is unavailable for a model, assign it **0** (not null). This ensures models are rewarded for performing well across ALL benchmarks, not just a subset.

### 3. Calculated Scores:
- **IQ Index**: Average of ALL 11 benchmark scores. Missing benchmarks count as 0.
  ```
  IQ = (AIME 2025 + HMMT 2025 + GPQA Diamond + ARC-AGI + BrowseComp + ARC-AGI v2 + HLE + MMLU-Pro + LiveCodeBench + SWE-Bench Verified + CodeForces) / 11
  ```
- **Value Index**: Calculated using logarithmic formula:
  \`\`\`
  Blended Cost = (3 × Input + 1 × Output) / 4
  Value = 100 × (1 - log(BlendedCost / 0.25) / log(60.00 / 0.25))
  \`\`\`
  - Floor: $0.25 blended cost = Value 100
  - Ceiling: $60.00 blended cost = Value 0
- **Unified Power Score**: IQ × (1 + Value/100)

### 4. Aggregate Statistics:
- Total scores for each team (USA, China)
- Average IQ for each team
- Average Value for each team
- Overall winner (team with highest total Unified Power Score)
- Top model (rank #1 by Unified Power Score)

## Integration Instructions

This new entry will be **prepended to the existing history array** in models.json. The structure should be:

\`\`\`json
{
  "metadata": { ... (keep existing unchanged) ... },
  "teams": { ... (keep existing unchanged) ... },
  "columns": { ... (keep existing unchanged) ... },
  "history": [
    {
      "timestamp": "[TODAY'S ISO TIMESTAMP at 12:00:00 UTC-5]",
      "leader": "usa" or "china",
      "auditDate": "[TODAY'S DATE formatted as 'Mon DD, YYYY']",
      "subtitle": "Performance Audit: [TODAY'S DATE formatted as 'Mon DD, YYYY']",
      "benchmarks": ["AIME 2025", "HMMT 2025", "GPQA Diamond", "ARC-AGI", "BrowseComp", "ARC-AGI v2", "HLE", "MMLU-Pro", "LiveCodeBench", "SWE-Bench Verified", "CodeForces"],
      "scores": {
        "usa": { "total": [sum], "avgIq": [avg], "avgValue": [avg] },
        "china": { "total": [sum], "avgIq": [avg], "avgValue": [avg] }
      },
      "models": [
        {
          "rank": 1-20,
          "name": "Model Name",
          "company": "Company Name",
          "companyLink": "https://...",
          "origin": "US" or "CN",
          "description": "Multi-sentence description...",
          "unified": [calculated score],
          "iq": [average of all 11 benchmarks],
          "value": [cost-adjusted score],
          "createdDate": "[Model release date in YYYY-MM-DD format]",
          "costInputPer1M": 0.50,
          "costOutputPer1M": 1.50,
          "benchmarks": {
            "AIME 2025": 92.5,
            "HMMT 2025": 85.0,
            "GPQA Diamond": 88.0,
            "ARC-AGI": 45.0,
            "BrowseComp": 52.0,
            "ARC-AGI v2": 30.0,
            "HLE": 28.0,
            "MMLU-Pro": 78.0,
            "LiveCodeBench": 65.0,
            "SWE-Bench Verified": 73.1,
            "CodeForces": 55.0
          }
        }
        ... (20 models total: 10 US + 10 CN)
      ]
    },
    { ... existing previous day entry ... },
    { ... any older entries ... }
  ]
}
\`\`\`

## Integration Process

1. **Fetch llm-stats.com data** to get current benchmark scores and pricing
2. **Generate only the new history entry object** (the single object with TODAY'S timestamp, auditDate, subtitle, benchmarks, and its 20 models)
3. **Do NOT modify** metadata, teams, or columns - keep them exactly as they are
4. **Insert at the beginning** of the history array (newest data first)
5. **Preserve all existing history entries** - this maintains the historical audit trail

## Quality Requirements

1. All benchmark scores must come from llm-stats.com (real data)
2. Cost data must be from llm-stats.com pricing columns
3. Model descriptions should mention key differentiators (reasoning, speed, cost, parameter count, etc.)
4. Ensure exactly 10 US + 10 China models (top 10 from each country by IQ Index)
5. **All 20 models must have ranks 1-20** (one for each position, no duplicates)

## Value Index Formula Reference

\`\`\`javascript
function calculateValue(inputCost, outputCost) {
  const blendedCost = (3 * inputCost + 1 * outputCost) / 4;
  const floor = 0.25;
  const ceiling = 60.00;
  
  if (blendedCost <= floor) return 100;
  if (blendedCost >= ceiling) return 0;
  
  return 100 * (1 - Math.log(blendedCost / floor) / Math.log(ceiling / floor));
}
\`\`\`

## Unified Score Formula Reference

\`\`\`javascript
function calculateUnified(iq, value) {
  return Math.round(iq * (1 + value / 100) * 10) / 10;
}
\`\`\`

## Verification Checklist

After generating the new day's data and before integration, verify:

- [ ] **JSON Syntax Valid**: The generated object parses as valid JSON
- [ ] **All Fields Present**: Each model has rank, name, company, companyLink, origin, description, unified, iq, value, createdDate, costInputPer1M, costOutputPer1M, and benchmarks object
- [ ] **Data Source**: All benchmark scores and pricing from llm-stats.com
- [ ] **Model & Company Existence**: 
  - All 20 model names are real and exist on llm-stats.com ✓
  - All 20 companies are real and currently operational ✓
  - companyLink URLs are valid and point to official company websites ✓
- [ ] **Benchmark Coverage**: All 11 benchmarks present for each model (use 0 for missing)
- [ ] **Ranks Unique**: Models ranked 1-20 with no duplicates or gaps
- [ ] **Score Calculations**: 
  - IQ Index = Average of ALL 11 benchmarks / 11 ✓
  - Value Index = calculated from pricing using log formula ✓
  - Unified Score = IQ × (1 + Value/100) ✓
- [ ] **Team Scores**: 
  - USA total = sum of 10 US model unified scores ✓
  - China total = sum of 10 CN model unified scores ✓
  - avgIq = average of 10 respective model IQ indices ✓
  - avgValue = average of 10 respective model Value indices ✓
- [ ] **Date Consistency**: auditDate and subtitle formatted correctly from timestamp
- [ ] **Leader Accuracy**: "leader" field matches team with higher total score
