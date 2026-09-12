# Frozen-version business acceptance: 78/90

CityBuddy: `69be167a3df030bf45795c49f444d6e7c24d0423`<br>
ShopMate: `9173037d6eb43d295f6ccb5876fa6284e882dfdb`<br>
Result directory: `evals/results/20260905T210851.446894Z`.<br>
Data cutoff: `2026-09-05T00:00:00Z`, UTC; fixture source is the CityBuddy commit above.<br>
Both main and analysis models used `gpt-5.6-terra` through the CLIPROXY Chat Completions adapter. Main/analysis calls shared 16 model calls and a 300-second deadline per chat turn. The main loop also had an 8-tool-round limit; budgets were unchanged.

Each of 30 fixed business scenarios ran 3 times. Every attempt started from R0 and a new conversation, retaining multi-turn dialogue and real operator steps within the scenario. Judgment used frozen task statements, actual user-visible answers/cards, reference SQL, approval receipts, and final write states. An internal error could pass if corrected within the original budget and the goal was completed. `executed` is not a business-pass marker. Failures retain their original denominator; hidden tool results do not fill gaps in the user answer, and successes from old batches or targeted regressions are not combined here.

**All 90 attempts were assessed: 78 PASS, 12 FAIL, for business completion of 78/90 (86.67%).** Execution status separately recorded 88 executed and 2 failed (S20-r3, S30-r1). Both stopped subsequent steps because no matching approvable draft existed, without attempting operator writes; neither was classified as a provider failure. Business failures also include normally executed attempts that did not meet the task, all retained in the denominator of 90.

The batch ended at `2026-09-05T23:02:57.800425+00:00` and shut down normally. The configuration and results below belong to this frozen version with 8 main-tool rounds. Later limit changes are not retroactively applied to this evidence.

Raw SSE, model/tool records, operator receipts, and SQL from each stage are retained in this directory. Task definitions and reference SQL are in `evals/formal.json` and `evals/sql/` at the same commit. Raw paths below are relative to this result directory.

## Per-scenario results

| Scenario | r1 | r2 | r3 | Completed |
|---|---|---|---|---|
| S01 | PASS | PASS | PASS | 3/3 |
| S02 | PASS | PASS | FAIL | 2/3 |
| S03 | PASS | PASS | PASS | 3/3 |
| S04 | PASS | PASS | PASS | 3/3 |
| S05 | PASS | PASS | PASS | 3/3 |
| S06 | FAIL | PASS | PASS | 2/3 |
| S07 | FAIL | PASS | FAIL | 1/3 |
| S08 | PASS | PASS | PASS | 3/3 |
| S09 | PASS | PASS | PASS | 3/3 |
| S10 | PASS | PASS | PASS | 3/3 |
| S11 | PASS | PASS | PASS | 3/3 |
| S12 | PASS | PASS | FAIL | 2/3 |
| S13 | PASS | PASS | FAIL | 2/3 |
| S14 | PASS | PASS | FAIL | 2/3 |
| S15 | PASS | PASS | PASS | 3/3 |
| S16 | PASS | PASS | PASS | 3/3 |
| S17 | FAIL | PASS | FAIL | 1/3 |
| S18 | PASS | PASS | PASS | 3/3 |
| S19 | PASS | PASS | PASS | 3/3 |
| S20 | PASS | PASS | FAIL | 2/3 |
| S21 | PASS | PASS | PASS | 3/3 |
| S22 | PASS | PASS | PASS | 3/3 |
| S23 | PASS | PASS | PASS | 3/3 |
| S24 | PASS | PASS | PASS | 3/3 |
| S25 | PASS | PASS | PASS | 3/3 |
| S26 | PASS | PASS | PASS | 3/3 |
| S27 | PASS | PASS | PASS | 3/3 |
| S28 | PASS | PASS | PASS | 3/3 |
| S29 | PASS | PASS | PASS | 3/3 |
| S30 | FAIL | FAIL | PASS | 1/3 |


## Twelve business failures

