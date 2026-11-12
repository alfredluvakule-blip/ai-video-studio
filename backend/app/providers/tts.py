"""Free text-to-speech providers. All run locally on CPU.

* PiperTTS  - natural-sounding neural voices (the `piper-tts` package). Voice files are
              downloaded once, on first use, from the public rhasspy/piper-voices repository
              on Hugging Face into PIPER_VOICES_DIR (no account needed). You can also drop
              any Piper `.onnx` + `.onnx.json` voice pair into that folder yourself.
              Voices run on the CPU; no text leaves the machine.
* EspeakTTS - espeak-ng, 100+ languages including Kiswahili. Robotic but dependable.
* FliteTTS  - CMU Flite through FFmpeg's built-in `flite` filter. English only.
"""
from __future__ import annotations

import importlib.util
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

from ..config import settings
from ..pipeline import ffmpeg as ff
from ..util import file_lock

log = logging.getLogger(__name__)

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

# Default Piper voices, chosen for licences that allow any use (public domain, CC0 or
# CC BY with credit). Licences come from each voice's MODEL_CARD in rhasspy/piper-voices.
# Some languages have only one voice, which is then used for both genders.
# Override one with PIPER_VOICE_<LANG>_<GENDER>, e.g. PIPER_VOICE_EN_MALE=en_US-ryan-high.
VOICE_INFO: dict[str, dict[str, str]] = {
    "en_US-ljspeech-high": {"gender": "female", "licence": "public domain (LJ Speech)"},
    "en_US-ljspeech-medium": {"gender": "female", "licence": "public domain (LJ Speech)"},
    "en_US-joe-medium": {"gender": "male", "licence": "CC0"},
    "fr_FR-siwis-medium": {"gender": "female", "licence": "CC BY 4.0",
                           "credit": "Voice trained on the SIWIS French Speech Synthesis Database (CC BY 4.0)"},
    "es_ES-davefx-medium": {"gender": "male", "licence": "CC0"},
    "pt_BR-faber-medium": {"gender": "male", "licence": "CC0"},
    "sw_CD-lanfrica-medium": {
        "gender": "", "licence": "non-profit, educational and public-benefit use only (Lanfrica Kiswahili TTS dataset)",
        "credit": "Kiswahili voice trained on the Lanfrica Kiswahili TTS dataset, permitted for non-profit, "
                  "educational and public-benefit use. For commercial videos, pick the eSpeak voice or record your own.",
    },
    "ar_JO-kareem-medium": {"gender": "male", "licence": "not stated by the voice's publisher; check before commercial use",
                            "credit": "Arabic voice ar_JO-kareem: its dataset licence is not stated. Check it before commercial use."},
}
PIPER_DEFAULTS: dict[str, dict[str, list[str]]] = {
    "en": {"female": ["en_US-ljspeech-high", "en_US-ljspeech-medium"], "male": ["en_US-joe-medium"]},
    "sw": {"female": ["sw_CD-lanfrica-medium"], "male": ["sw_CD-lanfrica-medium"]},
    "fr": {"female": ["fr_FR-siwis-medium"], "male": ["fr_FR-siwis-medium"]},
    "es": {"female": ["es_ES-davefx-medium"], "male": ["es_ES-davefx-medium"]},
    "pt": {"female": ["pt_BR-faber-medium"], "male": ["pt_BR-faber-medium"]},
    "ar": {"female": ["ar_JO-kareem-medium"], "male": ["ar_JO-kareem-medium"]},
}


def wanted_voices(language: str, gender: str) -> list[str]:
    """Voices to try for a language and gender: a configured override first, then the defaults."""
    override = (os.getenv(f"PIPER_VOICE_{language.upper()}_{gender.upper()}") or "").strip()
    defaults = PIPER_DEFAULTS.get(language, {}).get(gender, [])
    return ([override] if override and not override.startswith("#") else []) + [v for v in defaults if v != override]


def voice_credit(voice: str) -> str | None:
    """A note to show with a finished video when its narrator voice needs credit or has limits."""
    return VOICE_INFO.get(voice, {}).get("credit")


PIPER_URL = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
    "{family}/{code}/{name}/{quality}/{code}-{name}-{quality}{ext}?download=true"
)
_VOICE_RE = re.compile(r"^(?P<family>[a-z]+)_(?P<region>[A-Za-z]+)-(?P<name>[^-]+)-(?P<quality>.+)$")
_RETRY_FAILED_AFTER = 600  # seconds before a failed voice download is tried again
_failed_downloads: dict[str, float] = {}
_offline_until = 0.0  # set when the voice host cannot be reached at all


class TTSError(RuntimeError):
    pass


