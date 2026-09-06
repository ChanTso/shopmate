# Development smoke assessment

CityBuddy commit: `69be167a3df030bf45795c49f444d6e7c24d0423`
ShopMate commit: `3bea5a147319a434e06ad1dbe9e1e8b3239c08af`
Suite: development, D01/D04/D09, one execution each. Main Terra; analysis Luna. These are development failures, not formal acceptance results.

| Task | Execution | Business assessment | Reason |
|---|---|---|---|
| D01 | Executed | Fail | CNY amount/order/unit values agree with reference SQL, but requested payment-status explanation exists only in an internal tool result. Visible analysis cards display 0% without a comparison baseline. |
| D04 | Executed | Fail | Per-product units, historical amounts/averages and current prices agree with SQL. Visible card headline says four CNY products sold, while SQL and final text say three; cards again show inapplicable 0% changes. |
| D09 | Failed before approval | Fail | Search tool advertises unsupported filters. The model repeatedly supplies them, cannot resolve the coffee product and creates no matching draft. Driver makes no approval request. |

For D01/D04, product and historical SQL snapshots before/after are identical; no drafts or product events were created. D09 also contains no approved write. Raw SQL, user-facing SSE/card payloads and preserved sessions remain in their task directories. Internal findings alone do not count as a delivered answer.

The next development revision will narrow the deployment tool contract, allow absent/not-applicable change percentages, and display the analysis findings and accounting basis. Original task prompts, SQL references and success criteria remain unchanged.
