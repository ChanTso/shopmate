# ShopMate

连接 CityBuddy 交易后端的商家经营 Agent。围绕两件事工作：从已支付订单回答经营问题，以及把调价建议变成可核对、由操作员批准的业务草案。

工作台提供经营概览、商品查询、对话分析和审批历史。买家客服仍使用 CityBuddy 原有入口，ShopMate 是独立的商家入口。

![经营概览与待批准的调价草案](docs/demo-20260906/prepared.png)

## 工作流程

- **分析经营变化**：主 Agent 读取经营摘要、组织追问，复杂计算委派给只读分析子 Agent。按付款成功时间和历史成交金额统计，支持跨期、商品拆分及多轮修订。
- **提出价格调整**：最多三个同币种普通商品组成一份草案，展示旧价、目标价和商品版本。关联任何秒杀活动的商品不进入此流程。
- **操作员批准**：模型没有执行调价的工具。批准按钮携带登录操作员身份，由 Java 锁定整批商品、复核版本与业务条件，并原子提交价格、草案结果和商品事件。冲突整批拒绝，重复批准返回已有结果。
- **恢复与预算**：会话、草案引用和结果持久化；刷新后重新登录可查看历史。每个对话回合的主、分析子 Agent 共享 16 次模型调用与 300 秒截止时间，主循环最多 12 个工具轮；中断回合保留已产生的业务结果，后续可查，不从中间 token 续跑。

```mermaid
flowchart LR
  UI[商家工作台] --> Host[ShopMate API / 会话]
  Host --> Main[主 Agent]
  Main --> Analysis[只读分析子 Agent]
  Analysis --> Views[MySQL 受限经营视图]
  Main --> Tools[读取 / 建草案工具]
  Tools -->|申请短期精确 scope 委托| Auth[Auth]
  Auth -->|返回 OBO| Tools
  Tools -->|携带 OBO| Java[Commerce 业务接口]
  UI -->|操作员批准| Host
  Host -->|直接用户身份| Java
  Java --> TX[价格 + 草案回执 + Outbox 事务]
  TX --> Cache[RocketMQ / 商品缓存更新]
```

