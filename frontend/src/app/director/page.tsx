"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Asset, BrainStatus, PLAN_STATUS, Plan, api, fmtDuration, mediaUrl } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { ErrorNote, Field, Select } from "@/components/ui";

const EXAMPLES = [
  "Create a six-minute 3D educational video featuring my baby teaching children numbers from 1 to 20.",
  "A 3-minute Kiswahili cartoon about washing hands before eating, for nursery school children.",
  "A 10-minute documentary about how tea is grown in the Kenyan highlands.",
];

const lengthLabel = (s: number) => (s < 60 ? `${s} s` : s < 3600 ? `${s / 60} min` : `${s / 3600} hour`);

export default function DirectorHome() {
  const router = useRouter();
  const [status, setStatus] = useState<BrainStatus>();
  const { data: plans } = usePolling<Plan[]>("/director/plans", (d) => !!d?.some((p) => ["queued", "planning"].includes(p.status)), 3000);
  const [idea, setIdea] = useState("");
  const [seconds, setSeconds] = useState(180);
  const [sceneSeconds, setSceneSeconds] = useState(10);
  const [language, setLanguage] = useState("en");
  const [style, setStyle] = useState("auto");
  const [aspect, setAspect] = useState("16:9");
  const [voice, setVoice] = useState("female");
  const [mainCharacter, setMainCharacter] = useState("");
  const [refs, setRefs] = useState<Asset[]>([]);
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => { api<BrainStatus>("/brain/status").then(setStatus).catch((e) => setError(e.message)); }, []);

  async function upload(files: FileList | null) {
    if (!files) return;
    setUploading(true); setError("");
    try {
      for (const f of Array.from(files)) {
        const fd = new FormData(); fd.append("file", f);
        const a = await api<Asset>("/media", { form: fd });
        setRefs((x) => [...x, a]);
      }
    } catch (e) { setError((e as Error).message); } finally { setUploading(false); }
  }

  async function start(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      const p = await api<Plan>("/director/plans", { body: {
        idea, target_seconds: seconds, scene_seconds: sceneSeconds, language, style, aspect, voice,
        main_character: mainCharacter, reference_asset_ids: refs.map((r) => r.id),
      } });
      router.push(`/director/${p.id}`);
    } catch (e) { setError((e as Error).message); setBusy(false); }
  }

  const presets = (status?.length_presets ?? [30, 60, 180, 300, 600, 900, 1800, 3600]).filter((s) => s <= (status?.max_seconds ?? 3600));
  const ready = status?.writer.available;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="h1">AI Director</h1>
        <p className="muted max-w-3xl">
          Describe your video in one sentence. A team of AI agents (director, scriptwriter, storyboard artist, camera, sound and editor)
          plans the whole production: script, scenes, camera moves, characters, timing and prompts. You review and edit the plan
          before anything is made.
        </p>
      </div>

      {status && (ready ? (
        <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 px-4 py-3 text-sm text-emerald-200">
          AI writer connected: {status.writer.label}.
        </div>
      ) : (
        <div className="rounded-xl border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-sm text-amber-100">
          <b>The AI Director needs an AI writer.</b> {status.writer.help}
        </div>
      ))}

      <form onSubmit={start} className="grid gap-6 lg:grid-cols-3">
        <div className="card space-y-4 lg:col-span-2">
          <Field label="Your idea">
            <textarea className="input min-h-28" value={idea} onChange={(e) => setIdea(e.target.value)} maxLength={4000} required minLength={3}
              placeholder={EXAMPLES[0]} />
          </Field>
          <div className="flex flex-wrap gap-2">
            {EXAMPLES.map((x) => <button type="button" key={x} className="btn-ghost text-left text-xs" onClick={() => setIdea(x)}>{x}</button>)}
          </div>
          <Field label="Main character (optional)" hint="Who should appear throughout, for example “Amani, my one-year-old daughter”.">
            <input className="input" value={mainCharacter} onChange={(e) => setMainCharacter(e.target.value)} maxLength={600} />
          </Field>
          <Field label={`Reference photos (${refs.length})`} hint="Saved with the main character. The free picture service cannot copy a face, so to show the real person, the photo is used on the scenes you choose.">
            <input type="file" accept="image/*" multiple className="input" disabled={uploading} onChange={(e) => upload(e.target.files)} />
            {refs.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2">
                {refs.map((a) => (
                  <div key={a.id} className="relative">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={mediaUrl(`/media/${a.id}/file`)} alt={a.filename} className="h-16 w-16 rounded-lg object-cover" />
                    <button type="button" aria-label="Remove" className="absolute right-0.5 top-0.5 rounded bg-black/70 px-1 text-xs" onClick={() => setRefs((x) => x.filter((y) => y.id !== a.id))}>✕</button>
                  </div>
                ))}
              </div>
            )}
          </Field>
        </div>
        <div className="card space-y-4">
          <Field label="Length">
            <div className="flex flex-wrap gap-2">
              {presets.map((s) => (
                <button type="button" key={s} onClick={() => setSeconds(s)}
                  className={`rounded-lg border px-2.5 py-1 text-xs ${seconds === s ? "border-violet-500 bg-violet-600/20 text-violet-100" : "border-white/15 text-slate-300"}`}>
                  {lengthLabel(s)}
                </button>
              ))}
            </div>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Minutes"><input className="input" type="number" min={0.5} max={(status?.max_seconds ?? 3600) / 60} step={0.5}
              value={seconds / 60} onChange={(e) => setSeconds(Math.max(10, Math.round(Number(e.target.value) * 60)))} /></Field>
            <Field label="Scene length (s)"><input className="input" type="number" min={3} max={30} value={sceneSeconds} onChange={(e) => setSceneSeconds(Number(e.target.value))} /></Field>
            <Field label="Language"><Select value={language} onChange={setLanguage} options={Object.keys(status?.languages ?? { en: "English" })} labels={status?.languages} /></Field>
            <Field label="Voice"><Select value={voice} onChange={setVoice} options={["female", "male"]} /></Field>
            <Field label="Style"><Select value={style} onChange={setStyle} options={status?.styles ?? ["auto"]} labels={{ auto: "Let the director choose" }} /></Field>
            <Field label="Format"><Select value={aspect} onChange={setAspect} options={["16:9", "9:16", "1:1"]} labels={{ "16:9": "16:9 landscape", "9:16": "9:16 portrait", "1:1": "1:1 square" }} /></Field>
          </div>
          <div className="rounded-xl bg-black/30 p-3 text-xs text-slate-400">
            About {Math.max(1, Math.round(seconds / sceneSeconds))} scenes. Making the plan uses a few free AI writer calls; nothing is drawn, voiced or rendered yet.
          </div>
          <ErrorNote error={error} />
          <button className="btn-primary w-full py-3" disabled={!ready || busy || uploading || idea.trim().length < 3}>{busy ? "Starting…" : "✦ Plan my video"}</button>
        </div>
      </form>

      {plans && plans.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-lg font-semibold text-white">Your plans</h2>
          {plans.map((p) => (
            <Link key={p.id} href={`/director/${p.id}`} className="card flex flex-wrap items-center gap-3 hover:border-violet-500/50">
              <span className="font-medium text-white">{p.title}</span>
              <span className="badge bg-white/10 text-slate-300">{PLAN_STATUS[p.status]}</span>
              <span className="text-xs text-slate-400">{fmtDuration(p.settings.target_seconds)} · {p.scene_count} scenes · {new Date(p.created_at).toLocaleString()}</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