| Attempt | Business reason | Raw paths |
|---|---|---|
| S02-r3 | load_skill plus 7 serial catalog queries exhausted the 8 main-tool rounds. The ninth call was forced to return text only, before querying revenue or delivering the top three products, amounts, and shares. The shared 16-call / 300-second budget was not exhausted; this was not a confirmed provider or database failure. | `S02-r3/step-01.sse`, `S02-r3/step-01-terminal.json`, `S02-r3/sql/after/S02.jsonl` |
| S06-r1 | Described the actual 14-day half-open interval as 15 days and showed a sales-day coverage of 4/15 = 26.67%, instead of 4/14 ≈ 28.57%. Correct dates and amounts for the four days do not offset the wrong denominator and derived value. | `S06-r1/saved-session.json`, `S06-r1/step-01-terminal.json`, `S06-r1/sql/after/S06.jsonl` |
| S07-r1 | Two bare sales references both resolved to the CNY snapshot 2304 / +17.79%, while one description labeled it USD 280 / +11.11%, creating a visible amount/currency/growth contradiction. Correct prose did not retract the incorrect card. | `S07-r1/step-01.sse`, `S07-r1/saved-session.json`, `S07-r1/sql/after/S07.jsonl` |
| S07-r3 | Prose gave the prior CNY amount as 2058 instead of 1956. Its current amount 2304, difference 348, and 17.79% were also incompatible with 2058. | `S07-r3/saved-session.json`, `S07-r3/step-01-terminal.json`, `S07-r3/sql/after/S07.jsonl` |
| S12-r3 | Repeated period-length validation failures exhausted the turn's analysis opportunities. No analysis queries ran, and the final answer omitted both periods' amounts, quantities, and product contributions. | `S12-r3/step-01.sse`, `S12-r3/step-01-terminal.json`, `S12-r3/saved-session.json` |
| S13-r3 | Covered only 6 products, including USD, without querying the limited edition. The final answer explicitly left that required CNY product unchecked, so the full scope was incomplete. | `S13-r3/step-01-terminal.json`, `S13-r3/saved-session.json`, `S13-r3/sql/after/S13.jsonl` |
| S14-r3 | Queried only 5 CNY products and explicitly excluded the limited edition from the CNY total. Queried products and the mug's date contributions were correct, but the required full scope was incomplete. | `S14-r3/step-01-terminal.json`, `S14-r3/saved-session.json`, `S14-r3/sql/after/S14.jsonl` |
| S17-r1 | The follow-up requested stock ≥ 50 within the preceding turn's products with sales. It added the zero-sales Canvas tote and showed 3 retained products; only coffee and tea qualified. | `S17-r1/step-02.sse`, `S17-r1/step-02-terminal.json`, `S17-r1/sql/after/S17.jsonl` |
| S17-r3 | As in r1, the second turn replaced the candidates with coffee/tea/tote. Both actual SQL and the visible card added the tote from outside the original sales set, without correction. | `S17-r3/step-02.sse`, `S17-r3/step-02-terminal.json`, `S17-r3/sql/after/S17.jsonl` |
| S20-r3 | load_skill plus 7 serial catalog reads exhausted the 8 main-tool rounds, forcing a text-only ending before analysis or draft creation. SQL confirmed 0 drafts, 0 events, and price still 2400. The missing match resulted from no draft being created, not an amount/currency mismatch; no operator write was attempted. | `S20-r3/step-01.sse`, `S20-r3/execution.json`, `S20-r3/sql/step-02-before/drafts.jsonl`, `S20-r3/sql/after/products.jsonl` |
| S30-r1 | load_skill, separate search/get/context calls for two products, and pending used 8 serial tool rounds, after which the main loop was forced to end in text. Neither draft was created. SQL confirmed 0 drafts, 0 events, and unchanged coffee/tea prices. Subsequent approvals could not run; no operator writes were attempted. | `S30-r1/step-01.sse`, `S30-r1/execution.json`, `S30-r1/sql/step-02-before/drafts.jsonl`, `S30-r1/sql/after/products.jsonl` |
| S30-r2 | Two independent drafts and coffee approval were correct. After an explicit request to cancel tea, the model only read products and pending changes without calling discard_change. Tea remained PREPARED, with result/resolved_at empty. Honestly stating that cancellation had not happened did not complete the task. | `S30-r2/step-03.sse`, `S30-r2/step-02-operator.json`, `S30-r2/sql/after/drafts.jsonl`, `S30-r2/sql/after/events.jsonl` |

