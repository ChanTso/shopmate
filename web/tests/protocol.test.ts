import assert from "node:assert/strict";
import test from "node:test";
import { readEventStream } from "../../vendor/commerce-agents/examples/web-shared/api.ts";

function stream(chunks: Uint8Array[], onCancel?: () => void) {
  return new ReadableStream<Uint8Array>({ start(controller) { for (const chunk of chunks) controller.enqueue(chunk); controller.close(); }, cancel: onCancel });
}

test("SSE preserves UTF-8 text and authoritative rejected receipt across arbitrary chunk boundaries", async () => {
  const receipt = { state: "REJECTED", result: { reason: "VERSION_CONFLICT" } };
  const body = new TextEncoder().encode('event: text_delta\ndata: {"text":"正在读取成交"}\n\nevent: change_update\ndata: ' + JSON.stringify({ change: { change_id: "draft-one", status: "rejected", receipt } }) + '\n\nevent: turn_complete\ndata: {}\n\n');
  const chunks = Array.from(body, byte => new Uint8Array([byte]));
  const events = await Array.fromAsync(readEventStream(stream(chunks)));
  assert.equal(events[0].data.text, "正在读取成交");
  assert.deepEqual(events[1].data.change, { change_id: "draft-one", status: "rejected", receipt });
  assert.equal(events[2].type, "turn_complete");
});

test("closing the event iterator cancels the underlying connection", async () => {
  let cancelled = false;
  const body = new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(new TextEncoder().encode('event: text_delta\ndata: {"text":"部分回复"}\n\n')); }, cancel() { cancelled = true; } });
  for await (const event of readEventStream(body)) { assert.equal(event.type, "text_delta"); break; }
  assert.equal(cancelled, true);
  assert.equal(body.locked, false);
});

test("server error is one terminal event, while an unexplained EOF is a disconnect", async () => {
  const { readChatEventStream } = await import("../../vendor/commerce-agents/examples/web-shared/api.ts");
  const encode = (value: string) => stream([new TextEncoder().encode(value)]);
  const events = await Array.fromAsync(readChatEventStream(encode('event: error\ndata: {"message":"Task deadline reached"}\n\n')));
  assert.deepEqual(events, [{ type: "error", data: { message: "Task deadline reached" } }]);
  await assert.rejects(Array.fromAsync(readChatEventStream(encode('event: text_delta\ndata: {"text":"部分回复"}\n\n'))), /连接已中断/);
  const complete = await Array.fromAsync(readChatEventStream(encode('event: turn_complete\ndata: {}\n\n')));
  assert.equal(complete[0].type, "turn_complete");
});

test("missing and partial provider usage cannot be displayed as measured totals", async () => {
  const { formatTurnUsage } = await import("../../vendor/commerce-agents/examples/web-shared/usage.ts");
  const sdkPlaceholders = { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0 };
  const provider = { usage_complete: false, model_calls: 2, calls_with_usage: 0, known_input_tokens: 0, known_output_tokens: 0, known_cache_read_input_tokens: 0 };
  assert.equal(formatTurnUsage({ usage: sdkPlaceholders, provider_usage: provider }), "usage unknown · 2 model calls");
  const measured = { ...provider, calls_with_usage: 1, known_input_tokens: 125, known_output_tokens: 30 };
  assert.equal(formatTurnUsage({ usage: sdkPlaceholders, provider_usage: measured }), "known in 125 · out 30 · cache read unknown · total unknown (1/2 calls reported)");
  assert.equal(formatTurnUsage({ provider_usage: { ...measured, usage_complete: true, calls_with_usage: 2 } }), "in 125 · out 30 · cache read unknown");
  const complete = { ...measured, usage_complete: true, calls_with_usage: 2 };
  assert.equal(formatTurnUsage({ provider_usage: { ...complete, cache_read_usage_complete: true, calls_with_cache_read_usage: 2 } }), "in 125 · out 30 · cache read 0");
  assert.equal(formatTurnUsage({ provider_usage: { ...complete, cache_read_usage_complete: false, calls_with_cache_read_usage: 1, known_cache_read_input_tokens: 20 } }), "in 125 · out 30 · cache read known 20 (1/2 calls reported; total unknown)");
});


test("an attached SQL table survives streamed chunks without dropping trailing rows or NULL", async () => {
  const { readChatEventStream } = await import("../../vendor/commerce-agents/examples/web-shared/api.ts");
  const rows = Array.from({ length: 87 }, (_, index) => [`sku-${index + 1}`, `商品 ${index + 1}`, "12.50", "CNY", null]);
  const payload = { metrics: [], analysis: { headline: "87 个商品", findings: [], caveats: [], table: { columns: ["sku", "name", "price", "currency", "unknown"], rows, row_count: 87, truncated: false } } };
  const bytes = new TextEncoder().encode(`event: ui\ndata: ${JSON.stringify({ component: "metrics", payload })}\n\nevent: turn_complete\ndata: {}\n\n`);
  const chunks = Array.from({ length: Math.ceil(bytes.length / 37) }, (_, index) => bytes.slice(index * 37, (index + 1) * 37));
  const events = await Array.fromAsync(readChatEventStream(stream(chunks)));
  assert.deepEqual(events[0], { type: "ui", data: { component: "metrics", payload } });
  assert.equal(events.at(-1)?.type, "turn_complete");
});
