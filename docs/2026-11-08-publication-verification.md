# November 7 and 8 publication verification

The November 8 scrape retained both snapshots: November 8 at 03:37:41 UTC and
November 7 at 03:31:27 UTC. Production was still on November 7 while PR #31
awaited resolution of evidence review findings.

## Exact-model source verification

Verified November 8, 2026 using both the source text and the rendered HTML table:
https://thinkingmachines.ai/model-card/inkling-2-small/

Although this is the Inkling model card, its comparison table explicitly names
Claude Haiku 5.5 in the final model column. In that exact column:

| Benchmark row | Claude Haiku 5.5 | Inkling 2 Small |
| --- | --- | --- |
| MMMU Pro (Standard 10) | 79.1 | 81.6 |
| Charxiv RQ, original / with Python | 84.4 / unavailable | 85.6 / 87.7 |

Values in the source table are percentage scores. The stored Claude findings
match the Claude comparison column, not the Inkling column. The review claim
that the page does not identify Claude Haiku 5.5 is incorrect. Preserve both
findings and their existing availability dates; make the model column explicit
in catalog configuration, cache notes, and audit records. No algorithm or score
change is required. Regenerate the complete publication so all fingerprints,
provenance, summaries, and artifacts agree.
