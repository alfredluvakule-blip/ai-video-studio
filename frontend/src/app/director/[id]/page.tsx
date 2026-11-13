"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AgentActivity, BrainStatus, PLAN_STATUS, Plan, PlanBody, PlanCharacter, PlanLocation, PlanScene, api, fmtDuration, mediaUrl } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { ErrorNote, Field, Select } from "@/components/ui";

const busy = (p?: Plan) => !!p && ["queued", "planning"].includes(p.status);

export default function PlanPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data: p, setData, error: loadError } = usePolling<Plan>(`/director/plans/${id}`, busy, 2000);
  const [status, setStatus] = useState<BrainStatus>();
  const [draft, setDraft] = useState<PlanBody>();
  const [dirty, setDirty] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set(["c1"]));

  useEffect(() => { api<BrainStatus>("/brain/status").then(setStatus).catch(() => {}); }, []);
  useEffect(() => { if (p?.plan && !dirty) setDraft(structuredClone(p.plan)); }, [p, dirty]);

  async function act(fn: () => Promise<Plan | void>) {
    setWorking(true); setError("");
    try { const r = await fn(); if (r) { setData(r); setDirty(false); setDraft(structuredClone(r.plan)); } }
    catch (e) { setError((e as Error).message); } finally { setWorking(false); }
  }
  const edit = (fn: (d: PlanBody) => void) => { setDraft((d) => { const n = structuredClone(d!); fn(n); return n; }); setDirty(true); };
  const save = (extra: object = {}) => act(() => api<Plan>(`/director/plans/${id}`, { method: "PATCH", body: {
    brief: draft?.brief, characters: draft?.characters, locations: draft?.locations, scenes: draft?.scenes, ...extra,
  } }));

  if (loadError && !p) return <ErrorNote error={loadError} />;
  if (!p) return <p className="muted">Loading…</p>;

  const plan = draft ?? p.plan ?? {};
  const scenes = plan.scenes ?? [];
  const total = scenes.reduce((a, s) => a + Number(s.duration || 0), 0);
  const editable = p.status === "ready";
  const warnings = (plan.checks ?? []).filter((c) => c.level === "warning");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <Link href="/director" className="text-xs text-slate-400 hover:underline">‹ AI Director</Link>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="h1">{plan.brief?.title || p.title}</h1>
            <span className="badge bg-violet-500/20 text-violet-200">{PLAN_STATUS[p.status]}</span>
          </div>
          <p className="muted">“{p.idea}”</p>
          <p className="text-xs text-slate-500">
            Asked for {fmtDuration(p.settings.target_seconds)} · planned {fmtDuration(total)} · {scenes.length} scenes · {p.settings.aspect} · {p.provider ?? "AI writer"} · {p.llm_calls} AI writer calls
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {p.status === "approved" && p.project_id && <Link className="btn-primary" href={`/projects/${p.project_id}`}>Open the storyboard ›</Link>}
          {editable && dirty && <button className="btn-primary" disabled={working} onClick={() => save()}>Save changes</button>}
          {editable && dirty && <button className="btn-ghost" disabled={working} onClick={() => { setDirty(false); setDraft(structuredClone(p.plan)); }}>Undo changes</button>}
          {editable && Math.abs(total - p.settings.target_seconds) > 0.05 && (
            <button className="btn-ghost" disabled={working} onClick={() => save({ fit_to_length: true })}>Fit to {fmtDuration(p.settings.target_seconds)}</button>
          )}
          {(editable || p.status === "failed") && scenes.some((s) => !(s.narration || s.dialogue) || !s.action) && (
            <button className="btn-ghost" disabled={working || dirty} onClick={() => act(() => api<Plan>(`/director/plans/${id}/fill`, { method: "POST" }))}>Fill empty scenes with AI</button>
          )}
          {(editable || p.status === "failed") && (
            <button className="btn-ghost" disabled={working} onClick={() => confirm("Start the plan again from your idea? Your edits will be replaced.") && act(() => api<Plan>(`/director/plans/${id}/replan`, { method: "POST" }))}>Start again</button>
          )}
          {p.status !== "approved" && !busy(p) && (
            <button className="btn-danger" disabled={working} onClick={() => confirm("Delete this plan?") && act(async () => { await api(`/director/plans/${id}`, { method: "DELETE" }); router.push("/director"); })}>Delete</button>
          )}
        </div>
      </div>

      <ErrorNote error={error || p.error || ""} />
      {busy(p) && <div className="card animate-pulse text-slate-300">{p.stage || "Starting"}… this page updates by itself.</div>}

      <div className="grid gap-6 xl:grid-cols-3">
        <div className="space-y-6 xl:col-span-2">
          {plan.brief && (
            <section className="card space-y-4">
              <h2 className="font-semibold text-white">Production brief <span className="text-xs font-normal text-slate-400">by the Film Director</span></h2>
              <div className="grid gap-3 md:grid-cols-2">
                {(["title", "logline", "audience", "goal", "visual_style", "tone", "camera_language"] as const).map((k) => (
                  <Field key={k} label={k.replace(/_/g, " ")}>
                    <input className="input" disabled={!editable} value={plan.brief![k]} onChange={(e) => edit((d) => { d.brief![k] = e.target.value; })} />
                  </Field>
                ))}
                <div className="grid grid-cols-3 gap-2">
                  <Field label="Style"><Select value={plan.brief.style} onChange={(v) => edit((d) => { d.brief!.style = v; })} options={(status?.styles ?? [plan.brief.style]).filter((s) => s !== "auto")} /></Field>
                  <Field label="Narration"><Select value={plan.brief.narration_style} onChange={(v) => edit((d) => { d.brief!.narration_style = v; })} options={status?.narration_styles ?? [plan.brief.narration_style]} /></Field>
                  <Field label="Music"><Select value={plan.brief.music_mood} onChange={(v) => edit((d) => { d.brief!.music_mood = v; })} options={status?.music ?? [plan.brief.music_mood]} /></Field>
                </div>
              </div>
              {(plan.brief.assumptions.length > 0 || plan.brief.questions.length > 0) && (
                <div className="grid gap-3 text-sm md:grid-cols-2">
                  {plan.brief.assumptions.length > 0 && <div><div className="label">Decided for you</div><ul className="space-y-1 text-slate-300">{plan.brief.assumptions.map((a, i) => <li key={i}>• {a}</li>)}</ul></div>}
                  {plan.brief.questions.length > 0 && <div><div className="label">Worth checking</div><ul className="space-y-1 text-amber-100">{plan.brief.questions.map((a, i) => <li key={i}>• {a}</li>)}</ul></div>}
                </div>
              )}
            </section>
          )}

          {plan.characters && (
            <section className="card space-y-3">
              <h2 className="font-semibold text-white">Characters <span className="text-xs font-normal text-slate-400">locked looks are written into every picture prompt</span></h2>
              {plan.characters.map((c, i) => (
                <CharacterRow key={i} c={c} editable={editable}
                  onChange={(n) => edit((d) => { d.characters![i] = n; })} onRemove={() => edit((d) => { d.characters!.splice(i, 1); })} />
              ))}
              {editable && <button className="btn-ghost text-xs" onClick={() => edit((d) => { d.characters!.push({ name: "New character", role: "", appearance: "", clothing: "", personality: "", voice: "", reference_asset_ids: [], locked: true }); })}>＋ Add character</button>}
            </section>
          )}

          {plan.locations && (
            <section className="card space-y-3">
              <h2 className="font-semibold text-white">Locations</h2>
              {plan.locations.map((l, i) => (
                <LocationRow key={i} l={l} editable={editable}
                  onChange={(n) => edit((d) => { d.locations![i] = n; })} onRemove={() => edit((d) => { d.locations!.splice(i, 1); })} />
              ))}
              {editable && <button className="btn-ghost text-xs" onClick={() => edit((d) => { d.locations!.push({ name: "New place", description: "", lighting: "", locked: true }); })}>＋ Add location</button>}
            </section>
          )}

          {(plan.chapters ?? []).map((ch) => {
            const list = scenes.filter((s) => s.chapter_id === ch.id);
            const secs = list.reduce((a, s) => a + Number(s.duration || 0), 0);
            const isOpen = open.has(ch.id);
            return (
              <section key={ch.id} className="card space-y-3">
                <button className="flex w-full flex-wrap items-baseline gap-3 text-left" onClick={() => setOpen((o) => { const n = new Set(o); if (n.has(ch.id)) n.delete(ch.id); else n.add(ch.id); return n; })}>
                  <span className="text-slate-400">{isOpen ? "▾" : "▸"}</span>
                  <span className="font-semibold text-white">{ch.title}</span>
                  <span className="text-xs text-slate-400">{list.length} scenes · {fmtDuration(secs)}</span>
                  <span className="w-full text-sm text-slate-400">{ch.summary}</span>
                </button>
                {isOpen && list.map((s) => {
                  const idx = scenes.indexOf(s);
                  return <SceneRow key={s.number} s={s} editable={editable} status={status} plan={plan}
                    checks={(plan.checks ?? []).filter((c) => c.scene === s.number)}
                    onChange={(n) => edit((d) => { d.scenes![idx] = n; })}
                    onRemove={scenes.length > 1 ? () => edit((d) => { d.scenes!.splice(idx, 1); }) : undefined} />;
                })}
              </section>
            );
          })}
        </div>

        <div className="space-y-6">
          {p.status === "ready" && (
            <section className="card space-y-3 border-violet-500/40">
              <h2 className="font-semibold text-white">Approve the plan</h2>
              <p className="text-sm text-slate-300">This turns the plan into a storyboard project. You can still change every scene there, and nothing renders until you press render.</p>
              {warnings.length > 0 && <p className="text-xs text-amber-200">{warnings.length} thing(s) to look at first (see Checks).</p>}
              <button className="btn-primary w-full" disabled={working || dirty}
                onClick={() => act(async () => { const r = await api<{ project_id: string }>(`/director/plans/${id}/approve`, { method: "POST" }); router.push(`/projects/${r.project_id}`); })}>
                ✓ Approve &amp; create storyboard
              </button>
              {dirty && <p className="text-xs text-slate-400">Save your changes first.</p>}
            </section>
          )}

          {plan.estimate && plan.recommendation && (
            <section className="card space-y-2 text-sm">
              <h2 className="font-semibold text-white">How it will be made</h2>
              <p className="text-slate-200">{plan.recommendation.label}</p>
              <ul className="space-y-1 text-slate-400">{plan.recommendation.reasons.map((r, i) => <li key={i}>• {r}</li>)}</ul>
              <div className="grid grid-cols-2 gap-2 pt-2">
                <Stat label="Cost" value={`$${plan.estimate.cost_usd.toFixed(2)}`} />
                <Stat label="Time to make" value={`≈ ${plan.estimate.estimated_minutes} min`} />
                <Stat label="Video length" value={fmtDuration(plan.estimate.video_seconds)} />
                <Stat label="AI writer calls" value={String(p.llm_calls)} />
              </div>
              <p className="text-xs text-slate-500">{plan.estimate.cost_note} Time is based on {plan.estimate.time_basis}.</p>
              <details className="text-xs text-slate-400">
                <summary className="cursor-pointer">All ways to make scenes</summary>
                <ul className="mt-2 space-y-1">
                  {(status?.routes ?? []).map((r) => <li key={r.name}><span className={r.connected ? "text-emerald-300" : "text-slate-500"}>{r.connected ? "● connected" : "○ not connected"}</span> {r.label}. {r.note}</li>)}
                </ul>
              </details>
            </section>
          )}

          {plan.audio && (
            <section className="card space-y-1 text-sm text-slate-300">
              <h2 className="font-semibold text-white">Sound</h2>
              <p>Narrator: {plan.audio.narrator} ({plan.audio.narration_style})</p>
              <p>Music: {plan.audio.music_mood}. {plan.audio.music_note}</p>
              <p className="text-xs text-slate-500">{plan.audio.sound_effects_note}</p>
              {plan.audio.song_note && <p className="text-xs text-amber-200">{plan.audio.song_note}</p>}
            </section>
          )}

          {plan.checks && (
            <section className="card space-y-2 text-sm">
              <h2 className="font-semibold text-white">Checks <span className="text-xs font-normal text-slate-400">continuity and timing</span></h2>
              {plan.checks.length === 0 && <p className="text-emerald-300">Everything adds up.</p>}
              <ul className="max-h-72 space-y-1 overflow-auto">
                {plan.checks.map((c, i) => (
                  <li key={i} className={c.level === "warning" ? "text-amber-200" : "text-slate-400"}>
                    {c.scene ? `Scene ${c.scene}: ` : ""}{c.text}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <ActivityPanel items={p.activity ?? []} />
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl bg-black/30 p-2"><div className="text-xs text-slate-400">{label}</div><div className="font-semibold text-white">{value}</div></div>;
}

function ActivityPanel({ items }: { items: AgentActivity[] }) {
  const color = { running: "text-sky-300", done: "text-emerald-300", failed: "text-red-300", skipped: "text-slate-400" };
  const mark = { running: "◌", done: "✓", failed: "✕", skipped: "–" };
  return (
    <section className="card space-y-2">
      <h2 className="font-semibold text-white">Agent activity</h2>
      <p className="text-xs text-slate-500">Each line is a step that really ran, with the AI writer calls it used. “Rules” steps are plain code with no AI call.</p>
      {items.length === 0 && <p className="text-sm text-slate-400">Nothing yet.</p>}
      <ol className="max-h-[32rem] space-y-2 overflow-auto text-sm">
        {items.map((a) => (
          <li key={a.id} className="rounded-lg bg-black/20 p-2">
            <div className="flex gap-2"><span className={color[a.status]}>{mark[a.status]}</span><span className="font-medium text-slate-100">{a.agent}</span>
              <span className="ml-auto text-xs text-slate-500">{a.llm_calls ? `${a.llm_calls} AI call${a.llm_calls > 1 ? "s" : ""}` : a.provider?.startsWith("rules") ? "rules" : ""}</span></div>
            <div className="text-slate-300">{a.action}</div>
            {a.detail && <div className={`text-xs ${a.status === "failed" ? "text-red-300" : "text-slate-400"}`}>{a.detail}</div>}
          </li>
        ))}
      </ol>
    </section>
  );
}

function CharacterRow({ c, editable, onChange, onRemove }: { c: PlanCharacter; editable: boolean; onChange: (c: PlanCharacter) => void; onRemove: () => void }) {
  const set = (k: keyof PlanCharacter, v: string | boolean) => onChange({ ...c, [k]: v });
  return (
    <div className="space-y-2 rounded-xl border border-white/10 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <input className="input max-w-xs font-medium" disabled={!editable} value={c.name} onChange={(e) => set("name", e.target.value)} aria-label="Name" />
        <input className="input max-w-xs" disabled={!editable} value={c.role} onChange={(e) => set("role", e.target.value)} placeholder="role" aria-label="Role" />
        <label className="flex items-center gap-1 text-xs text-slate-300"><input type="checkbox" disabled={!editable} checked={c.locked} onChange={(e) => set("locked", e.target.checked)} /> Locked look</label>
        {c.reference_asset_ids.map((a) => (
          // eslint-disable-next-line @next/next/no-img-element
          <img key={a} src={mediaUrl(`/media/${a}/file`)} alt="reference" className="h-9 w-9 rounded object-cover" />
        ))}
        {editable && <button className="ml-auto text-xs text-slate-400 hover:text-red-300" onClick={onRemove}>Remove</button>}
      </div>
      <div className="grid gap-2 md:grid-cols-2">
        <input className="input" disabled={!editable} value={c.appearance} onChange={(e) => set("appearance", e.target.value)} placeholder="Appearance (age, face, hair, build)" aria-label="Appearance" />
        <input className="input" disabled={!editable} value={c.clothing} onChange={(e) => set("clothing", e.target.value)} placeholder="Clothing" aria-label="Clothing" />
      </div>
    </div>
  );
}

function LocationRow({ l, editable, onChange, onRemove }: { l: PlanLocation; editable: boolean; onChange: (l: PlanLocation) => void; onRemove: () => void }) {
  const set = (k: keyof PlanLocation, v: string | boolean) => onChange({ ...l, [k]: v });
  return (
    <div className="grid gap-2 md:grid-cols-[12rem_1fr_12rem_auto]">
      <input className="input font-medium" disabled={!editable} value={l.name} onChange={(e) => set("name", e.target.value)} aria-label="Place name" />
      <input className="input" disabled={!editable} value={l.description} onChange={(e) => set("description", e.target.value)} placeholder="Description" aria-label="Description" />
      <input className="input" disabled={!editable} value={l.lighting} onChange={(e) => set("lighting", e.target.value)} placeholder="Lighting" aria-label="Lighting" />
      {editable && <button className="text-xs text-slate-400 hover:text-red-300" onClick={onRemove}>Remove</button>}
    </div>
  );
}

function SceneRow({ s, editable, status, plan, checks, onChange, onRemove }: {
  s: PlanScene; editable: boolean; status?: BrainStatus; plan: PlanBody; checks: { level: string; text: string }[];
  onChange: (s: PlanScene) => void; onRemove?: () => void;
}) {
  const [more, setMore] = useState(false);
  const set = <K extends keyof PlanScene>(k: K, v: PlanScene[K]) => onChange({ ...s, [k]: v });
  return (
    <div className="space-y-2 rounded-xl border border-white/10 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="badge bg-white/10 text-slate-200">Scene {s.number}</span>
        <input className="input max-w-56" disabled={!editable} value={s.title} onChange={(e) => set("title", e.target.value)} aria-label="Title" />
        <label className="flex items-center gap-1 text-xs text-slate-400">
          <input className="input w-20" type="number" min={1} max={120} step={0.5} disabled={!editable} value={s.duration} onChange={(e) => set("duration", Number(e.target.value))} aria-label="Seconds" /> s
        </label>
        <span className="text-xs text-slate-400">{s.shot.replace(/_/g, " ")} · {s.movement.replace(/_/g, " ")} · {s.location}</span>
        <button className="ml-auto text-xs text-violet-300" onClick={() => setMore(!more)}>{more ? "Less" : "Camera, prompts…"}</button>
        {editable && onRemove && <button className="text-xs text-slate-400 hover:text-red-300" onClick={onRemove}>Remove</button>}
      </div>
      <div className="grid gap-2 md:grid-cols-2">
        <Field label="Narration"><textarea className="input" rows={2} disabled={!editable} value={s.narration} onChange={(e) => set("narration", e.target.value)} /></Field>
        <Field label="On screen"><textarea className="input" rows={2} disabled={!editable} value={s.action} onChange={(e) => set("action", e.target.value)} /></Field>
      </div>
      {checks.map((c, i) => <p key={i} className={`text-xs ${c.level === "warning" ? "text-amber-200" : "text-slate-500"}`}>{c.text}</p>)}
      {more && (
        <div className="grid gap-2 md:grid-cols-3">
          <Field label="Dialogue"><input className="input" disabled={!editable} value={s.dialogue} onChange={(e) => set("dialogue", e.target.value)} /></Field>
          <Field label="Characters (comma separated)"><input className="input" disabled={!editable} value={s.characters.join(", ")} onChange={(e) => set("characters", e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} /></Field>
          <Field label="Location">
            <Select value={s.location} onChange={(v) => set("location", v)} options={Array.from(new Set([s.location, ...(plan.locations ?? []).map((l) => l.name)]))} />
          </Field>
          <Field label="Shot"><Select value={s.shot} onChange={(v) => set("shot", v)} options={status?.shots ?? [s.shot]} /></Field>
          <Field label="Camera movement"><Select value={s.movement} onChange={(v) => set("movement", v)} options={status?.movements ?? [s.movement]} /></Field>
          <Field label="Transition"><Select value={s.transition} onChange={(v) => set("transition", v as PlanScene["transition"])} options={["fade", "cut"]} /></Field>
          <Field label="Expression"><input className="input" disabled={!editable} value={s.expression} onChange={(e) => set("expression", e.target.value)} /></Field>
          <Field label="Lighting"><input className="input" disabled={!editable} value={s.lighting} onChange={(e) => set("lighting", e.target.value)} /></Field>
          <Field label="Sound effects / music"><input className="input" disabled={!editable} value={[s.sound_effects, s.music_cue].filter(Boolean).join(" · ")} readOnly /></Field>
          <div className="md:col-span-3">
            <Field label="Picture prompt" hint={s.prompt_edited ? "Edited by you, so it is no longer rebuilt automatically." : "Built automatically from the scene; edit it to take over."}>
              <textarea className="input font-mono text-xs" rows={3} disabled={!editable} value={s.image_prompt ?? ""} onChange={(e) => onChange({ ...s, image_prompt: e.target.value, prompt_edited: true })} />
            </Field>
          </div>
          <div className="md:col-span-3">
            <Field label="Video-model prompt" hint="Ready for when an AI video model is connected. Not used by the free picture route.">
              <textarea className="input font-mono text-xs" rows={3} readOnly value={s.video_prompt ?? ""} />
            </Field>
          </div>
        </div>
      )}
    </div>
  );
}
