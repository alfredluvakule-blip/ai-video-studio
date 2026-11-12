"""Check the AI providers on this server end to end.

    docker compose exec worker python -m app.selftest

Speaks a short sentence with the natural narrator voice, fetches one AI picture and,
when a key is set, asks the AI writer for a two-scene storyboard. Prints what worked,
what it fell back to, and why. Writes only into STORAGE_DIR/selftest.
"""
from __future__ import annotations

import sys
import time

from .config import settings
from .pipeline import ffmpeg as ff
from .providers import tts
from .providers.llm import StoryboardRequest, pick_writer
from .providers.visual import PROVIDERS, pick_image_provider


def _line(ok: bool | None, text: str) -> None:
    mark = {True: "OK  ", False: "FAIL", None: "--  "}[ok]
    print(f"[{mark}] {text}", flush=True)


def main() -> int:
    out = settings.storage_dir / "selftest"
    out.mkdir(parents=True, exist_ok=True)
    problems = 0

    # ---- voice
    piper = tts.ENGINES[0]
    if not piper.available():
        _line(False, "Natural voice: the piper-tts package is not installed in this image (rebuild with docker compose up --build -d)")
        problems += 1
    for lang, gender in (("en", "female"), ("en", "male"), ("sw", "female")):
        t0 = time.time()
        wav = out / f"voice-{lang}-{gender}.wav"
        try:
            _, engine = tts.synthesize(
                "Habari, karibu kwenye studio yako ya video." if lang == "sw" else "Hello, and welcome to your video studio.",
                lang, gender, "neutral", wav,
            )
            natural = engine.startswith("piper")
            _line(natural, f"Voice {lang}/{gender}: {engine}, {ff.probe_duration(wav):.1f} s of audio in {time.time() - t0:.0f} s")
            problems += 0 if natural else 1
        except Exception as e:
            _line(False, f"Voice {lang}/{gender}: {e}")
            problems += 1
    print(f"       voices folder {settings.piper_voices_dir}: {', '.join(piper.installed_voices()) or 'empty'}")

    # ---- pictures
    prov = pick_image_provider()
    if not prov.is_ai:
        _line(False, "AI pictures: no AI picture source is enabled, so scenes will be text cards")
        problems += 1
    else:
        t0 = time.time()
        try:
            img = prov.image("a misty tea plantation on green hills at sunrise, cinematic film still", "cinematic",
                             1280, 720, out / "picture.png", seed=7)
            from PIL import Image

            size = Image.open(img).size
            _line(True, f"AI pictures: {prov.name} returned a {size[0]}x{size[1]} picture in {time.time() - t0:.0f} s ({img})")
        except Exception as e:
            _line(False, f"AI pictures: {prov.name} failed: {e}")
            problems += 1
    for name, p in PROVIDERS.items():
        print(f"       {name}: {'available' if p.available() else 'off'}")

    # ---- writer
    writer = pick_writer()
    if writer.name == "template":
        _line(None, "AI writer: none configured (add GEMINI_API_KEY to .env for AI-written storyboards); "
                    "your own script is still used, word for word")
    else:
        t0 = time.time()
        try:
            req = StoryboardRequest(mode="text", prompt="how rain forms", script="", style="educational",
                                    target_seconds=20, scene_seconds=10, language="en", narration_style="neutral")
            scenes, _ = writer.storyboard(req)
            _line(True, f"AI writer: {writer.label} wrote {len(scenes)} scenes in {time.time() - t0:.0f} s; "
                        f"first picture prompt: {scenes[0]['prompt'][:100]}")
        except Exception as e:
            _line(False, f"AI writer: {writer.label} failed: {e}")
            problems += 1

    print("All checks passed." if not problems else f"{problems} problem(s) found; see the lines marked FAIL.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
