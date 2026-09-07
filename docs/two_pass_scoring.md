# Nineteen-benchmark scoring

`data/core_benchmarks.json` is the single source of benchmark selection,
aliases and weights for both research and scoring. Only these nineteen benchmark
columns are retained in current and historical application data.

For reference, the benchmarks fall into four groups. These are descriptive categories,
not separate scoring formulas or claims about llm-stats' official taxonomy:

| Group | Benchmarks |
|---|---|
| LLM Stats (general capability) | MMMU-Pro, CharXiv-R, IFBench |
| Reasoning | GPQA, GPQA Diamond, MMLU-Pro, AIME 2025, Humanity’s Last Exam, ARC-AGI-2, FrontierMath — Tiers 1–3 v2 |
| Coding | DeepSWE, DeepSWE 1.1, LiveCodeBench v6, SWE-bench Verified, Terminal-Bench 2.1 |
| Agent | Toolathlon, Agents’ Last Exam, BrowseComp, OfficeQA Pro |

The fixed allocations are calibrated to approximate the supplied llm-stats
ranking. This is a calibrated ranking, not an independently selected balance of
capabilities. All nineteen remain active.

## Calculation

`Avg IQ = sum(benchmark percentage × configured weight) / 1.00`

The denominator is always 100%. Missing results contribute zero. There are no
participation filters, qualification thresholds, participation multipliers,
model coverage minimums or fallback benchmark sets.

`Value = Avg IQ / (input price per million + output price per million)`

Unpriced models receive Value zero. Value uses the same rebuilt nineteen-benchmark
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

Only the nineteen selected raw benchmark percentages, model metadata/pricing,
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
mixed-model fallback exclusions remain enforced. The nineteen fixed weights and
missing-as-zero denominator are unchanged. Historical calibration reports describe
the evidence available when the weights were fitted; scores can change as new
verified evidence arrives, without automatically refitting the weights.

DeepSWE and DeepSWE 1.1 are separate components with equal allocations. Adding
DeepSWE proportionally renormalizes all allocations to preserve the fixed total.
Neither version supplies missing results for the other.

LiveCodeBench uses v6 consistently with retained historical observations. Its
allocation equals each DeepSWE component. Other LiveCodeBench releases are not
substituted. All allocations are renormalized together to retain the fixed total.

GPQA, MMLU-Pro and AIME 2025 are included regardless of participation. In the
absence of new allocation instructions, each uses the same allocation as the
previous coding additions. GPQA and GPQA Diamond retain separate source labels;
results are never automatically copied from one into the other.

Humanity’s Last Exam (HLE) is distinct from Agents’ Last Exam. Text-only,
tool-enabled and revised HLE variants are not automatically aliases of the
selected benchmark. SWE-bench Verified is distinct from SWE-bench Pro, Lite and
full SWE-bench. Both additions use the same allocation as the recent additions.
