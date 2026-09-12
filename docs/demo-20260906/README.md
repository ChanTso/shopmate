# Business feature demonstration

The main demonstration ran around 00:00–00:05 UTC on 2026-09-06 in an isolated local environment with the fixed R0 transaction fixture. A real browser, model, Java APIs, and database completed analysis, drafting, manual approval, and recovery. This functional demonstration is separate from the formal 90 attempts and targeted 24-attempt regression.

- CityBuddy: `69be167a3df030bf45795c49f444d6e7c24d0423`
- Main demo ShopMate: `02d1bf0d0d1e4f5d71925f7db92ed3c4d9726b28`

Original SQL, conversations, and transport chunks are in [raw.tar.gz](raw.tar.gz), which extracts to `browser-demo/`. Paths described as inside the archive below refer to that directory. Chinese prompts and UI labels are retained verbatim.

## Analysis and approval

After sign-in, a draft referenced by an old conversation returned 404 because the fixture had been reset. The existing “新建会话” entry started a new conversation. The prompt “近 14 天和前 14 天，人民币成交额分别是多少？按商品解释变化。” produced a visible answer using UTC windows `2026-08-22, 2026-09-05)` and `[2026-08-08, 2026-08-22)`: pre-refund paid revenue was CNY 2,304 and 1,956, up 348. Coffee contributed +994, tea −658, and cups +12, matching original order-reference SQL inside `sql/before/S12.jsonl`. [Analysis screenshot](analysis.png)

The next prompt, “把咖啡价格调到 25.20 元，先生成草案”, produced a `PREPARED` draft. The actual price was still 2,400 minor units at version 3, with no product-change event. [Draft screenshot](prepared.png) · Original draft: `sql/prepared/drafts.jsonl` inside the archive · Product before approval: `sql/prepared/products.jsonl`

Clicking approval in the browser changed that same draft to `APPLIED` and the coffee price to 2,520 minor units at version 4. There was one product change and one corresponding Outbox event, `9d3347bf-8ce1-41b7-9e04-772e2394d88b`; the event was published and stock was unchanged. Inside the archive: product after approval, `sql/applied/products.jsonl`; receipt, `sql/applied/drafts.jsonl`; event output, `sql/applied/events.jsonl`.

A subsequent real query read back CNY 25.20, version 4, and `APPLIED`. After refreshing, signing in again, and selecting the original conversation, approval history still showed the same receipt and event. [Readback screenshot](readback.png) · [Recovery screenshot](restored.png) · Restored conversation: `restored-session.json` inside the archive.

Product, draft, event, historical-order, and scope-summary files matched between the approved and restored stages. Historical orders remained unchanged throughout. The event file contains two result sets pointing to the same event, not two publications. The `after-analysis` snapshot was captured after the second turn had started and created a draft, so it is not an independent write boundary for the analysis turn alone.

## Subsequent streaming observations

A separate observation at ShopMate `ac6b1404e17a007b8c5563449872c69c520787a0` checked the response-header fix: the browser displayed analysis step 2 running a query before the answer reached its terminal state. [Streaming progress screenshot](streaming-progress.png)

The follow-up “这两期咖啡的成交件数分别是多少？能说是刚才这次调价导致了历史成交变化吗？” failed the business task. The model moved both original windows one day later and returned 65/31 units instead of 70/28 for the requested windows. It correctly refused to attribute historical changes to the just-applied price change, but that did not offset the date-range error. The full conversation and actual SQL trajectory are in `streaming-followup-session.json` inside the archive.

Visible streaming progress and answer correctness are recorded separately. This turn is not assigned retroactively to the main demo version and does not change formal evaluation scores.

Finally, at the same `ac6b1404e17a007b8c5563449872c69c520787a0` version, an explicit clarification restated the two original UTC half-open windows. The new query returned coffee sales of 70 units versus 28, up 42 (+150%); the visible answer, actual SQL, and reference results matched. [Clarified screenshot](clarified.png) · Conversation and query trajectory: `clarified-session.json` inside the archive.

After clarification, products, drafts, events, historical orders, and scope summaries matched the restored state, with no additional product change or event. This recovery through explicit clarification does not erase the preceding date-drift failure or add a new formal model result.
