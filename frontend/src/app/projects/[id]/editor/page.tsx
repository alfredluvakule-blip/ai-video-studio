"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { Asset, Meta, Project, Scene, api, fmtDuration, mediaUrl } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { ErrorNote, Field, RenderProgress, Select, StatusBadge } from "@/components/ui";

const busy = (p?: Project) => !!p && ["storyboarding", "rendering", "assembling"].includes(p.status);
const len = (s: Scene) => s.clip_seconds || s.duration;

export default function Editor() {
  const { id } = useParams<{ id: string }>();
  const { data: p, reload, setData } = usePolling<Project>(`/projects/${id}`, busy, 2500);
  const [meta, setMeta] = useState<Meta>();
  const [music, setMusic] = useState<Asset[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [zoom, setZoom] = useState(12); // px per second
  const [playhead, setPlayhead] = useState(0);
  const [dragId, setDragId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<"final" | "scenes">("scenes");
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    api<Meta>("/meta").then(setMeta).catch(() => {});
    api<Asset[]>("/media?kind=music").then(setMusic).catch(() => {});
  }, []);
  useEffect(() => { if (p?.has_video) setPreview("final"); }, [p?.has_video]);

  const scenes = useMemo(() => p?.scenes ?? [], [p]);
  const starts = useMemo(() => { let t = 0; return scenes.map((s) => { const a = t; t += len(s); return a; }); }, [scenes]);
  const total = scenes.reduce((a, s) => a + len(s), 0);
  const current = scenes.find((s) => s.id === sel) ?? null;
  const idxAtPlayhead = Math.max(0, starts.findLastIndex((t) => t <= playhead + 1e-6));

  async function act(fn: () => Promise<unknown>) {
    setError("");
    try { const r = await fn(); if (r && typeof r === "object" && "scenes" in (r as object)) setData(r as Project); else await reload(); }
    catch (e) { setError((e as Error).message); }
  }
  const patchScene = (s: Scene, body: Partial<Scene>) => act(() => api(`/scenes/${s.id}`, { method: "PATCH", body }));
  const patchProject = (body: Partial<Project>) => act(() => api(`/projects/${id}`, { method: "PATCH", body }));

  // Scene-by-scene preview: play each rendered clip in order.
  const playable = scenes.map((s, i) => ({ s, i })).filter(({ s }) => s.has_clip);
  const previewScene = preview === "scenes" ? scenes[idxAtPlayhead] : null;
  function onEnded() {
    if (preview !== "scenes") return;
    const next = playable.find(({ i }) => i > idxAtPlayhead);
    if (next) { setPlayhead(starts[next.i]); setTimeout(() => videoRef.current?.play(), 50); }
  }
  function onTime() {
    const v = videoRef.current;
    if (!v) return;
    if (preview === "final") setPlayhead(v.currentTime);
    else setPlayhead(starts[idxAtPlayhead] + v.currentTime);
  }
  function seek(t: number) {
    setPlayhead(t);
    const v = videoRef.current;
    if (v && preview === "final") v.currentTime = t;
  }

  function drop(targetId: string) {
    if (!dragId || dragId === targetId || !p) return;
    const ids = scenes.map((s) => s.id).filter((x) => x !== dragId);
    ids.splice(ids.indexOf(targetId), 0, dragId);
    setDragId(null);
    act(() => api(`/projects/${p.id}/reorder`, { body: { scene_ids: ids } }));
  }

  if (!p) return <p className="muted">Loading…</p>;
  const stale = scenes.filter((s) => s.status !== "done").length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <Link href={`/projects/${p.id}`} className="text-sm text-violet-300 hover:underline">‹ Storyboard</Link>
          <h1 className="h1">{p.title}</h1>
          <StatusBadge status={p.status} />
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn-primary" disabled={busy(p)} onClick={() => act(() => api(`/projects/${p.id}/render`, { body: { approve_all: true } }))}>
            {stale ? `Render ${stale} changed scene${stale > 1 ? "s" : ""} & export` : "Re-export MP4"}
          </button>
          {p.has_video && <a className="btn-ghost" href={mediaUrl(`/projects/${p.id}/download/video`)}>⬇ MP4</a>}
        </div>
      </div>
      <ErrorNote error={error || p.error || ""} />
      <RenderProgress p={p} />

      <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
        <div className="card space-y-3">
          <div className="flex gap-2 text-xs">
            <button className={`btn-ghost text-xs ${preview === "scenes" ? "bg-white/10" : ""}`} onClick={() => setPreview("scenes")}>Scene preview</button>
            <button className={`btn-ghost text-xs ${preview === "final" ? "bg-white/10" : ""}`} disabled={!p.has_video} onClick={() => setPreview("final")}>Final export</button>
            <span className="ml-auto self-center text-slate-400">{fmtDuration(playhead)} / {fmtDuration(total)}</span>
          </div>
          <div className="grid aspect-video place-items-center overflow-hidden rounded-xl bg-black">
            {preview === "final" && p.has_video ? (
              <video ref={videoRef} key="final" controls className="h-full" onTimeUpdate={onTime} src={mediaUrl(`/projects/${p.id}/download/video`, { inline: true, bust: p.updated_at })} />
            ) : previewScene?.has_clip ? (
              <video ref={videoRef} key={previewScene.id + previewScene.attempts} controls className="h-full" onEnded={onEnded} onTimeUpdate={onTime}
                src={mediaUrl(`/scenes/${previewScene.id}/clip`, { bust: String(previewScene.attempts) })} />
            ) : (
              <p className="text-sm text-slate-500">{previewScene ? `Scene ${previewScene.position + 1} is not rendered yet` : "No scenes"}</p>
            )}
          </div>
        </div>

        <div className="card space-y-4">
          {current ? (
            <SceneInspector key={current.id} s={current} meta={meta} playheadInScene={playhead - starts[current.position]}
              onPatch={(b) => patchScene(current, b)}
              onSplit={(at) => act(() => api(`/scenes/${current.id}/split`, { body: { at_seconds: at } }))}
              onMerge={() => act(() => api(`/scenes/${current.id}/merge-next`, { method: "POST" }))}
              onDelete={() => confirm("Delete this scene?") && act(async () => { await api(`/scenes/${current.id}`, { method: "DELETE" }); setSel(null); })}
              onRegenerate={() => act(() => api(`/scenes/${current.id}/regenerate`, { method: "POST" }))} />
          ) : (
            <ProjectInspector p={p} meta={meta} music={music} onPatch={patchProject} />
          )}
        </div>
      </div>

      <div className="card space-y-2 overflow-hidden">
        <div className="flex items-center gap-3 text-xs text-slate-400">
          <span>Timeline · drag scenes to reorder · click to select</span>
          <label className="ml-auto flex items-center gap-2">Zoom
            <input type="range" min={2} max={60} value={zoom} onChange={(e) => setZoom(Number(e.target.value))} />
          </label>
          {sel && <button className="btn-ghost text-xs" onClick={() => setSel(null)}>Project settings</button>}
        </div>
        <div className="overflow-x-auto pb-2">
          <div className="relative" style={{ width: Math.max(600, total * zoom + 80) }}>
            <Ruler total={total} zoom={zoom} onSeek={seek} />
            <Track label="V1 Video">
              {scenes.map((s, i) => (
                <div key={s.id} draggable onDragStart={() => setDragId(s.id)} onDragOver={(e) => e.preventDefault()} onDrop={() => drop(s.id)}
                  onClick={() => { setSel(s.id); seek(starts[i]); }}
                  title={`Scene ${i + 1}: ${s.title}`}
                  className={`absolute top-0 h-full cursor-grab overflow-hidden rounded-md border px-1 text-[10px] leading-tight ${sel === s.id ? "border-violet-300 bg-violet-600/60" : s.status === "done" ? "border-emerald-400/30 bg-emerald-500/25" : s.status === "failed" ? "border-red-400/40 bg-red-500/25" : "border-white/15 bg-white/10"}`}
                  style={{ left: starts[i] * zoom, width: Math.max(4, len(s) * zoom - 2) }}>
                  {s.has_image && zoom * len(s) > 50 && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={mediaUrl(`/scenes/${s.id}/image`, { bust: String(s.attempts) })} alt="" className="pointer-events-none absolute inset-0 h-full w-full object-cover opacity-40" />
                  )}
                  <span className="relative">{i + 1}{s.speed !== 1 ? ` ×${s.speed}` : ""}{s.transition === "fade" ? " ◐" : ""}</span>
                </div>
              ))}
            </Track>
            <Track label="A1 Voice">
              {scenes.map((s, i) => (s.voiceover || s.voice_asset_id) ? (
                <div key={s.id} className="absolute top-1 bottom-1 overflow-hidden rounded bg-sky-500/30 px-1 text-[10px] text-sky-100" style={{ left: starts[i] * zoom + 0.3 * zoom, width: Math.max(3, (len(s) - 0.8) * zoom) }}>
                  {s.voice_asset_id ? "🎙 recording" : "TTS"}
                </div>
              ) : null)}
            </Track>
            <Track label="A2 Music">
              {p.music !== "none" && <div className="absolute inset-y-1 left-0 rounded bg-amber-500/25 px-2 text-[10px] text-amber-100" style={{ width: total * zoom }}>♪ {p.music.startsWith("asset:") ? "your track" : p.music} (ducked under voice)</div>}
            </Track>
            <Track label="T1 Subtitles">
              {scenes.map((s, i) => s.voiceover ? (
                <div key={s.id} className="absolute top-1 bottom-1 overflow-hidden whitespace-nowrap rounded bg-white/10 px-1 text-[10px]" style={{ left: starts[i] * zoom, width: Math.max(3, len(s) * zoom - 2) }}>{s.voiceover}</div>
              ) : null)}
            </Track>
            <div className="pointer-events-none absolute top-0 bottom-0 w-px bg-red-400" style={{ left: 80 + playhead * zoom }} />
          </div>
        </div>
        <p className="text-xs text-slate-500">Planned: extra overlay tracks for images and text titles, and sound-effect tracks.</p>
      </div>
    </div>
  );
}

