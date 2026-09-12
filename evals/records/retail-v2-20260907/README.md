# Final business acceptance after retail fact-expression fixes

CityBuddy: `76c293178923bf78e747ab1ba9590e6348108ad8`; ShopMate: `4020ff93f4797e2ae3142e8a4123442d3d8693b7`. The run used real `gpt-5.6-terra` on 2026-09-07, with default main, analysis, and memory configuration. Chat Completions adapted the main loop, Responses performed search, and an isolated Docker sandbox executed Python. Model aliases are not immutable snapshots.

Under `evals/retail/acceptance-v2.md`, 18 known scenarios produced 30 attempts: **24 business passes, 3 business failures, 3 provider failures, and 0 unrun attempts**. Of the 27 attempts that completed the business workflow, 24 passed; the full registered denominator remains 30. This is not an unseen-task generalization rate or proof of stable success for every scenario.

Main behavior and scoring stayed unchanged throughout the batch. Every attempt used the original retail-v1 isolated R0, actual business APIs, and authoritative SQL, with 87 catalog roots / 104 tradable SKUs / 90 complete Shanghai days / synthetic CNY data. Each chat turn allowed at most 16 shared model calls / 300 seconds and 12 main-tool rounds; failures received no extra budget. Four pre-merge development regressions on D04/D05/R05/R07 all passed and remain separate from the denominator below.

| Task | Repetition outcomes | Review focus |
|---|---|---|
| D02 Cross-period business comparison | PASS | Amounts, SKU suborders, change rates, Shanghai half-open intervals |
| D04 Historical prices and complete catalog | FAIL / FAIL / provider failure | Date boundaries; current prices must not be presented as prices at the historical report cutoff |
| D05 Aggregation follow-up | Provider failure / provider failure / PASS | All 104 SKUs reconcile to 4564150 minor units and 239 suborders |
| D07 Missing-date clarification | PASS | Clarify first, then query the specified products and period |
| D08 Zero sales | PASS | Growth with a zero denominator remains unknown; no invented advertising causality |
| D10 Batch price change | PASS | All 3 SKUs change after approval, with matching versions and 3 published events |
| D11 Replace a draft | PASS | Cancel the old draft, approve the new draft, and apply only the new price |
| R01 Buyer shopping, payment, and refund | PASS / PASS / PASS | Compare → add to cart → confirm checkout → simulated payment → confirm a 100-minor-unit refund; repeated confirmation returns the original receipt |
| R02 Owned orders and policies | FAIL | Correct order isolation and fulfillment, but omitted account preferences, membership, and order-modification guidance |
| R03 Product-family maintenance | PASS | Change only family material, with matching versions and 8 published events for 8 leaf SKUs |
| R04 Restock and resume sales | PASS | Add 5 units while keeping sales paused, then resume separately without another stock increment |
| R05 Campaign-copy approval | PASS / PASS / PASS | Change only name/copy; budget, spend, unknown revenue, and observation window remain unchanged |
| R06 Promotion through actual purchase | PASS / PASS / PASS | CNY 27 → 24.30; buyer pays that price and merchant reads the new same-day order |
| R07 SQL/Python analysis | PASS / PASS / PASS | Complete 28-day SQL → real Python; amount, population standard deviation, and peak date agree |
| B01 Budget shopping plan | PASS | CNY 100 covers lighting, storage, and floor activities, without early cart writes |
| B02 Cart additions and changes | PASS | ADD → SET/REMOVE; final cart contains only 1 specified desk lamp at CNY 22 |
| S01 Brand care search | PASS | Actual public sources for two brands; preserve differences in applicability without changing store product facts |
| S02 Official promotion guidance | PASS | Separate Google's conditions from store approval and external publishing; no writes |

The three business failures were D04's first repetition, which described September 4 as the exclusive end in an additional card; its second, which described current catalog prices as prices at the report cutoff; and R02, which omitted requested content. Correct SQL does not offset incorrect visible answers. All other write tasks were checked before approval, after approval, and against final SQL. No unapproved writes, unauthorized acceptance, duplicate charges, or unresolved write outcomes were found in those attempts.

