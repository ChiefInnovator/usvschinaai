# Goldfish review and implementation

Date: 2026-11-02.
Target: [design draft](design_draft.md) and the resulting repository changes.
Status: Implemented and verified locally; not committed or deployed.

## Owner decisions

- The owner authorized all aspects of the draft and implementation of the
  Goldfish recommendations.
- Every scoring algorithm change requires a full historical rescore before
  publication. A research date window never limits algorithm migration.
- Historical timestamps, exact model membership, price profiles and dated
  evidence remain intact. Historical results use the current algorithm.
- No deployment, commit, paid research or remote social posting was performed
  during this implementation.

## Reviewer status

All Goldfish sessions used fresh conversation contexts and read their assigned
personas, standards, target ranges and required resources. Reviewers were
read-only; implementation workers were separate from these review sessions.

<!-- markdownlint-disable MD013 -->

| Stage | Reviewers | Result |
| --- | --- | --- |
| Initial Zoom Out | `goldfish_stage5` | Completed; two findings resolved |
| Comprehension | `goldfish_stage6` | Completed; two findings resolved |
| Critic | `goldfish_stage7_design`, structure, style | Completed; three findings resolved |
| Intermediate Zoom Out | `goldfish_stage8` | Completed; no remaining material findings |
| Readiness | `goldfish_stage9_readiness`, codebase, style | Completed; six findings consolidated and resolved |
| Actual delivery code | `goldfish_code_delivery` | Completed; five findings resolved |
| Actual scoring code | `goldfish_code_scoring` | Completed; three findings resolved |

<!-- markdownlint-enable MD013 -->

Individual reports are [initial review](zoom_out_report.md),
[comprehension](comprehension_report.md), [critic](critic_report.md),
[intermediate review](intermediate_zoom_out_report.md), and
[readiness](implementation_readiness_report.md).

## Findings, decisions and implementation trace

Every finding below was accepted as **PROPOSE FIX**. No findings were contested,
escalated or silently treated as clean reviews.

<!-- markdownlint-disable MD013 -->

| Finding | Severity | Implemented resolution | Evidence |
| --- | --- | --- | --- |
| Z5-1: missing scoring dependency | Major | Hash transitive local imports, including historical adapters | `scoring_revision.py`, revision tests |
| Z5-2: ambiguous unpriced label | Nit | Distinguish missing price/Value from Unified ranking | Home/archive evidence UI |
| C6-1: evidence selection undefined | Major | Reuse exact resolver and evidence IDs; UTC/tie parity | ModelStore and browser tests |
| C6-2: freshness undefined | Nit | 26h UI, 30h health, future-clock warning | Dashboard and health checks |
| D7-1: incomplete generation identity | Major | Hash canonical sources, verify response bytes | Publication manifest and SiteData |
| D7-2: incomplete transaction | Major | Stage full outputs, journal installation, manifest last | Publication failure/recovery tests |
| Y7-1: Value denominator ambiguous | Nit | Explicit price-sum formula | Draft and methodology |
| R9-1/B9-2: social generation ordering | Major | Snapshot-time deterministic staging; no later mutation | Preparation and writer workflows |
| R9-2: worker protocol incomplete | Major | Hashed complete-shell caches and active pointer | Worker generation tests |
| R9-3: generation hash unspecified | Major | Four named source paths and compact sorted JSON | Revision/generation tests |
| B9-1: staged roots/caches unsafe | Major | Complete copied script tree in fresh subprocess | Staging and isolation tests |
| B9-3: private helpers lack contracts | Major | Declare contracts for all inventoried methods | Application contract suite |
| GD-1: obsolete backfill always exits | Blocker | Modern dated research, full replay and preparation | Research/deployment tests |
| GD-2: deployed artifact untested | Major | Serve unchanged dist in actual Chromium tests | Built-site acceptance tests |
| GD-3: chart failure erases ranking | Major | Separate optional chart error boundaries | Throwing-constructor regression |
| GD-4: future timestamp looks fresh | Major | Explicit clock/data warning | Future-date browser regression |
| GD-5: offline data unlabeled | Major | Connectivity and cached-response indication | Worker header/browser regressions |
| GS-1: retired evidence blocks replay | Major | Retain observations; exclude inactive components | Benchmark replacement regression |
| GS-2: offset date leaks future evidence | Major | Parse applicability dates in UTC | UTC boundary/parity regressions |
| GS-3: legacy recovery can overwrite files | Major | Validate full intent/paths/symlinks before writes | Malicious-journal regressions |

<!-- markdownlint-enable MD013 -->

## Product changes

- Phone rows keep rank, model and Unified together. Scorecards are compact;
  secondary navigation is in a native “Explore sections” disclosure. National
  totals explain the global Top 10 rule and contributing-model counts.
