import assert from "node:assert/strict";
import test from "node:test";
import { ApiError, checkedResponse } from "../lib/http.ts";

const response = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

test("future promotion remains an actionable business conflict instead of session busy", async () => {
  await assert.rejects(checkedResponse(response(409, { category: "promotion_not_started", detail: "Promotion has not started" }), () => assert.fail("must not logout")), (error: unknown) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.category, "promotion_not_started");
    assert.match(error.message, /草案仍待批准/);
    assert.doesNotMatch(error.message, /会话正在运行/);
    return true;
  });
});

test("only actual session contention has the busy message; other conflicts retain their reason", async () => {
  await assert.rejects(checkedResponse(response(409, { detail: "Session is busy" }), () => {}), /会话正在运行/);
  await assert.rejects(checkedResponse(response(409, { category: "stale_quote", detail: "报价已变化，请核对最新价格。" }), () => {}), /报价已变化/);
  await assert.rejects(checkedResponse(response(503, { category: "unavailable", detail: "目录读取暂不可用" }), () => {}), /目录读取暂不可用/);
});

test("401 clears authentication and errors never become successful empty responses", async () => {
  let unauthorized = 0;
  await assert.rejects(checkedResponse(response(401, { detail: "invalid token" }), () => { unauthorized++; }), /重新登录/);
  assert.equal(unauthorized, 1);
  await assert.rejects(checkedResponse(new Response("gateway failure", { status: 502 }), () => {}), /502/);
  const good = response(200, { listings: [], next_offset: null });
  assert.equal(await checkedResponse(good, () => {}), good);
});
