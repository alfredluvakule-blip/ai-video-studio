"use client";
import { Project, STATUS_LABEL, fmtDuration } from "@/lib/api";

const STATUS_COLOR: Record<Project["status"], string> = {
  draft: "bg-slate-500/20 text-slate-300",
  storyboarding: "bg-sky-500/20 text-sky-300",
  storyboard_ready: "bg-amber-500/20 text-amber-200",
  rendering: "bg-violet-500/20 text-violet-200",
  assembling: "bg-violet-500/20 text-violet-200",
  done: "bg-emerald-500/20 text-emerald-300",
  failed: "bg-red-500/20 text-red-300",
};

export function StatusBadge({ status }: { status: Project["status"] }) {
  return <span className={`badge ${STATUS_COLOR[status]}`}>{STATUS_LABEL[status]}</span>;
}

export function ProgressBar({ value, total }: { value: number; total: number }) {
  const pct = total ? Math.round((value / total) * 100) : 0;
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-white/10" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
      <div className="h-full rounded-full bg-violet-500 transition-all" style={{ width: `${pct}%` }} />
    </div>
  );
}

/** Real progress only: counts of scenes the workers have finished. */
export function RenderProgress({ p }: { p: Project }) {
  const pr = p.progress;
  if (!["rendering", "assembling"].includes(p.status) && pr.done === 0) return null;
  return (
    <div className="space-y-1">
      <ProgressBar value={pr.done} total={pr.total} />
      <div className="flex flex-wrap justify-between gap-2 text-xs text-slate-400">
        <span>
          {pr.done}/{pr.total} scenes rendered{pr.rendering ? ` · ${pr.rendering} rendering` : ""}{pr.failed ? ` · ${pr.failed} failed` : ""}
          {p.status === "assembling" && " · stitching final video"}
        </span>
        {p.status === "rendering" && p.estimate.remaining_output_seconds > 0 && (
          <span title={p.estimate.basis}>≈ {fmtDuration(p.estimate.estimated_wall_seconds)} of render work left ({p.estimate.basis})</span>
        )}
      </div>
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <div>
      <span className="label">{label}</span>
      {children}
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

export function Select({ value, onChange, options, labels }: { value: string | number; onChange: (v: string) => void; options: (string | number)[]; labels?: Record<string, string> }) {
  return (
    <select className="input" value={value} onChange={(e) => onChange(e.target.value)}>
      {options.map((o) => <option key={o} value={o}>{labels?.[String(o)] ?? String(o).replace(/_/g, " ")}</option>)}
    </select>
  );
}

export function ErrorNote({ error }: { error: string }) {
  if (!error) return null;
  return <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">{error}</div>;
}
