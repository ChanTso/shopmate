# Scope-routing and product-identity regression: 2/2

CityBuddy: `69be167a3df030bf45795c49f444d6e7c24d0423`<br>
ShopMate: `9173037d6eb43d295f6ccb5876fa6284e882dfdb`<br>
S08 and S11 each ran once using the original formal tasks and fixed data. Main and analysis models both used `gpt-5.6-terra`, sharing 16 calls and 300 seconds per turn. Task statements, reference SQL, field limits, and scoring rules did not change. Both attempts finished and met their business goals, separately from the old 84/90 and preceding 1/3.

| Scenario | Verdict | Checked outcome |
|---|---|---|
| S08-r1 | PASS | The catalog confirmed the canvas tote existed with stock 80. There were no sales for 42 days; both 14-day periods were zero, their difference was zero, and growth was inapplicable because the baseline was zero. Both delegation segments contained only the tote ID, and all three actual SQL queries used it. Prose and analysis cards fully delivered the result without substituting store totals. Duplicate historical metric cards and a redundant USD zero row remain process observations. |
| S11-r1 | PASS | Actual catalog data and SQL joined by product_id. Quantities were coffee 70 / tea 14 / mug 12; amounts were coffee 1610 / mug 456 / tea 238 CNY, correctly showing tea and mug switching places. MySQL 1690 actually occurred; the next query used CAST AS SIGNED within the same scope and succeeded. Correctness did not rely on an error-free SQL run. Excess brief segments were also corrected within the original budget, with 11 model calls in total. |

Products, historical transactions, generation, and scope were identical before/after both attempts; drafts and product events were empty. Original model/tool/SQL records, visible content, and recovery after failure are retained. This targeted regression confirms the fixes only; the full 30 × 3 batch at the same version reports formal business outcomes separately.
