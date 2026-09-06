# 零售夹具与本地重置

当前夹具由 [`scripts/retail_fixture.py`](../scripts/retail_fixture.py) 定义，由 [`scripts/local_runtime.py`](../scripts/local_runtime.py) 初始化和重置。数据版本为 `shopmate-retail-v1`，仅用于独立的 `shopmate` Compose project。需要 CityBuddy PR #158 及此前的 V020–V025 零售、购物、运营和营销迁移。

## 数据范围与来源

| 数据 | 当前定义 | 权威读取 |
| --- | --- | --- |
| 商品目录 | 83 个单品、4 个系列，共 87 个目录根；4 个系列含 21 个规格，总计 104 个 SKU | `product` 与 `retail_product_family/metadata` |
| 当前运营 | 库存、低库存阈值、可售状态、成本与内容质量观察 | 商品表及 `retail_product_operations` |
| 成交历史 | 报告截止前 90 个完整 Shanghai 日；历史价格版本及金额固定，另有未开始付款、PENDING、FAILED 样本 | `standard_order`、`mock_payment_attempt/callback`、相关账本与订单原始记录 |
| 买家与售后事实 | 两个演示买家、偏好和会员、本人订单、带来源的履约观察及订单问题；退款申请保留 REQUESTED | `crm_profile`、`retail_order_fulfillment/issue`、`mock_refund` |
| 流量与营销 | 90 日全店访问观察、五个原始营销计划及各自归因期间；C-203 收入未知 | `retail_store_traffic_daily`、`retail_campaign` |
| 政策与指南 | 与当前业务能力对应的政策、购买指南及配送估算配置 | 通过实际 FAQ 发布服务写入的 `faq_source`，以及 `retail_fulfillment_config` |

商品、紧凑规格、运营样例、买家、订单问题和营销观察来自 [`vendor/commerce-agents/examples/retail/data`](../vendor/commerce-agents/examples/retail/data)。商品图片只复用仓库内已有文件，保留[图片来源](../web/public/products/IMAGE-CREDITS.md)；没有图片的商品使用组件缺省展示，不生成失效图片地址。

金额统一转换为 CNY 演示金额，不声称进行汇率换算。历史订单按确定性规则构造，流量使用样例序列构造对应日观察，来源和数据版本写入记录；它们不是商店真实销售或广告成绩。已提供的营销支出与归因收入保留原有数值关系及明确期间，不再导入一套 mock sales 作为第二套成交事实。

系列共同内容只存于 family；当前 21 个规格没有额外展示内容覆盖，叶 metadata 保留实际 option_values，使用父内容继承。缺货规格 `AR-1606-KING-BLUSH` 和 `AR-1902-FULL` 有明确零库存；`AR-1207` 有库存但暂停出售，不能混为缺货。库存是本次演示的当前快照，历史造数不会再次扣减该库存。

买家订单的历史单价和版本独立于今天的商品价格。成功付款订单同时具备付款尝试、回调和支付账本；退款 REQUESTED 表示已预留申请金额，不表示资金已退回。履约使用明确阶段、时间和 `FIXTURE` 来源，不从 PAID 或预计送达时间推断已发货。原样例缺少发运时间的记录采用固定的演示交接假设，时间不得晚于观察时刻。

商家入口为 `/`，买家入口为 `/buyer`；两端复用这套业务事实。买家购物、人工确认、恢复与记忆管理见[买家说明](BUYER.md)。新版买家真实模型验收另行记录，本夹具说明不声明已经通过。

## 时间和统计口径

固定报告截止为 `2026-09-05T00:00:00+08:00`，交易覆盖 `[2026-06-07, 2026-09-05)` 的 90 个完整 Shanghai 日。SQL 连接和时间戳按 UTC 使用，本地日/月边界先转换成对应 UTC 瞬间再查询。裸日期指 Shanghai 午夜，显式带 offset 的时间保留其实际瞬间。

报告截止与真实操作时钟分开：`settings.as_of` 只传入 backend 的 `report_as_of`；主 Agent 每轮看到真实 Shanghai 操作时间。`last_14_days` 等相对报表以报告截止为参照，促销“今天生效”按真实操作日期处理。新增的现实时间订单不会被塞入旧固定报告窗口，覆盖外的期间也不能当成已观察到零成交。

- 成交额采用成功付款的历史订单金额，退款前总额；不按现价重算，不把不同币种直接相加。
- 转化率为同一完整期间的付款 **SKU 子单数 / 全店访问次数**，不是去重买家数或 checkout 头数；缺失任一天的流量观察不补零。类别和商品没有独立流量分母。
- 退款申请订单比例不是成功退款率或实物退货率。成本和毛利来自当前运营观察，是经营估算，不是会计利润或强制价格底线。
- 营销预算是可编辑的计划字段；支出、归因收入和观察期间独立保留。ROAS 仅在同一活动/期间/币种的收入和非零支出均存在时计算；未知收入不呈现为 0。
- `merchant_daily_sales` 保留旧 UTC 日聚合。上海日、周和月分析应从 `merchant_paid_orders.succeeded_at` 按实际本地边界聚合，不能直接将旧日标签换成 Shanghai。

