# 冻结版本业务验收：78/90

CityBuddy：`69be167a3df030bf45795c49f444d6e7c24d0423`  
ShopMate：`9173037d6eb43d295f6ccb5876fa6284e882dfdb`  
结果目录：`evals/results/20260905T210851.446894Z`。  
数据截止：`2026-09-05T00:00:00Z`，UTC；fixture来源为上述CityBuddy提交。  
主模型与分析模型均为`gpt-5.6-terra`，经CLIPROXY Chat Completions适配调用。每个chat turn主/分析调用共用16次模型调用、300秒截止时间；主循环另有8个工具轮次限制，未调整预算。

固定30个业务场景各执行3次；每次从R0和新会话开始，同一场景内部保留多轮对话和真实操作员步骤。按冻结题面、实际用户可见回答和卡片、参考SQL、审批回执及写入终态判定。内部错误若在原预算内自行纠正并完成目标，可判通过；`executed`不是业务通过标记。失败保留原分母，不用隐藏工具结果补用户答案，不拼接旧批或定向回归的成功。

**90次全部完成判读：78 PASS、12 FAIL，业务完成率78/90（86.67%）。** 执行状态另计88 executed、2 failed（S20-r3、S30-r1）；两次均因没有可批准的匹配草案而停止后续步骤，未尝试操作员写入，未被归为provider故障。业务失败包括正常executed但未完成题目要求的样本，全部保留在90次分母。

本批结束时间为`2026-09-05T23:02:57.800425+00:00`，运行正常收尾。以下配置和结果属于本批冻结版本，主工具轮次上限为8；不将后续版本的限制调整倒写进本批证据。

原始SSE、模型/工具记录、操作员回执与各阶段SQL保留在本目录。任务定义与参考SQL在同一提交的`evals/formal.json`和`evals/sql/`。下文原件路径均相对本结果目录。

## 逐场景结果

| 场景 | r1 | r2 | r3 | 完成数 |
|---|---|---|---|---|
| S01 | PASS | PASS | PASS | 3/3 |
| S02 | PASS | PASS | FAIL | 2/3 |
| S03 | PASS | PASS | PASS | 3/3 |
| S04 | PASS | PASS | PASS | 3/3 |
| S05 | PASS | PASS | PASS | 3/3 |
| S06 | FAIL | PASS | PASS | 2/3 |
| S07 | FAIL | PASS | FAIL | 1/3 |
| S08 | PASS | PASS | PASS | 3/3 |
| S09 | PASS | PASS | PASS | 3/3 |
| S10 | PASS | PASS | PASS | 3/3 |
| S11 | PASS | PASS | PASS | 3/3 |
| S12 | PASS | PASS | FAIL | 2/3 |
| S13 | PASS | PASS | FAIL | 2/3 |
| S14 | PASS | PASS | FAIL | 2/3 |
| S15 | PASS | PASS | PASS | 3/3 |
| S16 | PASS | PASS | PASS | 3/3 |
| S17 | FAIL | PASS | FAIL | 1/3 |
| S18 | PASS | PASS | PASS | 3/3 |
| S19 | PASS | PASS | PASS | 3/3 |
| S20 | PASS | PASS | FAIL | 2/3 |
| S21 | PASS | PASS | PASS | 3/3 |
| S22 | PASS | PASS | PASS | 3/3 |
| S23 | PASS | PASS | PASS | 3/3 |
| S24 | PASS | PASS | PASS | 3/3 |
| S25 | PASS | PASS | PASS | 3/3 |
| S26 | PASS | PASS | PASS | 3/3 |
| S27 | PASS | PASS | PASS | 3/3 |
| S28 | PASS | PASS | PASS | 3/3 |
| S29 | PASS | PASS | PASS | 3/3 |
| S30 | FAIL | FAIL | PASS | 1/3 |

## 十二次业务失败

