# LLM Cost Optimization — AI Gap-Filling Pass

**Status:** Implemented.
**Applies to:** `scripts/gap_fill_benchmarks.py`
**Companion spec:** [ai_gap_filling.md](ai_gap_filling.md)

This doc is the single source of truth for every token-saving trick we use in the gap-filling pass. Each practice is described with (a) what it does, (b) why it matters, and (c) how it's implemented here. Order is rough impact, highest-impact first.

## 1. Batch multiple benchmarks per call (the biggest lever)

**What.** Instead of one API call per (model, benchmark) pair, we group all candidates by model and emit **one** batched call that asks for every missing benchmark for that model in a single request. The Responses API returns an array of results, one per requested benchmark.

**Why.** The dominant cost is the `web_search` tool injecting fetched page content back into the prompt — a single benchmark lookup for Claude Opus 4.6 burns ~8,600 input tokens, almost all of which is the Anthropic vendor-blog page content. Asking for one benchmark at a time makes us pay for that same page fetch over and over. Asking for **all missing benchmarks for Claude Opus 4.6 in one call** amortizes the ~8,600-token page content across 5–7 benchmarks instead of 1, cutting per-benchmark cost by 5–7×.

**Measured effect.** 40 candidates → ~15 batched calls. Live API spend dropped from ~$1.00/run to ~$0.20/run in our smoke tests, and latency dropped because there are fewer round trips.

**How.** See `_group_by_model()` and the orchestration loop in `run_gap_filling_pass()`. One batched call per model; the JSON-schema response has a `model` field plus a `results: [{...}, {...}, ...]` array.

## 2. Stable system prompt (prompt-cache prefix hits)

**What.** The system message is byte-identical on every call. No per-call variables (model name, benchmark list, URL) are ever interpolated into it. All variables live in the user message.

**Why.** OpenAI, Anthropic, and Google all cache LLM input prefixes and bill re-hits at ~50% of the normal rate. The cache key is a hash of the literal bytes, so any variation (even whitespace) invalidates the cache. By splitting the prompt into a stable system message + per-call user message, every call after the first one in a run gets the ~470-token system prefix at discount.

**Caveat.** OpenAI's current prompt cache has a minimum-size threshold (~1024 tokens) that our ~470-token system message doesn't hit. We structure for caching regardless because (a) it's free discipline, (b) the threshold may change, and (c) other providers have lower thresholds that we'd benefit from immediately on migration.

**How.** `_SYSTEM_PROMPT` is a module-level constant. `build_prompt_batch()` returns `(_SYSTEM_PROMPT, per_call_user_message)` — never interpolates into the system side.

## 3. Right-sized model chain with graceful fallback

**What.** The `DEFAULT_MODEL_CHAIN` tries `gpt-5.4` first, then `gpt-5.4-pro`, then `gpt-5.3` as a last-resort fallback. The discovery step picks the first model the account can actually call **and** that supports the `web_search` tool.

**Why.** `gpt-5.4` is the sweet spot for research-style benchmark lookups — strong enough reasoning to extract the right row from a vendor blog page, cheaper than `-pro`. We keep `gpt-5.4-pro` in the chain as a stronger fallback in case base 5.4 isn't available, and `gpt-5.3` as a compatibility floor for older accounts. The `reasoning.effort: "low"` setting (§4) keeps hidden-reasoning tokens minimal regardless of which model is picked.

**Why NOT `gpt-5.4-mini`.** Earlier versions of the chain defaulted to the mini tier, but the savings didn't justify the occasional quality slips on variant-matching (e.g. attributing a "GPT-5 High" score to "GPT-5"). For a research task where the *correctness* of the extraction is the whole point, a full reasoning model is worth the extra cents per call.

**How.** `DEFAULT_MODEL_CHAIN: List[str] = ["gpt-5.4", "gpt-5.4-pro", "gpt-5.3"]`. Override with the `AI_GAP_FILL_MODEL` environment variable if needed.

## 4. `reasoning.effort: "low"`

**What.** We pass `"reasoning": {"effort": "low"}` on every Responses API request, telling the model to minimize hidden reasoning tokens.

**Why.** The Responses API bills both visible output AND hidden reasoning tokens against `max_output_tokens`. On a research task where the model just needs to search, fetch, extract, and emit JSON, deep chain-of-thought adds nothing and costs a lot. Default `effort: "medium"` can burn 1,000+ hidden reasoning tokens per call. `"low"` cuts that by 5–10×.

**How.** `REASONING_EFFORT = "low"` at module scope; wired into the request body in `query_openai_responses()`.

