# ShopMate business tasks and evaluation records

Before execution, stop the manually started API on port 8101 while preserving ShopMate data and Java services. The driver supports fixed local addresses only and owns its production-API subprocess. Before each task reset, it checks for quiescence and recovers pending prepare operations in the current user's old conversations, then stops the API, resets, restarts, and signs in again. It does not kill processes by port or manage external APIs. Uncertain stopping, recovery, or write state retains the fixture and stops the batch. `--describe` neither starts processes nor reads runtime configuration.

The current default protocol is [`retail/development.json`](retail/development.json): 12 development tasks over the full retail catalog, with 90 Shanghai calendar days and synthetic CNY pricing. Migrated tasks, reference SQL, and baselines awaiting collection live separately in [`retail/`](retail/README.md); old scores are not reused, and `not_run` is not a pass. These 12 tasks preserve the original intents of business questions, historical prices, follow-ups, clarification, real approval, and cancellation. They are not a complete retail-tool acceptance suite or part of a future formal denominator.

```sh
uv run python scripts/run_tasks.py --describe
uv run python scripts/run_tasks.py --suite retail/development
uv run python scripts/run_tasks.py --suite evals/formal.json --describe
```

Before execution, the new driver reads each target SKU's prior price and version from that run's authoritative SQL and records relative version expectations. It does not assume a fixed 3→4 transition or automatically classify completed execution as business success. Price approval through the general change API still requires one unique match for `PRICE_UPDATE`, CNY, PREPARED, and the complete product/target-minor-unit set. Uncertain calls or state still stop execution and retain the fixture.

Original `development.json`, `formal.json`, `baseline.json`, `sql/`, and `records/` artifacts remain. The current driver permits old protocols only through `--describe` and rejects running them after a new retail reset. Reproducing an older experiment requires the two original repository commits in its record; runs on the new fixture cannot enter the old 78/90 or targeted 21/24.

## Historical seven-product protocols and results

The data, commands, R0, and fixed-version descriptions below belong to the old seven-product implementation and apply only to its recorded source versions. Use [retail/README.md](retail/README.md) for current retail execution.

`development.json` defines 12 development tasks; `formal.json` defines 30 formal business scenarios with 3 repetitions each. Planning status in JSON is not the latest run status; see the [record index](records/README.md). `baseline.json` defines a synthetic fixture, while raw database output determines business truth.

The latest complete historical batch scored **78/90** at ShopMate `9173037d6eb43d295f6ccb5876fa6284e882dfdb`. After changes, regression over 8 known failing scenarios scored **21/24** at `02d1bf0d0d1e4f5d71925f7db92ed3c4d9726b28`. Both used CityBuddy `69be167a3df030bf45795c49f444d6e7c24d0423`. The old subset's 13/24 and new subset's 21/24 are compared separately: they do not replace failures, establish a single-variable experiment, or form another complete 90-attempt result. The earlier 84/90 and development/debug records also remain separate.

## Data and grading definitions

The cutoff is fixed at `2026-09-05T00:00:00Z`, with UTC start-inclusive/end-exclusive windows. Revenue uses pre-refund amounts from successfully paid historical orders, not current prices. CNY and USD are calculated separately without currency conversion or addition. The fixture contains seven products, 42 complete transaction days, historical prices, successful standard-order payments, and payment-not-started/PENDING/FAILED samples; it has no seckill sale samples.

Manual grading checks actual visible text and cards, tool trajectories, reference SQL, draft receipts, and final database state. Key numbers, product sets, periods, currencies, business states, and readback must agree; natural-language wording need not match exactly. Integer minor units are authoritative for money. Percentage change uses the preceding period as denominator and is undefined for a zero base. Recovery within the original budget can pass; correct internal queries do not excuse an incorrect visible answer, and `executed` is not business PASS.

Permissions, unapproved writes, concurrent/repeated approval, version conflicts, lost responses, budgets, and SQL limits are covered by separate tests and excluded from the business completion-rate denominator. Proposal-only, approval, and cancellation steps in normal tasks are graded against the task request. Avoiding an incorrect write is not equivalent to completing the request.

## Execution

Start the isolated ShopMate environment, stop other tasks and product writes, and ensure the measured implementation is committed and source-clean. Record both full SHAs, fixture version, model, protocol, budget, and actual task list. Model settings come from existing local configuration; credentials are not written into run records.

