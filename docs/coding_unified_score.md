# Specification: Software Coding Unified Score

**Status:** Proposed — not yet implemented.
**Date:** 2026-04-12
**Owner:** aiolympics

## 1. Goal

Produce a **separate Unified score** that ranks AI models specifically on **software coding ability**, using the same two-pass scoring pipeline as the general Unified score but restricted to a curated set of coding-relevant benchmarks. Display it alongside the general score so visitors can compare overall capability vs. coding-specific capability.

Rationale: the general Unified score mixes math, reasoning, multimodal, and coding benchmarks. A model that's exceptional at coding but weak at vision (or vice-versa) is hard to surface from the blended number. A domain-specific score gives a cleaner answer to "which model should I use for code?".

## 2. Definition of "software coding"

A benchmark counts as a software coding benchmark if it primarily measures the model's ability to **write, modify, debug, or reason about source code** — including agentic workflows that act on code via a terminal, editor, or repository.

The initial curated set (see §3) captures every such benchmark currently present in `models.json`. The set is explicit rather than tag-derived because llm-stats' category labels overlap with other domains (e.g. "agents" covers coding and web-browsing agents alike).

### Included categories

- **Repository-level code tasks** (file modification, test-passing): SWE-bench and its variants.
- **Terminal / environment agents**: Terminal-Bench, OSWorld — any benchmark where the model executes commands and edits files.
- **Competitive / short-form coding**: LiveCodeBench, CodeForces, OJBench.
- **Scientific / domain coding**: SciCode.
- **Security-focused coding**: SecCodeBench.
- **Chatbot Arena coding subcategory**: CodeArena.

### Excluded

- **Pure math / reasoning benchmarks** even if sometimes solved via code (GPQA, AIME, FrontierMath, HMMT, IMO-AnswerBench, MathArenaApex).
- **Document understanding / OCR** (OmniDocBench, CharXiv-R).
- **General multimodal or vision** (MMMU, MMMU-Pro, VideoMMMU, etc.).
- **Web browsing / search agents** (BrowseComp, DeepSearchQA) — these overlap with "agents" but aren't coding.

## 3. Initial curated benchmark set

```python
CODING_BENCHMARKS = {
    # Chatbot Arena coding Elo (non-percentage; uses (1000, 2000) range)
    "CodeArena",

    # SWE-bench family (repository-level code editing)
    "SWE-benchVerified",
    "SWE-benchPro",
    "SWE-benchMultilingual",
    "Multi-SWE-Bench",
    "SWE-Lancer(IC-Diamondsubset)",

    # Terminal / environment agents
    "Terminal-Bench2.0",
    "TerminalBench",
    "OSWorld",
    "OSWorld-Verified",

    # Competitive / short-form coding
    "LiveCodeBenchv6",
    "LiveCodeBenchPro",
    "CodeForces",
    "OJBench",
    "OJBench(C++)",

    # Scientific / specialized
    "SciCode",
    "SecCodeBench",
}
```

The set lives in `scripts/scrape_models.py` alongside `BENCHMARK_KNOWN_RANGES`. To add a new coding benchmark later, update this set and the new score will pick it up on the next run.

**Future improvement:** switch from an explicit allowlist to category-derived filtering once `extract_detail_benchmarks()` captures the llm-stats `categories` field. A benchmark would then be considered coding iff its categories contain `"code"` (optionally combined with an additional keyword check). That makes the rule self-maintaining as llm-stats adds new benchmarks.

## 4. Scoring algorithm

The algorithm is identical to the general two-pass scoring defined in [two_pass_scoring.md](two_pass_scoring.md), with one substitution: everywhere `benchmark_headers` appears, use `benchmark_headers ∩ CODING_BENCHMARKS` instead.

Concretely:

### Pass 1 — coding cohort Top 10 selection

1. For each model, compute `codingAvgIq_1` as the participation-weighted average of normalized benchmark scores, restricted to `CODING_BENCHMARKS ∩ benchmark_headers`. Use `resolve_benchmark_range()` for each benchmark (known range → percentage auto-detect → cohort fallback). Benchmarks with participation ≤ 1 across the full cohort are still excluded.
2. Compute `codingValue_1 = codingAvgIq_1 / (Input $/M + Output $/M)`.
3. Min–max normalize `codingAvgIq_1` and `codingValue_1` across the full cohort.
4. `codingUnified_1 = 10 × (0.9 × norm(codingAvgIq_1) + 0.1 × norm(codingValue_1))`.
5. Sort the combined US+CN cohort by `codingUnified_1` descending. The top 10 become the **Coding Initial Top 10**.

Note: this is a **coding-specific** top 10 — it is not guaranteed to match the general-score Initial Top 10. A model strong at coding but weak overall can make the coding top 10 without making the general one.

### Qualified coding benchmark set

6. For each coding benchmark, count how many of the Coding Initial Top 10 reported a non-missing value. Keep benchmarks where that count is **≥ 8**. This is the **qualified coding set**.
7. If fewer than **2** coding benchmarks qualify, the coding score is undefined for this snapshot. Emit `codingAvgIq`, `codingValue`, and `codingUnified` as `null` and log a warning. (The threshold is 2 instead of the general-score floor of 3 because the coding benchmark universe is smaller — see §7.)

