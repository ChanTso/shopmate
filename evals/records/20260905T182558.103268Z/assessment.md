# Development evaluation assessment

CityBuddy commit: `69be167a3df030bf45795c49f444d6e7c24d0423`
ShopMate commit: `115b6a360ae502665f88063429e67230ab5ec37d`
Main/analysis model: `gpt-5.6-terra` / `gpt-5.6-terra`.

All 12 original development tasks executed once. Human review of user-visible text/cards and authoritative SQL gives **8 passed, 4 failed**. This is a development result, not the planned 90-run formal acceptance.

| Task | Business result | Evidence and reason |
|---|---|---|
| D01 | Fail | Correct CNY 2304/32/96 in the snapshot; model picks units, but snapshot enrichment removes it from the card and the final answer omits units. |
| D02 | Pass | CNY 1956→2304 (+348, +17.8%), 32→32 orders, correct windows and gross historical-payment basis; USD remains separate. |
| D03 | Pass | Requested cross-month product totals match SQL; zero CNY rows, currency and UTC scope are explicit. |
| D04 | Pass | Three CNY sold products: coffee70/1610/average23/current24, tea14/238/17/18, mug12/456/38/39. Unsold product prices and the separate USD product are visible. Comparison percentages are absent. |
| D05 | Pass | Follow-up keeps the same period/currency: coffee1610/14orders, tea238/14, mug456/4; sums reconcile. |
| D06 | Fail | Both windows and amounts are correct, but the same snapshot mapping drops the requested 96/48 units from visible cards and text. |
| D07 | Fail | Amount896→238 and units56→14 are correct; the analysis incorrectly copies the amount change of -73.4375% to units, whose change is -75%. Initial clarification contains suggestion chips but no explicit question. |
| D08 | Pass | Correct zero result, undefined zero-baseline percentage and no claim of an advertising cause. |
| D09 | Pass | Explicit operator approval changes only coffee2400→2500/version3→4, one matching event, APPLIED receipt. Final answer reads back current price/version and state. |
| D10 | Fail | Business write succeeds correctly: one three-item APPLIED draft, coffee2460/tea1830/mug3950, versions4 and three events. Requested final read-back has internal get_listing results but only suggestion chips visible, with no factual answer. |
| D11 | Pass | Old2500 draft remains CANCELLED; new2550 draft APPLIED; one coffee update/version4/event. Final answer distinguishes both drafts and reads current price. |
| D12 | Pass | Operator cancels1750 tea draft; tea remains1800/version3, generation unchanged, no product event; final answer confirms cancellation and unchanged price. |

For D01–D08, all product/history snapshots remain unchanged and no drafts/events were created. For D09–D12, the pre-operator snapshots still hold all R0 prices/version3; writes occur only after explicit operator steps. Untargeted product fields and all historical payment/order rows remain unchanged. D09/D10/D11 catalog generation advances by one/three/one, respectively; D12 remains unchanged.

The next revision addresses the snapshot units mapping, SQL-derived arithmetic and factual completion after a tool-only presentation round. Original prompts, reference SQL and task criteria remain unchanged. These failures and their raw SQL/SSE records are retained.