function Ruler({ total, zoom, onSeek }: { total: number; zoom: number; onSeek: (t: number) => void }) {
  const step = zoom > 30 ? 1 : zoom > 10 ? 5 : zoom > 4 ? 15 : 60;
  const marks = [];
  for (let t = 0; t <= total; t += step) marks.push(t);
  return (
    <div className="relative ml-20 h-6 cursor-pointer border-b border-white/10" onClick={(e) => {
      const r = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
      onSeek(Math.max(0, Math.min(total, (e.clientX - r.left) / zoom)));
    }}>
      {marks.map((t) => <span key={t} className="absolute top-0 text-[10px] text-slate-500" style={{ left: t * zoom }}>|{fmtDuration(t)}</span>)}
    </div>
  );
}

function Track({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex h-12 items-stretch border-b border-white/5">
      <div className="sticky left-0 z-[1] w-20 shrink-0 bg-[#11131c] py-3 text-[10px] font-medium text-slate-400">{label}</div>
      <div className="relative flex-1 py-1">{children}</div>
    </div>
  );
}

function SceneInspector({ s, meta, playheadInScene, onPatch, onSplit, onMerge, onDelete, onRegenerate }: {
  s: Scene; meta?: Meta; playheadInScene: number; onPatch: (b: Partial<Scene>) => void; onSplit: (at: number) => void;
  onMerge: () => void; onDelete: () => void; onRegenerate: () => void;
}) {
  const [dur, setDur] = useState(s.duration);
  const [vo, setVo] = useState(s.voiceover);
  const locked = s.status === "queued" || s.status === "rendering";
  const splitAt = playheadInScene > 0.5 && playheadInScene < s.duration - 0.5 ? playheadInScene : s.duration / 2;
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between"><span className="font-semibold text-white">Scene {s.position + 1}</span><span className="text-xs text-slate-400">{s.status}</span></div>
      <Field label={`Duration / trim (${dur}s)`}>
        <input type="range" min={1} max={60} step={0.5} value={dur} disabled={locked} className="w-full"
          onChange={(e) => setDur(Number(e.target.value))} onMouseUp={() => dur !== s.duration && onPatch({ duration: dur })} onTouchEnd={() => dur !== s.duration && onPatch({ duration: dur })} />
      </Field>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Speed"><Select value={s.speed} options={[0.25, 0.5, 0.75, 1, 1.25, 1.5, 2]} labels={{ "0.25": "0.25× slow-mo", "0.5": "0.5× slow-mo", "0.75": "0.75×", "1": "1× normal", "1.25": "1.25×", "1.5": "1.5×", "2": "2× fast" }} onChange={(v) => onPatch({ speed: Number(v) })} /></Field>
        <Field label="Transition"><Select value={s.transition} options={meta?.transitions ?? ["fade", "cut"]} onChange={(v) => onPatch({ transition: v })} /></Field>
        <Field label="Camera"><Select value={s.camera} options={meta?.cameras ?? [s.camera]} onChange={(v) => onPatch({ camera: v })} /></Field>
      </div>
      <Field label="Voice-over">
        <textarea className="input" rows={4} disabled={locked} value={vo} onChange={(e) => setVo(e.target.value)} onBlur={() => vo !== s.voiceover && onPatch({ voiceover: vo })} />
      </Field>
      <div className="grid grid-cols-2 gap-2">
        <button className="btn-ghost text-xs" disabled={locked} onClick={() => onSplit(splitAt)}>Split at {splitAt.toFixed(1)}s</button>
        <button className="btn-ghost text-xs" disabled={locked} onClick={onMerge}>Merge with next</button>
        <button className="btn-ghost text-xs" disabled={locked} onClick={onRegenerate}>Regenerate</button>
        <button className="btn-danger text-xs" disabled={locked} onClick={onDelete}>Delete</button>
      </div>
      <p className="text-xs text-slate-500">Changes mark this scene for re-render. Other scenes are reused, so exports after small edits are fast.</p>
    </div>
  );
}

