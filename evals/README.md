# ShopMate 业务任务定义

这里是任务表、参考 SQL 和预期业务状态，**不是运行结果**。`development.json` 含 12 个开发任务；`formal.json` 另列 30 个业务场景，各从独立初态执行 3 次，共计划 90 次。两者独立计数，正式文件目前 `status: not_run`。`baseline.json` 的数字来自合成夹具定义，实际验收以权威数据库查询及原始输出为准。

固定截止时间 `2026-09-05T00:00:00Z`，使用 UTC 左闭右开窗口。CNY、USD 分别计算；成交额是成功付款的历史订单金额，退款前口径。当前夹具有普通订单成功付款及未开始/PENDING/FAILED 样本，没有秒杀成交样本；不能把 SQL 支持两种订单来源当成该数据已覆盖秒杀成交。

权限、未批准越权写入、并发/重复批准、版本冲突、响应丢失、预算耗尽、SQL 超时及写语句拒绝在独立测试中验证，不加入这 90 次正常业务完成率。正常经营目标中的“仅提案”“取消”保留在任务表内。

## 任务 JSON 与驱动约定

每份 JSON 包含 `common_context`、`as_of`、`tasks`、重复数及需记录的运行配置。每个任务包含 `steps` 和仅供评估者使用的 `evaluator`。

- 只把 `common_context` 与 `steps[kind=chat].message` 送入模型。第一次 chat 将背景置于题面之前；同一场景的后续步骤沿用该会话，不再次注入答案、SQL、商品排名或写入期望。
- `kind: chat`：按原文 POST `/api/merchant/chat`，读取完整 SSE 和结束状态后进入下一步。预设追问/澄清按表执行，不临时纠正模型的商品、金额或查询结果。预算内模型自行纠错可继续；修代码后重跑或人工补答案另记，不覆盖原失败。
- `kind: operator`：这是已预先授权的操作员步骤，可由小驱动经真实 ShopMate 审批 API 执行，无需 90 次逐次浏览器点击。UI 操作另做产品演示。
- `draft_match` 属于操作员与评估者字段，不发给模型。先从当前会话 `/overview` 的草案引用及流式卡片取得实际 ID，再 GET `/changes/{id}` 取得权威 receipt。匹配币种、PREPARED 状态与完整商品/目标分金额集合，忽略项目顺序但不能少项、多项或拆批。不存在唯一匹配草案时停止该任务、记录执行失败，不批准其他写入。驱动保存旧价、expectedVersion 与审批前后 SQL；旧价与 expectedVersion=3、商品初态是否符合 R0 由后续业务判读核对，Java 在批准时执行版本校验。
- 匹配后使用直接操作员 Bearer 和相同 `X-Session-Id`，POST `/changes/{id}/apply` 或 `/changes/{id}/discard`。保存 `{ok,change,receipt}` 原件；聊天文字、模型工具、直接 SQL 更新价格都不能替代批准。不要把“我已批准”文本先送模型再补实际批准。
- `evaluator.reference_sql` 是相对于 `evals/` 的文件路径。SQL 文件是完整语句；不需要自行拼接 CTE。`sql/drafts.sql`、`sql/events.sql` 的 `@session_id` 必须由实际 POST session 返回值通过参数绑定设置，不能采用模型猜测 ID。
- `expected_product_changes` 是相对 R0 的完整预期变更集合；未列商品必须保持原状态。`expected_drafts` 列出应保留的每份草案及真实终态，修订场景中的旧草案不能被原地改成新意图。商品应保持币种、库存、名称、说明、available 和发布状态，只有已批准目标价、版本及正常更新时间可以改变。
- 每个 APPLIED 项应有匹配的 `PRODUCT_PUBLICATION_CHANGED` 事件及版本 3→4；PREPARED/CANCELLED 不产生价格事件。审批前后 `sql/history.sql` 输出相同。全局 generation 以本次 G0 为基线，独占库中批准 N 款为 G0+N，不要求固定为 1。

接口前缀为 `/api/merchant`。先 POST `/login {loginIdentifier,password}` 得到 `accessToken`，再 POST `/session`；每个重复都新建会话。Bearer 只在驱动内存持有，不能写入任务记录、日志、模型历史或 SQLite。执行中保存 chat SSE、工具/模型元数据、无凭证的请求题面、草案及操作回执；不存 login 响应全文或 Authorization 请求头。

