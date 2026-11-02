"""Task-specific API defaults; standard token prices verified 2026-11-02.

Sources: https://developers.openai.com/api/docs/models/gpt-6.1-terra
         https://developers.openai.com/api/docs/models/gpt-6-luna
Prices exclude web-search calls, cache writes and regional/processing premiums.
"""

RESEARCH_MODEL = 'gpt-6.1-terra'
ECONOMY_MODEL = 'gpt-6-luna'
# Availability fallback stays cheaper; never silently escalates to a flagship.
RESEARCH_MODEL_CHAIN = (RESEARCH_MODEL, ECONOMY_MODEL)

# USD per million tokens: input, cached input, output. Retain old rates for
# explicit legacy overrides; existing ledger entries are never rewritten.
TOKEN_PRICES = {
    'gpt-6.1-terra': (1.00, 0.05, 5.00),
    'gpt-6-luna': (0.10, 0.01, 0.50),
    'gpt-5.6-luna': (0.20, 0.02, 1.20),
    'gpt-5.6-terra': (2.00, 0.20, 12.00),
    'gpt-5.4-nano': (0.20, 0.02, 1.25),
}
