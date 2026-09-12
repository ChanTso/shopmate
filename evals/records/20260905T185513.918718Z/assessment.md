# First full business acceptance: 84/90

CityBuddy: `69be167a3df030bf45795c49f444d6e7c24d0423`<br>
ShopMate: `0db5538c1d46bf440542c6159323e2bcd2ec755a`<br>
Data cutoff: `2026-09-05T00:00:00Z`; fixture source is the CityBuddy commit above.<br>
Both main and analysis models used `gpt-5.6-terra` through the CLIPROXY Chat Completions adapter. Each chat turn shared 16 model calls and a 300-second deadline.

Each of 30 fixed business scenarios ran 3 times. Every attempt began from R0 and a new conversation, retaining multi-turn and operator steps within the scenario. All 90 attempts finished, with no unrun attempts or executor interruptions. Under the frozen task statements, actual visible answers, reference SQL, and final write states, business completion was **84/90 (93.33%)**. `executed` is not a business-pass marker.

The batch ran from 18:55 to 20:38 UTC on 2026-09-05. Raw SSE, model/tool records, operator receipts, and SQL from each stage are retained, including failures and tool self-correction. Task definitions and reference SQL are in `evals/formal.json` and `evals/sql/` at the same commit.

## Per-scenario results

| Scenario | r1 | r2 | r3 | Completed |
|---|---|---|---|---|
| S01 | PASS | PASS | PASS | 3/3 |
| S02 | PASS | PASS | PASS | 3/3 |
| S03 | PASS | PASS | FAIL | 2/3 |
| S04 | PASS | PASS | PASS | 3/3 |
| S05 | PASS | PASS | PASS | 3/3 |
| S06 | PASS | PASS | PASS | 3/3 |
| S07 | PASS | PASS | PASS | 3/3 |
| S08 | FAIL | FAIL | FAIL | 0/3 |
| S09 | PASS | PASS | PASS | 3/3 |
| S10 | PASS | PASS | PASS | 3/3 |
| S11 | FAIL | FAIL | PASS | 1/3 |
| S12 | PASS | PASS | PASS | 3/3 |
| S13 | PASS | PASS | PASS | 3/3 |
| S14 | PASS | PASS | PASS | 3/3 |
| S15 | PASS | PASS | PASS | 3/3 |
| S16 | PASS | PASS | PASS | 3/3 |
| S17 | PASS | PASS | PASS | 3/3 |
| S18 | PASS | PASS | PASS | 3/3 |
| S19 | PASS | PASS | PASS | 3/3 |
| S20 | PASS | PASS | PASS | 3/3 |
| S21 | PASS | PASS | PASS | 3/3 |
| S22 | PASS | PASS | PASS | 3/3 |
| S23 | PASS | PASS | PASS | 3/3 |
| S24 | PASS | PASS | PASS | 3/3 |
| S25 | PASS | PASS | PASS | 3/3 |
| S26 | PASS | PASS | PASS | 3/3 |
| S27 | PASS | PASS | PASS | 3/3 |
| S28 | PASS | PASS | PASS | 3/3 |
| S29 | PASS | PASS | PASS | 3/3 |
| S30 | PASS | PASS | PASS | 3/3 |


## Six business failures

- **S03-r3: unsupported business explanation.** Historical average sale price and current selling price were numerically correct, but the visible answer asserted historical discounts, promotions, or bundled sales. The data establishes different price definitions, not that a promotion occurred. A later “原因无法确定” (verbatim model text: cause uncertain) did not retract those specific assertions.
- **S08-r1/r2/r3: expanded analysis scope.** The question specified the canvas tote, and the follow-up comparison should have stayed on that product. Main-agent delegation expanded to the whole catalog, and the final answer did not fully deliver the tote's zero sales in both periods and inapplicable growth rate. r1 also exceeded the tool's brief-length contract; silent runtime truncation dropped conditions. The other two briefs were not truncated but had already selected the wrong scope.
- **S11-r1/r2: no ranking results after query failure.** Query errors were generalized as “数据库不可用或拒绝” (verbatim model text: database unavailable or rejected), and the requested quantity/revenue rankings were missing. A separate read-only replay of r1's first failed SQL returned MySQL 1690 from unsigned subtraction underflow; a signed comparison query returned negative values. That replay was not a formal attempt. r3 rewrote its query within the original budget and completed the task, passing under the original rules.

Read-only tasks did not change products, drafts, or transaction history. In all actual approval, cancellation, and proposal-only scenarios, products, versions, final draft states, events, and historical invariants matched the original definitions. These boundary checks were not counted as extra completions.

## Retained process observations

- Intermediate SQL in S04-r3 double-counted an aggregate before the model corrected it ahead of visible final delivery. S13-r2's second analysis added a product omitted by the first. Both completed within budget.
- S06's dates and values were correct, but “均匀/不集中” (verbatim model text: uniform/not concentrated) applied only to the four days with sales, not the entire fourteen-day window. The original task defined no concentration threshold, so the wording concern was retained without adding a threshold retrospectively to change the verdict.
- S14-r3 correctly reported date contributions, but described incidental fluctuation too strongly; this does not establish statistical significance or definite causality.
- S22-r1 and S23-r2 called the presentation tool without available metrics. The errors produced no incorrect cards; subsequent visible answers and actual business outcomes were complete and correct. Tool errors remain recorded without treating recovered intermediate failures as separate task failures.

## Actual calls and elapsed time

Across 147 chat turns, 832 model calls were recorded: 663 main-loop and 169 analysis-loop calls. All reported input/output usage. Total input was **5,027,066 tokens** and output **191,747 tokens**. Each call was counted once; input includes cache reads, without adding runtime aggregates again.

- Scenario executor wall time: median 62.770 seconds, p95 124.340 seconds, range 22.716–147.925 seconds. This includes login, reset, SQL checks, and scripted operator steps, not pure model latency.
- Per-chat server duration: median 26.749 seconds, p95 103.109 seconds, range 7.676–143.313 seconds. This includes the turn's main/analysis calls and tools, excluding actual human approval waiting.
- This batch did not retain cache-field presence. A zero cache-read count cannot distinguish an explicit proxy report from an adapter default; zero cache writes were SDK placeholders. Neither a cache hit rate nor benefits can be inferred.
- SSE lacks per-event receive timestamps, so time to the first useful result cannot be reconstructed. Without proxy rates or invoices, token counts are not converted to actual monetary cost.

Percentiles use linear interpolation after sorting and include passing and failing tasks. They describe this local run, not capacity or an online SLO. See `statistics.json` for details; full originals are retained in this directory.

## Subsequent versions

The follow-up work identified by this batch covered general analysis-scope rules, complete-brief validation, actionable SQL error feedback, and cache-field availability flags. Regressions and full runs after those fixes are saved independently, without overwriting this batch or combining successful samples across versions. The fixed task matrix serves business acceptance and regression; it is not an unseen public benchmark or a generalization estimate.
