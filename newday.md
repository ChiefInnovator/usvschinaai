# Prompt: Generate & Add New Day's Data to models.json

Create a comprehensive JSON dataset for **TODAY'S DATE** (use the current date), to be **added to the existing models.json history array**. This will append a new day's competitive analysis of top AI models from the United States and China.

## Data Structure Requirements

### 1. Top 10 US Models and Top 10 China Models with:
- Model name and company
- Company website link
- Detailed model description (capabilities, parameters, architecture highlights)
- Release/creation date
- Base cost ($ per 1M input tokens)
- Cost per output ($ per 1M output tokens)

### 2. Benchmark Scores across these 11 benchmarks:
- AIME 2025 (Math reasoning, 0-100 scale)
- HMMT 2025 (High school math, 0-100 scale)
- GPQA Diamond (Graduate-level science, 0-100 scale)
- ARC-AGI (General reasoning, 0-100 scale)
- BrowseComp (Web browsing/search, 0-100 scale)
- ARC-AGI v2 (Advanced reasoning, 0-100 scale)
- HLE (Human-level evaluation, 0-100 scale)
- MMLU-Pro (Professional knowledge, 0-100 scale)
- LiveCodeBench (Real-time coding, 0-100 scale)
- SWE-Bench Verified (Software engineering verified, 0-100 scale)
- CodeForces (Competitive coding, 0-100 scale)

### 3. Calculated Scores:
- **IQ Index**: Average of all 11 benchmark scores (0-100)
- **Value Index**: Inverse relationship to cost - models with lower cost per capability rank higher (0-100, normalized)
- **Unified Power Score**: Weighted combination (60% IQ, 40% Value) to determine overall ranking

### 4. Aggregate Statistics:
- Total scores for each team (USA, China)
- Average IQ for each team
- Average Value for each team
- Overall winner (team with highest total Unified Power Score)
- Top model (rank #1 by Unified Power Score)

## Data Assumptions

- **Realistic Performance**: US models typically excel in reasoning (AIME, GPQA, ARC-AGI) but China excels in scale and coding tasks (CodeForces, SWE-Bench)
- **Cost Variance**: Premium reasoning models cost $0.50-$3.00 per 1M tokens; faster models cost $0.01-$0.10
- **Competitive Balance**: Vary which country leads - some benchmarks favor US, others favor China
- **Realistic Gaps**: Top models should score 85-95+ on their strongest benchmarks; lower-ranked models 60-80

## Integration Instructions

This new entry will be **prepended to the existing history array** in models.json. The structure should be:

```json
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
      "benchmarks": ["AIME 2025", "HMMT 2025", ..., "CodeForces"],
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
          "iq": [avg benchmark score],
          "value": [cost-adjusted score],
          "createdDate": "[TODAY'S DATE in YYYY-MM-DD format]",
          "costInputPer1M": 0.50,
          "costOutputPer1M": 1.50,
          "benchmarks": {
            "AIME 2025": 92.5,
            "HMMT 2025": 89.3,
            ... (all 11 benchmarks with scores)
          }
        }
        ... (20 models total: 10 US + 10 CN)
      ]
    },
    { ... existing previous day entry ... },
    { ... any older entries ... }
  ]
}
```

## Integration Process

1. **Generate only the new history entry object** (the single object with TODAY'S timestamp, auditDate, subtitle, benchmarks, and its 20 models)
2. **Do NOT modify** metadata, teams, or columns - keep them exactly as they are
3. **Insert at the beginning** of the history array (newest data first)
4. **Preserve all existing history entries** - this maintains the historical audit trail

## Quality Requirements

1. All benchmark scores must be realistic and internally consistent (higher-ranked models score higher overall)
2. Cost data must be current and realistic for TODAY'S DATE
3. Model descriptions should mention key differentiators (reasoning, speed, cost, parameter count, etc.)
4. Ensure ~50% US, ~50% China representation in top 20
5. Make the competition competitive - no team should dominate by >20% on Unified Power Score
6. Unified scores should range from ~120 (top) to ~80 (10th place)
7. **All 20 models must have ranks 1-20** (one for each position, no duplicates)
8. **Team USA and China team totals** should be roughly competitive (within 10-15% of each other)

## Verification Checklist

After generating the new day's data and before integration, verify:

- [ ] **JSON Syntax Valid**: The generated object parses as valid JSON
- [ ] **All Fields Present**: Each model has rank, name, company, companyLink, origin, description, unified, iq, value, createdDate, costInputPer1M, costOutputPer1M, and benchmarks object
- [ ] **Benchmark Coverage**: All 11 benchmark scores present for each of 20 models
- [ ] **Ranks Unique**: Models ranked 1-20 with no duplicates or gaps
- [ ] **Score Calculations**: 
  - IQ Index = average of 11 benchmarks ✓
  - Value Index = cost-adjusted (higher value for lower cost) ✓
  - Unified Score = (IQ × 0.6) + (Value × 0.4) ✓
- [ ] **Team Scores**: 
  - USA total = sum of 10 US model unified scores ✓
  - China total = sum of 10 CN model unified scores ✓
  - avgIq = average of 10 respective model IQ indices ✓
  - avgValue = average of 10 respective model Value indices ✓
- [ ] **Date Consistency**: auditDate and subtitle formatted correctly from timestamp
- [ ] **Leader Accuracy**: "leader" field matches team with higher total score
- [ ] **Data Competitiveness**: No team dominates by >20%, score ranges realistic (120-80)
