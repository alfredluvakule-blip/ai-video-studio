// Empty means "same web address as the app" (the Docker setup sends /api to the backend).
export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export type Scene = {
  id: string; project_id: string; position: number; duration: number; title: string; visual_description: string;
  camera: string; character: string; dialogue: string; voiceover: string; sound_effects: string;
  prompt: string; image_asset_id: string | null; voice_asset_id: string | null; transition: string;
  speed: number; approved: boolean; status: "draft" | "queued" | "rendering" | "done" | "failed";
  attempts: number; clip_seconds: number; render_seconds: number; provider_used: string | null;
  error: string | null; has_clip: boolean; has_image: boolean;
};

export type Progress = {
  total: number; done: number; rendering: number; queued: number; failed: number; draft: number;
  planned_seconds: number; rendered_seconds: number;
};

export type Project = {
  id: string; title: string; mode: "text" | "image" | "script"; prompt: string; script: string;
  style: string; aspect: string; resolution: number; fps: number; target_seconds: number;
  scene_seconds: number; language: string; voice: string; narration_style: string; music: string;
  burn_subtitles: boolean; compression: string; visual_provider: string;
  status: "draft" | "storyboarding" | "storyboard_ready" | "rendering" | "assembling" | "done" | "failed";
  error: string | null; notes: string[]; output_seconds: number; has_video: boolean;
  created_at: string; updated_at: string; progress: Progress;
  estimate: { remaining_output_seconds: number; measured_ratio: number | null; estimated_wall_seconds: number; basis: string };
  scenes?: Scene[];
};

export type Asset = { id: string; kind: "image" | "audio" | "video" | "music"; filename: string; size_bytes: number; project_id: string | null; created_at: string };

export type Meta = {
  styles: string[]; aspects: string[]; resolutions: number[]; fps: number[];
  languages: Record<string, string>; voices: string[]; narration_styles: string[]; music: string[];
  cameras: string[]; transitions: string[];
  visual_providers: { name: string; label: string; note: string; is_ai: boolean }[];
  limits: { max_project_minutes: number; storage_quota_mb: number; daily_render_minutes: number | null; max_upload_mb: number; self_hosted: boolean; paid_services: string; signup_code_required?: boolean };
};

export type Usage = {
  limits: Meta["limits"]; storage_used_mb: number; storage_quota_mb: number; rendered_last_24h_minutes: number;
  projects: number; videos_completed: number; minutes_exported: number; render_speed_ratio: number | null;
};

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try { return localStorage.getItem("studio_token"); } catch { return null; }
}

export function setToken(t: string | null) {
  try { if (t) localStorage.setItem("studio_token", t); else localStorage.removeItem("studio_token"); } catch {}
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function api<T = unknown>(path: string, opts: { method?: string; body?: unknown; form?: FormData } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(opts.body); }
  const res = await fetch(`${API_URL}/api${path}`, { method: opts.method || (body ? "POST" : "GET"), headers, body });
  if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth")) {
    setToken(null);
    window.location.href = "/login";
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : Array.isArray(j.detail) ? j.detail.map((d: { msg: string }) => d.msg).join("; ") : msg;
    } catch {}
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

/** URL for media that the browser loads directly (video/img tags cannot send headers). */
export function mediaUrl(path: string, opts: { inline?: boolean; bust?: string } = {}): string {
  const t = getToken() || "";
  const q = new URLSearchParams({ token: t });
  if (opts.inline) q.set("inline", "true");
  if (opts.bust) q.set("v", opts.bust);
  return `${API_URL}/api${path}?${q.toString()}`;
}

export function fmtDuration(sec: number): string {
  sec = Math.round(sec);
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? `${h}h ${m}m` : m ? `${m}m ${s.toString().padStart(2, "0")}s` : `${s}s`;
}

export const STATUS_LABEL: Record<Project["status"], string> = {
  draft: "Draft", storyboarding: "Writing storyboard", storyboard_ready: "Storyboard ready",
  rendering: "Rendering scenes", assembling: "Assembling video", done: "Video ready", failed: "Needs attention",
};

// ---------------------------------------------------------------- Luvakule AI Brain

export type Route = { name: string; label: string; connected: boolean; paid?: boolean; motion: string; note: string; cost_per_second: number | null };

export type BrainStatus = {
  writer: { available: boolean; name: string | null; label: string | null; help: string | null };
  routes: Route[]; length_presets: number[]; max_seconds: number; languages: Record<string, string>;
  styles: string[]; shots: string[]; movements: string[]; narration_styles: string[]; music: string[];
};

export type PlanScene = {
  number: number; chapter_id: string; duration: number; title: string; narration: string; dialogue: string;
  characters: string[]; location: string; action: string; expression: string; shot: string; movement: string;
  lighting: string; transition: "cut" | "fade"; sound_effects: string; music_cue: string;
  image_prompt?: string; video_prompt?: string; negative_prompt?: string; camera?: string; prompt_edited?: boolean; scene_id?: string;
};

export type PlanCharacter = { name: string; role: string; appearance: string; clothing: string; personality: string; voice: string; reference_asset_ids: string[]; locked: boolean };
export type PlanLocation = { name: string; description: string; lighting: string; locked: boolean };
export type PlanCheck = { level: "warning" | "info"; scene: number | null; text: string };

export type PlanBody = {
  settings?: Record<string, unknown>;
  brief?: {
    title: string; logline: string; audience: string; goal: string; style: string; visual_style: string; tone: string;
    camera_language: string; narration_style: string; music_mood: string; is_song: boolean; assumptions: string[]; questions: string[];
  };
  characters?: PlanCharacter[]; locations?: PlanLocation[];
  chapters?: { id: string; title: string; summary: string; seconds: number }[];
  scenes?: PlanScene[]; checks?: PlanCheck[];
  audio?: { narrator: string; narration_style: string; music_mood: string; music_note: string; sound_effects_note: string; song_note: string };
  editing?: { subtitles: string; aspect: string; resolution: number; fps: number; transitions: number };
  recommendation?: { route: string; label: string; reasons: string[]; connected: string[]; not_connected: string[] };
  estimate?: { scenes: number; video_seconds: number; cost_usd: number; cost_note: string; ai_writer_calls: number; ai_writer_note: string; estimated_minutes: number; time_basis: string };
};

export type AgentActivity = { id: number; agent: string; action: string; status: "running" | "done" | "failed" | "skipped"; provider: string | null; llm_calls: number; detail: string; started_at: string; finished_at: string | null };

export type Plan = {
  id: string; idea: string; settings: { target_seconds: number; scene_seconds: number; language: string; style: string; aspect: string; voice: string; resolution: number; main_character: string; reference_asset_ids: string[] };
  status: "queued" | "planning" | "ready" | "failed" | "approved"; stage: string; error: string | null; provider: string | null;
  llm_calls: number; project_id: string | null; title: string; scene_count: number; created_at: string; updated_at: string;
  plan?: PlanBody; activity?: AgentActivity[];
};

export type MemoryItem = { id: string; project_id: string; kind: "character" | "location" | "style" | "fact"; name: string; description: string; data: Record<string, unknown>; locked: boolean; updated_at: string };

export const PLAN_STATUS: Record<Plan["status"], string> = {
  queued: "Waiting to start", planning: "Agents at work", ready: "Plan ready for review", failed: "Needs attention", approved: "Approved",
};