class PiperTTS:
    name = "piper"
    label = "Piper neural voices (natural-sounding, local, free)"

    def _dir(self) -> Path:
        return settings.piper_voices_dir

    def _installed(self, voice: str) -> Path | None:
        model, cfg = self._dir() / f"{voice}.onnx", self._dir() / f"{voice}.onnx.json"
        ok = model.exists() and model.stat().st_size > 1_000_000 and cfg.exists() and cfg.stat().st_size > 0
        return model if ok else None

    def installed_voices(self) -> list[str]:
        d = self._dir()
        if not d.exists():
            return []
        return sorted(p.name[: -len(".onnx")] for p in d.glob("*.onnx") if self._installed(p.name[: -len(".onnx")]))

    def available(self) -> bool:
        return importlib.util.find_spec("piper") is not None

    def supports(self, language: str) -> bool:
        if any(v.startswith(language + "_") for v in self.installed_voices()):
            return True
        return settings.piper_auto_download and bool(wanted_voices(language, "female") or wanted_voices(language, "male"))

    def _download(self, voice: str) -> Path | None:
        m = _VOICE_RE.match(voice)
        if not m or not settings.piper_auto_download:
            return None
        global _offline_until
        if time.time() < _offline_until or time.time() - _failed_downloads.get(voice, 0) < _RETRY_FAILED_AFTER:
            return None
        d = self._dir()
        try:
            d.mkdir(parents=True, exist_ok=True)
            with file_lock("piper-download"):
                if self._installed(voice):  # another worker fetched it while we waited
                    return self._installed(voice)
                code = f"{m['family']}_{m['region']}"
                log.info("downloading Piper voice %s (one-time)", voice)
                for ext in (".onnx.json", ".onnx"):
                    url = PIPER_URL.format(family=m["family"], code=code, name=m["name"], quality=m["quality"], ext=ext)
                    tmp = d / f".{voice}{ext}.part"
                    with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(120, connect=15)) as r:
                        r.raise_for_status()
                        with open(tmp, "wb") as fh:
                            for chunk in r.iter_bytes(1 << 20):
                                fh.write(chunk)
                    tmp.replace(d / f"{voice}{ext}")
                if not self._installed(voice):
                    raise TTSError("the downloaded voice file is incomplete")
                log.info("Piper voice %s is ready", voice)
            return self._installed(voice)
        except Exception as e:
            log.warning("could not download Piper voice %s: %s", voice, e)
            _failed_downloads[voice] = time.time()
            if isinstance(e, httpx.ConnectError | httpx.ConnectTimeout):
                _offline_until = time.time() + _RETRY_FAILED_AFTER
            for part in d.glob(f".{voice}*.part"):
                part.unlink(missing_ok=True)
            return None

    def voice_for(self, language: str, gender: str) -> tuple[str, Path] | None:
        wanted = wanted_voices(language, gender)
        for v in wanted:  # a preferred voice that is already here
            if self._installed(v):
                return v, self._installed(v)
        for v in wanted:  # otherwise fetch the first one that downloads
            path = self._download(v)
            if path:
                return v, path
        for v in self.installed_voices():  # otherwise any voice the user added for this language
            if v.startswith(language + "_"):
                return v, self._installed(v)
        return None

    def synth(self, text: str, language: str, gender: str, style: str, out: Path) -> Path:
        choice = self.voice_for(language, gender)
        if not choice:
            raise TTSError(f"no Piper voice available for {language}")
        voice, model = choice
        wpm, _ = STYLES.get(style, STYLES["neutral"])
        length_scale = round(160 / wpm, 2)
        p = subprocess.run(
            [sys.executable, "-m", "piper", "-m", str(model), "-f", str(out),
             "--length-scale", str(length_scale), "--sentence-silence", "0.3"],
            input=re.sub(r"\s+", " ", text).strip() + "\n",
            text=True,
            capture_output=True,
            timeout=900,
        )
        if p.returncode != 0 or not out.exists() or out.stat().st_size < 1000:
            raise TTSError(p.stderr[-500:] or "piper produced no audio")
        self.last_voice = voice
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
                path = eng.synth(text, language, gender, style, out)
                voice = getattr(eng, "last_voice", None)
                return path, f"{eng.name} ({voice})" if voice else eng.name
            except Exception as e:  # try the next engine
                log.warning("TTS engine %s failed, trying the next one: %s", eng.name, e)
                errors.append(f"{eng.name}: {e}")
    raise TTSError("No local TTS engine could speak this language. " + "; ".join(errors))


def preload(languages: tuple[str, ...] = ("en",)) -> None:
    """Fetch the default voices ahead of the first render (a no-op when they are present)."""
    piper = ENGINES[0]
    if not isinstance(piper, PiperTTS) or not piper.available() or not settings.piper_auto_download:
        return
    for lang in languages:
        for gender in ("female", "male"):
            try:
                piper.voice_for(lang, gender)
            except Exception as e:  # never let a download problem stop the worker
                log.warning("voice preload failed for %s/%s: %s", lang, gender, e)


def status() -> list[dict]:
    out = []
    for e in ENGINES:
        ok = e.available()
        row = {"name": e.name, "label": e.label, "available": ok,
               "languages": [l for l in LANGUAGES if ok and e.supports(l)]}
        if isinstance(e, PiperTTS):
            row["installed_voices"] = e.installed_voices()
            row["voices"] = [
                {"language": lang, "gender": g, "voice": (wanted_voices(lang, g) or [""])[0],
                 "licence": VOICE_INFO.get((wanted_voices(lang, g) or [""])[0], {}).get("licence", "see the voice's MODEL_CARD")}
                for lang in LANGUAGES for g in ("female", "male") if wanted_voices(lang, g)
            ]
            row["note"] = (
                "Voices download once on first use (60-120 MB each)." if settings.piper_auto_download
                else "Automatic voice download is off; add .onnx voices to the voices folder."
            )
        out.append(row)
    return out
