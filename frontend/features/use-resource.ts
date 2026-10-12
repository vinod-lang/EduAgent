"use client";
import { useCallback, useEffect, useState } from "react";
import {useActionFeedback} from "@/components/action-feedback";
import { APIError } from "@/lib/api";
export function useResource<T>(load: (signal: AbortSignal) => Promise<T>) {
  const {begin,finish}=useActionFeedback();
  const [data, setData] = useState<T | null>(null); const [error, setError] = useState<string | null>(null); const [loading, setLoading] = useState(true); const [generation, setGeneration] = useState(0);
  const retry = useCallback(() => setGeneration((value) => value + 1), []);
  useEffect(() => { const controller = new AbortController(); const run = async () => { const id=generation>0?begin("Refreshing workspace…"):null; setLoading(true); setError(null); setData(null); try { const value = await load(controller.signal); if (!controller.signal.aborted) {setData(value);if(id!==null)finish(id,"Workspace refreshed.");} } catch (e) { if (!controller.signal.aborted) {setError(e instanceof APIError ? e.message : "Cannot load this workspace. Check the connection and retry.");if(id!==null)finish(id,"Workspace refresh failed.",true);} } finally { if (!controller.signal.aborted) setLoading(false); } }; void run(); return () => controller.abort(); }, [load, generation,begin,finish]);
  return { data, error, loading, retry };
}
