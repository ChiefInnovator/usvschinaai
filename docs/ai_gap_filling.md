# Specification: AI-Assisted Benchmark Gap Filling

**Status:** Proposed — not yet implemented.
**Date:** 2026-04-12
**Owner:** aiolympics

## 1. Goal

After the existing **Pass 1** ranks the top 20 models by participation-weighted benchmark scores, but **before Pass 2** rescores them on the qualified set, insert a new **Gap-Filling Pass** that uses an LLM to research and fill in missing benchmark scores for the top-20 cohort. The objective is to enlarge the qualified benchmark set so Pass 2 has more shared signal to work with.

Today, the qualified set is small (6 benchmarks at threshold ≥ 8/10) because providers selectively publish benchmarks. The vast majority of dropped cells are not "the model failed this benchmark" — they're "this model never published a result here." If a published score exists in a vendor blog, paper, or third-party leaderboard but isn't on llm-stats, an LLM with web access can typically find it. Filling those gaps makes the qualified set richer, the Pass 2 ranking more stable, and the inversion class of bugs we just fixed less likely to recur.

## 2. Position in the pipeline

```text
[Scrape leaderboard]            ← scripts/scrape_models.py (existing)
        │
        ▼
[Detail-page enrichment]        ← extract_detail_benchmarks (existing)
        │
        ▼
[Sparse benchmark drop]         ← MIN_COHORT_PARTICIPATION = 4 (existing)
        │
        ▼
[Gap-Filling Pass]              ← NEW — this spec
        │
        ▼
[Pass 1 — Initial Top 10]       ← participation-weighted (now sees filled data)
        │
        ▼
[Pass 2 — Qualified rescoring]  ← iterates if needed (rarely now)
        │
        ▼
[Write models.json]
```

The Gap-Filling Pass runs **before Pass 1**, not after it. This is a deliberate choice: putting it after Pass 1 would mean Pass 1's Initial Top 10 — and therefore the qualified-set seed — gets computed against missing cells that gap-filling could have filled. By gap-filling first, Pass 1 sees the enriched data from the start, the iteration loop in Pass 2 has less reconciliation work to do, and the whole pipeline converges faster.

The trade-off: gap-filling needs a "top tier" reference to prioritize candidates (the §6 tiering rule asks "how close is this benchmark to the 8/10 top-10 threshold?") — but Pass 1 hasn't run yet, so we don't have *our* top 10. We use **llm-stats' raw leaderboard rank** as the top-10 proxy instead. That ranking is available immediately after the scrape, doesn't depend on any of our scoring, and is a reasonable approximation of "the top tier" — which is what the qualified-set rule is trying to capture anyway. Pass 1 will compute its own top 10 a moment later, and Pass 2 will reconcile any difference via iteration.

## 3. The current gap landscape (snapshot)

To make the spec concrete, here is the actual gap shape from the 2026-04-12 cohort (29 tracked benchmarks after the cohort sparse filter, 7 currently qualified for Pass 2). The "Top 10" column below is computed against the post-Pass-2 top 10 because that's what was in `models.json` when this snapshot was taken — but in production the gap-filler will use **llm-stats raw leaderboard rank** as the top-10 reference (see §6) since gap-filling runs before Pass 1. The two are usually very similar in practice; the snapshot here is illustrative:

### 3.1 Already qualified — no gap-filling needed

| Benchmark | Cohort | Top 10 |
| --- | ---: | ---: |
| CodeArena | 20/20 | 10/10 |
| GPQA | 17/20 | 9/10 |
| Terminal-Bench 2.0 | 14/20 | 9/10 |
| BrowseComp | 14/20 | 8/10 |
| HLE | 14/20 | 8/10 |
| MCP Atlas | 9/20 | 8/10 |
| SWE-bench Verified | 15/20 | 8/10 |

Skip these entirely. Filling them buys nothing.

### 3.2 Tier 1 — within 1 fill of qualifying (highest ROI)

These are at **7/10** in the top 10. A single accepted fill flips them into the qualified set, growing IQ from 7 → 8 benchmarks per model.

| Benchmark | Top 10 | Missing top-10 models |
| --- | ---: | --- |
| ARC-AGI v2 | 7/10 | GLM-5, GLM-5.1, Kimi K2.5 |
| MMMU-Pro | 7/10 | Claude Opus 4.5, GLM-5, GLM-5.1 |

**Tier 1 fill budget** = 6 calls (3 missing models × 2 benchmarks). Even at $0.05/call this is well under $1 per scrape run.

### 3.3 Tier 2 — within 2–3 fills of qualifying

