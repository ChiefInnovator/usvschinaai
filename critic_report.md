# Critic Review

Target: [design draft](design_draft.md), feature specification.

| Reviewer | Reads | Status |
| --- | --- | --- |
| `goldfish_stage7_design` | Persona, standard, draft, sources | Completed |
| `goldfish_stage7_structure` | Persona, standard, target | Completed |
| `goldfish_stage7_style` | Persona, target | Completed |

## Findings and resolutions

- **D7-1 — Major — PROPOSE FIX:** Algorithm revision/catalog hash cannot identify
  a new scrape with unchanged evidence. Add a publication manifest with exact
  artifact hashes and a generation ID, and verify deferred responses against it.
  Accepted; design now binds summary, raw data and cache generation explicitly.
- **D7-2 — Major — PROPOSE FIX:** Required image/social outputs were outside the
  recovery boundary. Stage generation and validation before installing output;
  certify publication only after the complete generation exists. Accepted;
  preparation now stages canonical replay, audit, summary, image/social outputs
  and manifest before a recoverable installation.
- **Y7-1 — Nit — PROPOSE FIX:** Value denominator wording was ambiguous.
  Accepted; specify IQ divided by the sum of input and output prices.

Structural reviewer found no material issues. No design blockers were reported.
