# Business evaluation records

For the full retail version, start with the [final 30-attempt business acceptance run](retail-v2-20260907/README.md): 18 known scenarios, **24 passes, 3 business failures, and 3 provider failures**. It includes waiting times, model usage, search sources, and the raw batch mapping. After provider failures, only unrun tasks resumed; failed attempts were not replaced.

The [preceding 54-attempt run](retail-v1-20260907/README.md) scored **46/54**. Its subsequent 12 targeted regressions and page, memory, concurrency, and recovery checks retain their own source versions. Both retail rounds use the fixture with 87 catalog roots, 104 tradable SKUs, and 90 Shanghai days; denominators from different batches remain separate.

## Historical merchant versions

Read each batch's business assessment first, then download its raw archive as needed. The latest full historical 30 × 3 run scored **78/90**; a later fixed version scored **21/24** on 8 targeted scenarios × 3. They use different versions and task scopes and cannot replace one another.

The historical batches below use CityBuddy `69be167a3df030bf45795c49f444d6e7c24d0423` and the fixed UTC fixture cutoff `2026-09-05T00:00:00Z`. All use `gpt-5.6-terra` as the main model. Only the earliest development smoke used `gpt-5.6-luna` for analysis; the rest used Terra. Each `run.json` records both full SHAs, protocol, budget, and actual task list.

The Execution column means executed / failed, distinct from manually judged business PASS. None of these batches has unrun attempts. The latest full batch contains 88 executed attempts and 2 execution failures, with a business denominator of 90.

| Batch / scope | Full ShopMate SHA | Execution | Business PASS | Records |
| --- | --- | --- | --- | --- |
| Latest full 30 scenarios × 3 | `9173037d6eb43d295f6ccb5876fa6284e882dfdb` | 88 / 2 | **78/90** | [Assessment](20260905T210851.446894Z/assessment.md) · [Run](20260905T210851.446894Z/run.json) · [Statistics](20260905T210851.446894Z/statistics.json) · [Raw archive](20260905T210851.446894Z/raw.tar.gz) |
| Post-fix 8 scenarios × 3 | `02d1bf0d0d1e4f5d71925f7db92ed3c4d9726b28` | 24 / 0 | **21/24** | [Assessment](20260905T231113.095557Z/assessment.md) · [Run](20260905T231113.095557Z/run.json) · [Statistics](20260905T231113.095557Z/statistics.json) · [Raw archive](20260905T231113.095557Z/raw.tar.gz) |
| D01/D04/D09 development smoke | `3bea5a147319a434e06ad1dbe9e1e8b3239c08af` | 2 / 1 | 0/3 | [Assessment](20260905T180849.909066Z/assessment.md) · [Run](20260905T180849.909066Z/run.json) · [Raw archive](20260905T180849.909066Z/raw.tar.gz) |
| Full 12 development tasks | `115b6a360ae502665f88063429e67230ab5ec37d` | 12 / 0 | 8/12 | [Assessment](20260905T182558.103268Z/assessment.md) · [Run](20260905T182558.103268Z/run.json) · [Raw archive](20260905T182558.103268Z/raw.tar.gz) |
| D01/D06/D07/D10 development regression | `0db5538c1d46bf440542c6159323e2bcd2ec755a` | 4 / 0 | 4/4 | [Assessment](20260905T184922.043835Z/assessment.md) · [Run](20260905T184922.043835Z/run.json) · [Raw archive](20260905T184922.043835Z/raw.tar.gz) |
| First full 30 scenarios × 3 | `0db5538c1d46bf440542c6159323e2bcd2ec755a` | 90 / 0 | 84/90 | [Assessment](20260905T185513.918718Z/assessment.md) · [Run](20260905T185513.918718Z/run.json) · [Statistics](20260905T185513.918718Z/statistics.json) · [Raw archive](20260905T185513.918718Z/raw.tar.gz) |
| S03/S08/S11 diagnostic regression | `91347b986fcfc65d08c4012dcaa14e47dd7f0ada` | 3 / 0 | 1/3 | [Assessment](20260905T204513.490639Z/assessment.md) · [Run](20260905T204513.490639Z/run.json) · [Raw archive](20260905T204513.490639Z/raw.tar.gz) |
| S08/S11 diagnostic regression | `9173037d6eb43d295f6ccb5876fa6284e882dfdb` | 2 / 0 | 2/2 | [Assessment](20260905T210133.531635Z/assessment.md) · [Run](20260905T210133.531635Z/run.json) · [Raw archive](20260905T210133.531635Z/raw.tar.gz) |


The latest regression selected S02/S07/S12/S13/S14/S17/S20/S30, three times each. The same subset in the original 917 full batch scored 13/24; this run scored 21/24. Set and metric contracts and main-tool rounds changed together, and model output is stochastic, so this does not isolate a causal effect. Version 02d allowed 12 main-tool rounds while retaining the shared main/analysis budget of 16 model calls and 300 seconds. This was not a new full 90-attempt run. Remaining failures were S13-r2, which did not finish analysis after parameter rejection; S17-r2, which expanded the product set in a follow-up; and S30-r3, which omitted an explicitly requested cancellation.

The six failures in the original 84/90, the subsequent 1/3 diagnostic regression, and all 12 failures in the latest 78/90 remain recorded. Development 4/4 does not rewrite development 8/12, and later successes do not replace old formal failures. Business judgment uses actual visible content, SQL, and real approval terminal states; execution completion or the absence of incorrect writes alone does not complete a business task.

Each `raw.tar.gz` expands to its run-ID root, retaining per-attempt execution, SSE, saved sessions, analysis/reference SQL, and operator requests/receipts. Task-relative paths in `assessment.md` point inside that archive. Only a small readable subset is expanded in the repository; local raw results are also retained. Tasks and reference SQL are available under `evals/` at the measured SHA listed in the table. The archive commit SHA is not the measured source SHA.

Statistics files summarize observed calls and elapsed times only. The cache-read share is neither a request hit rate nor a cost saving; cache creation was not measured. Timing separates chat server execution from scenario wall time including reset/SQL, and is not first-token latency or production capacity. Authorization, concurrent-transaction, and browser-demo records are outside these business denominators.