The products omitted in S13/S14 happened to have zero sales in the fixture, but the evaluator cannot supply missing queries or conclusions. S02/S20/S30's main-tool-round limit is distinct from the total model-call allowance. A model's “无法读取” (verbatim model text: cannot read) claim was not treated as an actual data-source failure.

## Checked business terminal states and process observations

Read-only S01–S18 tasks did not change products, drafts, events, or payment history. Every approval actually attempted in S19, S20, and S21–S30 matched the specified draft. Prices remained unchanged while pending; after approval, product prices, versions, generation, and corresponding events matched receipts. No unapproved price changes, extra product changes, or payment-history contamination were observed.

S21–S29 reached their specified terminal states for single-product, same-batch multi-product, USD-price, pending-only, cancel/resubmit, and cancel-after-analysis cases. S30-r1 had zero drafts/writes. S30-r2 completed only coffee approval, leaving tea pending, so it failed. S30-r3 approved coffee, canceled tea, and read both back. These observations add no extra passes, do not substitute no incorrect writes for task completion, and do not replace independent authorization or concurrent-transaction tests.

- All three S11 attempts actually encountered MySQL 1690 and completed correct rankings after switching to SIGNED subtraction within the original budget. Intermediate errors were not separate task failures.
- One SQL query in S16-r3 executed successfully but inflated totals through repeated JOINs. Before visible delivery, the model reaggregated to the correct 96 units / CNY 2304 and passed the original goal.
- S02-r1 used a change-percentage style to display share, but adjacent explanations and the expanded card made the share meaning clear. An extra duplicate metric card in S20-r1 labeled 6 products plus an aggregate metric as “7款商品” (verbatim model text: 7 products), while the full analysis card, selection rationale, and approval outcome remained correct. These presentation-quality issues are retained; PASS does not mean perfect expression.
- Several attempts recovered from present_metrics references or brief-validation failures through actual queries, analysis cards, or final prose. Passing does not mean no tool errors, and a tool's is_error flag alone does not determine task failure.

## Actual calls and elapsed time

Across 145 chat turns, 928 model calls were recorded: 743 main-loop and 185 analysis-loop calls. All 928 explicitly reported input/output and cache-read fields. Counting each call once, total input was **5,954,918 tokens** and output **191,877 tokens**. Input already includes cache reads; runtime aggregates and cached tokens are not added again.

Explicitly reported cache reads totaled **4,727,296 tokens**, or **79.38%** of input (4,727,296 / 5,954,918). This is the share of reported input tokens read from cache, **not a request cache hit rate or demonstrated latency/cost benefit**. Cache creation was not measured. Without proxy rates or invoices, token counts are not converted to actual cost.

| Measurement | Samples | Median | p95 | Range |
|---|---|---|---|---|
| Scenario executor wall time | 90 attempts | 69.002554 seconds | 135.225086 seconds | 36.669278–206.127213 seconds |
| Per-chat server duration | 145 turns | 31.942 seconds | 98.746 seconds | 7.440–201.106 seconds |

Scenario wall time includes reset, SQL collection, and scripted operator approvals. Per-chat duration includes main/analysis models and tools, excluding actual human approval waiting. Neither measures first-token or first-useful-result latency; this batch retained no corresponding first-result timestamps. Percentiles use linear interpolation after sorting, include passes and failures, and describe this local run without capacity or online-SLO claims.

See `statistics.json` in this directory for detailed statistics. Raw per-call records, SSE, receipts, and SQL remain available. This is business acceptance/regression of 30 fixed scenarios repeated 3 times on one frozen version, not 90 distinct scenarios, an unseen public benchmark, or an estimate of online generalization. Later versions and targeted regressions are saved independently without overwriting this batch or combining successful samples.
