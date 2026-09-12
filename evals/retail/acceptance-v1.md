# Repeated retail business acceptance v1

This is a repeatability check of the complete retail workflow, not generalization to unseen tasks. It registers existing business tasks, original inputs, R0, and per-task SQL definitions. Development passes from different source versions are not pooled into a final score.

## Scope and execution

After business behavior stabilizes and development defects are fixed, run each of the following 18 known scenarios 3 times, for 54 business attempts. A task may contain multiple chat turns and user clicks; model calls, tool calls, and chat turns are not the task denominator.

| Original suite | Selected tasks | Coverage |
|---|---|---|
| retail/development | D02,D04,D05,D07,D08,D10,D11 | Period comparisons, historical prices, follow-ups, clarification, zero sales/causal limits, batch approval, and cancellation followed by a new intent |
| retail/full-development | R01–R07 | Shopping comparison through payment/refund, both buyers' fulfillment/policies, listing maintenance, stock/sale state, campaigns, promotion-to-new-sale, and SQL/Python analysis |
| retail/buyer-planning-development | B01,B02 | Natural budget planning and authorized cart quantity/removal changes |
| retail/search-development | S01,S02 | Public-source research for both roles, source conditions, and store-fact boundaries |

Original D01–D12 tasks all remain available for development. The formal set omits overlapping flows without removing capabilities: R07 covers D01 sales statistics, D04/R07 cover D03 cross-month work, and broader approval flows include D09 single-product approval. D06 requerying after a period change and D12 operator cancellation are distinct behaviors/entry points; their single development runs and existing boundary checks remain separate. This repeated set does not claim D05's inherited period or D11's model cancellation fully replaces them.

```sh
.venv/bin/python scripts/run_tasks.py --suite retail/development --tasks D02,D04,D05,D07,D08,D10,D11 --repetitions 3
.venv/bin/python scripts/run_tasks.py --suite retail/full-development --repetitions 3
.venv/bin/python scripts/run_tasks.py --suite retail/buyer-planning-development --repetitions 3
.venv/bin/python scripts/run_tasks.py --suite retail/search-development --repetitions 3
```

Run commands serially. Every repetition uses the original retail-R0 rather than the previous task's prices, cart, or conversation. Manually review existing success_criteria, actual HTTP/cards, and reference SQL; the driver does not assign business scores automatically. Network or uncertain-write failures preserve the incident state until the outcome is known; do not reset past its marker. Three consecutive provider system failures stop the current suite, with unrun items retained in the planned denominator and their reason reported separately.

Before the first formal task, record full clean CityBuddy/ShopMate commits, fixture version, registered suites, main/analysis model aliases, actual transport protocol, budgets, and hardware. All formal tasks use the same source version and runtime settings. A model alias is not an immutable provider snapshot. Reports retain the fixed Shanghai cutoff; promotion dates are bound to each task's actual run date rather than treating the report cutoff as today.

## Grading and stopping conditions

Report business passes, incomplete business tasks, provider failures, unknown execution states, and unrun tasks separately. A batch is complete only when all planned tasks have explicit outcomes, required SQL, and visible output. Completion ratios use all 54 planned attempts, not just successfully executed ones; report category counts and task details too.

Write invariants are release gates: amounts, identities, whole-batch versions, stock, original receipts, and repeat execution must be correct. Unapproved operations must not execute, and uncertain writes must be resolved or explicitly retained. Stop and fix dependent flows when these fail. Ordinary errors in answer numbers, products, citations, or conditions are business failures; an HTTP success or card is not a pass.

Known, consistently reproducible development defects should be resolved before the formal batch. If a clear engineering defect appears during the batch, it may be fixed while preserving the original batch. Results after application behavior changes use a separate source version; old failures are not overwritten or pooled into a single-version score. Report occasional model errors honestly instead of repeating until success; any additional experiment first states the question and new workload it distinguishes.

Memory save/new-conversation/process-restart/edit/delete and role isolation, actual overlap between two conversations, same-conversation busy rejection, active stream interruption, and browser walkthroughs are separate from the 54-attempt denominator. Existing real-Java lost-response, partial-payment-recovery, and sandbox-cleanup integration checks cover transaction/recovery boundaries. StateEval ownership ablation addresses a separate permission question.

## Waiting and usage

Retain client monotonic samples from each POST to first nonempty text, first complete UI event, terminal event, and stream closure, interpreted by component and task type. They are not browser first paint or pure service latency. Record multi-turn task timing and user actions separately rather than adding per-turn p99s. Small samples describe their observed distribution and range, not an agent HTTP capacity ceiling.

Main, analysis, memory, and search usage uses existing provider_usage fields. Responses internal search_calls are not model-request counts. Cache observations use only reported read fields; unknown is not 0. Do not infer provider bills or explicit Anthropic cache hit rates. Budget exhaustion and call failures are separate categories; costs for both successes and failures remain included.

## Targeted regression after semantic clarification

After the complete 54 attempts, analysis guidance was found not to distinguish integer resource revisions from source labels; some answers also confused aggregation units, calendar days, or excluded endpoints. Required analysis guidance was clarified for field semantics, product sets, and zero-fill conditions, alongside main/analysis aggregation and date-expression rules. On a new commit, original D04, D05, R05, and R07 were rerun 3 times each, for 12 attempts. Main-agent date guidance lives in the existing merchant context read automatically each turn, with its original length limit preserved.

```sh
.venv/bin/python scripts/run_tasks.py --suite retail/development --tasks D04,D05 --repetitions 3
.venv/bin/python scripts/run_tasks.py --suite retail/full-development --tasks R05,R07 --repetitions 3
```

This subset was selected for observed failures. Original prompts, R0, reference SQL, model, and per-turn 16-call/300-second budget remain unchanged, while results record the new source version separately. These 12 attempts neither replace the original 54 failures nor establish another complete 54-attempt run. Existing transaction, permission, UI, memory, and runtime observations retain their actual versions and boundaries.

Ordinary model-semantic errors remaining after this regression are reported as limitations requiring analytical review, without repeatedly tuning prompts to select successes. New defects in actual data, execution, or permission boundaries still require fixing first.
