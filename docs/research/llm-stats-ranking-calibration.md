# Approximate llm-stats rank calibration

Adopted September 6, 2026 after the user accepted an approximate match.

The fit minimizes `sum((1 + 5/targetRank) * abs(fittedRank - targetRank))`
over all 15 screenshot models. Weights total 100%, use 0.1 percentage-point
increments, and each benchmark receives at least 0.1%. Missing scores remain
zero. A 0.01-point pair margin prevents ties from masquerading as matched ranks.
SciPy HiGHS certified the optimum for these constraints (solver gap 0).

Total unweighted rank displacement improves from 78 to 38; 74 of 105 model pairs match the target order.

This is calibration to a requested external order, not independent validation
of model capability. FrontierMath receives 64.2% and GPQA Diamond 25.8%,
so together they determine 90% of Avg IQ. Missing evidence is still consequential.
The fit does not reproduce the full order, and Muse Spark remains far below its
target. Results apply to the frozen evidence matrix in the feasibility JSON.

| Benchmark | Weight |
|---|---:|
| Toolathlon | 0.1% |
| Agents’ Last Exam | 0.1% |
| DeepSWE 1.1 | 0.1% |
| Terminal-Bench 2.1 | 0.1% |
| BrowseComp | 0.1% |
| MMMU-Pro | 0.1% |
| CharXiv-R | 5.1% |
| ARC-AGI-2 | 3.9% |
| OfficeQA Pro | 0.3% |
| IFBench | 0.1% |
| GPQA Diamond | 25.8% |
| FrontierMath — Tiers 1–3 v2 | 64.2% |

| Target | Fitted | Model | Avg IQ |
|---:|---:|---|---:|
| 1 | 1 | GPT-6 Astra | 89.03 |
| 2 | 2 | Claude Fable 5.1 | 85.66 |
| 4 | 3 | GPT-5.6 Sol | 85.63 |
| 3 | 4 | Claude Opus 5 | 83.08 |
| 13 | 5 | Claude Opus 4.8 | 83.07 |
| 12 | 6 | GPT-5.6 Terra | 83.06 |
| 7 | 7 | Claude Fable 5 | 82.00 |
| 8 | 8 | Kimi K3 | 78.18 |
| 11 | 9 | Qwen3.8 Max | 72.31 |
| 9 | 10 | GLM-5.3 | 68.08 |
| 10 | 11 | DeepSeek-V4-Pro-0813 | 68.06 |
| 6 | 12 | Claude Mythos Preview | 29.28 |
| 15 | 13 | Gemini 3.8 Flash | 29.23 |
| 5 | 14 | Muse Spark 1.3 | 24.36 |
| 14 | 15 | Hy4 preview | 24.26 |

These positions compare the 15 screenshot models. The application retains its
existing model cohorts and default Unified sorting; the target is Avg IQ,
not the cost-sensitive Unified ranking. Unreleased or no-longer-retained models
are not inserted into snapshots. All 233 snapshots are rescored with the same
new weights, using each snapshot's retained benchmark evidence and prices.
Historical model membership, raw benchmarks and the UI are preserved.

Reproduce the fit with `uv run --no-project --python .venv/bin/python --with scipy python scripts/fit_benchmark_weights.py`.
The fitting utility is offline analysis only; daily scoring reads the fixed
weights from `data/core_benchmarks.json` and does not refit each day.
