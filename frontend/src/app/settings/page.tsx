"use client";
import { useEffect, useState } from "react";
import { API_URL, Usage, api } from "@/lib/api";

type Prov = {
  writers: { name: string; label: string; available: boolean; active: boolean }[];
  visuals: { name: string; label: string; available: boolean; is_ai: boolean; active: boolean }[];
  video_model: { label: string; available: boolean; note: string };
  tts: { name: string; label: string; available: boolean; languages: string[] }[];
  whisper: { available: boolean; model: string };
  ffmpeg: boolean; queue: { backend: string; ok: boolean; error?: string }; planned: string[];
};

const Dot = ({ ok }: { ok: boolean }) => <span className={`inline-block h-2 w-2 rounded-full ${ok ? "bg-emerald-400" : "bg-slate-600"}`} />;

export default function Settings() {
  const [p, setP] = useState<Prov>();
  const [u, setU] = useState<Usage>();
  useEffect(() => { api<Prov>("/providers").then(setP).catch(() => {}); api<Usage>("/usage").then(setU).catch(() => {}); }, []);

  return (
    <div className="space-y-6">
      <div><h1 className="h1">Settings</h1><p className="muted">What this server can generate right now, and the limits that apply. Providers are configured with environment variables on the server (see README).</p></div>

      <section className="card space-y-3">
        <h2 className="font-semibold text-white">Free usage</h2>
        {u && (
          <ul className="space-y-1 text-sm text-slate-300">
            <li>Max video length per project: <b>{u.limits.max_project_minutes} minutes</b></li>
            <li>Storage: <b>{u.storage_used_mb} / {u.storage_quota_mb} MB</b></li>
            <li>Rendering on this server: <b>{u.limits.daily_render_minutes ? `${u.limits.daily_render_minutes} min of output per 24 h` : "no daily cap (self-hosted)"}</b></li>
            <li>Measured render speed: <b>{u.render_speed_ratio ? `${u.render_speed_ratio.toFixed(2)} s of compute per second of video` : "not measured yet"}</b></li>
            <li className="text-slate-400">{u.limits.paid_services}</li>
          </ul>
        )}
      </section>

      {p && (
        <>
          <section className="card space-y-3">
            <h2 className="font-semibold text-white">Visual generation</h2>
            {p.visuals.map((v) => (
              <div key={v.name} className="flex items-center gap-2 text-sm"><Dot ok={v.available} />{v.label}{v.active && <span className="badge bg-violet-500/20 text-violet-200">in use</span>}{!v.is_ai && <span className="badge bg-white/5 text-slate-400">not AI</span>}</div>
            ))}
            <div className="flex items-center gap-2 text-sm"><Dot ok={p.video_model.available} />{p.video_model.label}</div>
            <p className="text-xs text-slate-500">{p.video_model.note}</p>
          </section>
          <section className="card space-y-3">
            <h2 className="font-semibold text-white">Script & storyboard writer</h2>
            {p.writers.map((w) => <div key={w.name} className="flex items-center gap-2 text-sm"><Dot ok={w.available} />{w.label}{w.active && <span className="badge bg-violet-500/20 text-violet-200">in use</span>}</div>)}
          </section>
          <section className="card space-y-3">
            <h2 className="font-semibold text-white">Voice (all local and free)</h2>
            {p.tts.map((t) => <div key={t.name} className="flex items-center gap-2 text-sm"><Dot ok={t.available} />{t.label}{t.available && <span className="text-xs text-slate-500">({t.languages.join(", ")})</span>}</div>)}
            <div className="flex items-center gap-2 text-sm"><Dot ok={p.whisper.available} />Whisper subtitles for uploaded recordings ({p.whisper.model})</div>
          </section>
          <section className="card space-y-3">
            <h2 className="font-semibold text-white">System</h2>
            <div className="flex items-center gap-2 text-sm"><Dot ok={p.ffmpeg} />FFmpeg</div>
            <div className="flex items-center gap-2 text-sm"><Dot ok={p.queue.ok} />Job queue: {p.queue.backend}{p.queue.error ? ` (${p.queue.error})` : ""}</div>
            <div className="text-xs text-slate-500">API: {API_URL}</div>
          </section>
          <section className="card space-y-2">
            <h2 className="font-semibold text-white">Planned (not built yet)</h2>
            <ul className="list-disc pl-5 text-sm text-slate-400">{p.planned.map((x) => <li key={x}>{x}</li>)}</ul>
          </section>
        </>
      )}
    </div>
  );
}
