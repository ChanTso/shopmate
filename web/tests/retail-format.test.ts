import assert from "node:assert/strict";
import test from "node:test";
import { campaignRoas, changeValue, localDateTime, windowLabel } from "../lib/retail-format.ts";
import type { Campaign } from "../lib/types.ts";

test("five-kind previews distinguish money, stock, booleans and literal text", () => {
  for (const field of ["price", "promotion_price", "budget"]) {
    assert.match(changeValue({ target: "sku", field }, 90, "CNY"), /[¥￥]90\.00/);
    assert.match(changeValue({ target: "sku", field }, 90, "USD"), /\$90\.00/);
  }
  assert.equal(changeValue({ target: "sku", field: "stock" }, 90, "CNY"), "90");
  assert.equal(changeValue({ target: "sku", field: "available" }, false, "CNY"), "否");
  assert.equal(changeValue({ target: "sku", field: "title" }, "0012", "CNY"), "0012");
  assert.equal(changeValue({ target: "sku", field: "copy_text" }, "第一行\n第二行", "CNY"), "第一行\n第二行");
  assert.equal(changeValue({ target: "sku", field: "budget" }, null, "CNY"), "未设置");
});

test("historical observation missingness and periods govern ROAS, not planned budget", () => {
  const campaign = { budgetMinor: 100000, spendMinor: 1000, revenueMinor: null, observationStart: "2026-08-01T00:00:00Z", observationEnd: "2026-09-01T00:00:00Z" } as Campaign;
  assert.equal(campaignRoas(campaign), "未知");
  assert.equal(campaignRoas({ ...campaign, revenueMinor: 0 }), "0.00×");
  assert.equal(campaignRoas({ ...campaign, revenueMinor: 2500 }), "2.50×");
  assert.equal(campaignRoas({ ...campaign, revenueMinor: 2500, budgetMinor: 900000 }), "2.50×");
  assert.equal(campaignRoas({ ...campaign, revenueMinor: 2500, observationEnd: null }), "未知");
  assert.equal(campaignRoas({ ...campaign, revenueMinor: 2500, spendMinor: 0 }), "未知");
});

test("Shanghai window labels preserve instants across UTC calendar boundaries", () => {
  const instant = "2026-09-04T16:00:00Z";
  assert.equal(localDateTime(instant), localDateTime("2026-09-05T00:00:00+08:00"));
  assert.notEqual(localDateTime(instant), localDateTime(instant, "UTC"));
  const label = windowLabel({ start: instant, end: "2026-09-05T16:00:00Z", timeZone: "Asia/Shanghai" });
  assert.match(label, /Asia\/Shanghai/);
  assert.match(label, /结束不含/);
});