## 5. Terse user message (remove duplicated instructions)

**What.** The user message contains *only* the per-call data the model needs: model name, organization, country, llm-stats URL, and the benchmark list. No restated rules. No reminders. No output-format instructions.

**Why.** Every repeated instruction is re-billed tokens on every call. If a rule is in the stable system prompt, repeating it in the user message is waste. Earlier drafts of our user message included "use web_search efficiently", "return one entry per benchmark", "set score to null if not published" — all duplicated from the system message. Stripping them cut the user message from ~720 chars to ~220 chars (~70%).

**How.** `build_prompt_batch()` returns a minimal user message template — model identity and benchmark list only. All behavior rules (null handling, citation requirement, confidence levels, batching efficiency, variant discipline) live in `_SYSTEM_PROMPT`.

## 6. Structured-output JSON schema (no filler text)

**What.** We use OpenAI's Responses API `text.format: {type: json_schema, strict: true}` with a typed schema, instead of free-form prose or loose JSON mode.

**Why.** Strict structured outputs force the model to emit *only* the schema fields — no preamble ("Here is the result:"), no trailing apology, no markdown formatting, no extra commentary. Saves output tokens (billed ~4–5× higher than input tokens) and removes a whole class of parsing failures that would otherwise require retries.

**Caveat.** `web_search` is incompatible with `text.format: {type: json_object}` (strict JSON mode) — OpenAI explicitly rejects that combo. But `json_schema` with `strict: true` is accepted alongside `web_search`. Use the latter.

**How.** `query_openai_responses()` builds the schema with the `benchmark_lookup_batch` name. Every field is in the `required` array (even nullable ones — the nullable fields use `type: ["string", "null"]`).

## 7. Eventually-consistent cache

**What.** Positive fills (score != null) are cached in `data/ai_gap_cache.json` with a 30-day TTL. Subsequent runs that encounter the same (model, benchmark) pair skip the LLM call entirely and apply the cached result. The cache file is committed to the repo so CI runs benefit from all prior work.

**Why — and this is the part most cost analyses miss: the cache makes the system *eventually consistent* with the real benchmark landscape.** If a given run's `--gap-fill-max-calls` budget doesn't cover every candidate — say 40 calls but 19 groups so all 19 get processed, OR 20 calls and only 20 groups get processed — the **cached positive results from the current run** mean the next run only pays for the models we missed, plus any newly-added gaps. Over a handful of scrapes, every addressable gap gets filled even if no single run can afford to cover them all. The cache turns a hard budget into a soft budget amortized across scrape runs.

**Concretely:** if you set `--gap-fill-max-calls 20` on a 19-group cohort, the first run fills whatever it can in 20 calls and caches every positive result. The second run re-processes the cohort, finds those fills cached (zero cost), and spends its 20 calls on the models it didn't reach last time. By the third or fourth run the whole cohort is in the cache.

**How.** `load_cache()` / `save_cache()` in `gap_fill_benchmarks.py`, called at the start and end of `run_gap_filling_pass()`. Cache entries are keyed by `(model_name, benchmark)` with `cached_at` timestamps so `cache_is_fresh()` can honor the TTL.

## 8. No negative caching (freshness over cost)

**What.** Null results (score == null) are **not** cached. Every run re-queries any benchmark that previously returned null.

**Why.** A null today might be published tomorrow. Vendors roll out benchmark results on their own schedule, and the whole point of the gap-filling pass is to *discover* newly-available scores. Caching nulls would lock us out of those discoveries for whatever TTL we pick. The right trade-off is: pay for the re-query every run, but never miss new publications.

**Cost impact.** On the first run of a cohort, ~60–80% of gap candidates return null (the genuine "vendor didn't publish this") and ~20–40% return a score. On subsequent runs, the positive fills are cached so only the nulls get re-queried. The marginal cost is ~40 calls × ~9K tokens = ~360K tokens per run — well within the per-minute TPM budget, and well worth it for the freshness.

**How.** `cache_is_fresh()` returns `False` for any entry where `score is None`, making all null results fall through to a fresh query. The orchestration loop additionally skips the cache-write step for null results.

## 9. Pacing to avoid retry storms

**What.** A `REQUEST_INTERVAL_SECONDS = 1.5` sleep between consecutive API calls within a run. Retries on 429 honor `Retry-After` and additionally apply exponential backoff.

**Why.** Every 429 retry re-bills all the input tokens in the retried request. An aggressive retry storm multiplies the token bill. Spacing calls ~1.5s apart keeps us inside OpenAI's per-second token rate (each call uses ~9K tokens, so 40 calls/minute × 9K = 360K tokens/min, comfortably inside the 500K/min TPM envelope).

