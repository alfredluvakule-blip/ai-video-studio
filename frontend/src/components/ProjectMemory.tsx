"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { MemoryItem, api } from "@/lib/api";

/** Project memory: the characters, places and style the AI Director fixed for this project. */
export default function ProjectMemory({ projectId, onScenesChanged }: { projectId: string; onScenesChanged: () => void }) {
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [planId, setPlanId] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api<{ items: MemoryItem[]; plan_id: string | null }>(`/projects/${projectId}/memory`)
      .then((r) => { setItems(r.items); setPlanId(r.plan_id); }).catch(() => {});
  }, [projectId]);
  useEffect(() => { load(); }, [load]);

  async function save(m: MemoryItem, patch: Record<string, unknown>) {
    setError(""); setNote("");
    try {
      const r = await api<MemoryItem & { scenes_updated: number }>(`/memory/${m.id}`, { method: "PATCH", body: patch });
      if (r.scenes_updated) { setNote(`Updated ${r.scenes_updated} scene(s); they will render again.`); onScenesChanged(); }
      load();
    } catch (e) { setError((e as Error).message); }
  }

  if (!items.length) return null;
  return (
    <details className="card space-y-3">
      <summary className="cursor-pointer font-semibold text-white">
        Project memory <span className="text-xs font-normal text-slate-400">{items.length} items · characters, places and style kept the same in every scene</span>
      </summary>
      <p className="text-xs text-slate-400">
        Change a locked character&apos;s look or a place here and every scene that uses it is updated.
        {planId && <> <Link className="text-violet-300 hover:underline" href={`/director/${planId}`}>See the AI Director&apos;s plan</Link>.</>}
      </p>
      {note && <p className="text-sm text-emerald-300">{note}</p>}
      {error && <p className="text-sm text-red-300">{error}</p>}
      <div className="space-y-2">
        {items.map((m) => <Row key={m.id + m.updated_at} m={m} save={save} />)}
      </div>
    </details>
  );
}

function Row({ m, save }: { m: MemoryItem; save: (m: MemoryItem, patch: Record<string, unknown>) => void }) {
  const [appearance, setAppearance] = useState(String(m.data.appearance ?? ""));
  const [clothing, setClothing] = useState(String(m.data.clothing ?? ""));
  const [description, setDescription] = useState(m.description);
  return (
    <div className="grid gap-2 rounded-xl border border-white/10 p-2 text-sm md:grid-cols-[10rem_1fr_auto]">
      <div><span className="badge mr-1 bg-white/10 text-slate-300">{m.kind}</span><span className="text-white">{m.name}</span></div>
      {m.kind === "character" ? (
        <div className="grid gap-2 md:grid-cols-2">
          <input className="input" value={appearance} aria-label="Appearance" onChange={(e) => setAppearance(e.target.value)} onBlur={() => appearance !== m.data.appearance && save(m, { appearance })} />
          <input className="input" value={clothing} aria-label="Clothing" onChange={(e) => setClothing(e.target.value)} onBlur={() => clothing !== m.data.clothing && save(m, { clothing })} />
        </div>
      ) : (
        <input className="input" value={description} aria-label="Description" onChange={(e) => setDescription(e.target.value)} onBlur={() => description !== m.description && save(m, { description })} />
      )}
      <label className="flex items-center gap-1 text-xs text-slate-300">
        <input type="checkbox" checked={m.locked} onChange={(e) => save(m, { locked: e.target.checked })} /> Locked
      </label>
    </div>
  );
}