| Benchmark | Top 10 | Missing top-10 models |
| --- | ---: | --- |
| MMMLU | 6/10 | GPT-5.4, GLM-5, GLM-5.1, Kimi K2.5 |
| Tau2 Telecom | 5/10 | Gemini 3.1 Pro, GLM-5, GLM-5.1, Kimi K2.5, Gemini 3 Pro |
| AIME 2025 | 4/10 | Gemini 3.1 Pro, GPT-5.4, Claude Opus 4.5, GLM-5, GLM-5.1, Claude Sonnet 4.6 |
| CharXiv-R | 4/10 | Gemini 3.1 Pro, GPT-5.4, Claude Opus 4.5, GLM-5, GLM-5.1, Claude Sonnet 4.6 |
| TAU2 Retail | 4/10 | Gemini 3.1 Pro, GPT-5.4, GLM-5, GLM-5.1, Kimi K2.5, Gemini 3 Pro |
| SWE-bench Pro | 4/10 | Claude Opus 4.6, Claude Opus 4.5, GLM-5, Gemini 3 Pro, Claude Sonnet 4.6, GPT-5.2 |

### 3.4 Tier 3 — too far from qualifying for the gap-fill pass to rescue

Benchmarks at ≤ 3/10 in the top 10. Even a perfect fill rate would only get them to 7/10 if every missing model has a published score (almost never the case). Skip in v1; include only when budget is loose. Examples:

HMMT 2025, MRCR v2, MRCR v2 (8-needle), Toolathlon, VideoMMMU, t2-bench, IMO-AnswerBench, SWE-bench Multilingual, ScreenSpot Pro, GlobalPIQA, LiveCodeBench v6, MMLU-Pro, Seal-0, BrowseComp-zh.

### 3.5 The fill ceiling

Tier 1 alone can grow the qualified set from **7 → 9 benchmarks** with ≤ 6 calls per run. Tier 2 can push that to **13 benchmarks** with another ~30 calls. Beyond that, ROI per call drops sharply.

## 4. What "gap" means

A **gap candidate** is the cross-product of cohort models × tracked benchmarks where the cell is missing — minus everything filtered out by §5 (useless-work filters) and §6 (tiering).

For each (model, benchmark) pair where ALL of the following hold:

1. The **model** is in the cohort (top 20 = 10 US + 10 CN — the entire scrape).
2. The **benchmark** is one of the post-sparse-drop `benchmark_headers` (≥ 4 of 20 cohort models report it).
3. The cell is missing (`""`, `"-"`, `"—"`, `"–"`, `"n/a"`, `"N/A"`, `"null"`, `"None"`).
4. The benchmark is **not** filtered by §5.
5. The benchmark is in the active tier set per §6.

…we mark it as a gap candidate. Gap candidates are the input to the LLM batch.

## 5. Useless-work filters

Before generating a single LLM prompt, the orchestrator drops gap candidates that are conceptually unfillable. Each filter has a one-line rationale and is implemented as a small pure function so it's testable in isolation.

### 5.1 Origin-specific benchmarks (the `BrowseComp-zh` case)

> **Rule:** If every model that currently reports a benchmark belongs to a single country (US or CN), the benchmark is considered origin-specific and gap-filling is skipped for models from the *other* country.

**Why:** `BrowseComp-zh` (Chinese-text browsing) is reported by 4 of 20 cohort models — all of them Chinese. Asking the LLM "Has Anthropic published a BrowseComp-zh score for Claude Opus 4.6?" wastes a call: Anthropic doesn't run Chinese-locale browsing evals, and the answer is structurally `null`. Same logic applies in reverse for any US-only benchmark we might add later.

**Implementation:**

```python
def origin_lock(benchmark: str, entries) -> Optional[str]:
    """Return the locked origin ('US' or 'CN') if every reporter shares it, else None."""
    reporters = [e for e in entries if e.columns.get(benchmark, '') not in MISSING_VALUE_MARKERS]
    if not reporters:
        return None
    origins = {e.country for e in reporters}
    return next(iter(origins)) if len(origins) == 1 else None

def is_origin_blocked(model_origin: str, benchmark: str, entries) -> bool:
    """A gap is blocked if the benchmark is origin-locked to the *other* country."""
    locked_to = origin_lock(benchmark, entries)
    return locked_to is not None and locked_to != model_origin
```

Applied to the current snapshot, this drops `BrowseComp-zh` for all 10 US models in one shot — 10 prompts saved per run.

### 5.2 Locale-suffix heuristic

> **Rule:** Benchmark names with locale suffixes (`-zh`, `-ja`, `-ko`, `-de`, `-fr`, `-es`, plus `-en` when paired with origin asymmetry) get the same origin-lock treatment as §5.1, even if the cohort happens to have one cross-locale reporter that would defeat the strict rule.

**Why:** A safety net for cases where one Chinese model self-reports a `-en` variant for marketing reasons but the benchmark is still effectively English-locale.

### 5.3 Hopeless-tier filter

> **Rule:** Skip benchmarks at top-10 participation ≤ 3 unless the per-run budget cap explicitly includes Tier 3 (default: off).

