"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Asset, Meta, api, fmtDuration, mediaUrl } from "@/lib/api";
import { ErrorNote, Field, Select } from "./ui";

type Mode = "text" | "image" | "script";

const INTRO: Record<Mode, { title: string; text: string }> = {
  text: { title: "Text to Video", text: "Describe your video. The storyboard writer turns it into timed scenes with narration, which you review before anything renders." },
  image: { title: "Image to Video", text: "Upload photos. Each photo becomes an animated scene with camera motion, narration and subtitles." },
  script: { title: "Script to Video", text: "Paste a full script. It is split into scenes, given visuals and narration, and assembled into one video." },
};

const PRESETS: { label: string; v: Partial<Form> }[] = [
  { label: "YouTube long-form", v: { aspect: "16:9", resolution: 1080, target_seconds: 600 } },
  { label: "TikTok / Reels", v: { aspect: "9:16", resolution: 720, target_seconds: 45, scene_seconds: 5 } },
  { label: "Instagram square", v: { aspect: "1:1", resolution: 720, target_seconds: 60 } },
  { label: "Children's education", v: { style: "cartoon", narration_style: "children", music: "upbeat" } },
  { label: "Health education", v: { style: "educational", narration_style: "calm", music: "calm" } },
  { label: "Documentary", v: { style: "documentary", narration_style: "documentary", music: "documentary" } },
  { label: "Storytelling", v: { style: "storytelling", narration_style: "storytelling", music: "ambient" } },
];

type Form = {
  title: string; prompt: string; script: string; style: string; aspect: string; resolution: number; fps: number;
  target_seconds: number; scene_seconds: number; language: string; voice: string; narration_style: string;
  music: string; burn_subtitles: boolean; compression: string; visual_provider: string;
};

