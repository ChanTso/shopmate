# ShopMate 业务任务与评测记录

执行前先停止手工启动的8101 API，保留ShopMate数据与Java服务。驱动只支持固定本机地址，自持正式API子进程，在每题重置前确认静默并恢复本人旧会话的prepare，然后停API、重置、重启并重新登录。它不按端口杀进程，不管理外部API；停止、恢复或写状态不明则保留夹具并停批。`--describe`不启动进程、不读取运行配置。

当前默认协议是 [`retail/development.json`](retail/development.json)：完整零售目录的12个开发任务，使用90个上海自然日、CNY合成定价。迁移后的任务、参考SQL和待采集基线独立放在 [`retail/`](retail/README.md)，没有复用旧成绩；当前 `not_run` 不表示通过。12题保留经营问答、历史价格、追问、澄清、真实批准与取消的原业务意图，不代表完整零售工具验收，也不计入未来正式场景分母。

```sh
uv run python scripts/run_tasks.py --describe
uv run python scripts/run_tasks.py --suite retail/development
uv run python scripts/run_tasks.py --suite evals/formal.json --describe
```

新驱动执行前从本次权威SQL记录获得目标SKU旧价和版本，并记录相对版本预期；不会猜测固定3→4，也不自动把执行完成算成业务通过。通用变更接口中的价格审批仍需 `PRICE_UPDATE`、CNY、PREPARED和完整商品／目标分金额集合唯一匹配。实际调用和状态不明时停止、保留夹具的规则不变。

旧 `development.json`、`formal.json`、`baseline.json`、`sql/` 和 `records/` 原件继续保留。当前驱动只允许通过 `--describe` 读取旧协议，拒绝用新零售重置执行旧题；旧实验重现需使用各记录中的原始双仓库提交，不能把新夹具产生的运行并入旧78/90或定向21/24。

## 历史七商品协议与成绩

以下数据、执行命令、R0和固定版本描述属于旧七商品实现，仅适用于记录对应的历史源码。当前零售执行以 [retail/README.md](retail/README.md) 为准。

`development.json` 定义12个开发任务，`formal.json` 定义30个正式业务场景、每个重复3次。JSON中的规划状态不表示最新运行状态；实际结果见[记录索引](records/README.md)。`baseline.json` 是合成夹具定义，业务判定以数据库原始输出为准。

最近完整批次为 **78/90**（ShopMate `9173037d6eb43d295f6ccb5876fa6284e882dfdb`）；修改后选取8个已知失败场景回归为 **21/24**（`02d1bf0d0d1e4f5d71925f7db92ed3c4d9726b28`）。两批CityBuddy均为 `69be167a3df030bf45795c49f444d6e7c24d0423`。原选集13/24与新选集21/24单独对照，不替换旧失败，不称单变量实验或新完整90次结果。旧84/90及开发、调试记录也独立保留。

## 数据和判分口径

固定截止时间 `2026-09-05T00:00:00Z`，UTC左闭右开窗口。成交额是退款前成功付款的历史订单金额，不按现价重算；CNY和USD分别计算，不换汇相加。夹具包含七款商品、42个完整交易日、历史价格、普通订单成功付款及未开始／PENDING／FAILED样本，没有秒杀成交样本。

人工检查实际可见正文与卡片、工具轨迹、参考SQL、草案回执及数据库终态。关键数值、商品集合、期间、币种、业务状态和读回须一致，不逐字匹配自然语言。金额以整数分为真值；百分比以前期为分母，零基期不适用。预算内自行纠错可通过；内部查询正确不能替代错误的可见答案，`executed`也不等于业务PASS。

权限、未批准写入、并发／重复批准、版本冲突、响应丢失、预算与SQL限制在独立测试中验证，不加入业务完成率分母。正常任务中的仅提案、批准和取消按题面判定。没有错误写入不等于完成了用户要求。

## 执行

先启动独立ShopMate环境，停止其他任务和商品写入，确认待测实现已提交且源码干净；保留完整双SHA、fixture版本、模型、协议、预算及实际执行名单。模型配置从已有本地配置读取，凭证不写入执行记录。

```sh
uv run python scripts/run_tasks.py --suite development
uv run python scripts/run_tasks.py --suite formal
```

