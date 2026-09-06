# Targeted development rerun

CityBuddy commit: `69be167a3df030bf45795c49f444d6e7c24d0423`
ShopMate commit: `0db5538c1d46bf440542c6159323e2bcd2ec755a`
Main/analysis model: `gpt-5.6-terra` / `gpt-5.6-terra`.

The four original failed development tasks were rerun independently. **All four executed and passed human business review.** This targeted development result is not part of formal acceptance.

| Task | Result | User-visible and SQL evidence |
|---|---|---|
| D01 | Pass | Visible CNY2304, 32 orders and96 units, UTC range and successful historical-payment gross basis. USD is separate. This execution uses analysis; D06 below directly exercises snapshot unit presentation. |
| D06 | Pass | Both actual snapshot→presentation rounds include units. The second rereads UTC[08-29,09-05), showing1152 CNY/48 units rather than the first2304/96. Reference SQL agrees. |
| D07 | Pass | First turn explicitly asks for dates. Second shows tea896→238 CNY(-658,-73.4375%) and56→14 units(-42,-75%). The preserved actual analysis query computes distinct columns for the two changes and returns exactly these values. |
| D10 | Pass | One three-item APPLIED draft changes coffee2460/tea1830/mug3950, all version4, with three matching product events and generation31→34. Final visible answer names APPLIED and reads back all three prices and versions. |

D01/D06/D07 have identical before/after product and history snapshots and no draft/product event. D10 still has all R0 prices/version3 before operator approval; afterward only the three intended prices/versions change, with stock/availability/currency and historical payments unchanged. Original failures remain in their prior run directories; no results were overwritten or counted as formal successes.
