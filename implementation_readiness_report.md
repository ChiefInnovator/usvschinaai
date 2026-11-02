# Implementation Readiness Review

Target: [design draft](design_draft.md), Detailed Implementation Plan.

| Reviewer | Reads | Status |
| --- | --- | --- |
| `goldfish_stage9_readiness` | Persona, standard, draft | Completed |
| `goldfish_stage9_codebase` | Persona, standard, draft, source | Completed |
| `goldfish_stage9_style` | Persona, target, definitions | Completed |

## Findings and resolutions

- **R9-1 — Major — PROPOSE FIX:** Define one social-output order and offline
  policy. Use the existing snapshot-time deterministic image/caption renderer
  in staging; prohibit ordinary network caption publishing there. Remove later
  public-file mutations and stale caption-cache reuse. Accepted.
- **R9-2 — Major — PROPOSE FIX:** Define complete-generation worker activation.
  Add hashed shell artifacts, a generation-named staging cache, one active-cache
  pointer, previous-cache retention, bounded cleanup and interrupted-update tests.
  Accepted into the draft.
- **R9-3 — Major — PROPOSE FIX:** Specify exact generation inputs and framing.
  Hash the four named canonical data paths and scoring revision with sorted,
  compact JSON framing. Accepted into the draft.
- **B9-1 — Major — PROPOSE FIX:** Existing modules bind roots and cached
  configuration independently. Execute a complete staged script tree in a fresh
  subprocess, with explicitly copied rendering and data inputs. Accepted.
- **B9-2 — Major — PROPOSE FIX:** Freeze regenerated social facts/time to the
  snapshot and ignore stale paid-caption cache. Consolidated with R9-1.
- **B9-3 — Major — PROPOSE FIX:** Contract tests inventory private helpers too.
  Require contracts on every inventoried function/method and explicitly update
  the contract test inventory if new rule types are introduced. Accepted.

Style reviewer found no material issues. Implementation begins after the above
contracts are incorporated; this report is not proof of completed code changes.
