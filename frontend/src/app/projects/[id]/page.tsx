"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Asset, Meta, Project, api, fmtDuration, mediaUrl } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import SceneCard from "@/components/SceneCard";
import { ErrorNote, RenderProgress, StatusBadge } from "@/components/ui";

const PAGE = 20;
const busy = (p?: Project) => !!p && ["storyboarding", "rendering", "assembling"].includes(p.status);

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data: p, reload, error: loadError } = usePolling<Project>(`/projects/${id}`, busy, 2500);
  const [meta, setMeta] = useState<Meta>();
  const [images, setImages] = useState<Asset[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [page, setPage] = useState(0);
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);

  useEffect(() => {
    api<Meta>("/meta").then(setMeta).catch(() => {});
    Promise.all([api<Asset[]>("/media?kind=image"), api<Asset[]>("/media?kind=video")]).then(([a, b]) => setImages([...a, ...b])).catch(() => {});
  }, []);

  const scenes = useMemo(() => p?.scenes ?? [], [p]);
  const pages = Math.max(1, Math.ceil(scenes.length / PAGE));
  const visible = scenes.slice(page * PAGE, page * PAGE + PAGE);

  async function act(fn: () => Promise<unknown>) {
    setWorking(true); setError("");
    try { await fn(); await reload(); } catch (e) { setError((e as Error).message); } finally { setWorking(false); }
  }

  if (loadError && !p) return <ErrorNote error={loadError} />;
  if (!p) return <p className="muted">Loading…</p>;

  const approved = scenes.filter((s) => s.approved).length;
  const overLimit = meta && p.progress.planned_seconds > meta.limits.max_project_minutes * 60;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-3"><h1 className="h1">{p.title}</h1><StatusBadge status={p.status} /></div>
          <p className="muted">
            Storyboard · {scenes.length} scenes · {fmtDuration(p.progress.planned_seconds)} planned · {p.style} · {p.aspect} · {p.resolution}p · {p.fps} fps
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href={`/projects/${p.id}/editor`} className="btn-ghost">✂ Open editor</Link>
          <button className="btn-ghost" disabled={working || busy(p)} onClick={() => confirm("Rewrite the storyboard? Your scene edits will be replaced.") && act(() => api(`/projects/${p.id}/storyboard`, { method: "POST" }))}>Rewrite storyboard</button>
        </div>
      </div>

      {p.notes.length > 0 && (
        <ul className="space-y-1 rounded-xl border border-amber-400/20 bg-amber-400/5 p-3 text-sm text-amber-100">
          {p.notes.map((n, i) => <li key={i}>• {n}</li>)}
        </ul>
      )}
      <ErrorNote error={error || p.error || ""} />
      {overLimit && <ErrorNote error={`This project is ${fmtDuration(p.progress.planned_seconds)}, over the ${meta?.limits.max_project_minutes}-minute limit. Delete or shorten scenes before rendering.`} />}

      {p.status === "storyboarding" && <div className="card animate-pulse text-slate-300">Writing the storyboard… this page updates by itself.</div>}

      {p.has_video && (
        <div className="card space-y-4">
          <video controls className="mx-auto max-h-[70vh] rounded-xl bg-black" src={mediaUrl(`/projects/${p.id}/download/video`, { inline: true, bust: p.updated_at })} />
          <div className="flex flex-wrap items-center gap-2">
            <a className="btn-primary" href={mediaUrl(`/projects/${p.id}/download/video`)}>⬇ Download MP4</a>
            <a className="btn-ghost" href={mediaUrl(`/projects/${p.id}/download/audio`)}>Audio only (.m4a)</a>
            <a className="btn-ghost" href={mediaUrl(`/projects/${p.id}/download/srt`)}>Subtitles (.srt)</a>
            <span className="text-xs text-slate-400">{fmtDuration(p.output_seconds)} · H.264 / AAC</span>
          </div>
        </div>
      )}

      {scenes.length > 0 && (
        <div className="card sticky top-14 z-[5] space-y-3 bg-[#11131c]/95 backdrop-blur lg:top-2">
          <div className="flex flex-wrap items-center gap-2">
            <button className="btn-primary" disabled={working || busy(p) || !!overLimit}
              onClick={() => act(() => api(`/projects/${p.id}/render`, { body: { approve_all: true } }))}>
              ▶ Approve all &amp; render
            </button>
            <button className="btn-ghost" disabled={working || busy(p) || !!overLimit || approved === 0}
              onClick={() => act(() => api(`/projects/${p.id}/render`, { body: { scene_ids: scenes.filter((s) => s.approved).map((s) => s.id) } }))}>
              Render approved ({approved})
            </button>
            <button className="btn-ghost" disabled={working || busy(p) || selected.size === 0}
              onClick={() => act(async () => {
                await Promise.all([...selected].map((sid) => api(`/scenes/${sid}`, { method: "PATCH", body: { approved: true } })));
                await api(`/projects/${p.id}/render`, { body: { scene_ids: [...selected] } });
                setSelected(new Set());
              })}>
              Render selected batch ({selected.size})
            </button>
            {(p.status === "failed" || (p.progress.done > 0 && p.progress.done < p.progress.total && !busy(p))) && (
              <button className="btn-ghost" disabled={working} onClick={() => act(() => api(`/projects/${p.id}/resume`, { method: "POST" }))}>↻ Resume</button>
            )}
            <button className="btn-ghost text-xs" onClick={() => act(() => api(`/projects/${p.id}/approve-all`, { method: "POST" }))}>Approve all</button>
            <button className="btn-ghost text-xs" onClick={() => setSelected(new Set(visible.map((s) => s.id)))}>Select page</button>
            {selected.size > 0 && <button className="btn-ghost text-xs" onClick={() => setSelected(new Set())}>Clear selection</button>}
          </div>
          <RenderProgress p={p} />
        </div>
      )}

      <div className="space-y-4">
        {visible.map((s) => (
          <SceneCard key={s.id} scene={s} cameras={meta?.cameras ?? [s.camera]} images={images}
            selected={selected.has(s.id)}
            onSelect={(v) => setSelected((x) => { const n = new Set(x); if (v) n.add(s.id); else n.delete(s.id); return n; })}
            onChanged={reload} onAssetAdded={(a) => setImages((x) => [a, ...x])} />
        ))}
      </div>

      {pages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <button className="btn-ghost" disabled={page === 0} onClick={() => setPage(page - 1)}>‹ Prev</button>
          <span className="text-sm text-slate-400">Scenes {page * PAGE + 1}–{Math.min(scenes.length, (page + 1) * PAGE)} of {scenes.length}</span>
          <button className="btn-ghost" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>Next ›</button>
        </div>
      )}

      <div className="flex flex-wrap gap-2 border-t border-white/10 pt-6">
        <button className="btn-ghost" onClick={() => act(async () => { const scene = await api<{ id: string }>(`/projects/${p.id}/scenes`, { body: { title: "New scene", duration: p.scene_seconds } }); return scene; })}>＋ Add scene</button>
        <button className="btn-ghost" onClick={() => act(async () => { const c = await api<Project>(`/projects/${p.id}/duplicate`, { method: "POST" }); router.push(`/projects/${c.id}`); })}>Duplicate project</button>
        <button className="btn-danger ml-auto" onClick={() => confirm("Delete this project and its rendered files?") && act(async () => { await api(`/projects/${p.id}`, { method: "DELETE" }); router.push("/projects"); })}>Delete project</button>
      </div>
    </div>
  );
}