## R0

R0 不是只改回商品价格。每个场景重复都独立重置并新建会话；场景内部的多轮和审批保持同一 session。只操作独立 `shopmate` Compose project，不能用旧 CityBuddy 默认演示/bench 库。

1. 完成并归档上次任务的 SSE、草案、操作员回执和 SQL 原始输出。停止任务请求及其他商品写入，确认没有运行中 turn；在整个重置期间保持无并发写入。遇到结果不明的写操作，先查询保存结果再重置，不能覆盖现场。
2. 在 ShopMate 仓库根目录运行实际重置入口：

```sh
python3 scripts/reset_fixture.py
```

   该脚本先检查商品 Outbox 的 PENDING 数和明确 topic 的 `mqadmin consumerProgress` Diff/Inflight，等待发布与消费完成后才调用已有 `seed_business()`。队列状态不可读或未在等待窗口内排空时，保留失败并停止，不继续发送正式任务。这个入口依赖操作者已停写，不承诺能在任意并发环境中安全重置。
3. seed 复用 CityBuddy `scripts/seed_merchant_fixture.py --as-of 2026-09-05` 的命名空间 SQL：重建7款商品、42个交易日、支付/回调/账本和3种未成功付款样本，清理该命名空间的旧草案与相关 Outbox，保留身份凭证。operator subject 固定为 `shopmate-fixture-operator`。重置不会删除整库、Redis 或 Broker 队列。
4. fixture 会递增 `catalog_metadata.publication_generation`，商品缓存键包含 generation。旧消息已排空、新读取使用新 generation；通过 host 商品接口核对价格、版本和可编辑性为 `baseline.json`。若仍有旧状态先处理，再开始任务，无需全局 FLUSHALL。保存 `sql/products.sql`、`sql/history.sql`、`sql/scope.sql` 与实际 G0；模型可见商品集合须与题面一致，不能只在评估者 SQL 偷偷过滤其他业务数据。
5. reset 不删除 ShopMate SQLite 会话。每次重复重新登录并 POST `/session`，使用新的 session/history/state/prepare intent 范围，不恢复旧会话作下一次重复。保存新 session 的 `sql/drafts.sql`（应无草案）。先前会话和原始结果保留供追查；fixture 被重置后，旧草案引用不再是当前业务实例，不能用它们执行下一次操作。host `as_of` 必须仍为固定截止时间，然后才发送第一条任务。

`local_runtime.py up` 只在商品不存在时 seed，不等于完整 R0。重置命令、队列读数和新会话记录用于说明初态；不需要新的重置服务、判分器或证明框架。

## 参考 SQL

`sql/products.sql`、`drafts.sql`、`events.sql`、`history.sql` 对应商品、草案、商品事件和历史成交不变性。分析文件 `S*.sql` / `D*.sql` 从权威 standard/seckill_order 与 mock_payment_attempt 按 `order_kind + order_id` 关联，匹配付款主体、金额、币种及成功状态，独立于模型输出。模型实际分析仍使用它的只读视图账号，不能将评估者的基础表权限借给模型。

运行参考 SQL 前设置 UTC。公共基线在任务开始保存；写场景在每次操作员处置前后保存商品/草案/事件与历史输出。只读场景也要核对没有额外草案或商品事件。金额以整数分为真值，展示可四舍五入为两位小数；百分比以前期为分母，零基期标不适用。自然语言不逐字匹配，关键值、范围、业务状态与读回事实须一致。

## 执行记录与完成统计

首次正式场景前冻结完整 CityBuddy/ShopMate SHA、fixture源版本、实际主/分析模型与 provider、host 每轮预算及驱动的场景停止规则。不能把 task表中的规划版本或 SDK 占位 usage 当成实际模型执行证据。

每次保存：suite/task_id/repetition、完整版本与 as-of、session_id、起止时间、各 chat 原始 SSE、实际工具/模型记录、操作员动作和真实 draft_id、参考 SQL 与原始输出、completed/failed/not_run 及具体原因。人工等待与模型/工具执行时间分开；本任务表不新设性能阈值。

正式结果最终报告 x/90，并同时给已执行/未执行次数及每场景0/3至3/3。provider 故障、工具错误、错值、范围错误、错误草案或未读回均保留，不用开发成功或边界拒绝补数。尚未执行的次数保持 not_run；没有执行完就不能宣称“完成90次评测”。
