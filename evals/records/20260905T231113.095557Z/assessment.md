# Targeted regression after formal acceptance: 21/24

CityBuddy: `69be167a3df030bf45795c49f444d6e7c24d0423`<br>
ShopMate: `02d1bf0d0d1e4f5d71925f7db92ed3c4d9726b28`<br>
Result directory: `evals/results/20260905T231113.095557Z`.<br>
Data cutoff: `2026-09-05T00:00:00Z`, UTC; fixture source is the CityBuddy commit above.<br>
Both main and analysis models used `gpt-5.6-terra` through the CLIPROXY Chat Completions adapter.

The batch selected 8 business scenarios with known failures: S02, S07, S12, S13, S14, S17, S20, and S30, each repeated 3 times under the original `evals/formal.json` statements and success criteria. Every attempt started from independent R0 and a new conversation, retaining follow-ups, real operator approval, and readback within the scenario. Judgment used actual user-visible prose/cards, actual tool/analysis SQL, reference SQL, and authoritative business terminal states, allowing self-correction within budget. `executed` and business PASS were counted separately.

Compared with the preceding full batch at ShopMate `9173037d6eb43d295f6ccb5876fa6284e882dfdb`, this version revised metric references and set-delegation guidance in prompt/tool contracts and raised the main-tool-round limit from 8 to 12. Main/analysis models still shared at most 16 calls and a 300-second deadline per chat turn. Multiple factors changed together and model execution is stochastic, so this is a post-fix subset regression, **not a single-variable causal comparison or a new full 30 × 3 acceptance run**.

The batch started at UTC `2026-09-05T23:11:13.095965+00:00` and ended at `2026-09-05T23:50:13.064537+00:00`. The executor exited 0 and the run had no stop_reason. All 24 execution records were executed, with each reset completed. Normal execution does not mean all 24 passed the business task.

**All 24 attempts received independent business assessment: 21 PASS, 3 FAIL, for subset completion of 21/24 (87.50%).** S02/S07/S12/S13 scored 11/12; S14/S17/S20/S30 scored 10/12. All failures were normally executed attempts that did not fully complete the original task, retained in the denominator of 24.

## Per-scenario results

| Scenario | This r1 | This r2 | This r3 | This batch completed | Original 917 completed |
|---|---|---|---|---|---|
| S02 | PASS | PASS | PASS | 3/3 | 2/3 |
| S07 | PASS | PASS | PASS | 3/3 | 1/3 |
| S12 | PASS | PASS | PASS | 3/3 | 2/3 |
| S13 | PASS | FAIL | PASS | 2/3 | 2/3 |
| S14 | PASS | PASS | PASS | 3/3 | 2/3 |
| S17 | PASS | FAIL | PASS | 2/3 | 1/3 |
| S20 | PASS | PASS | PASS | 3/3 | 2/3 |
| S30 | PASS | PASS | FAIL | 2/3 | 1/3 |


In the original 917 full 90-attempt run, the same eight-scenario subset scored 13/24, compared with 21/24 here. The original full batch remains 78/90. Selection came from known failures, so this subset is not an estimate of unseen-task generalization. Its passes cannot replace old failures to rewrite 78/90. Raw paths below are relative to this result directory.

## Three business failures

| Attempt | Business reason | Raw paths |
|---|---|---|
| S13-r2 | The question in each of two run_analysis calls exceeded 300 characters. Although the third was shortened further, the two-analysis-calls-per-turn limit rejected it. No actual analysis SQL or amount/quantity card was produced; the final answer only asked the user to start again. Neither 12 main-tool rounds nor the shared 16-call / 300-second budget was exhausted; no provider or database unavailability was observed. | `S13-r2/step-01.sse`, `S13-r2/step-01-terminal.json`, `S13-r2/saved-session.json`, `S13-r2/sql/after/S13.jsonl` |
| S17-r2 | The follow-up requested stock ≥ 50 within the preceding turn's products with sales. The second turn's actual delegation, SQL, and visible result added the zero-sales Canvas tote (stock 80), retaining coffee/tea/tote instead of only coffee and tea. Values from real SQL do not compensate for an expanded analysis set. | `S17-r2/step-02.sse`, `S17-r2/step-02-terminal.json`, `S17-r2/saved-session.json`, `S17-r2/sql/after/S17.jsonl` |
| S30-r3 | Two independent drafts and approval of coffee only were completed. After the user explicitly requested tea cancellation, the model read products and pending work without calling discard_change. Tea remained PREPARED, with result/resolvedAt empty, and the model asked the user to act again. Honestly stating that cancellation remained undone did not complete it. | `S30-r3/step-03.sse`, `S30-r3/step-02-operator.json`, `S30-r3/saved-session.json`, `S30-r3/sql/after/drafts.jsonl`, `S30-r3/sql/after/events.jsonl` |

