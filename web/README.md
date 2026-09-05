# ShopMate 工作台

复用 `vendor/commerce-agents/examples/retail/merchant-web` 与 `examples/web-shared` 的 Next、PortalShell、聊天流和卡片交互。许可证和原始版权声明保留在 vendor 及复制文件中。

```sh
cd web
npm ci
npm run typecheck
npm test
npm run build
SHOPMATE_API_URL=http://127.0.0.1:8000 npm run dev
```

访问 `http://127.0.0.1:3100`。浏览器请求同源 `/api/merchant`；Next 根据 `SHOPMATE_API_URL` 转发至 Python host。生产构建时也要设置此变量，因为 rewrites 在构建时确定。

登录使用 CityBuddy Auth 操作员账号。Bearer 只保留在页面内存，刷新需重新登录，然后恢复已持久化会话。会话 ID 随 `X-Session-Id` 发送。草案批准/取消直接调用 host 操作端点；聊天文字不能批准调价。运行中的会话禁止新的聊天和审批，刷新会话可恢复已保存结果。

`web-shared` 是 `file:` 依赖；`.npmrc` 的 `install-links=true` 将其作为本地包复制安装，避免源目录无法解析 React。修改 vendor UI 后重新执行 `npm ci`，确保检查和运行使用最新代码。页面宽度可以保存于 localStorage，身份令牌不写入浏览器存储。