交易与授权边界由 [CityBuddy](https://github.com/ChanTso/citybuddy) 承担，Python 不重复实现价格事务。分析账号仅获三个经营视图的 SELECT 权限，并限制查询时间、结果行数和字节数；模型不接触数据库或服务凭证。

## 本地运行

需要同级 CityBuddy 仓库、Java 21、Python 3.11+、Node.js 24、uv、Docker Compose。CityBuddy 需包含商家接口与视图迁移（PR #149）。

```sh
cd ../citybuddy
make init-local setup-java setup-python
./mvnw --batch-mode --no-transfer-progress -pl auth-service,commerce-service -am package

cd ../shopmate
uv sync --frozen
python3 scripts/local_runtime.py up
uv run uvicorn shopmate.app:create_app --factory --host 127.0.0.1 --port 8101
```

另一个终端启动前端：

```sh
npm --prefix web ci
npm --prefix web run build
npm --prefix web run start
```

打开 `http://127.0.0.1:3100`。本地登录账号为 `shopmate-fixture-operator`，生成的密码在 `.run/operator_password`。本地配置、私钥和数据库凭证仅保存在忽略的 `.run/` 中。

启动脚本复用 CityBuddy 的 Compose、迁移和 SQL 夹具，使用独立的 `shopmate` Compose project 及数据卷，不重置旧买家演示库。Auth/Commerce 分别使用 9081/9082，ShopMate API 使用 8101，前端使用 3100。`python3 scripts/local_runtime.py stop` 停止本项目 Java 与数据服务并保留数据卷；API 与前端在其终端中停止。

## 模型与数据配置

模型代理配置沿用同级 `citybuddy/.env` 中的 `CLIPROXY_BASE_URL` 和 `CLIPROXY_API_KEY`。由运行中的 API 读取，不复制到源代码、浏览器或执行记录。默认主模型和分析模型均为 `gpt-5.6-terra`；模型名、业务服务地址与每轮预算通过 `.run/settings.json` 配置，也可用 `SHOPMATE_CONFIG` 指向另一份本地配置。

实际网络协议为 Chat Completions，通过进程内适配对接 Merchant 的 Messages 循环。主模型流式返回工具参数，收齐后执行并回传；分析子循环使用同一客户端和共享预算。缓存用量只显示代理实际返回的数据，未提供时标为未知，不宣称专属协议的提前派发或缓存收益。

本地夹具固定对账截止时间 `2026-09-05T00:00:00Z`，包含七款商品、42 个完整交易日、历史价格和多种付款状态。成交额采用退款前已支付口径，按 UTC 左闭右开窗口统计，CNY/USD 分别计算。这是可复现的演示数据。

## 演示流程

以下流程已在实际浏览器与 Java 服务上验证，截图与 SQL 记录见[演示记录](docs/demo-20260906/README.md)。完成本地启动并登录后，在新会话中依次体验：

1. 问「近 14 天和前 14 天，人民币成交额分别是多少？按商品解释变化。」查看实际分析表、件数／金额及采用的时间范围。
2. 问「把咖啡价格调到 25.20 元，先生成草案。」核对卡片中的商品、币种、旧价、目标价和版本，此时商品价格仍未改变。
3. 点击批准，查看 Java 返回的 APPLIED 状态和实际价格；再问「读回咖啡当前售价和这次草案状态」。
4. 刷新页面、重新登录并打开原会话，检查已保存的分析与审批结果。恢复读取当前业务状态，不重新执行调价。

演示使用固定 UTC 截止时间和本地交易夹具。若先前验收已改过价格，按下面的重置约定保存旧结果、停写并重置，再创建新会话。不要在模型任务或批准仍在进行时重置。

## 真实模型业务验收

固定 30 个业务场景，每个独立重置并运行 3 次，使用真实模型、实际业务接口和操作员审批步骤。按用户可见回答与卡片、参考 SQL、草案回执和数据库终态判分。CityBuddy 被测版本为 `69be167a3df030bf45795c49f444d6e7c24d0423`；主模型和分析模型均为 `gpt-5.6-terra`。

| 记录 | ShopMate 版本 | 范围 | 业务结果 |
| --- | --- | --- | --- |
| [最近完整批次](evals/records/20260905T210851.446894Z/assessment.md) | `9173037d6eb43d295f6ccb5876fa6284e882dfdb` | 30 场景 × 3 次 | **78/90（86.67%）** |
| [首个完整批次](evals/records/20260905T185513.918718Z/assessment.md) | `0db5538c1d46bf440542c6159323e2bcd2ec755a` | 30 场景 × 3 次 | 84/90（93.33%），保留为独立历史 |
| [修复后定向回归](evals/records/20260905T231113.095557Z/assessment.md) | `02d1bf0d0d1e4f5d71925f7db92ed3c4d9726b28` | S02、S07、S12、S13、S14、S17、S20、S30，各 3 次 | **21/24（87.50%）** |

最近完整批次有 12 次业务失败，涵盖商品集合遗漏、币种卡片绑定与数值错误，以及未完成建案或取消。原始失败保留在 90 次分母，执行结束不等于业务通过。实际发生的审批均与指定草案、价格、版本和事件相符，未观察到额外商品写入或历史交易变动；权限与并发事务另由集成检查验证。

定向回归的被测代码为 `02d1bf0d0d1e4f5d71925f7db92ed3c4d9726b28`，补充集合与指标引用契约，并将 ShopMate 主循环工具轮数由 8 调为 12，共享 16 次模型调用／300 秒预算保持不变。**78/90 属于修改前的 917 版本，02d 版本只记录这次定向回归。** 这八个已知失败场景在原批中为 13/24，本次为 21/24；提示与工具轮数同时变化，模型执行也有随机性，不能据此归因于单项改动或替换原 90 次成绩。

定向回归的三次失败是 S13-r2 在 brief 拒绝后未完成分析、S17-r2 扩大追问商品集合、S30-r3 漏掉明确要求的茶草案取消。失败原件与历史批次见 [评测记录索引](evals/records/README.md)。

该完整批次 145 个对话回合的服务端耗时中位数为 31.942 秒、p95 为 98.746 秒，涵盖本轮主／分析模型和工具。928 次调用累计输入 5,954,918 token，其中代理明确报告的缓存读取占 79.38%；这是输入 token 的缓存读取占比，缓存创建量和实际费用未测量。原始调用及统计口径见 [statistics.json](evals/records/20260905T210851.446894Z/statistics.json)。

浏览器已验证分析、实际点击批准、接口读回及刷新后重新登录恢复回执。随后修正 SSE 响应的代理压缩，终态前可见工具进度；[传输记录](docs/demo-20260906/transport.md)与业务评测分别保存。

## 检查与业务验收

```sh
uv run ruff check src tests scripts integration_tests
uv run ruff format --check src tests scripts integration_tests
uv run pytest --import-mode=importlib tests \
  vendor/commerce-agents/commerce-common/tests \
  vendor/commerce-agents/merchant-agent/core/tests \
  vendor/commerce-agents/merchant-agent/runtime-messages-api/tests
npm --prefix web run typecheck
npm --prefix web test
npm --prefix web run build
```

独立本地环境启动后，真实数据库与 Java 边界检查另行执行：

```sh
uv run pytest integration_tests -q
```

该检查会修改保留的演示商品和草案。进入下一轮业务任务前，先结束其他任务写入并保存结果，再执行 `python3 scripts/reset_fixture.py`。脚本确认商品事件已发布和消费后，复用 CityBuddy 的 SQL 造数，不清整库或消息队列。

[业务任务约定](evals/README.md) 分开维护 12 个开发任务与 30 个正式业务场景。正式场景每个重复三次，通过真实模型和实际业务接口执行；权限与事务边界单独验证。任务定义不代表已通过，最终业务结论以执行记录、参考 SQL 和数据库终态为准。
