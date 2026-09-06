import assert from "node:assert/strict";
import test from "node:test";
import { registerHooks } from "node:module";

// Native Node refuses TypeScript under node_modules; use the same vendored package source.
const hooks = registerHooks({ resolve(specifier, context, nextResolve) {
  if (specifier === "web-shared/api.ts") return { url: new URL("../../vendor/commerce-agents/examples/web-shared/api.ts", import.meta.url).href, shortCircuit: true };
  return nextResolve(specifier, context);
} });
const { ShopMateApi } = await import("../lib/api.ts");
hooks.deregister();

test("paged reads forward identity and query; server read failures reject rather than become empty pages", async () => {
  const original = globalThis.fetch;
  const api = new ShopMateApi("", "/api/merchant");
  api.setToken("test-only-token"); api.session = "session-one";
  try {
    globalThis.fetch = async (input, init) => {
      assert.equal(String(input), "/api/merchant/listings?query=desk+lamp&offset=24&limit=24");
      assert.equal(new Headers(init?.headers).get("Authorization"), "Bearer test-only-token");
      assert.equal(new Headers(init?.headers).get("X-Session-Id"), "session-one");
      assert.equal(init?.cache, "no-store");
      return new Response(JSON.stringify({ category: "unavailable", detail: "目录读取失败" }), { status: 503 });
    };
    await assert.rejects(api.get("/listings", { query: "desk lamp", offset: "24", limit: "24" }), /目录读取失败/);
  } finally { globalThis.fetch = original; }
});

test("stopping the actual chat fetch aborts its body and the next turn has a new controller", async () => {
  const original = globalThis.fetch;
  const api = new ShopMateApi("", "/api/merchant");
  let firstSignal: AbortSignal | undefined;
  try {
    globalThis.fetch = async (_, init) => {
      firstSignal = init?.signal as AbortSignal;
      return new Response(new ReadableStream({ start(controller) {
        controller.enqueue(new TextEncoder().encode('event: text_delta\ndata: {"text":"已读取部分商品"}\n\n'));
        firstSignal!.addEventListener("abort", () => controller.error(new DOMException("Aborted", "AbortError")), { once: true });
      } }));
    };
    const turn = api.chatStream("检查库存");
    assert.equal((await turn.next()).value?.type, "text_delta");
    const waiting = turn.next();
    api.stopChat();
    await assert.rejects(waiting, /已保存的业务结果不会撤销/);
    assert.equal(firstSignal?.aborted, true);
    globalThis.fetch = async (_, init) => {
      assert.notEqual(init?.signal, firstSignal);
      assert.equal(init?.signal?.aborted, false);
      return new Response('event: turn_complete\ndata: {}\n\n');
    };
    const next = await Array.fromAsync(api.chatStream("重新读取状态"));
    assert.equal(next[0].type, "turn_complete");
  } finally { api.stopChat(); globalThis.fetch = original; }
});

test("401 read expires login and clears the current session", async () => {
  const original = globalThis.fetch;
  const api = new ShopMateApi("", "/api/merchant");
  api.setToken("test-only-token"); api.session = "session-one";
  let cleared = false; api.onUnauthorized = () => { cleared = true; };
  try {
    globalThis.fetch = async () => new Response("{}", { status: 401 });
    await assert.rejects(api.get("/overview"), /重新登录/);
    assert.equal(cleared, true); assert.equal(api.session, null);
    assert.equal(new Headers(api.headers()).has("Authorization"), false);
  } finally { globalThis.fetch = original; }
});
