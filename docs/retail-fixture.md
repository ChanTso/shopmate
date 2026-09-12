# Retail fixture and local reset

The fixture is defined by [`scripts/retail_fixture.py`](../scripts/retail_fixture.py) and initialized/reset through [`scripts/local_runtime.py`](../scripts/local_runtime.py). Its data version is `shopmate-retail-v1`, used only in the isolated `shopmate` Compose project. It requires CityBuddy PR #158 and the preceding V020–V025 retail, shopping, operations, and campaign migrations.

## Data scope and sources

| Data | Definition | Authoritative reads |
| --- | --- | --- |
| Catalog | 83 individual products and 4 families, totaling 87 catalog roots; the 4 families contain 21 variants, for 104 SKUs overall | `product` and `retail_product_family/metadata` |
| Current operations | Stock, low-stock thresholds, sale availability, cost, and content-quality observations | Product tables and `retail_product_operations` |
| Sales history | 90 complete Shanghai days before the reporting cutoff; fixed historical price versions and amounts, plus payment-not-started, PENDING, and FAILED samples | `standard_order`, `mock_payment_attempt/callback`, related ledgers, and original order records |
| Buyer and after-sales facts | Two demo buyers, preferences and membership, own orders, sourced fulfillment observations, and order issues; refund requests remain REQUESTED | `crm_profile`, `retail_order_fulfillment/issue`, `mock_refund` |
| Traffic and campaigns | 90 days of store-wide traffic observations, five original campaigns with their own attribution periods; C-203 revenue is unknown | `retail_store_traffic_daily`, `retail_campaign` |
| Policies and guides | Policies, buying guides, and delivery-estimate settings matching current business capabilities | `faq_source` populated through the real FAQ publication service, and `retail_fulfillment_config` |

Products, compact variant definitions, operations samples, buyers, order issues, and campaign observations come from [`vendor/commerce-agents/examples/retail/data`](../vendor/commerce-agents/examples/retail/data). Product images reuse existing repository files with [credits](../web/public/products/IMAGE-CREDITS.md) preserved. Products without images use the component's default presentation rather than a broken image address.

Amounts are converted into CNY demo amounts, not presented as an exchange-rate conversion. Historical orders use deterministic construction rules, and traffic samples form matching daily observations; records include their source and data version. These are not actual store sales or advertising results. Supplied campaign spend and attributed revenue retain their original numeric relationship and explicit periods; a second mock-sales dataset is not imported as another source of sales truth.

Shared family content lives only on the family. The current 21 variants have no additional display-content overrides: leaf metadata retains actual `option_values` and inherits parent content. Out-of-stock variants `AR-1606-KING-BLUSH` and `AR-1902-FULL` explicitly have zero stock. `AR-1207` has stock but is paused for sale, which is a different condition. Stock is the current demo snapshot; generating historical orders does not deduct it again.

Buyer orders retain historical unit prices and versions independently of today's product prices. Successfully paid orders have payment attempts, callbacks, and payment ledgers. A REQUESTED refund reserves the requested amount but does not mean funds have been returned. Fulfillment has explicit stages, times, and a `FIXTURE` source; PAID or an estimated delivery date does not imply shipment. Original samples missing dispatch times use a fixed demo handoff assumption whose time cannot exceed the observation time.

For the browser clients described by this fixture, the merchant entry point was `/` and the buyer entry point was `/buyer`; both reused these business facts. See the [buyer guide](BUYER.md) for shopping, confirmation, recovery, and memory management. New buyer real-model acceptance is recorded separately; this fixture description does not claim that it passed.

## Time and metric definitions

The fixed reporting cutoff is `2026-09-05T00:00:00+08:00`, with transactions covering 90 complete Shanghai days in `[2026-06-07, 2026-09-05)`. SQL connections and timestamps use UTC; local day/month boundaries are converted into their UTC instants before querying. A bare date means Shanghai midnight, while an explicit offset retains its actual instant.

The reporting cutoff is separate from the operation clock: `settings.as_of` reaches the backend only as `report_as_of`; each main-agent turn sees the actual Shanghai operation time. Relative report periods such as `last_14_days` use the cutoff, while promotion wording such as effective today uses the real operation date. New orders at the real current time do not enter an old fixed reporting window. Periods outside coverage cannot be treated as observed zero sales.

- Revenue is the pre-refund amount of successfully paid historical orders. It is not recalculated at today's price, and different currencies are not added together.
- Conversion is **paid SKU suborders / store-wide visits** over the same complete period, not distinct buyers or checkout headers. A missing daily traffic observation is not filled with zero. Categories and products have no separate traffic denominator.
- The proportion of orders with refund requests is not a successful-refund or physical-return rate. Cost and gross margin come from current operations observations; they are estimates, not accounting profit or an enforced price floor.
- Campaign budget is an editable plan field. Spend, attributed revenue, and observation periods remain separate. ROAS requires revenue and nonzero spend for the same campaign, period, and currency; unknown revenue is not shown as 0.
- `merchant_daily_sales` retains the old UTC daily aggregation. Shanghai day, week, and month analysis should aggregate `merchant_paid_orders.succeeded_at` using actual local boundaries rather than relabeling UTC days.

The analysis subagent has SELECT on only these six views. Base tables and the local read-only verification account are not exposed to the model:

1. `merchant_products`: current products and price-editability.
2. `merchant_paid_orders`: historical sales joined by order type, order ID, subject, amount, and payment state.
3. `merchant_daily_sales`: the old UTC daily aggregation.
4. `merchant_listing_facts`: current families, categories, stock, and cost/content observations.
5. `merchant_store_traffic_daily`: Shanghai daily visits and their sources.
6. `merchant_campaign_facts`: local plans and separate attribution observations.

