import assert from "node:assert/strict";
import test from "node:test";
import { registerHooks } from "node:module";
import { POLICY_TOPICS, policySearchQuery } from "../lib/buyer-policy-search.ts";

const hooks = registerHooks({ resolve(specifier, context, nextResolve) {
  if (specifier === "web-shared/api.ts") return { url: new URL("../../vendor/commerce-agents/examples/web-shared/api.ts", import.meta.url).href, shortCircuit: true };
  return nextResolve(specifier, context);
} });
const { BuyerApi } = await import("../lib/buyer-api.ts");
hooks.deregister();

test("policy keywords reject empty, oversized and more-than-eight-word queries with visible guidance", () => {
  for (const input of ["", "   ", "\t\n"]) assert.throws(() => policySearchQuery(input), /输入政策关键词/);
  assert.throws(() => policySearchQuery("退".repeat(201)), /200 个字符/);
  assert.throws(() => policySearchQuery("one two three four five six seven eight nine"), /8 个/);
  assert.equal(policySearchQuery("  退款  "), "退款");
  assert.equal(policySearchQuery("退".repeat(200)).length, 200);
  assert.equal(policySearchQuery("one two three four five six seven eight").split(" ").length, 8);
});

test("policy topic shortcuts use searchable published language, including English buying guides", () => {
  for (const topic of POLICY_TOPICS) assert.equal(policySearchQuery(topic.query), topic.query);
  assert.equal(POLICY_TOPICS.find(topic => topic.label === "配送与运费")?.query, "配送");
  assert.deepEqual(POLICY_TOPICS.filter(topic => topic.label.endsWith("指南")).map(topic => topic.query), ["tent", "coffee", "desk"]);
});

test("explicit policy reads encode the chosen query and keep no matches distinct from HTTP failure", async () => {
  const original = globalThis.fetch;
  const api = new BuyerApi("", "/api/buyer");
  api.session = "buyer-session";
  api.setToken("buyer-test-token");
  try {
    globalThis.fetch = async (input, init) => {
      assert.equal(String(input), "/api/buyer/policies?query=%E9%80%80%E6%AC%BE");
      assert.equal(new Headers(init?.headers).get("X-Session-Id"), "buyer-session");
      return Response.json({ policies: [] });
    };
    assert.deepEqual(await api.get("/policies", { query: policySearchQuery("  退款 ") }), { policies: [] });
    globalThis.fetch = async () => Response.json({ detail: "政策暂时无法读取" }, { status: 503 });
    await assert.rejects(api.get("/policies", { query: policySearchQuery("配送") }), /政策暂时无法读取/);
  } finally { globalThis.fetch = original; }
});
