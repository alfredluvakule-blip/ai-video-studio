"""Speech-to-text for subtitles of uploaded voice recordings (Whisper, local).

Uses `faster-whisper` if installed (pip install faster-whisper). Without it, uploaded
recordings still play in the video but get no automatic subtitles.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ..config import settings


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401

        return True
    except Exception:
        return False


@lru_cache(maxsize=1)
def _model():
    from faster_whisper import WhisperModel

    return WhisperModel(settings.whisper_model, device="auto", compute_type="int8")


def transcribe(path: Path, language: str | None = None) -> list[tuple[float, float, str]]:
    """Returns [(start, end, text), ...]."""
    segments, _ = _model().transcribe(str(path), language=language)
    return [(s.start, s.end, s.text.strip()) for s in segments if s.text.strip()]
