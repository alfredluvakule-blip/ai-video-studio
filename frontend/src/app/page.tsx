"use client";
import Link from "next/link";
import { Project, Usage, fmtDuration } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { ProgressBar, RenderProgress, StatusBadge } from "@/components/ui";

const busy = (p: Project) => ["storyboarding", "rendering", "assembling"].includes(p.status);

export default function Dashboard() {
  const { data: projects } = usePolling<Project[]>("/projects", (d) => !!d?.some(busy), 3000);
  const { data: usage } = usePolling<Usage>("/usage");
  const active = projects?.filter(busy) ?? [];

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="h1">Dashboard</h1>
          <p className="muted">Turn an idea, a script or your photos into a video up to one hour long.</p>
        </div>
        <Link href="/create" className="btn-primary px-5 py-3 text-base">＋ Create New Video</Link>
      </div>

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Videos completed" value={usage ? String(usage.videos_completed) : "–"} sub={usage ? `${usage.minutes_exported} min exported` : ""} />
        <Stat label="Projects" value={usage ? String(usage.projects) : "–"} />
        <div className="card space-y-2">
          <div className="label">Storage</div>
          <div className="text-2xl font-semibold text-white">{usage ? `${usage.storage_used_mb} MB` : "–"}</div>
          {usage && <ProgressBar value={usage.storage_used_mb} total={usage.storage_quota_mb} />}
          <div className="text-xs text-slate-500">{usage ? `of ${usage.storage_quota_mb} MB free storage` : ""}</div>
        </div>
        <div className="card space-y-2">
          <div className="label">Free render allowance</div>
          {usage?.limits.daily_render_minutes ? (
            <>
              <div className="text-2xl font-semibold text-white">{Math.max(0, usage.limits.daily_render_minutes - usage.rendered_last_24h_minutes).toFixed(1)} min</div>
              <ProgressBar value={usage.rendered_last_24h_minutes} total={usage.limits.daily_render_minutes} />
              <div className="text-xs text-slate-500">left in the last 24 h (of {usage.limits.daily_render_minutes} min). Self-host for no limit.</div>
            </>
          ) : (
            <>
              <div className="text-2xl font-semibold text-white">{usage ? "Unlimited" : "–"}</div>
              <div className="text-xs text-slate-500">Self-hosted: limited only by your hardware.</div>
            </>
          )}
        </div>
      </section>

      {active.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-white">Generation in progress</h2>
          {active.map((p) => (
            <Link key={p.id} href={`/projects/${p.id}`} className="card block space-y-3 hover:border-violet-500/40">
              <div className="flex items-center justify-between gap-2"><span className="font-medium text-white">{p.title}</span><StatusBadge status={p.status} /></div>
              <RenderProgress p={p} />
            </Link>
          ))}
        </section>
      )}

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Recent projects</h2>
          <Link href="/projects" className="text-sm text-violet-300 hover:underline">All projects</Link>
        </div>
        {projects && projects.length === 0 && (
          <div className="card text-center text-slate-400">No projects yet. <Link className="text-violet-300 underline" href="/create">Create your first video</Link>.</div>
        )}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects?.slice(0, 6).map((p) => (
            <Link key={p.id} href={`/projects/${p.id}`} className="card space-y-2 hover:border-violet-500/40">
              <div className="flex items-start justify-between gap-2">
                <span className="font-medium text-white">{p.title}</span>
                <StatusBadge status={p.status} />
              </div>
              <div className="text-xs text-slate-400">
                {p.mode} · {p.style} · {p.aspect} · {p.resolution}p · {p.progress.total} scenes · {fmtDuration(p.output_seconds || p.progress.planned_seconds)}
              </div>
            </Link>
          ))}
        </div>
      </section>

      {usage && <p className="text-xs text-slate-500">{usage.limits.paid_services}</p>}
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card space-y-1">
      <div className="label">{label}</div>
      <div className="text-2xl font-semibold text-white">{value}</div>
      {sub && <div className="text-xs text-slate-500">{sub}</div>}
    </div>
  );
}