function ProjectInspector({ p, meta, music, onPatch }: { p: Project; meta?: Meta; music: Asset[]; onPatch: (b: Partial<Project>) => void }) {
  return (
    <div className="space-y-3">
      <div className="font-semibold text-white">Project & export</div>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Format"><Select value={p.aspect} options={meta?.aspects ?? [p.aspect]} onChange={(v) => onPatch({ aspect: v })} /></Field>
        <Field label="Resolution"><Select value={p.resolution} options={meta?.resolutions ?? [p.resolution]} labels={{ 480: "480p", 720: "720p", 1080: "1080p" }} onChange={(v) => onPatch({ resolution: Number(v) })} /></Field>
        <Field label="Frame rate"><Select value={p.fps} options={meta?.fps ?? [p.fps]} onChange={(v) => onPatch({ fps: Number(v) })} /></Field>
        <Field label="Compression"><Select value={p.compression} options={["high", "balanced", "small"]} labels={{ high: "High quality", balanced: "Balanced", small: "Smallest file" }} onChange={(v) => onPatch({ compression: v })} /></Field>
        <Field label="Voice"><Select value={p.voice} options={meta?.voices ?? [p.voice]} onChange={(v) => onPatch({ voice: v })} /></Field>
        <Field label="Language"><Select value={p.language} options={Object.keys(meta?.languages ?? { [p.language]: p.language })} labels={meta?.languages} onChange={(v) => onPatch({ language: v })} /></Field>
      </div>
      <Field label="Background music">
        <Select value={p.music} options={[...(meta?.music ?? [p.music]), ...music.map((m) => `asset:${m.id}`)]} labels={Object.fromEntries(music.map((m) => [`asset:${m.id}`, `Your track: ${m.filename}`]))} onChange={(v) => onPatch({ music: v })} />
      </Field>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={p.burn_subtitles} onChange={(e) => onPatch({ burn_subtitles: e.target.checked })} /> Burn in subtitles</label>
      <p className="text-xs text-slate-500">Changing format, resolution, frame rate, voice or language re-renders every scene. Music and subtitle changes only re-run the final export.</p>
    </div>
  );
}
