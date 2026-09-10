import type { ChatItem } from "web-shared";
import type { StagedChange } from "./types";

/** A delayed stream card must not replace an approval receipt already returned by Java. */
export function applyKnownChanges(
  items: ChatItem[],
  changes: Record<string, StagedChange>,
): ChatItem[] {
  return items.map((item) => {
    if (item.kind !== "assistant") return item;
    let changed = false;
    const segments = item.segments.map((segment) => {
      if (segment.type !== "ui" || segment.block.component !== "change_preview")
        return segment;
      const payload = segment.block.payload as { change_id?: string };
      const change = payload.change_id ? changes[payload.change_id] : undefined;
      if (!change) return segment;
      changed = true;
      return {
        ...segment,
        block: { ...segment.block, payload: { ...payload, change } },
      };
    });
    return changed ? { ...item, segments, suggestionsStale: true } : item;
  });
}
