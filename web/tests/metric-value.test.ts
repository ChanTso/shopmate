import assert from "node:assert/strict";
import test from "node:test";
import { metricValue } from "../lib/metric-value.ts";

test("analysis sales uses explicit USD and preserves currency precision", () => {
  assert.equal(metricValue({ metric: "sales", value: 280, unit: "USD", currency: "USD" }, true), "$280.00");
  assert.equal(metricValue({ metric: "sales", value: 1280.35, unit: "USD", currency: "USD" }, true), "$1,280.35");
  assert.equal(metricValue({ metric: "sales", value: 280, unit: "CNY", currency: "CNY" }, true), "CN¥280.00");
});

test("analysis units override metric-name heuristics and missing units remain unspecified", () => {
  assert.equal(metricValue({ metric: "sales", value: 12.5, unit: "%" }, true), "12.5%");
  assert.equal(metricValue({ metric: "sales", value: 28, unit: "件" }, true), "28 件");
  assert.equal(metricValue({ metric: "conversion_rate", value: 28, unit: "件" }, true), "28 件");
  assert.equal(metricValue({ metric: "sales", value: 280, unit: null }, true), "280");
  assert.equal(metricValue({ metric: "sales", value: 280 }, true), "280");
});

test("ordinary snapshots retain their currency and percent conventions", () => {
  assert.equal(metricValue({ metric: "sales", value: 280, currency: "USD" }), "$280.00");
  assert.equal(metricValue({ metric: "sales", value: 280, currency: "CNY" }), "CN¥280.00");
  assert.equal(metricValue({ metric: "conversion_rate", value: 3.4 }), "3.4%");
  assert.equal(metricValue({ metric: "sales", value: null, currency: "USD" }), null);
});