export default function CreateForm({ mode }: { mode: Mode }) {
  const router = useRouter();
  const [meta, setMeta] = useState<Meta>();
  const [music, setMusic] = useState<Asset[]>([]);
  const [images, setImages] = useState<Asset[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [f, setF] = useState<Form>({
    title: "", prompt: "", script: "", style: "cinematic", aspect: "16:9", resolution: 720, fps: 25,
    target_seconds: 60, scene_seconds: 10, language: "en", voice: "female", narration_style: "neutral",
    music: "ambient", burn_subtitles: false, compression: "balanced", visual_provider: "auto",
  });
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((o) => ({ ...o, [k]: v }));

  useEffect(() => {
    api<Meta>("/meta").then(setMeta).catch((e) => setError(e.message));
    api<Asset[]>("/media?kind=music").then(setMusic).catch(() => {});
  }, []);

  async function upload(files: FileList | null) {
    if (!files) return;
    setUploading(true); setError("");
    try {
      for (const file of Array.from(files)) {
        const fd = new FormData(); fd.append("file", file);
        const a = await api<Asset>("/media", { form: fd });
        setImages((x) => [...x, a]);
      }
    } catch (e) { setError((e as Error).message); } finally { setUploading(false); }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      const p = await api<{ id: string }>("/projects", {
        body: { ...f, mode, title: f.title || (f.prompt || "Untitled video").slice(0, 60), asset_ids: images.map((i) => i.id) },
      });
      router.push(`/projects/${p.id}`);
    } catch (e) { setError((e as Error).message); setBusy(false); }
  }

  const sceneCount = mode === "image" ? images.length : Math.max(1, Math.round(f.target_seconds / f.scene_seconds));

  return (
    <form onSubmit={submit} className="space-y-6">
      <div>
        <h1 className="h1">{INTRO[mode].title}</h1>
        <p className="muted max-w-3xl">{INTRO[mode].text}</p>
      </div>

      <div className="flex flex-wrap gap-2">
        {PRESETS.map((p) => (
          <button type="button" key={p.label} className="btn-ghost text-xs" onClick={() => setF((o) => ({ ...o, ...p.v }))}>{p.label}</button>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="card space-y-4 lg:col-span-2">
          <Field label="Title">
            <input className="input" value={f.title} onChange={(e) => set("title", e.target.value)} placeholder="My video" maxLength={200} />
          </Field>
          {mode === "image" && (
            <Field label={`Photos (${images.length})`} hint="Each photo becomes one scene, in upload order. JPG, PNG or WebP.">
              <input type="file" accept="image/*" multiple className="input" onChange={(e) => upload(e.target.files)} disabled={uploading} />
              {images.length > 0 && (
                <div className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-5">
                  {images.map((a, i) => (
                    <div key={a.id} className="relative">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={mediaUrl(`/media/${a.id}/file`)} alt={a.filename} className="aspect-square w-full rounded-lg object-cover" />
                      <span className="absolute left-1 top-1 rounded bg-black/70 px-1.5 text-xs">{i + 1}</span>
                      <button type="button" aria-label="Remove" className="absolute right-1 top-1 rounded bg-black/70 px-1.5 text-xs" onClick={() => setImages((x) => x.filter((y) => y.id !== a.id))}>✕</button>
                    </div>
                  ))}
                </div>
              )}
              {uploading && <p className="mt-2 text-xs text-slate-400">Uploading…</p>}
            </Field>
          )}
          <Field label={mode === "script" ? "Topic (optional)" : mode === "image" ? "Narration (optional)" : "Describe your video"}
            hint={mode === "image" ? "Write what the narrator should say. It is split across your photos." : undefined}>
            <textarea className="input min-h-28" value={f.prompt} onChange={(e) => set("prompt", e.target.value)} maxLength={4000}
              placeholder={mode === "text" ? "A 5-minute documentary about how coffee is grown on Mount Kilimanjaro, from planting to the cup." : ""} />
          </Field>
          {mode === "script" && (
            <Field label="Script" hint="Paste your full narration. Long scripts (up to about one hour of speech) are split into scenes automatically.">
              <textarea className="input min-h-64 font-mono" value={f.script} onChange={(e) => set("script", e.target.value)} required />
            </Field>
          )}
        </div>

        <div className="card space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Style"><Select value={f.style} onChange={(v) => set("style", v)} options={meta?.styles ?? [f.style]} /></Field>
            <Field label="Format"><Select value={f.aspect} onChange={(v) => set("aspect", v)} options={meta?.aspects ?? [f.aspect]} labels={{ "16:9": "16:9 landscape", "9:16": "9:16 portrait", "1:1": "1:1 square" }} /></Field>
            <Field label="Resolution"><Select value={f.resolution} onChange={(v) => set("resolution", Number(v))} options={meta?.resolutions ?? [f.resolution]} labels={{ 480: "480p", 720: "720p", 1080: "1080p" }} /></Field>
            <Field label="Frame rate"><Select value={f.fps} onChange={(v) => set("fps", Number(v))} options={meta?.fps ?? [f.fps]} labels={{ 24: "24 fps", 25: "25 fps", 30: "30 fps" }} /></Field>
          </div>
          {mode === "text" && (
            <div className="grid grid-cols-2 gap-3">
              <Field label="Length (minutes)"><input className="input" type="number" min={0.1} max={meta?.limits.max_project_minutes ?? 60} step={0.5}
                value={f.target_seconds / 60} onChange={(e) => set("target_seconds", Math.round(Number(e.target.value) * 60))} /></Field>
              <Field label="Scene length (s)"><input className="input" type="number" min={3} max={30} value={f.scene_seconds} onChange={(e) => set("scene_seconds", Number(e.target.value))} /></Field>
            </div>
          )}
          <div className="grid grid-cols-2 gap-3">
            <Field label="Language"><Select value={f.language} onChange={(v) => set("language", v)} options={Object.keys(meta?.languages ?? { en: "English" })} labels={meta?.languages} /></Field>
            <Field label="Voice"><Select value={f.voice} onChange={(v) => set("voice", v)} options={meta?.voices ?? [f.voice]} /></Field>
            <Field label="Narration"><Select value={f.narration_style} onChange={(v) => set("narration_style", v)} options={meta?.narration_styles ?? [f.narration_style]} /></Field>
            <Field label="Music">
              <Select value={f.music} onChange={(v) => set("music", v)} options={[...(meta?.music ?? [f.music]), ...music.map((m) => `asset:${m.id}`)]}
                labels={Object.fromEntries(music.map((m) => [`asset:${m.id}`, `Your track: ${m.filename}`]))} />
            </Field>
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input type="checkbox" checked={f.burn_subtitles} onChange={(e) => set("burn_subtitles", e.target.checked)} />
            Burn subtitles into the video (an .srt file is always exported too)
          </label>
          <div className="rounded-xl bg-black/30 p-3 text-xs text-slate-400">
            {mode === "script" ? "Scenes are created from your script." : `${sceneCount} scene${sceneCount === 1 ? "" : "s"}`}
            {mode === "text" && ` × ${f.scene_seconds}s ≈ ${fmtDuration(f.target_seconds)}`}
            {meta && <> · Max {meta.limits.max_project_minutes} min per project.</>}
          </div>
          <ErrorNote error={error} />
          <button className="btn-primary w-full py-3" disabled={busy || uploading || (mode === "image" && images.length === 0)}>
            {busy ? "Creating…" : "Generate storyboard"}
          </button>
          <p className="text-xs text-slate-500">Nothing renders until you review and approve the storyboard.</p>
        </div>
      </div>
    </form>
  );
}