**Why:** Tier 3 benchmarks need 5+ accepted fills to reach 8/10. The historic accept rate for tier-1/tier-2 fills (where vendors actually published numbers) is generously ~70%; for tier 3 most missing cells are missing because the vendor never published, so the accept rate drops below 20%. The expected qualified-set lift per dollar is < 0.05 benchmarks. Not worth it.

### 5.4 Vendor-internal benchmark filter

> **Rule:** If every model reporting a benchmark belongs to a single `Organization` (e.g. all reporters are OpenAI models), mark the benchmark as vendor-internal and skip gap-filling for models from other organizations.

**Why:** Some benchmarks (e.g. early `MRCR v2` reports were OpenAI-only) are run only by one vendor's evals team. Other vendors won't have a score, and the LLM would just return `null`.

### 5.5 Already-qualified filter

> **Rule:** If a benchmark is already in the qualified set computed from the *current* top 10, it doesn't need any more fills. Skip every gap for it.

**Why:** Filling already-qualified benchmarks consumes budget without changing the IQ. Save the calls for benchmarks that can actually flip into the qualified set.

### 5.6 Negative-cache cooldown

> **Rule:** If a (model, benchmark) pair returned `null` from the LLM in the last 14 days (the negative-cache TTL from §10), skip it without making a new call. The cache is the source of truth for "we already asked, the answer was no."

**Why:** Already covered by the cache mechanism in §10, but called out here so the useless-work pipeline is documented in one place.

## 6. Tiered priority and per-run budget

The orchestrator processes gap candidates in tier order, stopping when the per-run cap (`AI_GAP_FILL_MAX_CALLS`, default **40**) is reached. This guarantees the highest-ROI fills happen first.

The benchmark scope is **Tier 1 and Tier 2 only** — close-to-qualifying benchmarks. Tier 3 is permanently off (its expected fill rate is too low to justify the call) and there is no separate "cohort fill" pass for already-qualified benchmarks (filling them changes nothing because they already feed the IQ).

### Top-10 reference (llm-stats raw rank)

The tier definitions below ask "how many of the top 10 reported this benchmark?" Since gap-filling runs **before Pass 1** (see §2), we don't have our own top 10 yet. Instead we use the **llm-stats raw leaderboard rank** — the ordering llm-stats publishes on its leaderboard page, which is what the scraper sees first. That's a reasonable proxy for the top tier:

- It's available immediately after scraping, with no scoring required.
- It's independent of our two-pass scoring, so we don't bake our methodology into the gap-fill prioritization.
- It approximates "the models the world considers top tier," which is exactly what the qualified-set rule (§4 in [two_pass_scoring.md](two_pass_scoring.md)) is trying to capture.

The orchestrator passes the top 10 (by llm-stats rank) of each country into the gap-filling pass. Combined that's a 20-model "top tier" reference; the per-benchmark count below is computed against the 10 highest-ranked models per country, then reported as a single "X / 10" for clarity (it's actually "X / 20" but displayed as a top-10 average for parity with the existing two-pass spec).

### Tier definitions

| Tier | Definition | Default action |
| --- | --- | --- |
| **Tier 1** | Benchmark at **7/10** llm-stats top-10 participation | Always run. ≤ 6 calls per run typical. |
| **Tier 2** | Benchmark at **4–6/10** llm-stats top-10 participation | Run after Tier 1 if budget remains. |
| **Tier 3** | Benchmark at **≤ 3/10** llm-stats top-10 participation | **Permanently off in v1.** Even a perfect fill rate cannot push the benchmark over the 8/10 threshold. Re-evaluate in v2 if the cohort grows or new benchmarks emerge. |

**Cohort scope** is the full **scraped cohort (top 20 = 10 US + 10 CN)**, not just the top 10. Filling laggard models helps the next run's Pass 1 → Pass 2 iteration converge faster because today's #11 is occasionally tomorrow's #9. The *target* of each individual fill is a (cohort model, tracked benchmark) pair; the *priority signal* is the llm-stats top-10 participation count for the benchmark.

Within a tier, candidates are sorted by:

1. **Distance to qualifying** (ascending — closer first).
2. **Number of missing top-10 models** (ascending — fewer is faster to flip).
3. **Cache age** (descending — staler entries refreshed first).

## 7. Gap-candidate volume estimate (current snapshot)

Applying the §5 filters and §6 tiering to the 2026-04-12 cohort:

| Source | Raw candidates | After §5 filters | In Tier 1+2 |
| --- | ---: | ---: | ---: |
| Tier 1 (7/10 benchmarks) | 6 | 6 | 6 |
| Tier 2 (4–6/10 benchmarks) | ~25 | ~22 | 22 |
| Tier 3 (≤ 3/10 benchmarks) | ~120 | ~95 | 0 (permanently off) |
| **Total fillable per run** | ~151 | ~123 | **~28 active** |

So a typical run touches ~28 LLM calls, well under the 40-call cap. With ~80% cache hit rate after a few runs, real-world calls per scrape settle around **5–10**.

## 8. The LLM prompt (Role → Context → Task → Constraints → Output Format)