```sh
uv run python scripts/run_tasks.py --suite development
uv run python scripts/run_tasks.py --suite formal
```

A complete formal run defaults to the task table's 3 repetitions. Options such as `--tasks S08,S11 --repetitions 1` define a separately counted regression subset. Do not change tasks, prompts, budgets, or provide corrective answers midway through a batch.

- The model receives only `common_context` and verbatim chat steps, not `evaluator`, reference SQL, or expected rankings/prices. Follow-ups retain the same conversation; background is injected only at the first chat.
- Chat uses the actual `/api/merchant/chat` endpoint and saves full SSE and terminal output. Prespecified follow-ups come from the task table, not manual correction on the model's behalf.
- Operator steps are pre-agreed real approvals. The driver obtains an actual draft ID from current conversation references and cards, then GETs the authoritative receipt. Currency, PREPARED state, and the complete product/target-minor-unit set must uniquely match; otherwise the task stops without approving an approximate or incorrect draft.
- After matching, the driver calls the real apply/discard API using the direct operator identity and same session, saving the request path and receipt. A chat claim of approval, model tool, or direct SQL price change cannot substitute for this step. Browser interaction is demonstrated separately.
- Each repetition uses a new sign-in and conversation. Bearer tokens remain in memory; login responses, Authorization headers, passwords, and database/proxy credentials are not saved.

## R0 for each repetition

R0 rebuilds this project's fixture rather than merely restoring prices. It operates only on the isolated `shopmate` Compose project, not CityBuddy's old default demo or benchmark database.

1. End all task writes and preserve previous SSE, receipts, and SQL. Read back uncertain writes rather than resetting over the incident state.
2. Run `python3 scripts/reset_fixture.py`. It waits for product Outbox publication and the designated consumer queue to drain. Unreadable state or timeout stops the process before formal tasks. The operator must prevent concurrent writes throughout reset.
3. Reuse CityBuddy's namespaced SQL to reconstruct seven products and 42 days of orders/payments/callbacks/ledgers, cleaning drafts and related Outbox records in that namespace while retaining identities. Do not clear entire databases, Redis, or broker queues.
4. Record the baseline through actual host reads and `products.sql`/`history.sql`/`scope.sql`, checking prices, versions, editability, and model-visible scope. Generation is recorded as this run's G0, not a required constant.
5. Reset does not delete old SQLite conversations in this historical protocol; each repetition creates a new session. Old draft references deleted by reset no longer name current business instances. Retain originals for diagnosis and do not use an old conversation for the next task. `local_runtime.py up` seeds only when products are absent and is not a complete R0.

## SQL and write outcomes

`evaluator.reference_sql` paths are relative to this directory. Reference SQL grades authoritative order/payment tables by order type/ID, subject, amount, currency, and successful status. The model uses only a restricted business-view account and cannot obtain evaluator privileges. Queries use UTC; draft/event SQL binds `@session_id` to the actual created session.

Read-only tasks also check for zero extra drafts/product events. Write scenarios save raw products, drafts, events, and history before and after every operator disposition and at the end. Prices remain unchanged before approval, and PREPARED `result`/`resolvedAt` remain empty. APPLIED or CANCELLED records have authoritative results and completion times; original items are not rewritten into a new intent. Each approved product moves from version 3→4 with one matching PRODUCT_PUBLICATION_CHANGED event; approving N products advances generation from G0 to G0+N. Cancellation emits no price event.

Unspecified products retain their state. Approved products change only the target price, version, and normal update time; stock, name, description, availability, currency, and publication status remain unchanged. `history.sql` output is identical before and after. Incorrect drafts, values, scope, missing readback, incomplete actions, and provider failures remain in the results and are not replaced with other tests or later successes.

## Record layout

Expanded local originals are in `evals/results/<run-id>/`; public records are in [records](records/README.md), with one `raw.tar.gz` per batch and readable `assessment.md`, `run.json`, and available statistics. The archive root is the run ID; task-relative paths in assessments resolve within that extracted directory.

Each batch records both actual full SHAs, as-of time, model/protocol/budget, tasks and repetitions, start/end times, sessions, raw SSE, analysis SQL, actual operator receipts, and before/after authoritative SQL. Business PASS, execution status, usage, and timing are reported separately. Complete runs report x/90 plus each scenario's 0/3–3/3; subsets use their actual denominator, and unexecuted tasks remain not_run. The fixed matrix supports development and regression, not claims of generalization to unseen tasks.
