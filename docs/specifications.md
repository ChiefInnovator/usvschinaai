# US vs China AI — project specification

## Product

A public static website compares US and Chinese AI models using a configured
score and daily recorded rosters. National totals sum each country's models in
the combined global Top 10. Filtering the visible roster never changes national
totals. Editor-selected weights and their history are disclosed; this is not an
independent national capability standard.

## Pages and interaction

- `index.html`: compact national comparison, model ranking, deferred model
  evidence, accessible trend/matrix tables, companies and methodology.
- `history.html`: exact UTC date/time lookup, previous/next observation,
  optional comparison, keyboard sorting/filtering and URL-restorable state.
- `about.html`: current methodology, assumptions and weight-selection disclosure.
- `privacy.html` and `terms.html`: legal reading pages without moving news.
- `404.html`: focused recovery link.

Rank, model and Unified remain visible together on phones. Native controls expose
sorting, selected filters and disclosure state. Dates use recorded snapshots;
absent dates/models are not synthetic zeros. Price availability is distinct from
the numeric zero contribution used by the current scorer.

## Scoring

`data/core_benchmarks.json` is the selection/alias/weight authority for seventeen
benchmarks totaling 100%. `scripts/scoring.py` and its dependencies implement
calculation and applicability. Full rules and adjustment history are in
[two_pass_scoring.md](two_pass_scoring.md).

- Avg IQ is the weighted sum of the selected percentage scores with a fixed
  denominator; missing results contribute zero.
- Value = Avg IQ / (input price + output price), both prices per million tokens.
- Unified = 10 × (0.9 × cohort-normalized Avg IQ + 0.1 × cohort-normalized Value).
- National totals sum Unified for each country's entries within the global Top 10.
- Missing public pricing leaves the existing zero Value contribution; the UI
  explains availability rather than calling the model free or unranked.

### Full historical replay is mandatory

Every algorithm change triggers replay of all retained history, including changes
to weights, benchmarks, normalization, missing results, pricing calculations or
evidence selection. Replayed history retains timestamps, roster membership and
dated price profiles. Source evidence remains subject to its historical
availability date. Historical charts use the current algorithm, not a mixture of
old and new scoring rules.

`scoring_revision.py` fingerprints configuration, dependency pins and transitive
local scoring source. Publication verification independently replays all dates,
even when a fingerprint matches. Missing or mismatched revision metadata is a
migration condition, not permission to stamp old results without calculation.

## Canonical storage

- `data/model_catalog.json`: stable model IDs, historical profiles, dated evidence,
  sources, configurations and exclusions.
- `models.json`: exact dated roster/profile references and computed scores.
- `current.json`: latest reference-only snapshot.
- `data/scoring_revision.json`: current scoring source fingerprint/inventory.
- `data/historical_benchmark_gaps.json`: generated unresolved-evidence audit.

See [model_storage.md](model_storage.md) for recovery and availability rules.
Python/browser hydration select the same highest eligible result, resolving ties
by availability date and evidence ID. A historical observation is not
necessarily AI-researched.

## Public projections and publication identity

`data/site_summary.json` schema 1 contains current resolved profile/score rows,
benchmark definitions and weights, and a compact exact-timestamp index of national
totals. It omits full evidence/historical rosters. The homepage's first data load
does not download the full archive/catalog. Evidence and historical rosters load
only on request.

`data/publication.json` records the scoring revision, generation ID and exact
artifact byte digests. Generation identity hashes the four canonical source paths
(`models.json`, `current.json`, catalog and benchmark configuration) plus scoring
revision using sorted compact JSON framing. Browser loaders verify response hashes
and reject mixed generations. A failed detail request leaves the ranking intact
and can be retried.

Preparation executes the copied scripts in a fresh temporary directory, performs
full replay, renders snapshot-time images and deterministic social captions, then
validates and installs a complete generation. The durable publication journal
installs its manifest last and is excluded from source control/public builds.
Image/render failure before installation leaves the old publication untouched.
No paid research or remote social posting occurs during preparation/verification.

## Build and hosting

The runtime is static HTML and vanilla JavaScript on Azure Static Web Apps.
Tailwind 3.4.16, Chart.js 4.4.7 and Lucide 0.454.0 are exactly pinned in npm and
served locally after compilation. Python dependencies retain exact pins.

`npm run build` compiles assets, verifies publication, and writes `dist/` using a
public-file allowlist. Agent instructions, workflows, tests, research intake,
secrets and writer journals are never copied. Existing public raw JSON and current
social-slide URLs remain available.

The built manifest adds hashed shell artifacts and a shell revision. Offline
caches become active only after every required shell asset verifies. An interrupted
update retains the previous complete generation. At most two complete generations
and one staging cache are retained; raw evidence is not precached.

The deployment workflow verifies full replay, validates, builds and tests, uploads
that exact artifact, and deploys it in a dependent job without rebuilding. It
records a single candidate SHA, serializes production delivery and refuses to
replace a newer main-branch candidate. Fork code receives no deployment secrets.

## Operations

- Daily scrape schedule: 03:17 UTC, subject to workflow execution delay.
- Visible current-data warning: older than 36 hours. A daily snapshot is normally published by the scrape itself within about half an hour, and by a manual merge when a check or review needs a person.
- Operational freshness alert: older than 30 hours; timestamps over five minutes
  ahead also fail health checks.
- Health monitor: every 30 minutes, checking reachability, snapshot freshness and
  manifest/summary/revision agreement.
- Research budget policy remains in the daily workflow. Publication captions use
  deterministic facts; optional caption tooling remains separately available.
- Roll back the whole previously verified artifact. A source algorithm revert
  still requires a full replay before a new publication.

## Verification

See [testing.md](testing.md). Tests cover scoring/evidence boundaries, historical
pricing/identity, recoverable writes, revision mutations, summary parity, mixed
publication generations, phone layouts, keyboard controls, historical lookup,
request retry, public build exclusions and interrupted offline generation changes.
Local checks do not establish live Azure deployment or production acceptance.
