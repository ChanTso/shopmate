import assert from "node:assert/strict";
import test from "node:test";
import type { ChatItem } from "web-shared";
import type { StagedChange } from "../lib/types";
import { applyKnownChanges } from "../lib/change-state.ts";

test("a late staged card cannot overwrite the approved business receipt, including cards without changeIds", () => {
  const receipt = { change_id: "draft-1", status: "applied" } as StagedChange;
  const items: ChatItem[] = [
    {
      kind: "assistant",
      turn: 1,
      suggestions: [],
      pending: false,
      tools: [],
      segments: [
        {
          type: "ui",
          slotKey: "card-1",
          status: "final",
          block: {
            component: "change_preview",
            payload: { change_id: "draft-1", change: { status: "staged" } },
          },
        },
      ],
    },
  ];
  const updated = applyKnownChanges(items, { "draft-1": receipt });
  const item = updated[0];
  assert.equal(item.kind, "assistant");
  if (item.kind !== "assistant") throw new Error("Expected assistant");
  const segment = item.segments[0];
  assert.equal(segment.type, "ui");
  if (segment.type !== "ui") throw new Error("Expected card");
  assert.equal(
    (segment.block.payload as { change: StagedChange }).change,
    receipt,
  );
  assert.equal(item.suggestionsStale, true);
  assert.deepEqual(applyKnownChanges(items, {}), items);
  assert.notEqual(updated[0], items[0]);
});
