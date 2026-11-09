"""Local, free text-to-speech providers. All run offline on CPU.

* PiperTTS  - neural voices (best quality). Needs the `piper` binary and .onnx voice
              files in PIPER_VOICES_DIR, e.g. en_US-amy-medium.onnx, sw_CD-lanfrica-medium.onnx.
* EspeakTTS - espeak-ng, 100+ languages including Kiswahili. Robotic but dependable.
* FliteTTS  - CMU Flite through FFmpeg's built-in `flite` filter. English only.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..config import settings
from ..pipeline import ffmpeg as ff

STYLES = {  # words per minute, pitch (espeak 0-99)
    "neutral": (160, 50),
    "calm": (140, 42),
    "energetic": (185, 62),
    "storytelling": (150, 48),
    "documentary": (150, 40),
    "children": (145, 70),
}

LANGUAGES = {
    "en": "English",
    "sw": "Kiswahili",
    "fr": "French",
    "es": "Spanish",
    "pt": "Portuguese",
    "ar": "Arabic",
}


class TTSError(RuntimeError):
    pass


class PiperTTS:
    name = "piper"
    label = "Piper neural TTS (local)"

    def _voices(self) -> list[Path]:
        d = settings.piper_voices_dir
        return sorted(d.glob("*.onnx")) if d.exists() else []

    def available(self) -> bool:
        return shutil.which(settings.piper_bin) is not None and bool(self._voices())

    def supports(self, language: str) -> bool:
        return any(v.name.startswith(language + "_") for v in self._voices())

    def voice_for(self, language: str, gender: str) -> Path | None:
        matches = [v for v in self._voices() if v.name.startswith(language + "_")]
        if not matches:
            return None
        female_hints = ("amy", "lessac", "kathleen", "jenny", "female", "alba", "siwis")
        male_hints = ("ryan", "joe", "alan", "male", "danny", "lanfrica")
        hints = female_hints if gender == "female" else male_hints
        for v in matches:
            if any(h in v.name for h in hints):
                return v
        return matches[0]

    def synth(self, text: str, language: str, gender: str, style: str, out: Path) -> Path:
        voice = self.voice_for(language, gender)
        if not voice:
            raise TTSError(f"no Piper voice for {language}")
        wpm, _ = STYLES.get(style, STYLES["neutral"])
        length_scale = round(160 / wpm, 2)
        p = subprocess.run(
            [settings.piper_bin, "--model", str(voice), "--output_file", str(out), "--length_scale", str(length_scale)],
            input=text,
            text=True,
            capture_output=True,
            timeout=600,
        )
        if p.returncode != 0:
            raise TTSError(p.stderr[-500:])
        return out


class EspeakTTS:
    name = "espeak-ng"
    label = "eSpeak NG (local, many languages incl. Kiswahili)"

    def _bin(self) -> str | None:
        return shutil.which("espeak-ng") or shutil.which("espeak")

    def available(self) -> bool:
        return self._bin() is not None

    def supports(self, language: str) -> bool:
        return language in LANGUAGES

    def synth(self, text: str, language: str, gender: str, style: str, out: Path) -> Path:
        wpm, pitch = STYLES.get(style, STYLES["neutral"])
        variant = "f3" if gender == "female" else "m3"
        if gender == "female":
            pitch = min(99, pitch + 15)
        p = subprocess.run(
            [self._bin(), "-v", f"{language}+{variant}", "-s", str(wpm), "-p", str(pitch), "-w", str(out), "--stdin"],
            input=text,
            text=True,
            capture_output=True,
            timeout=600,
        )
        if p.returncode != 0 or not out.exists():
            raise TTSError(p.stderr[-500:] or "espeak-ng failed")
        return out


class FliteTTS:
    name = "flite"
    label = "CMU Flite via FFmpeg (local, English)"

    def available(self) -> bool:
        try:
            p = subprocess.run([settings.ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=10)
            return " flite " in p.stdout
        except Exception:
            return False

    def supports(self, language: str) -> bool:
        return language == "en"

    def synth(self, text: str, language: str, gender: str, style: str, out: Path) -> Path:
        txt = out.with_suffix(".txt")
        txt.write_text(text)
        voice = "slt" if gender == "female" else "rms"
        ff.run(["-f", "lavfi", "-i", f"flite=textfile='{txt.as_posix()}':voice={voice}", str(out)])
        txt.unlink(missing_ok=True)
        return out


ENGINES = [PiperTTS(), EspeakTTS(), FliteTTS()]


def synthesize(text: str, language: str, gender: str, style: str, out: Path) -> tuple[Path, str]:
    """Speak `text` into a WAV file. Returns (path, engine name)."""
    errors = []
    for eng in ENGINES:
        if eng.available() and eng.supports(language):
            try:
                return eng.synth(text, language, gender, style, out), eng.name
            except Exception as e:  # try the next engine
                errors.append(f"{eng.name}: {e}")
    raise TTSError("No local TTS engine could speak this language. " + "; ".join(errors))


def status() -> list[dict]:
    return [
        {
            "name": e.name,
            "label": e.label,
            "available": e.available(),
            "languages": [l for l in LANGUAGES if e.available() and e.supports(l)],
        }
        for e in ENGINES
    ]