The failures were incomplete recovery from invalid parameters, expansion of the follow-up set, and an unexecuted explicit cancellation. No incorrect writes is not a substitute for business completion.

## Business terminal states and process observations

For every assessed read-only task, products, payment history, and scope remained unchanged from its own R0, with zero drafts and product events. All three S20 attempts correctly selected coffee as the adjustable CNY product with the greatest absolute historical revenue increase (+994 CNY), creating a pending draft at CNY 25.20, 5% above the current CNY 24. Prices stayed unchanged before approval. The real operator approved only that draft; afterward coffee was 2520 minor units / v4 with one matching product event and readback confirmation. Other products and historical payments were unchanged.

All three S30 attempts created independent coffee 2400 → 2480 and tea 1800 → 1850 drafts. Prices stayed unchanged before approval, and the operator approved coffee only. Afterward coffee was 2480 minor units / v4 with one matching product event; tea stayed 1800 minor units / v3. r1/r2 actually called discard_change for tea, leaving CANCELLED with result/resolvedAt present and original items retained. r3 did not cancel, leaving tea PREPARED and causing FAIL. Across all six approval tasks (three each for S20/S30), each had exactly one approved coffee product event. Other products and all 138 historical payment rows were preserved, without unapproved tea changes or incorrect coffee cancellation.

- All three S07 attempts showed CNY 1956 → 2304 and USD 252 → 280, with consistent currencies, amounts, differences, and rates. They did not reuse bare sales as two independent currency results.
- S12-r2's first card analyzed only six products, then actually queried Limited coffee set and presented a second zero-amount/quantity/contribution card. Final prose explicitly stated that both cards covered the original seven products. PASS followed complete delivery after actual recovery, not evaluator-supplied zeros for an omitted product.
- An intermediate calendar SQL query in S14-r2 returned an incorrect five-day count and product amounts. Later reaggregation corrected them; the final visible four-day window, amounts, and mug sale dates were correct. Recovery within the original budget was allowed under the established rules.
- S12-r1 recovered by rewriting a query after an actual MySQL 1051 error. Other attempts completed after brief-length or SQL-input validation errors. PASS does not mean no tool errors; S13-r2 shows that parameter failures can still block completion.
- S02-r2 still used a change-rate Pill for share, but adjacent note/findings explicitly identified revenue share. This presentation-quality observation remains. Several tasks redundantly queried USD or added sales-date explanations; this did not expand the original tasks or add successes.

These results do not replace independent authorization, approval-idempotency, or concurrent-transaction tests. No incorrect writes does not replace the required analysis or cancellation.

## Actual calls and elapsed time

Across 33 chat turns, 259 model calls were recorded: 172 main-loop and 87 analysis-loop calls. All 259 had completed call observations, HTTP 200, and explicit input/output/cache-read fields. Observation counts matched each turn's reported call count, with no unobserved calls. Per-call totals matched role/scenario aggregates: input **1,630,176 tokens**, output **79,221 tokens**. Input already includes cache reads; runtime totals and cached tokens are not added again.

Explicitly reported cache reads were **1,227,264 tokens**, or **75.28%** of input (1,227,264 / 1,630,176). This is the share of reported input tokens read from cache, **not a request cache hit rate, cost benefit, or latency improvement**. Cache creation was not measured; without proxy invoices or applicable rates, no actual cost is calculated.

| Measurement | Samples | Median | p95 | Range |
|---|---|---|---|---|
| Scenario executor wall time | 24 attempts | 86.329003 seconds | 150.640429 seconds | 53.260682–168.234622 seconds |
| Per-chat server duration | 33 turns | 63.774 seconds | 138.4748 seconds | 12.278–146.047 seconds |

Scenario wall time includes reset, SQL collection, and scripted operator approvals. Per-chat duration covers main/analysis models and tools, excluding actual human approval waiting. Neither is first-token or first-useful-result time. Percentiles use linear interpolation after sorting and include every pass/failure in this batch. They describe this local subset, not capacity or an online SLO, and are not compared with the different task distribution of the full 90-attempt run as a performance improvement.

See [statistics.json](statistics.json) for details aggregated from this batch's raw per-call records. Raw SSE, analysis SQL, operator requests/receipts, and business SQL at each stage remain in this directory. Business judgment, execution state, call usage, and elapsed time are recorded separately and do not substitute for one another.
