"use client";
import Link from "next/link";
import { Project, fmtDuration } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { StatusBadge } from "./ui";

export default function ProjectPicker({ title, intro, suffix }: { title: string; intro: string; suffix: string }) {
  const { data } = usePolling<Project[]>("/projects");
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h1 className="h1">{title}</h1><p className="muted max-w-2xl">{intro}</p></div>
        <Link href="/create" className="btn-primary">＋ New video</Link>
      </div>
      {data?.length === 0 && <div className="card text-slate-400">No projects yet.</div>}
      <div className="grid gap-3 md:grid-cols-2">
        {data?.map((p) => (
          <Link key={p.id} href={`/projects/${p.id}${suffix}`} className="card flex items-center justify-between gap-3 hover:border-violet-500/40">
            <div>
              <div className="font-medium text-white">{p.title}</div>
              <div className="text-xs text-slate-400">{p.progress.total} scenes · {fmtDuration(p.progress.planned_seconds)}</div>
            </div>
            <StatusBadge status={p.status} />
          </Link>
        ))}
      </div>
    </div>
  );
}
