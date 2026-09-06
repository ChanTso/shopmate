"use client";
import { Button } from "web-shared";
export default function PageControls({ offset, nextOffset, pageSize, onPage }: { offset: number; nextOffset: number | null; pageSize: number; onPage: (value: number) => void }) {
  return <nav aria-label="列表分页" className="flex items-center justify-between gap-3 py-2"><Button variant="secondary" size="sm" disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - pageSize))}>上一页</Button><span className="text-xs text-(--ink-soft)">第 {Math.floor(offset / pageSize) + 1} 页</span><Button variant="secondary" size="sm" disabled={nextOffset === null} onClick={() => { if (nextOffset !== null) onPage(nextOffset); }}>下一页</Button></nav>;
}