分析子 Agent 只获以下六个视图的 SELECT；基础表和用于核对结果的本地只读账号不暴露给模型：

1. `merchant_products`：当前商品与可调价性。
2. `merchant_paid_orders`：按订单类型、订单 ID、主体、金额和付款状态关联的历史成交。
3. `merchant_daily_sales`：旧 UTC 日聚合。
4. `merchant_listing_facts`：当前系列、分类、库存和成本/内容观察。
5. `merchant_store_traffic_daily`：Shanghai 日访问观察及来源。
6. `merchant_campaign_facts`：本地计划与独立归因观察。

## 变更与判定

五类草案共用 CityBuddy 的变更账本和实际操作员审批入口。商品操作展开后至多 25 个 SKU；Java 在同一事务内核对完整目标、快照和版本，写入业务状态、回执及适用的商品事件。普通调价工具的 20% 幅度限制属于 host 工具约束，不声称 Java 也执行相同上限。

促销折扣必须为正且不超过 50%，分金额按 HALF_UP 生成并冻结。允许批准窗口开始前仍为 PREPARED；窗口过期后首次批准会拒绝；窗口内批准立即改变实际价格。日期形式的结束值包括该 Shanghai 日期全天，显式时间形式的结束值不包含该瞬间。到期不会自动恢复售价，商品之后再次改价或换币种时读取接口同时保留原促销价格与当前价格。

CAMPAIGN 创建或更新本站计划、预算、受众和文案。新计划没有支出或收入观察；修改旧计划不改写其已有归因数据。没有外部广告投放动作。

## 初始化与正常启动

从 ShopMate 根目录执行，且 API 未运行：

```sh
uv sync --frozen
python3 scripts/local_runtime.py up
uv run uvicorn shopmate.app:create_app --factory --host 127.0.0.1 --port 8101
```

完整依赖安装和前端启动见 [README](../README.md#本地运行)。`up` 先完成身份、迁移及 Java 服务配置；以当前版本的流量记录判断夹具是否已初始化。首次初始化会替换保留的旧七商品演示范围并建立统一零售数据；后续正常启动保留当前价格、库存、计划和会话，不等同于重置。

## 手工重置

重置会删除并重建保留范围内的业务记录。先保存需要保留的 SQL、SSE、草案与执行回执；状态不明的写入先读回，不能用重置覆盖问题现场。

1. 停止模型任务、集成测试和其他业务写入，在 API 终端按 Ctrl-C 停止 uvicorn。保持本项目 Java 和数据服务运行，以便排空商品事件；若使用非默认端口，也须自行停止对应 API。默认 8101 仍监听时脚本拒绝维护。
2. 在 ShopMate 根目录执行：

   ```sh
   python3 scripts/reset_fixture.py
   ```

3. 脚本确认商品 Outbox 已发布、指定 RocketMQ consumer 无待消费或在途记录后，停止 Java 写入，再重建 SQL 数据、处理 SQLite 夹具会话、通过实际 FAQ 发布服务写入政策，最后重新启动 Java。排空不可读或超时即停止。
4. 重置成功后重新启动 API，再登录并新建会话：

   ```sh
   uv run uvicorn shopmate.app:create_app --factory --host 127.0.0.1 --port 8101
   ```

清理按固定商品 ID、明确的夹具主体和版本进行，主体比较使用精确二进制语义。商品的非夹具订单、购物车或促销引用、其他操作员的商品变更草案，以及其他操作员对夹具营销活动的更新会阻止维护。清理顺序先处理促销、checkout、动作回执、退款、付款等依赖，再处理订单、商品元数据、商品与系列；不删整库、Redis 或消息队列，也不关闭外键约束。

存在 `.run/sessions.sqlite3` 时，脚本用 SQLite backup API 备份到 `.run/backups/sessions-<时间>.sqlite3`，然后清除对应夹具主体的会话、草案引用和未决 prepare intent，避免旧会话继续使用已删除的业务实例。其他会话不作为此次清理目标。

**自动备份仅涵盖 SQLite，不是 MySQL 业务库备份。** SQL 和 SQLite 不共享事务：SQL 重建完成后才处理会话备份/清理及政策发布。若后续步骤失败，维护失败并保持 host 未就绪；先检查忽略目录中的 `.run/runtime.log` 和实际库状态，再决定恢复或重新执行，不将局部成功当成完整重置。

`.run/` 包含本地凭证、会话与备份，保持忽略且不提交。需要保留上轮 MySQL 业务事实时，应在重置前另行保存所需数据库备份或权威 SQL 输出，而不是依赖会话副本恢复交易状态。

## 与旧记录的关系

旧 `evals/` 任务和[公开历史成绩](../evals/records/README.md)采用七商品、42 日 UTC 数据及不同代码版本，不能直接在此夹具下宣称复现同一分数。旧 78/90、定向 21/24 和[浏览器截图](demo-20260906/README.md)继续保留原始版本与分母；本说明不声明新版真实模型或端到端验收已通过。

新版验收应先固定这套业务数据与报告口径，再使用参考 SQL、实际用户可见结果和 Java 写入终态判定。权限、未批准写入、版本冲突、并发与重复批准以及停止恢复分别检查，不以任务执行结束代替业务成功。