### Pass 2 — coding rescore

8. For every model in the cohort, compute `codingAvgIq_2` as a flat average of normalized scores over the qualified coding benchmarks only. Flat, not participation-weighted.
9. `codingValue_2 = codingAvgIq_2 / (Input $/M + Output $/M)`.
10. Rebuild `min/max_codingAvgIq` and `min/max_codingValue` across the full cohort from Pass 2 outputs.
11. `codingUnified_2 = 10 × (0.9 × norm(codingAvgIq_2) + 0.1 × norm(codingValue_2))`.

Pass 2 values are the ones persisted to `models.json` under the new keys.

## 5. Data model

Each per-model row in `models.json` gains three new fields:

```json
{
  "model": "Claude Opus 4.6",
  "avgIq": 79.10,
  "value": 2.64,
  "unified": 907.58,

  "codingAvgIq": 84.2,
  "codingValue": 2.81,
  "codingUnified": 918.4,

  "GPQA": "91.3%",
  "…": "…"
}
```

Missing / insufficient coverage: `null` (not `0`, not `"-"`). Callers must handle `null` explicitly.

## 6. Display

Two surface changes:

1. **Leaderboard columns.** Add an optional "Coding" column group next to the main Unified column showing `codingUnified` (and optionally `codingAvgIq`). Models with `null` coding scores render as `—`.
2. **About page.** Add a dedicated "Software Coding Score" section explaining the curated benchmark set and the two-pass flow. Link to this spec.

The main site title and the primary sort order remain driven by the general Unified score. The coding score is an additional signal, not a replacement.

## 7. Open questions and known limitations

1. **Small qualified set.** In the 2026-04-12 snapshot only **CodeArena (20/20)** and **SWE-bench Verified (15/20)** are reported by enough of the general Top 10 to qualify at threshold 8. A coding-specific Top 10 may shift the count slightly, but coding benchmarks are genuinely fragmented across SWE-bench variants, LiveCodeBench versions, and Terminal-Bench versions — so 2–4 qualified benchmarks is likely the ceiling for now. The 2-benchmark floor (§4 step 7) is a concession to that.
2. **SWE-bench variant fragmentation.** Different providers publish different SWE-bench flavors (Verified vs Pro vs Multilingual vs Lancer vs Multi-SWE-Bench). Treating them as separate benchmarks is correct — they measure different things — but it means no single SWE-bench variant dominates the qualified set. An alternative is to define a **virtual "SWE-bench" rollup** that picks the model's best reported variant and uses that as a single column. Flagged as a future iteration.
3. **Terminal-Bench versioning.** `Terminal-Bench 2.0` (14/20) and the older `TerminalBench` (3/20) are separate columns. The 2.0 score is usually higher. We're treating them independently; if the rollup approach in (2) is adopted, Terminal-Bench should get the same treatment.
4. **Coding-Top-10 vs general-Top-10 divergence.** The spec explicitly uses a coding-specific Initial Top 10. This is cleaner semantically but means the two scores' qualified sets are derived from different cohorts. If display simplicity matters more than semantic purity, we could instead use the **general** Initial Top 10 to pick coding qualified benchmarks. Open decision.
5. **Category-derived filtering.** §3 flags the eventual move to llm-stats categories. Doing this requires extending `extract_detail_benchmarks()` to capture `categories`, which is a small parser change but not in scope for this spec.
6. **Historical data.** Old entries in `models.json` don't have `codingAvgIq` / `codingValue` / `codingUnified`. Front-end should handle `null` for historical rows gracefully without reformatting old data.

## 8. Files that would change

- **[scripts/scrape_models.py](../scripts/scrape_models.py)**
  - Add `CODING_BENCHMARKS` constant near `BENCHMARK_KNOWN_RANGES`.
  - Add a `run_coding_pass(...)` helper that mirrors the existing Pass 1 / Pass 2 block but restricted to `CODING_BENCHMARKS ∩ benchmark_headers`.
  - In `build_history_entry`, write the three new per-model fields.
- **[models.json](../models.json)**
  - New top-level columns in `columns` metadata if we want the coding score visible in the table config.
  - New per-row fields on each model object (new rows only; historical rows left alone).
- **[index.html](../index.html)**
  - Add a coding column group (hideable) and a filter toggle between "General" and "Coding" sort.
  - Add scoring-methodology copy explaining the coding score.
- **[docs/scraper_specification.md](scraper_specification.md)**
  - New section describing `run_coding_pass` output alongside the existing derived-score section.

## 9. Non-goals

- This spec does **not** replace the general Unified score.
- It does **not** adjust the 0.9 / 0.1 capability-vs-cost weighting.
- It does **not** introduce additional domain scores (math, reasoning, multimodal) even though the same pattern would generalize. If this works well we can revisit adding more domain scores, but one at a time.

## 10. Success criteria

- `codingUnified` is computed and written to `models.json` on every scraper run.
- The value is `null` if and only if fewer than 2 coding benchmarks qualified, and this case is logged.
- The front-end correctly displays `—` for null cases without breaking the layout.
- Manual spot-check: a recognised coding-strong model (e.g. Claude Opus 4.6 on SWE-bench Verified) lands in the top 3 of the coding ranking on a snapshot where it leads the shared benchmarks.
