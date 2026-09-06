# ShopMate 工作台

复用 `vendor/commerce-agents/examples/retail/merchant-web` 与 `examples/web-shared` 的 Next、PortalShell、聊天流和卡片交互。许可证和原始版权声明保留在 vendor 及复制文件中。

```sh
cd web
npm ci
npm run typecheck
npm test
npm run build
SHOPMATE_API_URL=http://127.0.0.1:8101 npm run dev
```

访问 `http://127.0.0.1:3100`。浏览器请求同源 `/api/merchant`；Next 根据 `SHOPMATE_API_URL` 转发至 Python host。生产构建时也要设置此变量，因为 rewrites 在构建时确定。

登录使用 CityBuddy Auth 操作员账号。Bearer 只保留在页面内存，刷新需重新登录，然后恢复已持久化会话。会话 ID 随 `X-Session-Id` 发送。草案批准/取消直接调用 host 操作端点；聊天文字不能批准变更。运行中的会话禁止新的聊天和审批，刷新会话可恢复已保存结果。

`web-shared` 是 `file:` 依赖；`.npmrc` 的 `install-links=true` 将其作为本地包复制安装，避免源目录无法解析 React。修改 vendor UI 后重新执行 `npm ci`，确保检查和运行使用最新代码。页面宽度可以保存于 localStorage，身份令牌不写入浏览器存储。

商家页面包含经营概览、分页目录和规格详情、库存健康、订单问题、营销计划/已批准促销、分页草案历史。目录、库存和经营图表标明报告窗口，操作日期使用真实 Shanghai 时间。营销预算是本地计划，支出与归因收入保持各自观察来源；未知收入不呈现为零或 ROAS=0。促销批准会修改实际价格，窗口结束后不会自动恢复。

`public/products/` 复用 vendored retail 的现有图片及 `IMAGE-CREDITS.md`，未新增远程素材或另一个站点。图片为空的商品使用组件缺省展示。此阶段不呈现尚未接通的买家或记忆管理入口。

HTTP 读取错误显式显示，不替换成空列表；401 清除内存登录，业务 409 保留分类（如未来促销仍待批准），仅实际会话繁忙显示等待提示。审批期间禁止新的聊天、审批和会话切换，“停止生成”中断当前 fetch，服务端继续沿现有断连清理保存状态；停止不撤销已经提交的结果，之后可刷新会话恢复。