| 次数 | 业务原因 | 原件路径 |
|---|---|---|
| S02-r3 | load_skill加7次串行目录查询耗尽8个主工具轮，第9次调用被强制仅输出文字；尚未查询成交额，未交付前三名、金额及份额。共享16次调用/300秒未耗尽，不是已证实的provider或数据库故障。 | `S02-r3/step-01.sse`、`S02-r3/step-01-terminal.json`、`S02-r3/sql/after/S02.jsonl` |
| S06-r1 | 将实际14日半开窗口写成15日，进一步向用户展示4/15=26.67%的成交日覆盖率；正确应4/14≈28.57%。四个日期及金额正确，不抵消错误分母和派生值。 | `S06-r1/saved-session.json`、`S06-r1/step-01-terminal.json`、`S06-r1/sql/after/S06.jsonl` |
| S07-r1 | 两项裸sales引用均解析为CNY快照2304/+17.79%；其中一项说明却标USD280/+11.11%，形成用户可见金额、币种、增幅矛盾。正确正文没有撤销错误卡片。 | `S07-r1/step-01.sse`、`S07-r1/saved-session.json`、`S07-r1/sql/after/S07.jsonl` |
| S07-r3 | 正文把CNY前期金额写为2058元，实际为1956元；同文的本期2304、差额348及17.79%也与2058不相容。 | `S07-r3/saved-session.json`、`S07-r3/step-01-terminal.json`、`S07-r3/sql/after/S07.jsonl` |
| S12-r3 | period长度验证连续失败后用尽本轮分析机会，实际分析查询0条，最终未给两期金额、件数与商品贡献。 | `S12-r3/step-01.sse`、`S12-r3/step-01-terminal.json`、`S12-r3/saved-session.json` |
| S13-r3 | 只完成6款商品（含USD），限量款未继续查询，最终明确本题所需的该CNY商品仍未核对，整体范围没有完成。 | `S13-r3/step-01-terminal.json`、`S13-r3/saved-session.json`、`S13-r3/sql/after/S13.jsonl` |
| S14-r3 | 实際只查5款CNY，最终明确限量款未纳入人民币合计；已查商品及杯的日期贡献正确，但所需整体范围仍未完成。 | `S14-r3/step-01-terminal.json`、`S14-r3/saved-session.json`、`S14-r3/sql/after/S14.jsonl` |
| S17-r1 | 追问要求在上一轮有成交商品中筛库存≥50，实际加入零成交的Canvas tote并显示保留3款；正确仅coffee和tea两款。 | `S17-r1/step-02.sse`、`S17-r1/step-02-terminal.json`、`S17-r1/sql/after/S17.jsonl` |
| S17-r3 | 与r1相同，第二轮将候选换成coffee/tea/tote，实际SQL和可见卡均加入原成交集合之外的帆布袋，错误没有纠正。 | `S17-r3/step-02.sse`、`S17-r3/step-02-terminal.json`、`S17-r3/sql/after/S17.jsonl` |
| S20-r3 | load_skill加7次串行目录读取耗尽8个主工具轮，尚未分析或建草案便被强制文字收尾。SQL确认草案0、事件0、价格仍2400；无匹配草案是未创建的结果，非金额或币种匹配错误；未尝试操作员写入。 | `S20-r3/step-01.sse`、`S20-r3/execution.json`、`S20-r3/sql/step-02-before/drafts.jsonl`、`S20-r3/sql/after/products.jsonl` |
| S30-r1 | load_skill、两款商品各自的search/get/context、pending共8个串行工具轮后，主循环强制文字收尾，两张草案均未创建。SQL确认草案0、事件0，咖啡/茶价格未变；后续审批无法执行，未尝试操作员写入。 | `S30-r1/step-01.sse`、`S30-r1/execution.json`、`S30-r1/sql/step-02-before/drafts.jsonl`、`S30-r1/sql/after/products.jsonl` |
| S30-r2 | 两张独立草案及咖啡批准正确，但用户明确要求取消茶后，模型仅读商品与pending，没有调用discard_change。最终茶仍PREPARED、result/resolved_at为空；诚实说明未取消不等于完成任务。 | `S30-r2/step-03.sse`、`S30-r2/step-02-operator.json`、`S30-r2/sql/after/drafts.jsonl`、`S30-r2/sql/after/events.jsonl` |

S13/S14遗漏的商品在夹具中恰为零，也不能由评估者代补其未完成的查询和结论。S02/S20/S30的主工具轮数上限与模型调用总额度不同；没有把模型“无法读取”的文字当成实际数据源故障。

## 已核对的业务终态与过程观察

S01–S18的只读任务未改变商品、草案、事件或付款历史。S19、S20及S21–S30中实际发起的审批均匹配指定草案，待审阶段保持原价，批准后商品价格、版本、generation与对应事件符合回执；未观察到未批准调价、额外商品变动或付款历史污染。

S21–S29的单品、同批多品、USD价格、只待审、撤销重提及分析后取消均符合各自终态。S30-r1零草案、零写入；S30-r2只完成咖啡审批，茶仍待审，故仍判失败；S30-r3完成咖啡批准、茶取消并分别读回。上述观察不额外增加通过次数，不用“没有错写”替代“完成任务”，也不代替独立权限或并发事务验证。

- S11三次均实际出现MySQL1690，并在原预算内改为SIGNED相减后完成正确排名；没有把中间错误单独判失败。
- S16-r3的一条SQL虽执行成功，却因重复JOIN放大总计；模型在可见交付前重新聚合为正确96件/2304元，按原目标通过。
- S02-r1用变化百分比样式展示份额，但相邻说明与展开卡明确份额含义；S20-r1的额外重复指标卡误将6款加一个聚合指标题为“7款商品”，完整分析卡、选品依据及批准终态仍正确。保留呈现质量问题，不把PASS描述成完美表达。
- 多次present_metrics引用或brief验证失败后通过实际重查、分析卡或最终正文完成目标；通过不等于没有工具错误，失败也不能只由工具is_error判断。

## 实际调用与耗时

145个chat turn共记录928次模型调用：主循环743次、分析子循环185次。928次均明确报告输入/输出和缓存读取字段。按每次调用累计一次，输入合计 **5,954,918 token**，输出 **191,877 token**；总输入已经包含缓存读取，不再叠加运行时汇总或缓存值。

明确报告的缓存读取为 **4,727,296 token**，占总输入 **79.38%**（4,727,296／5,954,918）。这是本次已报告输入token中来自缓存读取的比例，**不是请求缓存命中率，也不是已证明的时延或费用收益**。缓存创建未测量；没有代理费率或账单，不把token换算成实际成本。

| 统计对象 | 样本数 | 中位数 | p95 | 范围 |
|---|---|---|---|---|
| 场景执行器墙钟 | 90次 | 69.002554秒 | 135.225086秒 | 36.669278–206.127213秒 |
| 单chat turn服务端耗时 | 145轮 | 31.942秒 | 98.746秒 | 7.440–201.106秒 |

场景墙钟包含重置、SQL采集和脚本操作员审批等步骤；单chat turn涵盖本轮主/分析模型与工具，不加入真实人工审批等待。两者都不是首token或首个有效结果时延；本批没有相应首结果时间记录。分位数使用排序后线性插值，保留通过和失败任务，仅描述本次本地执行，不作为容量或线上SLO。

统计明细见同目录`statistics.json`，原始逐调用、SSE、回执及SQL继续保留。本结果是同一冻结版本、固定30个业务场景各3次的业务验收与回归；不称90种场景、未见过的公开基准或线上泛化能力估计。后续版本与针对性回归独立保存，不覆盖本批、不拼接成功样本。