The three provider failures were HTTP 500 on model call 7 of D04's third repetition and HTTP 429 on the first call of D05's first two repetitions. A subsequent minimal diagnostic reported `model_cooldown`. After the proxy recovered, a minimal Terra request returned 200, and only unrun tasks resumed. The three failures were retained without replacement or deletion. Model, code, tools, and budget did not change within this batch.

## Raw records and rerun entry point

Raw SSE, requests/receipts, SQL, and monotonic timings are retained in the local `evals/results/` directories below. Credentials continue to come from the existing private configuration and are not included here. The runner's `executed` means workflow completion only; business scoring uses actual responses/cards and SQL.

| Directory | Contents |
|---|---|
| `20260907T121748.529791Z` | D02/D07/D08/D10/D11 |
| `20260907T122551.504138Z` | All three D04 attempts and the first two D05 attempts; batch stopped after provider failures |
| `20260907T133302.167578Z` | Only the remaining D05 attempt; directory r1 corresponds to registered r3 |
| `20260907T133523.832944Z` | R02/R03/R04 |
| `20260907T134052.520821Z` | R01/R05/R06/R07, three repetitions each |
| `20260907T140405.930901Z` | B01/B02 |
| `20260907T140658.736057Z` | S01/S02 |

Example entry point: `uv run python scripts/run_tasks.py --suite retail/full-development --tasks R01,R05,R06,R07 --repetitions 3`; use the registration for the other suites. Runs reset isolated demo data and must not overlap other writes, integration tests, or capacity measurements. Reruns create new records without overwriting this batch. The old 54-attempt and targeted runs retain their original versions and are not combined into a new score.

## User waiting time and model usage

The 30 task attempts contain 61 chat turns: 58 `turn_complete` and 3 `error`. Raw monotonic timing gives terminal-event waiting time of **30.54 seconds p50**, **87.08 seconds p95**, and **159.65 seconds maximum**, including failures. Text or a complete UI event appeared in 59 turns; time to the first such event was **16.00 seconds p50** and **68.77 seconds p95**. The other 2 first-call failures had no such event and are not filled with zero. p95 uses nearest rank; these small samples were not extrapolated to p99 or concurrent capacity.

These timings measure chat waiting from request dispatch to actual events/terminal state, excluding human thinking and clicks. The first UI may be a suggestion card and is not always the first useful business result. A complete task with multiple turns, approvals, and payment is not a single chat.

There were 352 model calls, 348 with returned usage; usage was incomplete for 4 turns. Reported input was 2,724,351 tokens, including 2,042,240 cache-read tokens; output was 66,878 tokens. Cache reads are part of input tokens, not a request hit rate. Missing usage and unreported cache creation are not filled with zero, and these counts do not establish billed cost or savings.

In R07, the first two repetitions each recovered from an initial Python failure within the original budget; Python succeeded on the first attempt in the third repetition. All three required SQL corrections, so this is not first-attempt perfection. S01 made 2 Responses search requests, each reporting 1 search; S02 made 1 Responses search request reporting 2 searches. Search, analysis, and memory calls are included in the usage above.

## Search-source review

S01's key claims were checked against [LILYSILK's general cleaning page](https://blog.lilysilk.com/how-to-clean-silk/amp/), [its fitted-sheet care page](https://blog.lilysilk.com/how-to-care-for-your-silk-fitted-sheet-for-longer-usage/amp/), and [Slip's care page](https://www.slip.com/pages/care). The model distinguished machine-washing and temperature conditions for different products and did not invent a manufacturer care promise for store product AR-1606.

S02 was checked against Google's [promotion policies](https://support.google.com/merchants/answer/2877565?hl=en), [display guidance](https://support.google.com/merchants/answer/13507894?hl=en), [data specification](https://support.google.com/merchants/answer/2906014?hl=en), and [display dates](https://support.google.com/merchants/answer/13861050?hl=en). The answer retained eligibility, market, review, and data-mapping conditions without equating store approval with successful publication on Google. Sources were checked on 2026-09-07 and may change later.

Existing evidence for memory, conversation concurrency, stop/payment recovery, sandboxing, and authorization boundaries retains its own source versions and is not counted again here. The new buyer-ownership ablation remains 0/3 with the guard disabled and 0/3 enabled, with neither arm reaching a sensitive write. The historical customer-service result of 55/300 → 0/300 does not represent ShopMate's new workflow.
