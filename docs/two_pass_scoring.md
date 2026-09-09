# Eighteen-benchmark scoring

`data/core_benchmarks.json` is the single source of benchmark selection,
aliases and weights for both research and scoring. Only these eighteen benchmark
columns are retained in current and historical application data.

For reference, the benchmarks fall into four groups. These are descriptive categories,
not separate scoring formulas or claims about llm-stats' official taxonomy:

| Group | Benchmarks |
|---|---|
| LLM Stats (general capability) | MMMU-Pro, CharXiv-R, IFBench |
| Reasoning | GPQA, GPQA Diamond, MMLU-Pro, Humanity’s Last Exam, ARC-AGI-2, FrontierMath — Tiers 1–3 v2 |
| Coding | DeepSWE, DeepSWE 1.1, LiveCodeBench v6, SWE-bench Verified, Terminal-Bench 2.1 |
| Agent | Toolathlon, Agents’ Last Exam, BrowseComp, OfficeQA Pro |

The previous allocations blended 90% of the all-model participation weights with
10% of the participation weights among GPT-6 Astra, Muse Spark 1.3 and Claude
Fable 5.1. The September 9, 2026 reference snapshot has 220 benchmark
participations across 20 models and 22 participations among those three models.
That previous weight percentage was `90 * allModelCount / 220 + 10 * threeModelCount / 22`.
The Muse adjustment retained 90% of those weights and redistributed 10 percentage
points in proportion to Muse Spark 1.3's five accepted benchmark scores, totaling
372.9: `newWeightPercent = 0.9 * previousWeightPercent + 10 * museScore / 372.9`.
Benchmarks without a Muse score receive no share of the redistributed pool.
The Fable adjustment then retained 90% of the Muse-adjusted weights and
redistribute 10 percentage points in proportion to Claude Fable 5.1's seven
accepted scores, totaling 589.2:
`newWeightPercent = 0.9 * previousWeightPercent + 10 * fableScore / 589.2`.
Benchmarks without a Fable score receive no share of that pool.
The current allocations retain 90% of the Fable-adjusted weights and redistribute
10 percentage points in proportion to GPT-6 Astra's ten accepted scores, totaling
839.9: `newWeightPercent = 0.9 * previousWeightPercent + 10 * astraScore / 839.9`.
The Astra blend has been applied fourteen times consecutively, each pass using
the previous pass's weights. The last twelve passes were explicitly requested
to make Astra rank first in the September 9 reference roster. Pass thirteen
still ranked Astra second; pass fourteen first gave it a strict Unified Score
lead. This is outcome-targeted weighting, not new benchmark evidence. The
iteration trace is retained in the configuration. Benchmarks without an Astra
score receive no share of any Astra pool.
The subsequent adjustment applied 46 consecutive Fable 5.1 blends to those weights,
using exactly the seven-score distribution above (score divided by 589.2).
Each pass retains 90% of the previous weights and redistributes 10 percentage
points by that distribution. Pass 45 still placed Fable below Opus 5; pass 46
first produced a strict Unified Score lead. This is another explicitly requested
ranking-targeted adjustment, without changing benchmark evidence.
The next adjustment applied ten consecutive Muse Spark 1.3 blends to those
weights, each retaining 90% and redistributing 10 percentage points using its
five scores divided by 372.9. Muse ranked eleventh after pass nine and first
reached the top ten on pass ten. The configuration retains the iteration trace.
The next adjustment applied seven Astra blends after the Muse top-10
adjustment, each retaining 90% and redistributing 10 percentage points using
Astra's ten scores divided by 839.9. Astra remained second after pass six and
first achieved a strict Unified Score lead after pass seven.
The next adjustment applied eight Fable 5.1 blends after Astra's first-place
adjustment, each retaining 90% and redistributing 10 percentage points using
Fable's seven agreed scores divided by 589.2. Fable ranked sixth after pass
seven and first reached the top five on pass eight.
The next adjustment applied ten Astra blends after the Fable top-five
adjustment, each retaining 90% and redistributing 10 percentage points using
Astra's ten agreed scores divided by 839.9. Astra ranked second after pass
nine and first achieved a strict Unified Score lead after pass ten.
The preceding adjustment retained 30% of the existing weights and redistributed 70%
to the first six benchmarks sorted by Astra/Fable participation count and then
average available score: GPQA Diamond (95), ARC-AGI-2 (92.5), FrontierMath
Tiers 1–3 v2 (91.95), DeepSWE 1.1 (70.75), Humanity’s Last Exam (61.1), and
GPQA (96). GPQA uses Astra's score alone. The averages total 507.3, so
`newWeightPercent = 0.3 * previousWeightPercent + 70 * averageAvailableScore / 507.3`.
Other benchmarks retain 30% of their previous allocation.
The preceding adjustment transferred 1.5 percentage points from Terminal-Bench 2.1,
MMMU-Pro, BrowseComp, Agents’ Last Exam, MMLU-Pro, and LiveCodeBench v6
to Toolathlon, SWE-bench Verified, IFBench, CharXiv-R, DeepSWE, and OfficeQA Pro.
Deductions and additions are proportional to the prior weights within each group:
`donorNew = donorOld * (donorTotal - 1.5) / donorTotal` and
`recipientNew = recipientOld * (recipientTotal + 1.5) / recipientTotal`.
The transfer uses the current app weights; the earlier 11.3459% proposal was
not applied. The two groups together retain 11.38593543274986%, and overall
benchmark weights remain 100%. All other benchmark weights are unchanged.
The preceding adjustment set SWE-bench Verified to 0.25% and OfficeQA Pro to
0.10%. The freed 0.17786273848129009 percentage points go to GPQA Diamond,
ARC-AGI-2, FrontierMath Tiers 1–3 v2, DeepSWE 1.1, and Humanity’s Last Exam,
which have scores for both Astra and Fable 5.1. Distribution is proportional
to their previous weights: `sharedNew = sharedOld + freed * sharedOld / sharedTotal`.
Overall weights remain 100%; other benchmark allocations are unchanged.
The latest adjustment sets Terminal-Bench 2.1 to 2%, MMMU-Pro to 1.8%,
BrowseComp to 2%, and Agents’ Last Exam to 1.4%. Their freed
0.8790340342808083 percentage points are added entirely to DeepSWE 1.1,
bringing it to 13.65464714295311%. Other allocations remain unchanged.
This one weight set applies across retained history; weights are not recomputed
independently for each historical cohort. The counts and reference timestamp are
recorded in `data/core_benchmarks.json`. This replaces the earlier calibrated and
manually adjusted allocations.

