"use client";
import { type DependencyList, useEffect, useState } from "react";
import { UNREACHABLE } from "./http";

/** A different page or record must not keep the previous record's actionable content. */
export function useResource<T>(load: () => Promise<T | null>, deps: DependencyList) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setData(null); setError(null);
    void load().then(value => {
      if (cancelled) return;
      setData(value); if (value === null) setError(UNREACHABLE);
    }).catch(reason => { if (!cancelled) setError(reason instanceof Error ? reason.message : UNREACHABLE); });
    return () => { cancelled = true; };
    // Callers supply the request identity and refresh key as dependencies.
  }, deps);
  return { data, error, failed: error !== null };
}