正式完整运行默认采用题表的3次重复。使用 `--tasks S08,S11 --repetitions 1` 等参数属于选集回归，单独计数。不要在一批中临时改题、提示、预算或补发答案。

- 模型只接收 `common_context` 和原文chat步骤；`evaluator`、参考SQL和预期排名／价格不发送给模型。同场景的追问保留会话，只在首次chat注入背景。
- chat通过实际 `/api/merchant/chat` 执行并保存完整SSE与终态；预设追问按表发送，不由人工替模型纠错。
- operator是预先约定的真实审批步骤。驱动从当前会话引用和卡片取得实际草案ID，再GET权威回执；按币种、PREPARED和完整商品／目标分金额集合唯一匹配。没有唯一匹配即停止该任务，不批准近似或错误草案。
- 匹配后，驱动以直接操作员身份和同一session调用真实apply／discard接口，保存实际请求路径与回执。聊天“已批准”、模型工具或直接SQL改价不能代替这一步。浏览器交互另作演示。
- 每个重复新登录、新会话；Bearer仅在内存中使用。不保存login响应、Authorization、密码或数据库／代理凭证。

## 每次重复的R0

R0重建本项目夹具，不只是把价格改回。仅操作独立的 `shopmate` Compose project，不使用旧CityBuddy默认演示或bench库。

1. 先结束全部任务写入并保存上轮SSE、回执、SQL。状态不明的写操作先查结果，不能直接重置覆盖现场。
2. 执行 `python3 scripts/reset_fixture.py`。脚本等待商品Outbox发布与指定消费队列排空；状态不可读或超时即停止，不继续正式任务。重置期间仍须由操作者保持无并发写入。
3. 复用CityBuddy命名空间SQL重建七商品、42日订单／支付／回调／账本，清理该命名空间草案和相关Outbox，保留身份；不清整库、Redis或Broker队列。
4. 通过实际host读取及 `products.sql`／`history.sql`／`scope.sql`记录基线，确认价格、版本、可编辑性和模型可见范围正确。generation以本次G0计，不要求固定值。
5. 重置不删除SQLite旧会话；每次重复创建新session。被重置删除的旧草案引用不再是当前业务实例，原始记录保留追查，不能借旧会话执行下一题。`local_runtime.py up`仅在缺商品时造数，不能替代完整R0。

## SQL与写入终态

`evaluator.reference_sql`路径相对于本目录。参考SQL从权威订单、付款等基础表按订单类型／ID、主体、金额、币种和成功状态判定；模型只使用受限经营视图账号，不能取得评估者权限。查询设为UTC，草案／事件SQL的 `@session_id`绑定实际创建的session。

只读任务也检查零额外草案／商品事件。写场景保存每次操作员处置前后以及最终的商品、草案、事件、历史原始输出。批准前价格不变、PREPARED的result/resolvedAt为空；APPLIED或CANCELLED有权威结果与完成时间，原items不改成新意图。每个获批商品版本3→4且有一条匹配的PRODUCT_PUBLICATION_CHANGED事件，N款批准使generation从G0推进到G0+N。取消不产生价格事件。

未指定商品保持原状态；获批商品只改变目标价格、版本及正常更新时间，库存、名称、说明、可用性、币种和发布状态保持。`history.sql`输出在操作前后不变。错误草案、错值、范围错误、缺失读回、未完成动作及provider失败均保留，不用其他测试或后来成功补数。

## 记录组织

本地展开原件保留在 `evals/results/<run-id>/`；公开记录位于[records](records/README.md)，每批一份 `raw.tar.gz`，并提供直接阅读的 `assessment.md`、`run.json`及已有统计文件。包内根目录为该run-id，assessment中的任务相对路径在解包后对应原件。

每批记录实际双SHA、as-of、模型／协议／预算、任务和重复数、起止时间、session、原始SSE、分析SQL、真实操作员回执和前后权威SQL。业务PASS、执行状态、调用用量、耗时分别报告。全量以x/90并列每场景0/3至3/3，选集以实际分母报告；未执行保持not_run。固定矩阵用于开发和回归，不能称未见任务泛化评测。
