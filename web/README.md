# ShopMate merchant Web

A React + TypeScript + Vite single-page application, with Tailwind for styling and shadcn/ui for buttons, dialogs, and menus. The layout uses warm beige, ink black, and vermilion. Business cards, streaming contracts, and some merchant components reuse the existing `web-shared` package with its source license preserved. There is no Next service or server-side React rendering.

```sh
npm ci
npm run typecheck
npm test
npm run build
```

After building, restart the ShopMate API from the repository root and open `http://127.0.0.1:8101/`. Python serves the build entry point, hashed assets, and public product images; the browser calls same-origin `/api/merchant`. There is no separate production Node service. For development, `npm run dev` uses port 3100 and Vite proxies `/api` to 8101. `npm run start` previews static output only and does not provide business APIs.

## Operations and state

- Sign-in gives access to the overview, products, inventory, orders, and approvals without creating a chat. Opening the assistant creates a conversation; history uses `/conversations`.
- The bearer token stays in memory. After refreshing and signing in again, saved conversations can be restored. Ordinary requests omit `X-Session-Id`; chat explicitly uses `/conversations/{id}/chat`.
- Product, stock, promotion, and campaign changes first show their differences and require operator approval. The approval page is not blocked by model generation; authoritative receipts supersede late, stale draft cards in chat.
- Closing the assistant panel preserves the connection; stopping generation or signing out interrupts it. Reconnection reads saved state without assuming continuous background generation or approving committed operations again.
- Read errors are displayed explicitly, and 401 clears sign-in. Missing data remains unknown; historical sale prices, payment, refunds, and fulfillment are displayed separately. Refund requests do not mean funds arrived, promotions do not automatically restore prices at expiry, and campaign plans do not directly publish to external platforms.
- Memory and conversations are isolated by role and subject. The assistant panel supports viewing, editing, and forgetting memory. Web sources display only credential-free HTTP(S) citations actually supplied by the provider.

Images and credits in `public/products` are also used by Android. The buyer entry point is [native Android](../android/README.md); the old `/buyer` page and its components have left the build. A small amount of old browser transport code remains in `tests/fixtures` solely to preserve recovery-protocol regressions, not as an app entry point or runtime dependency.

`web-shared` is a local `file:` dependency; `.npmrc` sets `install-links=true` to copy the source package during installation. Run `npm ci` again after vendor changes. Common interactions reuse existing components; this project maintains the business-specific difference cards.
