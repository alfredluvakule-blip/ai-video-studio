"use client";
import { useState } from "react";
import { Asset, Usage, api, mediaUrl } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { ErrorNote, ProgressBar } from "@/components/ui";

const FILTERS = ["all", "image", "video", "audio", "music"] as const;

export default function Media() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("all");
  const { data, reload } = usePolling<Asset[]>(filter === "all" ? "/media" : `/media?kind=${filter}`);
  const { data: usage, reload: reloadUsage } = usePolling<Usage>("/usage");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function upload(files: FileList | null, purpose?: string) {
    if (!files) return;
    setBusy(true); setError("");
    try {
      for (const f of Array.from(files)) {
        const fd = new FormData(); fd.append("file", f); if (purpose) fd.append("purpose", purpose);
        await api("/media", { form: fd });
      }
      await reload(); await reloadUsage();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div><h1 className="h1">Media Library</h1><p className="muted">Photos, video clips, voice recordings and music you own or have a licence for.</p></div>
        <div className="flex flex-wrap gap-2">
          <label className="btn-primary cursor-pointer">Upload media<input type="file" multiple hidden accept="image/*,video/*,audio/*" onChange={(e) => upload(e.target.files)} /></label>
          <label className="btn-ghost cursor-pointer">Upload music track<input type="file" hidden accept="audio/*" onChange={(e) => upload(e.target.files, "music")} /></label>
        </div>
      </div>
      {usage && (
        <div className="card space-y-2">
          <div className="flex justify-between text-sm"><span>Storage used</span><span>{usage.storage_used_mb} / {usage.storage_quota_mb} MB</span></div>
          <ProgressBar value={usage.storage_used_mb} total={usage.storage_quota_mb} />
          <p className="text-xs text-slate-500">Max {usage.limits.max_upload_mb} MB per file. Rendered videos count towards storage; delete old projects to free space.</p>
        </div>
      )}
      <ErrorNote error={error} />
      {busy && <p className="muted">Uploading…</p>}
      <div className="flex gap-2">{FILTERS.map((f) => <button key={f} className={`btn-ghost text-xs ${filter === f ? "bg-white/10" : ""}`} onClick={() => setFilter(f)}>{f}</button>)}</div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {data?.map((a) => (
          <div key={a.id} className="card space-y-2 p-3">
            {a.kind === "image" ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={mediaUrl(`/media/${a.id}/file`)} alt={a.filename} className="aspect-video w-full rounded-lg object-cover" />
            ) : a.kind === "video" ? (
              <video src={mediaUrl(`/media/${a.id}/file`)} controls preload="none" className="aspect-video w-full rounded-lg bg-black" />
            ) : (
              <audio src={mediaUrl(`/media/${a.id}/file`)} controls preload="none" className="w-full" />
            )}
            <div className="truncate text-sm text-white" title={a.filename}>{a.filename}</div>
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>{a.kind} · {(a.size_bytes / 1e6).toFixed(1)} MB</span>
              <button className="text-red-300 hover:underline" onClick={async () => { try { await api(`/media/${a.id}`, { method: "DELETE" }); await reload(); } catch (e) { setError((e as Error).message); } }}>Delete</button>
            </div>
          </div>
        ))}
      </div>
      {data?.length === 0 && <div className="card text-slate-400">Nothing here yet.</div>}
    </div>
  );
}