**How.** `time.sleep(REQUEST_INTERVAL_SECONDS)` between calls in `run_gap_filling_pass()`, plus the exponential-backoff logic in `query_openai_responses()`.

## 10. Pre-filter dead candidates before the API call

**What.** Three layers of deterministic filtering happen *before* we generate a single prompt:

1. **Sparse benchmark drop.** Benchmarks reported by < 4 of 20 cohort models are dropped from `benchmark_headers` entirely — they're never even considered as gap candidates.
2. **Useless-work filters (§5 of ai_gap_filling.md).** Origin lock (e.g. BrowseComp-zh is blocked for US models), locale suffix heuristic, vendor-internal lock, already-qualified filter, hopeless-tier filter.
3. **Tier filtering (§6 of ai_gap_filling.md).** Tier 3 (≤ 3/20 top-cohort participation) is permanently off — those benchmarks are too far from qualifying to be worth calling the LLM about.

**Why.** Every candidate filtered here saves one API call. The filters are cheap dict lookups in Python, so they're essentially free relative to a $0.05 LLM call.

**Measured effect.** Raw cross-product of cohort × benchmarks is ~580 cells. After filters and tiering, it's ~28 candidates per run. That's a ~95% reduction *before* any token is spent.

**How.** `apply_useless_work_filters()` and tier assignment in `build_candidates()`.

## 11. Citation enforcement (reject uncited fills)

**What.** Every non-null score must include a working URL in the structured `source_url` field. If the model puts the URL only in the `notes` field (e.g. as markdown link syntax like `[openai.com](https://...)`), we salvage the URL via regex and promote it to the structured field. If there's no URL anywhere, the fill is rejected as if it had returned null.

**Why.** This doesn't save tokens directly — but it prevents us from **accepting bad fills that we'd later have to fix**. An accepted-but-unverifiable fill contaminates `models.json`, causes drift in the audit log, and eventually requires a manual cleanup that's more expensive than the call that produced it.

**How.** `_validate_result_entry()` enforces the citation rule with `_salvage_url_from_notes()` as the last-chance recovery path.

## 12. Cache-hit confidence re-check

**What.** When the cache hits, we re-apply the same `min_confidence` filter as a fresh call. A cached `medium`-confidence entry won't be applied when `min_confidence="high"`, even though it's in the cache.

**Why.** Without this, a cached low-confidence entry would be applied in perpetuity, bypassing the quality gate. We'd be paying zero dollars but accepting scores we'd never have accepted on a fresh call.

**How.** Inside the cache-hit branch of `run_gap_filling_pass()`, after counting the hit we check `cached_entry["confidence"]` against `min_confidence` and drop to the `fills_dropped_low_conf` counter if it doesn't qualify.

---

## Summary: stacked impact

Starting from the naive one-call-per-candidate approach with `gpt-5.4-pro` and a verbose prompt:

| Optimization | Effect |
| --- | --- |
| Batch by model (#1) | ~65% fewer calls |
| Smaller model (#3) | ~70% cheaper per token |
| `reasoning.effort: "low"` (#4) | ~5× fewer hidden reasoning tokens |
| Stable system prompt (#2) | ~10% cache-hit discount on the prefix |
| Terse user message (#5) | ~70% smaller user side per call |
| Pre-filter dead candidates (#10) | ~95% of the cross-product dropped before any call |
| Cache + eventual consistency (#7) | Positive fills are never paid for twice |
| Hard budget cap | Runaway loops can't blow the bill |

**Estimated per-run cost on the current 20-model cohort:** well under $0.25 in live OpenAI charges. **Per-month cost at daily cadence:** a few dollars. The §10 pre-filters and §1 batching are the biggest levers; the rest stack on top.

## What we deliberately did NOT do

- **Prompt compression** (LLMLingua et al.). Our prompts are already near-minimal; compression libraries add a dependency for marginal gain.
- **`previous_response_id` chaining.** OpenAI's server-side conversation state could in theory deduplicate shared context across calls, but our batching already puts all the shared context in a single call so there's no follow-up to thread.
- **External search API** (Brave, Tavily, Bing) to pre-fetch pages and bypass `web_search`. More plumbing, another API key, and OpenAI's `web_search` is already cost-effective at the mini-model tier.
- **Fine-tuned models for benchmark extraction.** The extraction task is simple enough that stock mini models do it well; training data curation would cost more than the savings would ever recover.
- **Negative caching with short TTL.** Rejected because freshness matters more than cost for this use case (see §8).
