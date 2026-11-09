"use client";
import { useEffect, useState } from "react";
import { Asset, Scene, api, mediaUrl } from "@/lib/api";
import { Field, Select } from "./ui";

const SCENE_STATUS: Record<Scene["status"], string> = {
  draft: "bg-slate-500/20 text-slate-300", queued: "bg-sky-500/20 text-sky-300", rendering: "bg-violet-500/20 text-violet-200",
  done: "bg-emerald-500/20 text-emerald-300", failed: "bg-red-500/20 text-red-300",
};

export default function SceneCard({ scene, cameras, images, selected, onSelect, onChanged }: {
  scene: Scene; cameras: string[]; images: Asset[]; selected: boolean;
  onSelect: (v: boolean) => void; onChanged: () => void;
}) {
  const [s, setS] = useState(scene);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => setS(scene), [scene]);
  const locked = scene.status === "queued" || scene.status === "rendering";

  async function save(patch: Partial<Scene>) {
    setSaving(true); setErr("");
    try { await api(`/scenes/${scene.id}`, { method: "PATCH", body: patch }); onChanged(); }
    catch (e) { setErr((e as Error).message); } finally { setSaving(false); }
  }
  const text = (k: keyof Scene, label: string, rows = 2, hint?: string) => (
    <Field label={label} hint={hint}>
      <textarea className="input" rows={rows} disabled={locked} value={String(s[k] ?? "")}
        onChange={(e) => setS({ ...s, [k]: e.target.value })}
        onBlur={() => { if (s[k] !== scene[k]) save({ [k]: s[k] } as Partial<Scene>); }} />
    </Field>
  );

  async function uploadVoice(file: File | undefined) {
    if (!file) return;
    const fd = new FormData(); fd.append("file", file);
    try { const a = await api<Asset>("/media", { form: fd }); await save({ voice_asset_id: a.id }); }
    catch (e) { setErr((e as Error).message); }
  }

  return (
    <div className={`card space-y-4 ${selected ? "border-violet-500/60" : ""}`}>
      <div className="flex flex-wrap items-center gap-3">
        <input type="checkbox" checked={selected} onChange={(e) => onSelect(e.target.checked)} aria-label={`Select scene ${scene.position + 1}`} />
        <span className="font-semibold text-white">Scene {scene.position + 1}</span>
        <span className={`badge ${SCENE_STATUS[scene.status]}`}>{scene.status}</span>
        <span className="text-xs text-slate-400">{(scene.clip_seconds || scene.duration).toFixed(1)}s</span>
        {scene.provider_used && <span className="text-xs text-slate-500">via {scene.provider_used}</span>}
        <div className="ml-auto flex items-center gap-2">
          {saving && <span className="text-xs text-slate-500">Saving…</span>}
          <label className="flex items-center gap-1 text-sm">
            <input type="checkbox" checked={scene.approved} disabled={locked} onChange={(e) => save({ approved: e.target.checked })} /> Approved
          </label>
          <button className="btn-ghost text-xs" disabled={locked} onClick={async () => {
            try { await api(`/scenes/${scene.id}/regenerate`, { method: "POST" }); onChanged(); } catch (e) { setErr((e as Error).message); }
          }}>{scene.status === "done" ? "Regenerate" : scene.status === "failed" ? "Retry" : "Render this"}</button>
        </div>
      </div>
      {scene.error && <p className="rounded-lg bg-red-500/10 p-2 text-xs text-red-300">{scene.error}</p>}
      {err && <p className="text-xs text-red-300">{err}</p>}

      <div className="grid gap-4 md:grid-cols-[220px_1fr]">
        <div className="space-y-2">
          {scene.has_clip ? (
            <video controls preload="none" className="w-full rounded-lg bg-black" poster={scene.has_image ? mediaUrl(`/scenes/${scene.id}/image`, { bust: String(scene.attempts) }) : undefined}
              src={mediaUrl(`/scenes/${scene.id}/clip`, { bust: String(scene.attempts) })} />
          ) : scene.image_asset_id ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={mediaUrl(`/media/${scene.image_asset_id}/file`)} alt="" className="w-full rounded-lg object-cover" />
          ) : (
            <div className="grid aspect-video place-items-center rounded-lg bg-black/40 text-xs text-slate-500">Not rendered yet</div>
          )}
          <Field label="Image / video reference">
            <select className="input" disabled={locked} value={scene.image_asset_id ?? ""} onChange={(e) => save({ image_asset_id: e.target.value || null })}>
              <option value="">Generate from prompt</option>
              {images.map((a) => <option key={a.id} value={a.id}>{a.filename}</option>)}
            </select>
          </Field>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Duration (s)">
              <input className="input" type="number" min={1} max={120} step={0.5} disabled={locked} value={s.duration}
                onChange={(e) => setS({ ...s, duration: Number(e.target.value) })} onBlur={() => s.duration !== scene.duration && save({ duration: s.duration })} />
            </Field>
            <Field label="Camera"><Select value={scene.camera} options={cameras} onChange={(v) => save({ camera: v })} /></Field>
          </div>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          {text("title", "Title", 1)}
          {text("visual_description", "Visual description")}
          {text("character", "Characters", 2, "Repeat the same description in every scene to keep characters consistent.")}
          {text("dialogue", "Dialogue")}
          <div className="md:col-span-2">{text("voiceover", "Voice-over (spoken by the narrator)", 3)}</div>
          {text("prompt", "AI generation prompt", 2)}
          {text("sound_effects", "Sound effects", 2, "Saved for planning. Automatic sound-effect generation is planned, not yet built.")}
          <div className="md:col-span-2 flex flex-wrap items-center gap-3 text-xs text-slate-400">
            <span>Custom voice recording:</span>
            {scene.voice_asset_id ? (
              <>
                <audio controls preload="none" src={mediaUrl(`/media/${scene.voice_asset_id}/file`)} className="h-8" />
                <button className="text-red-300 underline" disabled={locked} onClick={() => save({ voice_asset_id: null })}>Use TTS instead</button>
              </>
            ) : (
              <input type="file" accept="audio/*" disabled={locked} onChange={(e) => uploadVoice(e.target.files?.[0])} className="text-xs" />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
