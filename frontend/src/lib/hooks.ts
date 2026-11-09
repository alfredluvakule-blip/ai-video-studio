"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

/** Fetch a resource and re-fetch every `intervalMs` while `active(data)` is true. */
export function usePolling<T>(path: string | null, active: (d: T | undefined) => boolean = () => false, intervalMs = 2500) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState("");
  const activeRef = useRef(active);
  activeRef.current = active;

  const reload = useCallback(async () => {
    if (!path) return;
    try { setData(await api<T>(path)); setError(""); } catch (e) { setError((e as Error).message); }
  }, [path]);

  useEffect(() => { reload(); }, [reload]);
  useEffect(() => {
    const t = setInterval(() => { if (activeRef.current(data)) reload(); }, intervalMs);
    return () => clearInterval(t);
  }, [data, reload, intervalMs]);

  return { data, setData, error, reload };
}
