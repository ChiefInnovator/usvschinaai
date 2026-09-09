# Application tests and preconditions

Run every test, including dependency freshness, with:

```sh
.venv/bin/python -m playwright install chromium
CHECK_LATEST=1 .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/validate_models.py
```

On Linux CI, install Chromium system dependencies with `python -m playwright install --with-deps chromium`. The tests and backfill workflows now install the browser before running the suite. Browser tests use the real application HTML and Chart.js in Chromium, temporary deterministic roster data, and injected transport failures. They do not research models or publish posts. The two pinned frontend scripts are downloaded for browser testing; network failure is a test failure, not a skip.

## Coverage added

- The 30-day graph renders both countries and every plotted national total matches its archive snapshot. Tests cover the exact window boundary, two observations on the same day, and exclusion of models outside the global Top 10.
- A daily-update integration test accepts a finding, stores it once, adds a new roster, recalculates applicable earlier dates, and checks that current and full history agree.
- Interrupted-save tests fail each catalog/history/current write in turn. A durable pending transaction completes on the next Python read, preserving roster references and synchronizing all three files. Partial JSON writes leave the previous complete file intact. The temporary journal is removed after recovery and excluded from Git.
- Migration tests preserve every fixture date, roster row, price, and source observation, remove the former evidence file only after saving, and verify rerunning migration changes nothing.
- Browser tests exercise missing and malformed catalog/history responses, Retry buttons, page reload recovery, and invalid catalog structure. Failed catalog hydration now clears its cached response so Retry can recover. The archive rejects HTTP errors rather than showing an empty history.
- Model-release and benchmark-version tests prevent a Muse Spark 1.3 fill from affecting 1.2, GPQA Diamond from filling GPQA, or DeepSWE 1.1 from filling DeepSWE.

## Preconditions

`scripts/preconditions.py` provides explicit caller contracts on application functions and public/protected class methods. Contracts validate argument binding, types, optional values, finite numbers, positive sizes/budgets where required, dates, and accepted enum values before function bodies run. Permissive parsing helpers retain their documented missing-value behavior. No-argument entry points reject unexpected arguments; they do not invent input requirements.

`tests/test_app_preconditions.py` inventories application declarations and requires a contract on each. Each function/method gets a positive and negative contract test, with negative cases for every constrained argument. Positive contract tests intentionally avoid executing live network/publishing operations; the existing unit tests and new integration tests cover execution after accepted inputs. Thus contract coverage is not a claim of complete behavioral branch coverage. The contract mechanism itself is tested for default arguments, duplicate arguments, invalid declarations, and rejection before side effects.

`js/preconditions.js` checks browser-action inputs. All named page functions declare contracts. Browser tests verify positive contract cases and invoke each action with invalid inputs. Archive controls also check that indexes refer to existing snapshots. DOM event callbacks remain supported.

Evidence validation remains a separate semantic gate: a well-typed finding still needs the exact model/benchmark identity, an accepted source, and valid historical applicability. Invalid evidence cannot overwrite the shared catalog.

## Performance verification

A read-only full-history replay of 234 snapshots took about 14.0 seconds before this work and 8.4 seconds after indexing evidence by model, caching benchmark-name canonicalization, and avoiding expensive argument binding in the common positional-call path. Both measurements used the same retained data; all recalculated output was identical. These are local measurements, not CI timing thresholds.

Regression tests require building the evidence index once per replay and verify repeatable outputs. The graph now uses already-calculated roster scores directly; a browser regression test verifies it does not hydrate the entire benchmark catalog when rendering the trend.
