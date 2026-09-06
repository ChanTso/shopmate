# SSE 经前端代理的传输验证

CityBuddy：`69be167a3df030bf45795c49f444d6e7c24d0423`。  
修复前 ShopMate：`02d1bf0d0d1e4f5d71925f7db92ed3c4d9726b28`。  
修复后 ShopMate：`ac6b1404e17a007b8c5563449872c69c520787a0`。  
验证日期：2026-09-06 UTC；同一台本机、Next production 前端 3100 → Python API 8101，真实 `gpt-5.6-terra`。

真实浏览器演示中，流式回合完成前没有及时显示工具进度。沿前端代理定位到 Next 默认压缩：它会压缩 `text/event-stream`，而上游响应只有 `Cache-Control: no-cache`。以现有本地操作员登录，经实际 Next 入口新建独立会话，发送同一句只读问题「用一句话说明你能做什么，不需要查询业务数据。」，请求接受 gzip，保存响应白名单头和解码后的原始数据分块。

| 检查项 | 修复前 | 修复后 |
| --- | --- | --- |
| `Content-Encoding` | `gzip` | 无 |
| `Cache-Control` | `no-cache` | `no-cache, no-transform` |
| 客户端收到的解码数据块 | 1，包含整轮与终态 | 40，终态前已有 39 块 |

仅给 SSE 响应加 `no-transform`，使代理不再将事件缓存在压缩流中；其他页面压缩、模型协议、提示词和调用预算保持。已有完成流测试增加响应头断言；完整 Python 检查 517 通过、1 个既有可选 SDK 模块跳过。随后真实页面在回合尚未结束时已显示 `analysis: step 2 — running a query`，见 `streaming-progress.png`。

这证明了该压缩缓冲路径已被解除。数据块数量随模型文本和网络分包变化，不是吞吐量或模型提速指标；两次输出与模型耗时不要求相同，也没有据此计算延迟收益。最早页面观察中的全部等待时间不能都归因于压缩。该记录独立于 90 次完整业务验收和 24 次定向回归。

两份原始传输记录为 `sse-transport-before.jsonl` 与 `sse-transport-after.jsonl`，在本目录的原件包内；凭证和请求授权头未保存。