A single prompt is constructed per gap candidate. The five-section structure is enforced by template, not free-form, so the model has zero ambiguity about what it's allowed to return.

### Role

> You are a benchmark-data researcher for a public AI leaderboard. Your job is to find verifiable, published benchmark scores for AI models. You do not estimate, guess, or interpolate. If a score is not publicly documented, you say so.

### Context

> The benchmark `{benchmark_name}` is `{benchmark_description}`. It is reported on a `{scale_description}` scale (e.g. percentage 0–100, Elo rating, or absolute count). The model `{model_name}` was released by `{organization}` on `{release_date}`. Its model detail page on llm-stats.com is `{model_url}`. The current leaderboard does not show a `{benchmark_name}` score for this model.

### Task

> Research whether `{organization}` (or any independent third party) has published a `{benchmark_name}` score for `{model_name}`. If a published score exists, return it. If no published score exists, return `null` and explain in one sentence why (no result, paper not yet released, etc.).

### Constraints

> 1. Use only verifiable, public sources: vendor blog posts, model cards, papers (arXiv preprint or peer-reviewed), the model's own tech report, or established third-party leaderboards (Papers With Code, OpenLLM Leaderboard, HELM, LMArena).
> 2. **Do not** invent scores. **Do not** average or estimate from neighbouring benchmarks. **Do not** quote unverified social-media claims.
> 3. **Do not** use scores attributed to a different model variant. If only `{model_name}-Pro` has a score and we asked about `{model_name}`, return `null`.
> 4. The score must be the same metric and same evaluation protocol that `{benchmark_name}` defines. If the source uses a non-standard variant, return `null`.
> 5. Format the score in the same units the benchmark uses on llm-stats: percentages as `xx.x%`, Elo as integer, etc.

### Output Format

A strict JSON object with no surrounding prose:

```json
{
  "model": "{model_name}",
  "benchmark": "{benchmark_name}",
  "score": "92.4%" | 1623 | null,
  "source_url": "https://...",
  "source_type": "vendor_blog" | "paper" | "model_card" | "third_party_leaderboard" | "none",
  "confidence": "high" | "medium" | "low",
  "notes": "one short sentence — required only if score is null or confidence is not high"
}
```

The orchestrator parses this JSON and rejects any response that doesn't validate against the schema.

## 9. Choice of LLM

**Provider:** OpenAI (direct, via the Responses API).
**Default model:** `gpt-5.4-pro`.
**Required tool:** `web_search` (the model must have live web access during inference).

### Why OpenAI direct, not GitHub Models

