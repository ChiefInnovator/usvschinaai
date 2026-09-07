# Historical benchmark gap research — September 6, 2026

Checked all 90 retained models against 94 sources using the existing refresh workflow and all 19 configured benchmarks. The refresh found 765 observations but no new distinct evidence. Additional research inspected eight official publisher model repositories and the dated GPT-5.2 launch tables.

Accepted 261 dated observations covering 19 retained models. Official Hugging Face README revisions are pinned by commit, and their timestamps establish observation availability. Comparison columns retain the publishing vendor as their source; they are not represented as independent benchmark-operator measurements. Findings, configurations and citations are stored in `data/historical_gap_research_findings.json` and replayable evidence in `data/historical_benchmark_evidence.json`.

## Result

- Reviewed and rescored all 233 historical snapshots; benchmark values changed in 215.
- Filled 3,526 previously missing benchmark cells and improved 1,747 existing cells using higher date-applicable results.
- BrowseComp: 352 missing cells filled and 564 existing cells improved.
- Fully resolved 49 model–benchmark gap pairs; 1,028 pairs still have at least one unresolved historical day.
- Preserved every snapshot timestamp and model list, benchmark allocations, and the existing webpage layout. Regenerated chart inputs and image exports.

The rescore command's `cellsFilled` total includes both new values and upgrades; the accompanying JSON report separates them by comparing actual before/after benchmark cells.

## Boundaries and remaining gaps

Results apply only from their verified publication/observation date and the model/benchmark availability boundary. Effort does not restrict selection. No result was transferred between different model releases, Terminal-Bench versions, SWE-bench variants, or FrontierMath versions. Tool-enabled/text-only HLE and HLE-Verified were not treated as the selected full HLE. Unqualified GPQA rows in the Qwen card were omitted from this research because the subset is ambiguous. Unresolved gaps remain missing evidence and contribute zero under the existing scoring formula.

The largest remaining gaps include benchmarks unavailable during early snapshots and results with no date-applicable publication. This was a bounded research pass, not proof that every unpublished or undiscovered result is absent. See `data/historical_benchmark_gaps.json` for each remaining pair and date range.

Validation: 207 tests passed, one skipped; model data validation reported zero errors and warnings. Historical timestamp/model membership comparison passed. Changes remain local.
