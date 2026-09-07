# All-benchmark source audit — September 6, 2026

Scope: all 19 configured benchmarks, all 90 distinct retained historical models, and 233 snapshots. Current participation is measured against the latest 20 models. This is a bounded audit of the sources listed below, not proof that undiscovered results do not exist.

## Changes

- Added recurring Vals adapters for MMLU-Pro, AIME 2025, LiveCodeBench v6, SWE-bench Verified, GPQA Diamond, and Terminal-Bench 2.1.
- Added recurring official Agents’ Last Exam API ingestion using full-split pass rate.
- Audited all 19 llm-stats benchmark URLs alongside all historical model detail pages. Two guessed benchmark URLs returned 404; ARC-AGI-2 and FrontierMath Tiers 1–3 v2 were covered by the successful Epoch export refresh instead.
- Accepted seven dated OfficeQA Pro paper observations, using full-corpus configurations rather than oracle pages or OfficeQA-Full subsets.
- Filled 483 missing cells and improved 129 existing cells. Historical dates and model membership are unchanged. Benchmark selection and weights are unchanged.

## Participation and historical impact

| Benchmark | Current before | Current after | Historical cells filled | Existing cells improved |
|---|---:|---:|---:|---:|
| Toolathlon | 14 | 14 | 0 | 0 |
| Agents’ Last Exam | 15 | 15 | 0 | 0 |
| DeepSWE | 6 | 6 | 0 | 0 |
| DeepSWE 1.1 | 20 | 20 | 0 | 0 |
| LiveCodeBench v6 | 3 | 14 | 11 | 0 |
| Terminal-Bench 2.1 | 18 | 18 | 0 | 0 |
| BrowseComp | 8 | 8 | 0 | 0 |
| MMMU-Pro | 12 | 12 | 0 | 0 |
| CharXiv-R | 7 | 7 | 0 | 0 |
| ARC-AGI-2 | 8 | 8 | 0 | 0 |
| OfficeQA Pro | 6 | 6 | 460 | 126 |
| IFBench | 8 | 8 | 0 | 0 |
| GPQA Diamond | 18 | 19 | 1 | 3 |
| FrontierMath — Tiers 1–3 v2 | 12 | 12 | 0 | 0 |
| GPQA | 11 | 11 | 0 | 0 |
| MMLU-Pro | 14 | 14 | 0 | 0 |
| AIME 2025 | 0 | 0 | 0 | 0 |
| Humanity’s Last Exam | 11 | 11 | 0 | 0 |
| SWE-bench Verified | 2 | 13 | 11 | 0 |

## Sources and boundaries

The routine refresh checked 101 sources with no fetch/parser failures: 90 llm-stats model pages, Artificial Analysis, Epoch, original Toolathlon, CharXiv reasoning CSV, six Vals pages, and the ALE API. Additional benchmark-page audit results, pagination limits and URL failures are in `all-benchmark-leaderboard-audit.json`. The visible llm-stats tables are not exhaustive beyond their first page; model detail pages separately covered every retained model.

Vals task selection is explicit: AIME uses `aime_2025`, not the combined `overall` of 2024 and 2025. Other Vals sources use overall scores, not subjects, difficulty bins, or chart annotations. MMLU-Pro uses the 14-subject mean. Official ALE uses full-split `passRate`, never partial-credit `avgScore`. Effort suffixes are normalized without substituting a different release. Unknown date/preview IDs are listed as unmatched and require exact-release evidence before mapping.

DeepSWE operator page was checked for its separate v1/v1.1 series; existing Epoch v1.1 ingestion remains in use. AA full model records and Epoch CSVs cover the relevant selected components. Full HLE is kept separate from AA text-only HLE; original Toolathlon is kept separate from Toolathlon-Verified. BrowseComp remains separate from BrowseComp-Plus, -zh, and DeepSearchQA. No result was inferred from a predecessor or a benchmark of similar name.

## Remaining issues

- No exact, newly verified AIME 2025 result was found for the current 20-model roster. Vals labels AIME archived; its 2025 task adds dated-current evidence for older models, not a license to backdate scores or transfer them to successors.
- MMLU-Pro, LiveCodeBench and SWE-bench Verified are also marked archived by Vals. Many older models have scores even when current frontier models lack them.
- Most newly discovered leaderboard rows have no individual publication date, so they apply from retrieval. More historical filling requires dated publications or retained observations.
- Legacy ALE evidence includes launch-date assumptions for undated leaderboard rows (for example IDs `4a27054127bf465a` and `40288e1bc1615712`). The new adapter does not make that assumption. These older provenance claims need a separate date reconstruction before earlier history can be considered fully source-verified; this pass did not rewrite unsupported dates or erase retained observations.
- Source labels on older generic GPQA/HLE records do not always specify subsets/configurations. The new exact-source adapters do not resolve every legacy comparability ambiguity.

## Validation

211 tests passed, one skipped. Tests cover AIME subset selection, missing-subset failure, exact release matching across effort suffixes, and ALE metric/split separation. Historical timestamp/model membership comparison passed. Image exports and chart inputs were regenerated; no webpage layout changes. Changes remain local on `feature/capability-scoring`.

## Evidence files

- `data/benchmark_source_refresh.json`: recurring source status and Vals unmatched IDs.
- `data/benchmark_leaderboard_audit_findings.json`: benchmark-page observations.
- `data/ale_audit_findings.json`: full-split official ALE observations.
- `data/officeqa_paper_audit_findings.json`: dated OfficeQA paper observations.
- `data/historical_benchmark_evidence.json`: accepted evidence used for replay.
- `data/historical_benchmark_gaps.json`: remaining historical gaps.