We originally targeted GitHub Models for the unified auth story, but **GitHub Models does not expose a built-in web search tool today**. Gap-filling fundamentally needs the model to *find* a published score, not invent one from training-data memory — see [the fallback playbook in §19](#19-fallback-playbook-if-web_search-becomes-unavailable) for what's required when web search isn't available, and why the workaround is materially worse than native browsing.

OpenAI's Responses API supports a first-class `web_search` tool that the model can call mid-generation: it issues a search, fetches matching pages, summarizes them, and emits citations. For a research task like "find the published GPQA score for this model" that's exactly the right primitive.

### Authentication

- The scraper reads `OPENAI_API_KEY` from the environment at startup. **No vendor SDK fallback** — if the env var is missing, the gap-filling pass is skipped entirely (with a single-line log) and the scraper proceeds to Pass 2 unchanged.
- In CI: `OPENAI_API_KEY` is set via GitHub Actions secrets. The scraper workflow exposes `${{ secrets.OPENAI_API_KEY }}` to the scraper step as an env var. No code changes need to know whether the run is local or in CI.
- For local development: the user puts `OPENAI_API_KEY` in `.env` (gitignored) or exports it in their shell.
- The key is **never logged**. The orchestrator only logs the model name being used.

### Choosing the model

A single config knob, `AI_GAP_FILL_MODEL`, defaults to `gpt-5.4-pro`. A small fallback chain handles the (rare) case where OpenAI deprecates the primary model between scrapes:

```python
# scripts/gap_fill_benchmarks.py
DEFAULT_MODEL_CHAIN = [
    "gpt-5.4-pro",   # primary — strongest reasoning, native web_search support
    "gpt-5.4",       # same family, smaller; web_search still supported
    "gpt-5.2",       # last-resort fallback
]
```

The orchestrator queries `GET https://api.openai.com/v1/models` once at startup, walks `DEFAULT_MODEL_CHAIN`, and picks the first model that the API confirms is available **and** supports the `web_search` tool. If none of the fallbacks support web search, the gap-filling pass is skipped (we don't run blind).

### Calling shape (OpenAI Responses API)

Single-shot per gap candidate. The Responses API uses a different request shape from chat completions — input is a list of message objects but the top-level keys differ, and `tools` is where `web_search` is enabled.

```http
POST https://api.openai.com/v1/responses
Authorization: Bearer ${OPENAI_API_KEY}
Content-Type: application/json
```

```json
{
  "model": "gpt-5.4-pro",
  "input": [
    {"role": "system", "content": "<Role + Context + Constraints from §8>"},
    {"role": "user",   "content": "<Task + Output Format from §8>"}
  ],
  "tools": [
    {"type": "web_search"}
  ],
  "tool_choice": "auto",
  "temperature": 0.0,
  "max_output_tokens": 800,
  "text": {
    "format": {"type": "json_object"}
  },
  "store": false
}
```

Notes:

- `tools: [{"type": "web_search"}]` is the whole point of using OpenAI direct. The model decides when to call it; for gap-fill prompts it almost always will because the prompt explicitly tells it to use only verifiable sources (§8 Constraints).
- `tool_choice: "auto"` lets the model decide whether to search at all. For prompts where the answer is in training data and the model can confidently cite an existing public source, it may answer without a search call — which is fine and cheaper.
- `text.format: {"type": "json_object"}` is the Responses-API equivalent of `response_format: json_object` from chat completions — strict JSON output so the parser doesn't scrape Markdown.
- `temperature: 0.0` because gap-filling is a research task, not a creative one — we want deterministic answers we can audit.
- `max_output_tokens: 800` is slightly higher than the chat-completions estimate to leave headroom for the search-tool's intermediate reasoning trace before the final JSON block.
- `store: false` prevents OpenAI from retaining the request/response in their conversation store. We don't need server-side conversation history; the cache file in §10 handles persistence on our side.

### Why not call Anthropic / Google directly?

Still rejected for v1:

| Provider | Why not (today) |
| --- | --- |
| Anthropic Claude (with `web_search`) | Strong model and supports web search via its tools API. Plausible v2 fallback if OpenAI capacity dries up. Skipped in v1 because the user explicitly chose GPT-5.4 Pro. |
| Google Vertex / Gemini (with grounding) | Requires GCP credentials, IAM, project setup. Overkill for a small gap-fill pass. |
| GitHub Models | No native web search tool. See workarounds in §19 — they exist but are materially worse than browsing. |

These remain easy to add later by introducing a `provider` field in `AI_GAP_FILL_MODEL` config (e.g. `"openai:gpt-5.4-pro"` vs `"anthropic:claude-opus-4-6"`) and a thin per-provider adapter. Out of scope for v1.

## 10. Caching and idempotency

LLM calls are expensive and slow. The gap-filling pass must not re-query the same `(model, benchmark)` pair on every scrape run. Strategy:

1. **Cache file**: `data/ai_gap_cache.json`, structured as `{model_name: {benchmark_name: gap_response_object}}`.
2. **Cache key**: `(model_name, benchmark_name, model_version_hint)`. The `model_version_hint` is the model's `Released` date or `KnowledgeCutoff` from llm-stats — when that changes, the cache entry is invalidated for that model so we re-query.
3. **TTL**: Cache entries are valid for **30 days** by default. After 30 days, re-query (a vendor may have published a score in the meantime).
4. **Negative caching**: A `score: null` response is also cached, so we don't waste calls on benchmarks we already know aren't published. Negative entries get a shorter TTL (**14 days**) so we re-check sooner.
5. **Cache hits short-circuit** the prompt entirely. Only true gap candidates with stale-or-missing cache entries hit the LLM.

The cache file is committed alongside `models.json` so the pipeline is deterministic across runs and CI doesn't burn API budget on every push.

## 11. Score provenance

Filled scores **must not** be indistinguishable from scraped scores in `models.json`. Otherwise we lose the audit trail and a future bug could silently flow synthetic data into rankings.

Add a parallel `provenance` block per row:

```json
{
  "model": "Claude Opus 4.6",
  "GPQA": "91.3%",
  "SWE-benchVerified": "80.8%",
  "_provenance": {
    "GPQA": {"source": "scraped", "from": "llm-stats-leaderboard"},
    "SWE-benchVerified": {"source": "scraped", "from": "llm-stats-detail-page"},
    "MMMLU": {"source": "ai_filled", "model": "claude-opus-4-6", "url": "https://...", "confidence": "high", "filled_at": "2026-04-12T11:30:00Z"}
  }
}
```

UI implications:

- The leaderboard table renders ai-filled scores with a small icon (sparkles or similar) and a tooltip: "Filled by AI from {source_url}, confidence: {high/medium/low}".
- The "Benchmarks Included" pills can optionally toggle to show only scraped benchmarks (purist view) vs scraped + filled (enriched view).

### Audit log

In addition to the per-row `_provenance` block, every accepted fill is appended as a single JSON line to `data/ai_fill_history.jsonl`. This file is **committed to the repo** so the audit history lives in `git log` and is visible at any historical commit.

```jsonl
{"ts":"2026-04-12T11:30:00Z","model":"Claude Opus 4.6","benchmark":"MMMLU","score":"89.6%","source_url":"https://www.anthropic.com/news/claude-opus-4-6","confidence":"high","llm_model":"gpt-5.4-pro","scraper_run":"2026-04-12T11:30:00-04:00"}
{"ts":"2026-04-12T11:30:01Z","model":"GLM-5","benchmark":"ARC-AGI v2","score":"55.4%","source_url":"https://z.ai/research/glm-5","confidence":"high","llm_model":"gpt-5.4-pro","scraper_run":"2026-04-12T11:30:00-04:00"}
```

Why a separate file rather than just `_provenance`:

- `_provenance` only carries the **current** snapshot of who filled what. The audit log preserves every fill across time, including overwrites and corrections.
- Append-only JSONL means a single accepted fill is one line — no merge conflicts even if multiple parallel scraper runs append at once. (In practice the scraper is single-process per run, but the format is forward-compatible.)
- `git log -p data/ai_fill_history.jsonl` reads as a chronological list of every AI-sourced score, which is exactly what we'd want for "show me all the fills the LLM made in the last quarter."
- A future analysis script can compute fill drift (e.g. "did GPT-5.4-pro start citing different sources for GPQA after the model was updated?") just by parsing the file.

The orchestrator MUST append before writing the per-row `_provenance` block. If the audit append fails, the fill is rejected to keep the two stores in sync.

## 12. Validation and safety guardrails

Filled scores feed scoring math and bad data corrupts rankings. Guardrails:

1. **Schema validation**: every LLM response must validate against the JSON schema in §8. Invalid responses are dropped and the gap remains a gap.
2. **Sanity bounds**: percentage scores must be in `[0, 100]`. Elo scores must be in a reasonable Elo range (e.g. 500–3000). Out-of-range values are dropped.
3. **Confidence threshold**: only `high` confidence responses are written to `models.json` by default. `medium` and `low` are logged but not used. A config flag `AI_GAP_FILL_MIN_CONFIDENCE` lets you opt into lower-confidence fills if desired.
4. **Source URL must resolve**: optional but recommended — the orchestrator does a HEAD request on `source_url` and rejects fills where the URL 404s. (Cheap check, big credibility upside.)
5. **Per-run cap**: hard limit on gap-fill calls per scrape run (default 50) so a runaway loop can't burn the API budget.
6. **Diff visibility**: every gap-fill run logs a summary block:

   ```text
   AI Gap-Filling Pass:
     Top-20 cohort: 20 models
     Tracked benchmarks: 29
     Gaps identified: 312 (model × benchmark cells missing)
     Cache hits: 287 (skipped)
     LLM queries: 25
     High-confidence fills accepted: 19
     Medium/low confidence dropped: 4
     Schema invalid / dropped: 1
     Net new cells written: 19
     Qualified set size: was 6, now 8
   ```

## 13. Failure modes and fallbacks

| Scenario | Behavior |
| --- | --- |
| OpenAI API unavailable (5xx, network error) | Retry up to 3× with exponential backoff. After 3 failures, skip the gap-filling pass entirely. Pass 2 runs on the unmodified cohort. Logged loudly. |
| OpenAI API rate-limited (429) | Honor the `Retry-After` header. Up to 3 retries; then skip the pass. |
| `gpt-5.4-pro` not available on the account | Walk the `DEFAULT_MODEL_CHAIN` fallback in §9. If none of the fallbacks support `web_search`, skip the pass — we don't run blind. |
| `OPENAI_API_KEY` missing | Skip the pass with a single-line log explaining where to set it (`.env` locally, GitHub Actions secret in CI). Scraper proceeds to Pass 2 unaffected. |
| Schema validation failure | Drop the individual response. Continue processing the rest of the batch. |
| `web_search` tool returned no results | Treat as `score: null`, cache with the negative-cache TTL, continue. |
| Per-run cap reached | Stop dispatching new prompts; finish in-flight ones; proceed to Pass 2 with whatever was filled. |
| Cache file corrupted | Delete and rebuild on next run. Log a warning. |
| Hallucinated source URL (404) | Drop the fill. Mark the gap candidate as `low_confidence` and skip it for the next 7 days. |

## 14. Cost estimate

OpenAI pricing (Apr 2026) is published at <https://openai.com/api/pricing/> and changes periodically. There are two cost components for this pass:

1. **Model token usage** — input + output tokens billed per million.
2. **`web_search` tool usage** — billed per search call (not per query character). Each `tools: [{"type": "web_search"}]` invocation triggers one billable search; the model may call it 0–N times per request depending on the prompt.

Cost is dominated by **how many LLM calls actually fire**, which is set by §5 (useless-work filters) and §6 (tiering and per-run cap). The analysis below uses the 2026-04-12 cohort numbers from §3 and §7.

| Stage | Count | Cumulative drop |
| --- | ---: | --- |
| Naive cross-product (cohort × benchmarks) | ~580 | baseline |
| Cells already populated (no gap) | ~217 | -363 |
| **Raw gap candidates** | **~363** | start of pipeline |
| §5 useless-work filters | ~30 | -30 |
| Tier 3 dropped (permanently off) | ~95 | -95 |
| Tier 1+2 active set | **~28** | per-run target |
| Cache hit after a few warm runs (~80%) | ~22 | -22 |
| **Real LLM calls per scrape** | **~6–10** | net |

Per-call cost using `gpt-5.4-pro` Responses API pricing (illustrative — confirm at runtime):

- **Tokens.** Template prompt is ~600 input tokens (system + user from §8). Strict-JSON response is ~150 output tokens. Add ~300 tokens of intermediate reasoning trace when `web_search` is used. Token cost per call: low single-digit cents.
- **Web search.** `tool_choice: "auto"` means the model decides whether to search; for gap-fill prompts it will almost always call `web_search` once (sometimes twice if the first search misses). Search-tool surcharge per call: a few cents.
- **Per call total:** roughly **$0.05–$0.10** depending on whether the search fires and how many results it returns.
- **Per scrape run** (6–10 calls): **roughly $0.30–$1.00.**
- **Daily cadence:** **$10–$30/month** at the upper bound. Cheaper if you run gap-filling weekly instead of every scrape.

Cost optimisation knobs (in priority order):

1. **The §5 + §6 filters are the budget controller** — they cut the call volume by ~98% before the first prompt fires. Tightening them is more effective than swapping models.
2. Drop the fallback chain to `gpt-5.4` (non-pro) for routine runs and reserve `gpt-5.4-pro` for weekly catch-up runs.
3. Tighten cache TTL → fewer re-queries.
4. Lower `AI_GAP_FILL_MAX_CALLS` (default 40) → bound the worst case.
5. Run gap-filling weekly instead of daily.
6. As a last resort, set `tool_choice` to `"none"` for low-confidence prompts to skip the search-tool surcharge — but this throws away the main reason we chose OpenAI direct. Don't do this unless costs blow up unexpectedly.

## 15. Files that would change

- **`scripts/gap_fill_benchmarks.py`** — new module containing:
  - `build_prompt(model, benchmark, llm_stats_metadata) -> tuple[str, str]` — returns the (system, user) message pair per the §8 Role/Context/Task/Constraints/Output split.
  - `discover_available_model(chain: list[str], api_key: str) -> str` — queries `GET https://api.openai.com/v1/models`, walks `DEFAULT_MODEL_CHAIN`, returns the first model the account can call **and** that supports the `web_search` tool. Raises if no fallback supports web search.
  - `query_openai_responses(system: str, user: str, *, model: str, api_key: str) -> dict` — single `requests.post` to `https://api.openai.com/v1/responses` with the body shape from §9 (Responses API, `tools: [{"type": "web_search"}]`, `text.format: {type: json_object}`). Handles HTTP retries (3× exponential backoff) and 429 rate-limit responses gracefully (honors `Retry-After`).
  - `resolve_openai_key() -> Optional[str]` — reads `OPENAI_API_KEY` from the environment. Returns `None` if not set. **No SDK fallback, no shell-out.** In CI the key comes from `${{ secrets.OPENAI_API_KEY }}`; locally it comes from `.env` (loaded by python-dotenv at script startup).
  - `validate_response(raw: dict) -> Optional[dict]` — schema check from §8 plus the §12 sanity bounds.
  - `apply_useless_work_filters(candidates, entries) -> list` — drops gap candidates per §5 (origin lock, locale suffix, hopeless tier, vendor-internal, already-qualified, negative cache).
  - `tier_and_budget(candidates) -> list` — sorts surviving candidates per §6, truncates at `AI_GAP_FILL_MAX_CALLS`.
  - `run_gap_filling_pass(combined_entries, benchmark_headers, top20) -> int` — orchestrates one pass and returns the number of cells filled.
  - `load_cache() / save_cache()` — persistence for `data/ai_gap_cache.json`.
  - `append_audit_entry(entry: dict) -> None` — appends a single JSON line to `data/ai_fill_history.jsonl` per §11 audit storage.
- **`scripts/scrape_models.py`** — invoke `run_gap_filling_pass(...)` after the Initial Top 10 / Top 20 selection, before the Pass 2 qualified-set computation. Pass the discovered cohort and benchmark_headers in. Also load `.env` at startup via `python-dotenv` so the OpenAI key is available.
- **`scripts/requirements.txt`** — add `python-dotenv>=1.0.0` (for loading `.env` locally; CI doesn't need it because env vars are injected directly). No OpenAI SDK needed — we use plain `requests` against the Responses API HTTP endpoint. If this becomes painful, consider `openai>=1.50.0` later.
- **`models.json`** — gain a `_provenance` block per model row.
- **`index.html`** — render the provenance icon next to ai-filled scores; tooltip with source link.
- **`data/ai_gap_cache.json`** — new file, committed (so CI doesn't burn through API quota on every push).
- **`data/ai_fill_history.jsonl`** — new file, committed. Append-only audit log (§11). One JSON object per line.
- **`docs/scraper_specification.md`** — add a "Gap-filling pass" section between the existing Pass 1 and Pass 2 sections.
- **`README.md`** — mention the gap-filling step in the "scoring at a glance" block.
- **`.env.example`** — document `OPENAI_API_KEY=` and `AI_GAP_FILL_MODEL=gpt-5.4-pro`. The real `.env` file is gitignored.
- **`.github/workflows/scrape.yml`** (existing scraper workflow) — expose `OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}` as an env var on the scraper step. The repo secret was created on 2026-04-12 — no further setup needed.

## 16. Resolved decisions

| # | Question | Decision |
| --- | --- | --- |
| 1 | **In-cohort scope** — Top 10 only or full Top 20? | **Full scraped cohort (20 = 10 US + 10 CN).** Each individual fill targets a (cohort model, tracked benchmark) pair anywhere in the top 20. The "top 10" only enters as the *priority signal* for the §6 tiering (and that top 10 is **llm-stats raw leaderboard rank**, not our Pass 1 ranking — see §2 and §6 for why we run gap-fill before Pass 1). |
| 2 | **Benchmark scope** — fill everything, or only close-to-qualifying? | **Only close-to-qualifying.** Tier 1 (7/10 in llm-stats top 10) and Tier 2 (4–6/10) are the active set. Tier 3 (≤ 3/10) is permanently off. The ROI per call drops sharply outside of Tier 1+2 and we don't want to waste budget on benchmarks that can't be rescued. |
| 3 | **Provenance display** — include AI-filled scores in IQ scoring? | **Yes, include them.** Filled scores feed Pass 2 like any other reported value. Provenance is tracked per-cell in the `_provenance` block (§11) and the UI flags them with a sparkles icon + tooltip. Without inclusion the entire pass is theatre. |
| 4 | **Audit storage** — long-running append-only fill log? | **Yes.** `data/ai_fill_history.jsonl` is appended on every accepted fill (one JSON object per line: timestamp, model, benchmark, score, source URL, confidence, llm model used). The file is committed so historical drift is visible in `git blame` / `git log`. |
| 5 | **Manual override** — human blocklist file? | **Not in v1.** The §5 useless-work filters cover the foreseeable cases. A blocklist can be added in v2 if a real need emerges. |

## 17. Non-goals

- This spec does **not** introduce LLM-based scoring. The LLM only sources missing data; the scoring math stays deterministic.
- It does **not** allow the LLM to revise existing scraped scores. Scraped data is authoritative.
- It does **not** backfill historical `models.json` entries. Only forward runs are touched.
- It does **not** introduce a generic "any benchmark, any model" research tool — only models and benchmarks already in the tracked cohort.

## 18. Success criteria

- Pass 2 qualified set grows from 6 to **at least 10** benchmarks within the first week of running gap-fill on the live cohort.
- ≥ 90% of accepted fills have a source URL that returns 200 when re-checked 30 days later.
- Zero scoring drift from incorrect fills (verified by spot-checking 20 random fills against their source URLs each month).
- Per-run API spend stays under the configured cap (default $5/run).
- The ai_gap_cache hit rate stabilises above 75% after the first 5 runs.

## 19. Fallback playbook if `web_search` becomes unavailable

The v1 design depends on OpenAI's `web_search` tool for live source lookups. If OpenAI deprecates the tool, throttles it heavily, or we ever decide to migrate off OpenAI to a provider that doesn't expose equivalent browsing, the gap-filling pass needs a fallback. This section captures the options so we don't have to rediscover them under pressure.

Three workarounds, in order of preference:

1. **Switch to another provider with native web search.** Anthropic's Claude exposes `web_search_20250305`. Google's Gemini exposes grounding via Vertex AI. Either is a drop-in replacement for the OpenAI Responses call in §9, with a thin per-provider adapter. The §8 prompt template doesn't change. **This is the recommended fallback** — preserve the architecture, swap the SDK call.
2. **Pre-fetch candidate sources, then ask the model to validate.** The orchestrator runs a small set of deterministic lookups before each LLM call: fetch the model's vendor blog index (from the org's known URL pattern), fetch the Papers With Code page for the benchmark, fetch the model's HuggingFace model card if it exists. The contents (truncated to ~4 KB each) are passed to the LLM in the Context section as `candidate_sources: [...]`, and the prompt's Constraints are tightened to *only* cite a score that appears in one of those candidate sources. The model becomes a verifier, not a researcher. Slower and less accurate than native browsing, but works on any LLM.
3. **Run a separate search step against an external search API** (Brave Search, Tavily, Bing) and feed the top-N results into the LLM context. Adds another API key and another set of rate limits — keep this as a last resort.

Workaround (1) is the cheapest to implement (a new adapter file, no architectural change). Workarounds (2) and (3) are documented here for completeness but should not be implemented unless every native-search provider becomes unavailable.
