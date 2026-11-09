"""Visual providers: produce a still image (or a short clip) for a scene.

* ComfyUIProvider     - your own GPU via ComfyUI (SDXL / Flux stills, Stable Video Diffusion clips).
* HuggingFaceImage    - Hugging Face Inference text-to-image (free tier, rate-limited, needs HF_TOKEN).
* UploadedImage       - the user's own photo (Image-to-Video).
* TitleCardRenderer   - CPU, no AI. Draws a styled illustrated card with the scene text.
                        It is a real rendered image, clearly labelled as non-AI.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import random
import time
import uuid
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..config import settings

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
PROVIDERS = {p.name: p for p in (ComfyUIProvider(), HuggingFaceImage(), TITLECARD)}


def pick_image_provider(preference: str = "auto"):
    if preference in PROVIDERS and PROVIDERS[preference].available():
        return PROVIDERS[preference]
    for name in ("comfyui", "huggingface"):
        if PROVIDERS[name].available():
            return PROVIDERS[name]
    return TITLECARD