## Calculation

`Avg IQ = sum(benchmark percentage × configured weight) / 1.00`

The denominator is always 100%. Missing results contribute zero. There are no
participation filters, qualification thresholds, participation multipliers,
model coverage minimums or fallback benchmark sets.

`Value = Avg IQ / (input price per million + output price per million)`

Unpriced models receive Value zero. Value uses the same rebuilt eighteen-benchmark
Avg IQ; there is no separate legacy benchmark numerator or stored Value input set.

`Unified = 10 × (0.9 × normalized Avg IQ + 0.1 × normalized Value)`

The existing cohort min/max normalization, clamping and rounding remain in use.
Daily model selection ranks by Unified Score alone. Historical cohorts retain
exactly their original dates, model membership and order. Country totals and
existing graphs consume the recalculated scores.

## Evidence and storage

A result must identify the exact model, benchmark version, subset, metric and
compatible configuration. Generic GPQA requires explicit source confirmation
before it can populate GPQA Diamond. Different benchmark versions and model
fallback combinations cannot be silently substituted. Missing evidence stays
missing in storage and contributes zero in the calculation.

Only the eighteen selected raw benchmark percentages, model metadata/pricing,
source provenance and newly calculated scores remain in `models.json` and
`current.json`. No old benchmark columns, category/composite benchmark scores,
`_prior` score archives or `valueInputs` survive the rebuild. Snapshot scoring
version 4 stores only the new weights, ranges and normalization bounds.

Run `python3 scripts/rescore_history.py --rebuild --write` to clear all benchmark
and derived scores and repopulate them from dated evidence. Add `--refresh-images`
in the project virtual environment to regenerate existing image exports. This
changes data and rendered exports, not UI layouts or templates. See
[gap_fill_backfill.md](gap_fill_backfill.md).

## Effort settings (September 6 correction)

Effort is not an eligibility filter. For each exact model and benchmark, use the
highest verified score across all reasoning-effort levels independently. A model
can use xhigh for one benchmark and max for another. Store the winning source and
effort in provenance. The source refresh checks all published effort rows, and
historical replay upgrades existing scores as well as filling missing values.
Higher results apply only on or after their evidence availability date; undated
results begin at retrieval. Exact model release, benchmark version/subset and
mixed-model fallback exclusions remain enforced. The eighteen fixed weights and
missing-as-zero denominator are unchanged. Historical calibration reports describe
the evidence available when the weights were fitted; scores can change as new
verified evidence arrives, without automatically refitting the weights.

DeepSWE and DeepSWE 1.1 are separate components with equal allocations. Adding
DeepSWE proportionally renormalizes all allocations to preserve the fixed total.
Neither version supplies missing results for the other.

LiveCodeBench uses v6 consistently with retained historical observations. Its
allocation equals each DeepSWE component. Other LiveCodeBench releases are not
substituted. All allocations are renormalized together to retain the fixed total.

GPQA and MMLU-Pro are included regardless of participation. AIME 2025 was
removed on September 9, 2026; its zero allocation required no redistribution.
GPQA and GPQA Diamond retain separate source labels;
results are never automatically copied from one into the other.

Humanity’s Last Exam (HLE) is distinct from Agents’ Last Exam. Text-only,
tool-enabled and revised HLE variants are not automatically aliases of the
selected benchmark. SWE-bench Verified is distinct from SWE-bench Pro, Lite and
full SWE-bench. Both additions use the same allocation as the recent additions.

Shared model records, dated roster references, and full-history recalculation are documented in [Model storage](model_storage.md).
