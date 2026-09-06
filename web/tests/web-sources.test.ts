import assert from "node:assert/strict";
import test from "node:test";
import { sourceLinks } from "../lib/web-sources.ts";
import { memoryNotice } from "../../vendor/commerce-agents/examples/web-shared/memory-status.ts";

test("source links accept absolute HTTP(S) metadata and preserve citation numbering", () => {
  const links = sourceLinks([
    { url: "https://docs.example.com/retail?q=1#policy", title: "商品政策" },
    { url: "javascript:alert(1)", title: "不可用" },
    { url: "http://example.com/details", title: "" },
  ]);
  assert.deepEqual(links.map(link => [link.number, link.href, link.title]), [
    [1, "https://docs.example.com/retail?q=1#policy", "商品政策"],
    [3, "http://example.com/details", "example.com"],
  ]);
});

test("credentials, control characters, relative URLs and active schemes never become links", () => {
  const urls = ["https://operator:secret@example.com/", "https://operator@example.com/", "https://operator%40example.com@other.example/", "https://example.com/\nnext", "//example.com", "/policy", "data:text/html,hi", "file:///etc/passwd", "javascript:alert(1)", "https://", " https://example.com"];
  assert.deepEqual(sourceLinks(urls.map(url => ({ url, title: "external" }))), []);
});

test("citations and consulted sources stay separate; absent metadata invents no source", () => {
  const citations = [{ url: "https://example.com/cited", title: "引用" }];
  assert.equal(sourceLinks(citations).length, 1);
  assert.deepEqual(sourceLinks([]), []);
  assert.deepEqual(sourceLinks(citations).map(link => link.href), ["https://example.com/cited"]);
});

test("memory failure and revocation survive the same JSON shape as restored replies", () => {
  for (const status of ["unavailable", "revoked"]) {
    const item = JSON.parse(JSON.stringify({ kind: "assistant", memory_status: status }));
    assert.equal(memoryNotice(item.memory_status), memoryNotice(status));
    assert.ok(memoryNotice(item.memory_status));
  }
  assert.match(memoryNotice("unavailable")!, /未保存/);
  assert.match(memoryNotice("revoked")!, /不会恢复已清除/);
  for (const status of ["saved", "unchanged", "disabled", undefined, "future_state"]) assert.equal(memoryNotice(status), null);
});
