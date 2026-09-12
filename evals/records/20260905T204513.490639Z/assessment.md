# Three targeted regressions: 1/3

CityBuddy: `69be167a3df030bf45795c49f444d6e7c24d0423`<br>
ShopMate: `91347b986fcfc65d08c4012dcaa14e47dd7f0ada`<br>
The run retained the first formal task definitions, fixed data, main/analysis model `gpt-5.6-terra`, and per-turn budget of 16 calls / 300 seconds. S03, S08, and S11 ran once each. All three executed to completion; business completion was 1/3. This diagnostic regression is separate from the original 84/90.

| Scenario | Verdict | Actual outcome |
|---|---|---|
| S03-r1 | PASS | Historical average CNY 23, current price CNY 24, and 70 units / CNY 1610 were correct. The visible answer explicitly rejected inferring discounts or bundles from the price difference. Two metric-presentation calls failed, but the prose fully delivered the answer. |
| S08-r1 | FAIL | Stock 80 and no sales for 42 days were correct, but the two-period comparison again expanded to all seven products, omitting the tote's 0 → 0 and inapplicable growth rate. The Skill was actually loaded; the scope error was already in the first delegation parameters. After new validation rejected an overlong brief and too many segments, the third delegation hit the existing attempt limit, with no analysis-model calls. The main loop later obtained the tote's empty series but still delivered store totals. |
| S11-r1 | FAIL | All three SQL queries executed, but exact joins used guessed names such as `Ceramic mug（陶瓷杯）` (verbatim query value), missing the actual `Ceramic mug`. The final answer assigned the mug zero sales and claimed both rankings were identical. Reference SQL gives the mug 12 units / CNY 456; mug and tea exchange second/third place between quantity and revenue rankings. Error 1690 did not occur, so this attempt did not verify recovery using that feedback. |

Before/after products, historical transactions, generation, drafts, and product events remained unchanged in all three scenarios. Original tasks and raw records were not rewritten. Follow-up work addressed the general causes in main-loop scope routing and product-identity sources for analysis SQL, with independent regressions, without changing task statements or removing failed tasks to improve the score.
