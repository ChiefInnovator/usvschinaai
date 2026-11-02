# AI workflow cost and model routing

Verified on November 2, 2026. Defaults live in `scripts/ai_models.py`; workflow
values are checked against that policy by regression tests.

## Task-specific models

| Task | Default | Availability fallback |
| --- | --- | --- |
| Daily benchmark evidence research | `gpt-6.1-terra` | `gpt-6-luna` |
| Manual historical evidence research | `gpt-6-luna` | `gpt-6.1-terra` |
| Funded-account preflight | `gpt-6-luna` | Explicit override only |
| Optional routine caption tool | `gpt-6-luna` | Deterministic caption |
| Optional high-weight caption tool | `gpt-6.1-terra` | Deterministic caption |

The daily pass keeps the balanced tier for exact model/version/protocol work.
The larger manual research workload uses the economy tier and the same evidence
validation. Neither default availability chain escalates into Sol, Astra or older
expensive models. `AI_GAP_FILL_MODEL`, the backfill model input and
`SOCIAL_CAPTION_MODEL` remain explicit escape hatches; an override can cost more.

The routine publication pipeline already uses deterministic captions. It does
not start spending tokens on captions as a consequence of these changes. The
optional caption tools retain one attempt, their output cap and deterministic
fallback. Paid research remains outside builds and tests.

## Verified standard token rates

USD per million tokens, excluding web-search calls, search content, cache writes,
regional premiums and processing-mode differences:

| Model | Input | Cached input | Output |
| --- | ---: | ---: | ---: |
| GPT-5.6 Terra, previous daily default | 2.00 | 0.20 | 12.00 |
| GPT-6.1 Terra, new daily default | 1.00 | 0.05 | 5.00 |
| GPT-6 Luna, focused/economy tasks | 0.10 | 0.01 | 0.50 |

GPT-6.1 Terra reduces daily research token rates by 50% for input, 75% for cached
input and about 58% for output. These are token-rate comparisons, not a promise
that the total research bill falls by the same percentage. Search calls and
model token consumption also affect the bill. The caption ledger uses current
configured rates for the new models and retains legacy rates for explicit old
model overrides; existing ledger entries are not rewritten.

Sources: [GPT-5.6 Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra),
[GPT-6.1 Terra](https://developers.openai.com/api/docs/models/gpt-6.1-terra),
[GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), and
[tool pricing](https://developers.openai.com/api/docs/pricing).

## Avoid unnecessary API work

Research still refreshes direct sources before paid lookup, batches all missing
configured benchmarks for one model into a request, uses a stable system prompt,
strict structured output, low reasoning effort and bounded output. Existing
weekly/manual and new-model budgets remain unchanged. New-model calls retain
their separate ceiling; the manual research command disables that extra ceiling
so its requested maximum remains total.

Model discovery now occurs only when a batch is uncached and has a live-call
budget. Passes with no eligible live-call budget, and fully cached passes, skip
model discovery. Accepted
cached evidence can still be applied when the API key is absent. No-key or
unavailable-model states leave unresolved results missing rather than inventing
scores. A lightweight preflight uses reasoning `none` for the supported default
models, `store: false` and a 16-token output cap.

Positive findings retain their existing TTL and confidence checks. Negative
results are cached for established models for the existing 20-day interval;
new models are revisited during their first 14 days. No participation or country
filter is introduced: every configured missing component remains eligible.
Schema, exact identity, protocol, source URL and confidence checks are unchanged.

## Small live migration comparison

A bounded manual comparison used four API requests: GPT-5.6 Terra versus GPT-6.1
Terra, and GPT-5.6 Luna versus GPT-6 Luna. Each request extracted three synthetic
source fixtures covering model-version confusion, overall versus partial/subset
metrics, and a missing benchmark version. All four returned the expected
`[96.2, 25.7, null]`. These are synthetic test values, not real model claims.

Observed one-request latencies were 2.56s versus 1.43s for Terra, and 1.74s versus
1.31s for Luna. Every request used 329 input tokens; output tokens were 21, 21,
74 and 21 respectively. The older Luna response used 51 reasoning tokens.
No web search or production evidence writes occurred in this comparison.

This is a compatibility/quality smoke check, not proof of general research
superiority or a latency benchmark. Monitor source acceptance, exact-version
mistakes and per-run usage after deployment. Keep an explicit override available
if production evidence quality worsens.

## Verification and publication

Mocked tests cover request routing, discovery-free cached passes, missing keys,
unchanged call budgets, citation/confidence gates, cheap preflight and caption
pricing. No paid API call is part of the unit suite. Real account access to both
new models was checked separately during this migration.

These modules are in the transitive scoring-source inventory. Refresh the entire
publication after changes, even when the formula and existing evidence did not
change:

```sh
.venv/bin/python scripts/prepare_publication.py --write
.venv/bin/python scripts/prepare_publication.py
npm run build
```

Every retained historical snapshot is replayed; original roster, timestamp and
price-profile identity remain fixed. Include regenerated outputs with the model
routing change so publication checks do not certify a stale revision.
