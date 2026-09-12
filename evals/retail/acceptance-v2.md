# Final acceptance after retail fact-expression fixes

This run retains retail-v1 data, R0 reset, original tasks, and original SQL grading. Main, analysis, and memory models remain gpt-5.6-terra. Main/analysis use the existing Chat Completions adapter and search uses Responses. Each chat turn has 16 calls/300 seconds, with 12 main-loop rounds. The model alias is not an immutable snapshot.

Before the group starts, record actual full ShopMate/CityBuddy SHAs and use committed, source-clean versions. Do not change code, tools, budgets, or grading within a group. Results after a behavior change receive a separate version; passes from different versions cannot be pooled into one final score.

First run D04, D05, R05, and R07 once each as targeted development regression. Retain those separately from the final 30 attempts below.

| Suite | Tasks | Repetitions each | Attempts |
|---|---|---:|---:|
| retail/development | D02,D07,D08,D10,D11 | 1 | 5 |
| retail/development | D04,D05 | 3 | 6 |
| retail/full-development | R02,R03,R04 | 1 | 3 |
| retail/full-development | R01,R05,R06,R07 | 3 | 12 |
| retail/buyer-planning-development | B01,B02 | 1 | 2 |
| retail/search-development | S01,S02 | 1 | 2 |

There are 18 known scenarios and 30 attempts. Repetition concentrates on historical prices/aggregate follow-ups, campaign observation periods, SQL/Python, shopping/payment/refunds, and promotion approval through actual sale. This is not unseen-task generalization, and singly covered scenarios do not establish stable success rates. Every attempt uses the original independent R0 and task data. A task may contain multiple chats, tools, and operator clicks, which are counted separately.

Grading retains the original task's success_criteria, actual responses/cards, and authoritative SQL. Unapproved writes, unauthorized execution, duplicate charges or stock errors, and unresolved uncertain writes block subsequent dependent flows. Ordinary model errors in facts, dates, statistics, citations, or conditions remain business failures. HTTP success, correct tools, or a displayed card do not offset them; errors in additional answer content are retained too.

Existing unaffected memory, search-transport, sandbox, conversation-concurrency, interruption/payment-recovery, and permission tests retain their actual execution versions and are not added to the 30-task denominator. Only behavior affected by a change receives corresponding regression checks. The new buyer ownership ablation retains its 0/3 versus 0/3 finding and failure to reach the transaction check; old support-agent results are not substituted.

Close the batch once all 30 attempts have outcomes and uncertain writes have been resolved. Report business passes/failures, provider failures, and unexecuted tasks. Retain remaining ordinary model failures without repeatedly opening another final evaluation. Summarize waiting and usage from existing monotonic originals, including failures. Cache reads are already part of known input; missing usage is not zero, and unreported billing costs are not inferred.
