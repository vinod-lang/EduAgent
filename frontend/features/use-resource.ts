"use client";
import { useCallback, useEffect, useState } from "react";
import { APIError } from "@/lib/api";
export function useResource<T>(load: (signal: AbortSignal) => Promise<T>) {
  const [data, setData] = useState<T | null>(null); const [error, setError] = useState<string | null>(null); const [loading, setLoading] = useState(true); const [generation, setGeneration] = useState(0);
  const retry = useCallback(() => setGeneration((value) => value + 1), []);
  useEffect(() => { const controller = new AbortController(); const run = async () => { setLoading(true); setError(null); setData(null); try { const value = await load(controller.signal); if (!controller.signal.aborted) setData(value); } catch (e) { if (!controller.signal.aborted) setError(e instanceof APIError ? e.message : "Cannot load this workspace. Check the connection and retry."); } finally { if (!controller.signal.aborted) setLoading(false); } }; void run(); return () => controller.abort(); }, [load, generation]);
  return { data, error, loading, retry };
}