## Changes and grading

All five draft types use CityBuddy's change ledger and actual operator-approval endpoint. Product operations expand to at most 25 SKUs. Within one transaction, Java checks the complete target set, snapshots, and versions, then writes business state, receipts, and applicable product events. The ordinary price tool's 20% limit is a host-tool constraint; this does not claim that Java enforces the same limit.

Promotion discounts must be positive and no greater than 50%; amounts in minor units are generated with HALF_UP rounding and frozen. Before the approval window, the draft stays PREPARED. First approval after expiry is rejected; approval within the window changes the actual price immediately. A date-only end includes that entire Shanghai day; an explicit timestamp excludes the ending instant. Expiry does not restore the price automatically. If a product later changes price or currency, reads retain both the original promotional price and the current price.

CAMPAIGN creates or updates local plans, budgets, audiences, and copy. New plans have no spend or revenue observations; editing an existing plan does not overwrite its attribution data. No external advertisement is published.

## Initialize and start normally

Run from the ShopMate root while the API is stopped:

```sh
uv sync --frozen
python3 scripts/local_runtime.py up
uv run uvicorn shopmate.app:create_app --factory --host 127.0.0.1 --port 8101
```

See the [runtime guide](RUNTIME.md#run-locally) for complete dependencies and frontend setup. `up` configures identity, migrations, and Java services, then uses traffic records for the current version to detect initialization. First initialization replaces the retained old seven-product demo scope with unified retail data. Subsequent normal starts preserve current prices, stock, plans, and conversations; they are not resets.

<a id="手工重置"></a>
## Manual reset

Reset deletes and rebuilds business records in the reserved scope. Save any SQL, SSE, drafts, and execution receipts that must be retained first. Read back uncertain writes before resetting; do not overwrite an unresolved incident's state.

1. Stop model tasks, integration tests, and other writes. Press Ctrl-C in the API terminal to stop uvicorn. Keep this project's Java and data services running so product events can drain. Stop a non-default API port yourself as well; the script refuses maintenance while default port 8101 still listens.
2. Run from the ShopMate root:

   ```sh
   python3 scripts/reset_fixture.py
   ```

3. The script confirms product Outbox publication and no pending/in-flight work for the designated RocketMQ consumer, then stops Java writes. It rebuilds SQL data, handles SQLite fixture conversations, publishes policies through the actual FAQ service, and restarts Java. Unreadable drain state or a timeout stops the procedure.
4. After reset succeeds, restart the API, sign in, and create a new conversation:

   ```sh
   uv run uvicorn shopmate.app:create_app --factory --host 127.0.0.1 --port 8101
   ```

Cleanup uses fixed product IDs, explicit fixture subjects, and versions, with exact binary subject comparison. Non-fixture orders, carts, or promotion references to these products, other operators' product-change drafts, and other operators' updates to fixture campaigns block maintenance. Cleanup first removes dependent promotions, checkouts, action receipts, refunds, and payments, followed by orders, metadata, products, and families. It does not clear entire databases, Redis, or message queues, or disable foreign keys.

When `.run/sessions.sqlite3` exists, the script uses SQLite's backup API to write `.run/backups/sessions-<timestamp>.sqlite3`, then removes the relevant fixture subjects' conversations, draft references, and pending prepare intents so stale conversations cannot reuse deleted business instances. Other conversations are outside this cleanup scope.

**The automatic backup covers SQLite only, not the MySQL business database.** SQL and SQLite do not share a transaction: conversation backup/cleanup and policy publication follow SQL reconstruction. If a later step fails, maintenance fails and the host remains unready. Inspect ignored `.run/runtime.log` and the actual database state before deciding how to recover or rerun; partial success is not a complete reset.

`.run/` contains local credentials, conversations, and backups and remains ignored. To retain previous MySQL business facts, save the necessary database backup or authoritative SQL output before reset; a conversation copy cannot restore transaction state.

## Relationship to older records

The old `evals/` tasks and [public historical results](../evals/records/README.md) use seven products, 42 UTC days, and different source versions. Running against this fixture does not reproduce the same score. The old 78/90, targeted 21/24, and [browser screenshots](demo-20260906/README.md) retain their original versions and denominators. This description does not claim that newer real-model or end-to-end acceptance has passed.

New acceptance should first fix this dataset and reporting definition, then grade reference SQL, actual visible output, and Java write outcomes. Permissions, unapproved writes, version conflicts, concurrency/repeated approval, stopping, and recovery are checked separately; execution completion is not business success.

## Chinese demo catalog and product images

Chinese product copy is maintained in `scripts/data/demo-catalog-zh-CN.json` without rewriting the upstream catalog or historical order snapshots. Preview and apply it with:

```sh
uv run python scripts/localize_demo_catalog.py
uv run python scripts/localize_demo_catalog.py --apply
```

The script reads operator credentials from existing ignored storage, creates `LISTING_UPDATE` drafts, then obtains operator approval. It updates current product titles and descriptions while preserving prices, stock, historical amounts, and original snapshots; existing merchant titles that differ from initialization remain unchanged. `--product AR-1001` limits the operation to one item. Chinese copy can be explicitly reapplied after resetting the original fixture; normal startup does not overwrite operations changes.

Buyers and merchants share the same SKU assets in `web/public/products/`. An image explicitly supplied by the authoritative catalog takes precedence; a display path is added only when no image was specified and the corresponding asset exists. Native iOS image sets are format-converted copies for thumbnails. See that directory's `IMAGE-CREDITS.md` for sources and original product-concept visuals.
