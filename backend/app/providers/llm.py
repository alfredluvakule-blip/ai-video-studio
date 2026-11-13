"""Script + storyboard writers.

* OllamaWriter      - free, local LLM (e.g. llama3.2, mistral, qwen) via Ollama.
* GeminiWriter      - Google Gemini through a free Google AI Studio key (GEMINI_API_KEY).
                      Google's free tier is rate-limited and Google may use free-tier
                      content to improve its products.
* HuggingFaceWriter - Hugging Face Inference router (free tier, needs HF_TOKEN, rate limited).
* TemplateWriter    - no AI. Splits the user's own script/prompt into timed scenes.
                      Always available; it never invents narration.
"""
from __future__ import annotations

import json
import logging
import math
import re
import time
from dataclasses import dataclass

import httpx

from ..config import settings

log = logging.getLogger(__name__)

WORDS_PER_SECOND = {"en": 2.5, "sw": 2.2}
CAMERAS = ["zoom_in", "pan_right", "zoom_out", "pan_left", "pan_up", "zoom_in", "pan_down"]

STYLE_HINTS = {
    "realistic": "photorealistic, natural light, 35mm photo",
    "cinematic": "cinematic film still, dramatic lighting, shallow depth of field, anamorphic",
    "cartoon": "colorful cartoon illustration, bold outlines, flat shading",
    "animation": "3D animated movie style, soft lighting, vibrant",
    "educational": "clean educational illustration, clear diagram style, bright",
    "documentary": "documentary photograph, natural, authentic, high detail",
    "storytelling": "storybook illustration, warm painterly style",
}


@dataclass
class StoryboardRequest:
    mode: str
    prompt: str
    script: str
    style: str
    target_seconds: int
    scene_seconds: float
    language: str
    narration_style: str
    image_count: int = 0


class WriterError(RuntimeError):
    pass


class NetworkError(WriterError):
    """The AI service could not be reached (connection refused, cut off or timed out)."""


NETWORK_HELP = ("This is a network problem between this computer and {service}, not a problem with your key: "
                "the connection was cut off. It is often a firewall, antivirus web scanning, a VPN or a weak "
                "connection. Try again in a minute; if it keeps happening, see the README section "
                "'AI writer cannot connect'.")


