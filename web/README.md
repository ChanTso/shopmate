# ShopMate 商家 Web

React + TypeScript + Vite 单页应用，Tailwind 管理视觉样式，shadcn/ui 用于按钮、对话框和菜单。页面布局采用暖米色、墨黑与朱红，业务卡片、流式协议和部分经营组件复用现有 `web-shared`；来源许可证保留。没有 Next 服务或服务端 React 渲染。

```sh
npm ci
npm run typecheck
npm test
npm run build
```

构建完成后重启项目根目录的 ShopMate API，访问 `http://127.0.0.1:8101/`。Python 只提供构建入口、哈希静态资源和公共商品图片，浏览器调用同源 `/api/merchant`；不存在另一个生产 Node 服务。开发时 `npm run dev` 使用 3100 端口，Vite 将 `/api` 代理到 8101。`npm run start` 仅预览静态构建，不提供业务 API。

## 操作与状态

- 登录后即可查看经营概览、商品、库存、订单及审批，不创建聊天。打开助手才创建对话，历史列表使用 `/conversations`。
- Bearer 仅保存在内存中；刷新重新登录后，可从历史对话恢复。普通请求不发送 `X-Session-Id`，聊天显式使用 `/conversations/{id}/chat`。
- 商品、库存、促销、营销计划的修改都先展示差异，由操作员批准。审批页不受模型生成锁阻塞；服务器返回的回执覆盖聊天里迟到的旧草案卡。
- 关闭助手面板保留当前连接；停止生成或退出登录中断连接。断线恢复读取保存的状态，不宣称后台持续生成，也不重新批准已提交的操作。
- 读取错误显式呈现，401 清除登录；数据缺失保留未知，历史成交价、付款、退款和履约分别显示。退款申请不表示到账，促销到期不自动恢复价格，营销计划不直接投放外部平台。
- 记忆与对话按角色和主体隔离，助手面板支持查看、修改和忘记记忆。网页来源只展示代理实际提供的无凭证 HTTP(S) 引用。

`public/products` 图片及来源文件同时供 Android 使用。买家正式入口是 [原生 Android](../android/README.md)，旧 `/buyer` 页面及其组件已退出构建。少量旧浏览器传输代码保存在 `tests/fixtures`，仅用于保留原有恢复协议回归测试，不是应用入口或运行依赖。

`web-shared` 为本地 `file:` 依赖，`.npmrc` 的 `install-links=true` 复制安装源包。修改 vendor 后重新 `npm ci`。通用交互没有重新造组件框架，业务差异卡仍由本项目维护。
