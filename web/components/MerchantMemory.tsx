import { useState, type FormEvent } from "react";
import type { MemoryFact } from "web-shared";
import { Button } from "@/components/ui/button";
import { api, UNREACHABLE } from "@/lib/api";

function MemoryRow({
  fact,
  onChanged,
}: {
  fact: MemoryFact;
  onChanged: (key: string) => void;
}) {
  const [value, setValue] = useState(fact.value);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function save(event: FormEvent) {
    event.preventDefault();
    await write("PATCH");
  }
  async function write(method: "PATCH" | "DELETE") {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.requestJson(
        "/memory",
        method === "PATCH"
          ? { key: fact.key, value: value.trim() }
          : { key: fact.key },
        method,
      );
      onChanged(fact.key);
    } catch (error) {
      setError(error instanceof Error ? error.message : UNREACHABLE);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={save} className="space-y-2 rounded-xl border p-3">
      <label className="block text-xs font-medium">
        {fact.key}
        <input
          aria-label={`记忆 ${fact.key}`}
          required
          maxLength={200}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="mt-2 w-full rounded-lg border bg-(--ground) p-2 text-sm"
        />
      </label>
      <div className="flex gap-2">
        <Button
          type="submit"
          variant="outline"
          size="sm"
          disabled={busy || !value.trim() || value === fact.value}
        >
          保存修改
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={busy}
          onClick={() => void write("DELETE")}
        >
          忘记此条
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-xs text-(--danger)">
          {error}
        </p>
      )}
    </form>
  );
}
export default function MerchantMemory({
  facts,
  onChanged,
}: {
  facts: MemoryFact[];
  onChanged: (key: string) => void;
}) {
  return (
    <section className="space-y-3">
      <h3 className="font-semibold">当前操作员的经营记忆</h3>
      <p className="text-xs text-(--ink-soft)">
        用于持续理解偏好；价格、权限和订单状态仍以业务系统为准。
      </p>
      {facts.length ? (
        facts.map((fact) => (
          <MemoryRow
            key={`${fact.key}:${fact.value}`}
            fact={fact}
            onChanged={onChanged}
          />
        ))
      ) : (
        <p className="text-sm text-(--ink-soft)">暂无已保存的记忆。</p>
      )}
    </section>
  );
}
