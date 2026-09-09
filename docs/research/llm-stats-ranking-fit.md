# Requested llm-stats ranking: weight feasibility

On September 6, 2026, the user supplied a screenshot specifying an order for
15 models and requested benchmark weights that reproduce it as Avg IQ.
No benchmark weights, model scores, historical snapshots or UI were changed
as part of this feasibility check.

## Inputs and method

The audit uses the twelve configured components, each model's latest retained
row, and non-excluded evidence applicable on September 6. Missing results are
zero. Models no longer in the current cohort are included only for this diagnostic;
this does not add them to any current or historical roster. The screenshot also
includes the unreleased Claude Mythos Preview.

For each model, Avg IQ is `sum(weight[j] * benchmarkScore[j])`. Weights are
nonnegative and total 1. A linear program maximizes a common adjacent margin
`t`, subject to `score(model[i]) - score(model[i+1]) >= t` for the screenshot
order. This tests every possible real-valued nonnegative weight combination,
including zero weights. Requiring all twelve weights to remain positive cannot
make an infeasible solution feasible.

The optimum margin is **-4.1977902584 points**. Therefore at least one required
adjacent ordering is reversed by at least that amount under every valid set of
weights. Even allowing ties cannot reproduce the entire order. Removing Mythos
Preview still gives a negative optimum margin: **-3.6149217037 points**.
The first five alone are feasible, with a maximum common margin of only
**0.1310344828 points**; that does not satisfy the full request.

One irreducible conflicting set of requested comparisons is:

- Claude Mythos Preview above Claude Fable 5.
- GLM-5.3 above DeepSeek-V4-Pro-0813.
- DeepSeek-V4-Pro-0813 above Qwen3.8 Max.
- Qwen3.8 Max above GPT-5.6 Terra.
- GPT-5.6 Terra above Claude Opus 4.8.

The companion JSON contains the complete score matrix, target order and diagnostic
minimax solution. Its weights are **not proposed production weights**: that
solution gives nine benchmarks zero weight and still fails the target order.

## Reproduction

Using SciPy's HiGHS linear-program solver, with `X` equal to the JSON score matrix:

```python
A = numpy.column_stack([X[1:] - X[:-1], numpy.ones(len(X) - 1)])
result = scipy.optimize.linprog(
    [0] * 12 + [-1],
    A_ub=A, b_ub=numpy.zeros(len(X) - 1),
    A_eq=[[1] * 12 + [0]], b_eq=[1],
    bounds=[(0, None)] * 12 + [(None, None)], method="highs",
)
maximum_margin = -result.fun
```

Rescoring everything requires choosing a different achievable objective or
changing the scoring formula. A fit to the screenshot should be labeled as
calibrated to that external ordering, rather than independently selected
capability weights. Historical dates, model membership and source scores must
remain intact whichever approach is selected.
