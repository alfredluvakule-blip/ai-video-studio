"""Visual providers: produce a still image (or a short clip) for a scene.

* ComfyUIProvider     - your own GPU via ComfyUI (SDXL / Flux stills, Stable Video Diffusion clips).
* HuggingFaceImage    - Hugging Face Inference text-to-image (free tier, rate-limited, needs HF_TOKEN).
* PollinationsImage   - pollinations.ai text-to-image. Free, no account or key. Anonymous use is
                        limited to about one picture every 15 seconds, so requests are paced.
                        The scene's picture prompt is sent to that third-party service.
* UploadedImage       - the user's own photo (Image-to-Video).
* TitleCardRenderer   - CPU, no AI. Draws a styled illustrated card with the scene text.
                        It is a real rendered image, clearly labelled as non-AI.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import math
import random
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..config import settings
from ..util import file_lock

log = logging.getLogger(__name__)


class VisualError(RuntimeError):
    pass


PALETTES = {
    "realistic": [(28, 38, 52), (84, 110, 122), (210, 190, 160)],
    "cinematic": [(8, 12, 28), (40, 60, 110), (240, 150, 70)],
    "cartoon": [(255, 214, 90), (90, 200, 250), (255, 105, 140)],
    "animation": [(60, 30, 120), (120, 90, 220), (255, 190, 120)],
    "educational": [(235, 245, 255), (120, 180, 240), (30, 80, 160)],
    "documentary": [(40, 36, 30), (120, 100, 70), (220, 210, 190)],
    "storytelling": [(70, 40, 30), (190, 120, 70), (250, 225, 170)],
}

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def _font(size: int) -> ImageFont.ImageFont:
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


class TitleCardRenderer:
    name = "titlecard"
    label = "Title-card renderer (CPU, non-AI)"
    short = "Text cards (no AI)"
    note = ""
    is_ai = False

    def available(self) -> bool:
        return True

    def image(self, prompt: str, style: str, width: int, height: int, out: Path, caption: str = "", seed: int = 0) -> Path:
        pal = PALETTES.get(style, PALETTES["cinematic"])
        rng = random.Random(seed or int(hashlib.md5(prompt.encode()).hexdigest()[:8], 16))
        img = Image.new("RGB", (width, height))
        g = ImageDraw.Draw(img)
        for y in range(height):  # vertical gradient
            g.line([(0, y), (width, y)], fill=_lerp(pal[0], pal[1], y / max(1, height - 1)))
        layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        # soft "bokeh" shapes
        for _ in range(18):
            r = rng.randint(min(width, height) // 20, min(width, height) // 5)
            x, y = rng.randint(-r, width + r), rng.randint(-r, height + r)
            col = _lerp(pal[1], pal[2], rng.random())
            d.ellipse([x - r, y - r, x + r, y + r], fill=col + (rng.randint(30, 90),))
        # layered hills
        for k in range(3):
            base = height * (0.62 + 0.12 * k)
            amp, freq, ph = height * 0.05, rng.uniform(1.0, 3.0), rng.uniform(0, 6.28)
            pts = [(x, base + amp * math.sin(freq * x / width * 6.28 + ph)) for x in range(0, width + 20, 20)]
            pts += [(width, height), (0, height)]
            d.polygon(pts, fill=_lerp(pal[0], pal[2], 0.15 + 0.2 * k) + (200,))
        layer = layer.filter(ImageFilter.GaussianBlur(radius=max(2, width // 300)))
        img = Image.alpha_composite(img.convert("RGBA"), layer)

        text = (caption or prompt).strip()
        if text:
            size = max(18, int(min(width, height) / 16))
            font = _font(size)
            measure = ImageDraw.Draw(img)
            lines: list[str] = []
            for word in text.split():  # wrap by measured width (75% of frame)
                trial = f"{lines[-1]} {word}" if lines else word
                if lines and measure.textlength(trial, font=font) <= width * 0.75:
                    lines[-1] = trial
                else:
                    lines.append(word)
            lines = lines[:5]
            line_h = int(size * 1.3)
            block_h = line_h * len(lines)
            top = int(height * 0.40 - block_h / 2)
            pad = size // 2
            maxw = max(measure.textlength(l, font=font) for l in lines)
            box_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            bd = ImageDraw.Draw(box_layer)
            bd.rounded_rectangle([(width - maxw) / 2 - pad, top - pad, (width + maxw) / 2 + pad, top + block_h + pad],
                                 radius=pad, fill=(0, 0, 0, 120))
            for i, line in enumerate(lines):
                w = bd.textlength(line, font=font)
                bd.text(((width - w) / 2, top + i * line_h), line, font=font, fill=(255, 255, 255, 255))
            img = Image.alpha_composite(img, box_layer)
        out.parent.mkdir(parents=True, exist_ok=True)
        img.convert("RGB").save(out, "PNG")
        return out


class HuggingFaceImage:
    name = "huggingface"
    label = "Hugging Face text-to-image (free tier, rate-limited)"
    short = "AI pictures (Hugging Face)"
    note = "Picture descriptions are sent to Hugging Face. Its free allowance is small and rate-limited."
    is_ai = True

    def available(self) -> bool:
        return bool(settings.hf_token)

    def image(self, prompt: str, style: str, width: int, height: int, out: Path, caption: str = "", seed: int = 0) -> Path:
        r = httpx.post(
            f"https://router.huggingface.co/hf-inference/models/{settings.hf_image_model}",
            headers={"Authorization": f"Bearer {settings.hf_token}", "Accept": "image/png"},
            json={"inputs": prompt, "parameters": {"width": min(width, 1344) // 8 * 8, "height": min(height, 1344) // 8 * 8}},
            timeout=300,
        )
        if r.status_code == 429:
            raise VisualError("Hugging Face free-tier limit reached")
        if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/"):
            raise VisualError(f"Hugging Face returned {r.status_code}: {r.text[:200]}")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(r.content)
        return out


class PollinationsImage:
    """Free AI pictures from pollinations.ai (no account, no key).

    Anonymous requests are rate-limited by the service, so every worker process
    shares one gate (a lock file plus a small state file) that spaces requests
    out. After repeated failures the provider pauses itself for a while so a
    long render does not stall; affected scenes fall back to title cards and are
    labelled as such.
    """

    name = "pollinations"
    label = "Pollinations AI pictures (free online service, no account, about 1 picture per 15 s)"
    short = "AI pictures (Pollinations, free)"
    note = ("Picture descriptions are sent to pollinations.ai, a free online service. It allows about four pictures "
            "a minute, so long videos take a while. If it is unavailable, a scene falls back to a text card and says so.")
    is_ai = True
    URL = "https://image.pollinations.ai/prompt/"
    ATTEMPTS = 3
    PAUSE_AFTER_FAILURES = 3
    PAUSE_SECONDS = 600

    def available(self) -> bool:
        return settings.pollinations_enabled

    # ---- shared state (all worker processes) ----
    def _state_path(self) -> Path:
        return settings.storage_dir / ".locks" / "pollinations.json"

    def _load(self) -> dict:
        try:
            return json.loads(self._state_path().read_text())
        except Exception:
            return {}

    def _save(self, state: dict) -> None:
        self._state_path().write_text(json.dumps(state))

    def paused_for(self) -> float:
        """Seconds left of the pause that follows repeated failures (0 when not paused)."""
        return max(0.0, float(self._load().get("paused_until", 0)) - time.time())

    def image(self, prompt: str, style: str, width: int, height: int, out: Path, caption: str = "", seed: int = 0) -> Path:
        left = self.paused_for()
        if left > 0:
            raise VisualError(f"Pollinations is paused for {left / 60:.0f} more min after repeated failures")
        scale = min(1.0, 1280 / max(width, height))
        w, h = max(256, int(width * scale) // 8 * 8), max(256, int(height * scale) // 8 * 8)
        text = " ".join((prompt or caption or "abstract background").split())[:900]
        params = {"width": w, "height": h, "seed": seed or random.randint(1, 2**31 - 1),
                  "model": settings.pollinations_model, "nologo": "true", "private": "true"}
        last_error, rejected = "no attempt made", False
        with file_lock("pollinations"):  # one request at a time, across workers
            for attempt in range(1, self.ATTEMPTS + 1):
                state = self._load()
                if float(state.get("paused_until", 0)) > time.time():
                    raise VisualError("Pollinations is paused after repeated failures")
                wait = float(state.get("last_request", 0)) + settings.pollinations_interval * attempt - time.time()
                if wait > 0:
                    time.sleep(min(wait, 120))
                state["last_request"] = time.time()
                self._save(state)
                try:
                    r = httpx.get(self.URL + quote(text, safe=""), params=params, follow_redirects=True,
                                  timeout=httpx.Timeout(90, connect=15))
                    if r.status_code == 200:
                        img = Image.open(io.BytesIO(r.content))
                        img.load()
                        if min(img.size) < 128:
                            raise VisualError(f"unexpectedly small picture {img.size}")
                        out.parent.mkdir(parents=True, exist_ok=True)
                        img.convert("RGB").save(out, "PNG")
                        state["failures"] = 0
                        self._save(state)
                        return out
                    last_error = f"HTTP {r.status_code}: {r.text[:120]}"
                    if r.status_code not in (408, 425, 429) and r.status_code < 500:
                        rejected = True  # this prompt was refused; retrying will not help
                        break
                except VisualError as e:
                    last_error = str(e)
                except Exception as e:  # network trouble or an unreadable picture
                    last_error = f"{type(e).__name__}: {e}"
                log.warning("pollinations attempt %d/%d failed: %s", attempt, self.ATTEMPTS, last_error)
            state = self._load()
            state["failures"] = int(state.get("failures", 0)) + (0 if rejected else 1)
            if state["failures"] >= self.PAUSE_AFTER_FAILURES:
                state["paused_until"] = time.time() + self.PAUSE_SECONDS
                state["failures"] = 0
                log.warning("pollinations paused for %d s after repeated failures", self.PAUSE_SECONDS)
            self._save(state)
        raise VisualError(f"Pollinations did not return a picture ({last_error})")


def _fill(node, values: dict):
    if isinstance(node, dict):
        return {k: _fill(v, values) for k, v in node.items()}
    if isinstance(node, list):
        return [_fill(v, values) for v in node]
    if isinstance(node, str):
        for k, v in values.items():
            if node == "{{%s}}" % k:
                return v  # keep numeric types
            node = node.replace("{{%s}}" % k, str(v))
    return node


class ComfyUIProvider:
    """Runs ComfyUI workflows saved in API format with {{PROMPT}}, {{NEGATIVE}}, {{WIDTH}},
    {{HEIGHT}}, {{SEED}}, {{IMAGE}}, {{FRAMES}}, {{FPS}} placeholders."""

    name = "comfyui"
    label = "ComfyUI on your GPU (SDXL / Stable Video Diffusion)"
    short = "ComfyUI on your GPU"
    note = ""
    is_ai = True

    def available(self) -> bool:
        if not settings.comfyui_url:
            return False
        try:
            return httpx.get(f"{settings.comfyui_url}/system_stats", timeout=2).status_code == 200
        except Exception:
            return False

    def video_available(self) -> bool:
        return self.available() and bool(settings.comfyui_video_workflow)

    def _run(self, workflow_path: str, values: dict, out: Path, timeout: int = 1800) -> Path:
        wf = _fill(json.loads(Path(workflow_path).read_text()), values)
        base = settings.comfyui_url
        cid = uuid.uuid4().hex
        r = httpx.post(f"{base}/prompt", json={"prompt": wf, "client_id": cid}, timeout=30)
        if r.status_code != 200:
            raise VisualError(f"ComfyUI rejected workflow: {r.text[:300]}")
        pid = r.json()["prompt_id"]
        deadline = time.time() + timeout
        while time.time() < deadline:
            h = httpx.get(f"{base}/history/{pid}", timeout=30).json()
            if pid in h:
                entry = h[pid]
                if entry.get("status", {}).get("status_str") == "error":
                    raise VisualError("ComfyUI workflow failed")
                for node_out in entry.get("outputs", {}).values():
                    for key in ("gifs", "videos", "images"):
                        for f in node_out.get(key, []):
                            data = httpx.get(
                                f"{base}/view",
                                params={"filename": f["filename"], "subfolder": f.get("subfolder", ""), "type": f.get("type", "output")},
                                timeout=120,
                            )
                            data.raise_for_status()
                            target = out.with_suffix(Path(f["filename"]).suffix or out.suffix)
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_bytes(data.content)
                            return target
                raise VisualError("ComfyUI finished without outputs")
            time.sleep(2)
        raise VisualError("ComfyUI timed out")

    def image(self, prompt: str, style: str, width: int, height: int, out: Path, caption: str = "", seed: int = 0) -> Path:
        if not settings.comfyui_image_workflow:
            raise VisualError("COMFYUI_IMAGE_WORKFLOW is not set")
        return self._run(
            settings.comfyui_image_workflow,
            {
                "PROMPT": prompt,
                "NEGATIVE": "blurry, low quality, watermark, text, deformed",
                "WIDTH": min(width, 1344) // 8 * 8,
                "HEIGHT": min(height, 1344) // 8 * 8,
                "SEED": seed or random.randint(1, 2**31),
            },
            out,
        )

    def clip_from_image(self, image: Path, seconds: float, fps: int, width: int, height: int, out: Path, seed: int = 0) -> Path:
        up = httpx.post(
            f"{settings.comfyui_url}/upload/image",
            files={"image": (image.name, image.read_bytes(), "image/png")},
            data={"overwrite": "true"},
            timeout=120,
        )
        up.raise_for_status()
        frames = max(14, min(25, int(seconds * 6)))  # SVD-XT generates up to 25 frames per pass
        return self._run(
            settings.comfyui_video_workflow,
            {
                "IMAGE": up.json()["name"],
                "WIDTH": 1024 if width >= height else 576,
                "HEIGHT": 576 if width >= height else 1024,
                "FRAMES": frames,
                "FPS": 6,
                "SEED": seed or random.randint(1, 2**31),
            },
            out,
        )


TITLECARD = TitleCardRenderer()
PROVIDERS = {p.name: p for p in (ComfyUIProvider(), HuggingFaceImage(), PollinationsImage(), TITLECARD)}
AUTO_ORDER = ("comfyui", "huggingface", "pollinations")


def pick_image_provider(preference: str = "auto"):
    if preference in PROVIDERS and PROVIDERS[preference].available():
        return PROVIDERS[preference]
    for name in AUTO_ORDER:
        if PROVIDERS[name].available():
            return PROVIDERS[name]
    return TITLECARD


def fallback_chain(preference: str = "auto") -> list:
    """Providers to try for one scene, best first, always ending with the title card.

    An explicit choice is respected. With "auto", a failing AI source hands over to
    the next available one before the title card is used.
    """
    first = pick_image_provider(preference)
    chain = [first]
    if preference == "auto" and first.name in AUTO_ORDER:
        later = AUTO_ORDER[AUTO_ORDER.index(first.name) + 1:]
        chain += [PROVIDERS[n] for n in later if PROVIDERS[n].available()]
    if TITLECARD not in chain:
        chain.append(TITLECARD)
    return chain