def post_json(service: str, url: str, attempts: int = 3, **kw) -> httpx.Response:
    """POST with retries when the connection itself fails (TLS cut off, reset, timeout)."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            return httpx.post(url, **kw)
        except httpx.TransportError as e:
            last = e
            log.warning("%s connection failed (attempt %d/%d): %s", service, i + 1, attempts, e)
            if i < attempts - 1:
                time.sleep(3 * (i + 1) ** 2)
    raise NetworkError(f"Could not connect to {service} ({type(last).__name__}: {last}). " + NETWORK_HELP.format(service=service))


def _sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _chunk_sentences(sentences: list[str], words_per_scene: int) -> list[str]:
    chunks, cur, n = [], [], 0
    for s in sentences:
        w = len(s.split())
        if cur and n + w > words_per_scene:
            chunks.append(" ".join(cur))
            cur, n = [], 0
        cur.append(s)
        n += w
    if cur:
        chunks.append(" ".join(cur))
    return chunks


def _scene(i: int, text: str, req: StoryboardRequest, visual: str | None = None, duration: float | None = None) -> dict:
    visual = visual or text or req.prompt
    hint = STYLE_HINTS.get(req.style, "")
    return {
        "title": (text or visual)[:60],
        "duration": duration or req.scene_seconds,
        "visual_description": visual,
        "camera": CAMERAS[i % len(CAMERAS)],
        "character": "",
        "dialogue": "",
        "voiceover": text,
        "sound_effects": "",
        "prompt": f"{visual}, {hint}".strip(", "),
    }


class TemplateWriter:
    name = "template"
    label = "Rule-based splitter (no AI)"

    def available(self) -> bool:
        return True

    def storyboard(self, req: StoryboardRequest) -> tuple[list[dict], list[str]]:
        notes: list[str] = []
        wps = WORDS_PER_SECOND.get(req.language, 2.4)
        words_per_scene = max(5, int(req.scene_seconds * wps))
        source = req.script.strip() or req.prompt.strip()
        sentences = _sentences(source)

        if req.mode == "image" and req.image_count:
            n = req.image_count
            chunks = _chunk_sentences(sentences, max(5, math.ceil(sum(len(s.split()) for s in sentences) / n))) if sentences else []
            scenes = [_scene(i, chunks[i] if i < len(chunks) else "", req, visual=f"Photo {i + 1}") for i in range(n)]
            return scenes, notes

        if req.script.strip():
            chunks = _chunk_sentences(sentences, words_per_scene)
            scenes = []
            for i, c in enumerate(chunks):
                dur = max(req.scene_seconds * 0.5, min(req.scene_seconds * 2, len(c.split()) / wps + 1.0))
                scenes.append(_scene(i, c, req, duration=round(dur, 1)))
            return scenes, notes

        n = max(1, round(req.target_seconds / req.scene_seconds))
        chunks = _chunk_sentences(sentences, words_per_scene) if sentences else []
        scenes = [_scene(i, chunks[i] if i < len(chunks) else "", req, visual=req.prompt) for i in range(n)]
        if len(chunks) < n:
            notes.append(
                f"{n - len(chunks)} scene(s) have no narration: the rule-based writer does not invent text. "
                "Write the voice-over in the storyboard, paste a full script, or connect an AI writer "
                "(a free Gemini key, Ollama or Hugging Face)."
            )
        return scenes, notes


_LLM_INSTRUCTIONS = """You are a video scriptwriter and storyboard artist.
Write a {style} video about: "{prompt}".
Narration language: {language_name}. Narration style: {narration_style}.
Produce exactly {n} scenes of about {secs} seconds each (about {words} spoken words per scene).
Return ONLY a JSON array, no prose. Each item must have these string keys:
"title", "visual_description", "camera" (one of: zoom_in, zoom_out, pan_left, pan_right, pan_up, pan_down, static),
"character", "dialogue", "voiceover", "sound_effects", "prompt" (a detailed text-to-image prompt in English).
Keep characters consistent: repeat the same character description in every scene where they appear."""

LANG_NAMES = {"en": "English", "sw": "Kiswahili", "fr": "French", "es": "Spanish", "pt": "Portuguese", "ar": "Arabic"}


def _parse_json_array(text: str) -> list[dict]:
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        raise WriterError("model did not return a JSON array")
    data = json.loads(m.group(0))
    if not isinstance(data, list) or not data:
        raise WriterError("empty storyboard")
    return [d for d in data if isinstance(d, dict)]


def _normalise(items: list[dict], req: StoryboardRequest) -> list[dict]:
    out = []
    hint = STYLE_HINTS.get(req.style, "")
    for i, d in enumerate(items):
        s = _scene(i, str(d.get("voiceover", "")), req, visual=str(d.get("visual_description") or req.prompt))
        for k in ("title", "character", "dialogue", "sound_effects"):
            if d.get(k):
                s[k] = str(d[k])[: 200 if k == "title" else 4000]
        cam = str(d.get("camera", "")).lower()
        if cam in {"zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "static"}:
            s["camera"] = cam
        if d.get("prompt"):
            s["prompt"] = f"{d['prompt']}, {hint}".strip(", ")
        out.append(s)
    return out


class _LLMWriter:
    name = "llm"
    label = "LLM"
    batch = 12  # scenes per request so long-form projects stay within context windows

    def complete(self, prompt: str) -> str:  # pragma: no cover - network
        raise NotImplementedError

    def storyboard(self, req: StoryboardRequest) -> tuple[list[dict], list[str]]:
        if req.script.strip() or (req.mode == "image" and req.image_count):
            # The user's own words stay authoritative; the LLM only adds visuals.
            scenes, notes = TemplateWriter().storyboard(req)
            return self._enrich(scenes, req, notes), notes
        n = max(1, round(req.target_seconds / req.scene_seconds))
        words = int(req.scene_seconds * WORDS_PER_SECOND.get(req.language, 2.4))
        scenes: list[dict] = []
        while len(scenes) < n:
            k = min(self.batch, n - len(scenes))
            context = ""
            if scenes:
                recap = " ".join(s["voiceover"] for s in scenes[-3:])[-1200:]
                context = (
                    f"\nThis is part of a longer video. Scenes 1-{len(scenes)} are written. "
                    f"Continue from scene {len(scenes) + 1}. The last narration was: \"{recap}\"."
                )
            text = self.complete(
                _LLM_INSTRUCTIONS.format(
                    style=req.style,
                    prompt=req.prompt,
                    language_name=LANG_NAMES.get(req.language, req.language),
                    narration_style=req.narration_style,
                    n=k,
                    secs=int(req.scene_seconds),
                    words=words,
                )
                + context
            )
            batch = _normalise(_parse_json_array(text), req)[:k]
            if not batch:
                raise WriterError("model returned no scenes")
            scenes.extend(batch)
        return scenes, []

    def _enrich(self, scenes: list[dict], req: StoryboardRequest, notes: list[str] | None = None) -> list[dict]:
        missed, why = 0, ""
        for start in range(0, len(scenes), self.batch):
            part = scenes[start : start + self.batch]
            listing = "\n".join(f"{i + 1}. {s['voiceover'] or s['visual_description']}" for i, s in enumerate(part))
            prompt = (
                f"Topic: {req.prompt}\nStyle: {req.style}\nFor each numbered narration line below, write a "
                "storyboard entry. Return ONLY a JSON array with one object per line, keys: title, "
                "visual_description, camera (one of: zoom_in, zoom_out, pan_left, pan_right, pan_up, pan_down, static), "
                "character, sound_effects, prompt. The prompt is a detailed English text-to-image prompt that shows what "
                "the narration is about: subject, setting, action, lighting and mood, with no written words in the picture. "
                "Describe recurring people or places the same way every time so they look consistent.\n"
                + listing
            )
            try:
                items = _parse_json_array(self.complete(prompt))
            except Exception as e:  # keep the user's script even if enrichment fails
                log.warning("storyboard enrichment failed: %s", e)
                missed, why = missed + len(part), str(e)[:200]
                continue
            for s, d in zip(part, _normalise(items, req)):
                for k in ("title", "visual_description", "camera", "character", "sound_effects", "prompt"):
                    s[k] = d[k]
        if missed and notes is not None:
            notes.append(
                f"{self.label} could not describe the pictures for {missed} of {len(scenes)} scenes ({why}). "
                "Those scenes use your narration text as the picture description; you can edit it in the storyboard."
            )
        return scenes


class OllamaWriter(_LLMWriter):
    name = "ollama"
    label = "Ollama (local, free)"

    def available(self) -> bool:
        try:
            r = httpx.get(f"{settings.ollama_url}/api/tags", timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    def complete(self, prompt: str) -> str:
        r = httpx.post(
            f"{settings.ollama_url}/api/generate",
            json={"model": settings.ollama_model, "prompt": prompt, "stream": False, "options": {"temperature": 0.7}},
            timeout=600,
        )
        r.raise_for_status()
        return r.json().get("response", "")


class GeminiWriter(_LLMWriter):
    name = "gemini"
    label = "Google Gemini (free API key, rate-limited)"
    batch = 20  # fewer, larger requests: the free tier allows only a few requests per minute
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def available(self) -> bool:
        return bool(settings.gemini_api_key)

    model: str | None = None  # set when Google tells us the configured model was retired

    def complete(self, prompt: str) -> str:
        last = ""
        for attempt in range(4):
            model = self.model or settings.gemini_model
            r = post_json(
                "Google Gemini", self.URL.format(model=model),
                headers={"x-goog-api-key": settings.gemini_api_key or ""},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.7, "responseMimeType": "application/json"},
                },
                timeout=300,
            )
            if r.status_code == 200:
                parts = (r.json().get("candidates") or [{}])[0].get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts)
                if not text:
                    raise WriterError("Gemini returned no text (the request may have been blocked)")
                return text
            last = f"Gemini returned {r.status_code}: {r.text[:200]}"
            if r.status_code == 404:
                # Google retires models and names the replacement, e.g. "Please update your code
                # to use models/gemini-3.8-flash". Follow that once instead of failing every call.
                m = re.search(r"use models/([\w.\-]+)", r.text)
                if m and m.group(1) != model and attempt < 3:
                    log.warning("Gemini model %s is retired; using %s (set GEMINI_MODEL to keep it)", model, m.group(1))
                    self.model = m.group(1)
                    continue
                raise WriterError(f"Gemini does not offer the model '{model}'. Set GEMINI_MODEL in .env to a current "
                                  f"model (see https://ai.google.dev/gemini-api/docs/models). {last}")
            if r.status_code in (429, 500, 503) and attempt < 3:
                time.sleep(_retry_delay(r, default=20 * (attempt + 1)))
                continue
            if r.status_code == 429:
                raise WriterError("Gemini free-tier limit reached; try again in a minute (or tomorrow if the daily limit is used up)")
            if r.status_code in (400, 401, 403):
                raise WriterError(f"Gemini rejected the request. Check GEMINI_API_KEY and GEMINI_MODEL. {last}")
            raise WriterError(last)
        raise WriterError(last)


def _retry_delay(r: httpx.Response, default: float) -> float:
    """Seconds to wait before retrying, from the API's own hint when it gives one."""
    try:
        for d in r.json().get("error", {}).get("details", []):
            m = re.fullmatch(r"(\d+(?:\.\d+)?)s", str(d.get("retryDelay", "")))
            if m:
                return min(90.0, float(m.group(1)) + 1)
    except Exception:
        pass
    return min(90.0, default)


class HuggingFaceWriter(_LLMWriter):
    name = "huggingface"
    label = "Hugging Face Inference (free tier, rate-limited)"

    def available(self) -> bool:
        return bool(settings.hf_token)

    def complete(self, prompt: str) -> str:
        r = post_json(
            "Hugging Face", "https://router.huggingface.co/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.hf_token}"},
            json={
                "model": settings.hf_llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 4000,
                "temperature": 0.7,
            },
            timeout=300,
        )
        if r.status_code == 429:
            raise WriterError("Hugging Face free-tier rate limit reached; try again later or use Ollama locally")
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


WRITERS = {w.name: w for w in (OllamaWriter(), GeminiWriter(), HuggingFaceWriter(), TemplateWriter())}


def pick_writer() -> object:
    choice = settings.llm_provider
    if choice != "auto":
        w = WRITERS.get(choice)
        if w and w.available():
            return w
    for name in ("ollama", "gemini", "huggingface"):
        if WRITERS[name].available():
            return WRITERS[name]
    return WRITERS["template"]
