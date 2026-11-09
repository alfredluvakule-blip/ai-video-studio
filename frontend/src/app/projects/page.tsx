"use client";
import Link from "next/link";
import { useState } from "react";
import { Project, api, fmtDuration, mediaUrl } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { ErrorNote, RenderProgress, StatusBadge } from "@/components/ui";

export default function Projects() {
  const { data, reload } = usePolling<Project[]>("/projects", (d) => !!d?.some((p) => ["storyboarding", "rendering", "assembling"].includes(p.status)), 3000);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  async function act(fn: () => Promise<unknown>) { setError(""); try { await fn(); await reload(); } catch (e) { setError((e as Error).message); } }
  const list = data?.filter((p) => p.title.toLowerCase().includes(q.toLowerCase())) ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="h1">My Projects</h1>
        <div className="flex gap-2">
          <input className="input w-56" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} />
          <Link href="/create" className="btn-primary">＋ New</Link>
        </div>
      </div>
      <ErrorNote error={error} />
      <div className="space-y-3">
        {list.map((p) => (
          <div key={p.id} className="card space-y-3">
            <div className="flex flex-wrap items-center gap-3">
              <Link href={`/projects/${p.id}`} className="font-medium text-white hover:underline">{p.title}</Link>
              <StatusBadge status={p.status} />
              <span className="text-xs text-slate-400">{p.mode} · {p.aspect} · {p.resolution}p · {p.progress.total} scenes · {fmtDuration(p.output_seconds || p.progress.planned_seconds)} · updated {new Date(p.updated_at).toLocaleString()}</span>
              <div className="ml-auto flex flex-wrap gap-2">
                <Link className="btn-ghost text-xs" href={`/projects/${p.id}`}>{p.progress.done < p.progress.total && p.progress.done > 0 ? "Resume" : "Open"}</Link>
                <Link className="btn-ghost text-xs" href={`/projects/${p.id}/editor`}>Edit</Link>
                {p.has_video && <a className="btn-ghost text-xs" href={mediaUrl(`/projects/${p.id}/download/video`)}>⬇ MP4</a>}
                {p.has_video && <a className="btn-ghost text-xs" href={mediaUrl(`/projects/${p.id}/download/srt`)}>SRT</a>}
                <button className="btn-ghost text-xs" onClick={() => act(() => api(`/projects/${p.id}/duplicate`, { method: "POST" }))}>Duplicate</button>
                <button className="btn-danger text-xs" onClick={() => confirm(`Delete "${p.title}"?`) && act(() => api(`/projects/${p.id}`, { method: "DELETE" }))}>Delete</button>
              </div>
            </div>
            <RenderProgress p={p} />
          </div>
        ))}
        {data && list.length === 0 && <div className="card text-slate-400">No projects found.</div>}
      </div>
    </div>
  );
}