- Models expose reported coverage, prices, selected benchmark evidence, weights,
  sources, configurations and dates. Missing evidence stays missing; no AI
  attribution or confidence is invented.
- Archives selects exact UTC dates and intraday timestamps, supports comparison,
  preserves URL/Back behavior and loads only selected historical rosters.
- Native sorting/filter state, visible focus, accessible chart tables, named
  sharing controls and clipboard fallback support keyboard/touch use.
- Initial data is a 143,282-byte summary instead of the full catalog/archive.
  Full evidence is fetched on demand and checked against the publication.
- Local pinned CSS, chart and icon assets remove deployed CDN dependencies.
  The allowlisted build excludes agent instructions, research intake and secrets.
- Offline activation requires a fully verified generation. Failed updates retain
  the previous complete cache, and cached results are labeled.
- Legal reading pages have narrower text and no moving news. The existing
  competition identity and legal claims remain.

## Historical and publication acceptance

The full retained corpus was replayed after the final scoring changes:

- 255 snapshot timestamps and every country/model/profile reference preserved.
- Catalog evidence and historical profiles equal the original catalog.
- Zero existing rows changed derived numeric scores under this corpus; all were
  recalculated and stamped rather than merely relabeled.
- All current/history/summary outputs share the scoring revision and publication
  generation. Independent replay and installed-artifact validation pass.
- Data generation at completion of the interface/publication work:
  `59ab5500709165120b02efe0e00faffb603823d60754a74596b10de5d33b5c64`.

The builder emits one verified `dist/` artifact. The deployment workflow tests
that artifact, carries its exact candidate SHA, deploys without rebuilding and
prevents a superseded candidate from replacing newer production. Stale candidate
runs do not report successful delivery and trigger downstream publishing.

## Verification and limits

- Baseline: 788 tests, one optional dependency-freshness skip, no failures;
  canonical validator had zero errors/warnings.
- Final suite: 904 tests in 20.878 seconds, 903 passed and one optional latest
  dependency-release check skipped (`CHECK_LATEST=1` enables it). No failures or
  errors. Full replay, model validation and all five changed workflow lints pass.
  New design/report Markdown checks pass; table line length is exempted locally
  so complete traceability rows remain valid Markdown tables.
- Chromium exercises the actual built artifact, real chart library, 390px layout,
  archive interactions, local asset hashes and offline reload. Node tests also
  execute the actual worker under interrupted/mixed generation conditions.
- Combined desktop/mobile inspection covered all six public surfaces, followed
  by one bounded confirmation pass for material layout fixes. No page overflow
  or browser exceptions were observed. Contrast/glow warnings were fixed rather
  than suppressed in that pass. The later hook triage below records one
  narrowly scoped font exception.
- The committed source snapshot remains September 26. No claim is made about
  current production freshness, deployed Azure behavior or publishing credentials.
- The manually invocable research path is tested with mocks. No paid research,
  live source refresh or remote posting was run to verify this implementation.
- Downloaded EGM vendor documents retain their upstream formatting. Project
  design/report checks are separate from those upstream warnings.

## Next acceptance boundary

The changes remain local and uncommitted. Live deployment and production
acceptance require shipping the verified artifact; they are separate from the
completed local implementation and checks.

## Stop-hook follow-up

- Raised country badges and score labels to at least 11px.
- Flattened company/model containers, explanatory panels and the filter group;
  retained their content and keyboard controls.
- Replaced the repeated auto-scrolling news strip with a static, readable list
  of safe source links. No news content is duplicated for animation.
- Retained the reviewed incumbent Inter/system font stack. A single
  `overused-font=inter` exception is scoped to `index.html` in
  `.impeccable/config.json`; no whole-file or whole-rule ignores were added.
- The detector reports zero remaining findings on `index.html`. The build,
  three focused accessibility checks and four built-site browser checks pass.
  The scoring generation is unchanged; these are interface-only corrections.

## AI workflow optimization follow-up

[Current model routing and evaluation](docs/llm_cost_optimization.md) records the
subsequent GPT-6.1 Terra/GPT-6 Luna migration, verified prices and bounded live
comparison. Cached passes no longer require model discovery or a funded key to
apply previously accepted evidence. Existing evidence and budget checks remain.

All 255 snapshots were replayed again and independently verified. The new data
generation is `5af9861d1b948c01a9fd51383e95fe75d314e3411a6f2a638949bb973498db1e`.
The final built-artifact suite passed 911 tests: 910 passed, one optional latest
release check skipped, no failures/errors. Model validation, changed workflow
lint with shellcheck, build and cost-guide Markdown checks passed. Four manual
synthetic extraction calls passed separately; no web research or evidence writes
were part of that comparison. Changes remain local and uncommitted.
