"""Original background music, synthesised locally (no licensing issues).

Generates a seamless 32-second loop per mood: a soft chord pad, plus a gentle
pulse for "upbeat". Loops are cached in STORAGE_DIR/music.
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from ..config import settings

SR = 44100
PROGRESSIONS = {
    # chords as MIDI notes, 8 seconds each
    "ambient": [[57, 60, 64, 69], [53, 57, 60, 65], [48, 52, 55, 60], [55, 59, 62, 67]],
    "calm": [[48, 55, 60, 64], [45, 52, 57, 60], [41, 48, 53, 57], [43, 50, 55, 59]],
    "upbeat": [[48, 52, 55, 60], [55, 59, 62, 67], [57, 60, 64, 69], [53, 57, 60, 65]],
    "documentary": [[50, 57, 62, 65], [46, 53, 58, 62], [48, 55, 60, 64], [45, 52, 57, 61]],
}
MOODS = list(PROGRESSIONS)


def _hz(m: int) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def _render(mood: str) -> np.ndarray:
    chords = PROGRESSIONS[mood]
    seg = 8 * SR
    t = np.arange(seg) / SR
    out = []
    for chord in chords:
        x = np.zeros(seg)
        for i, note in enumerate(chord):
            f = _hz(note)
            x += np.sin(2 * np.pi * f * t + i) * (0.6 if i else 0.9)
            x += 0.25 * np.sin(2 * np.pi * f * 2.003 * t)  # slight chorus
        env = np.minimum(1, np.minimum(t / 1.5, (8 - t) / 1.5))  # crossfade-friendly envelope
        x *= env * (0.85 + 0.15 * np.sin(2 * np.pi * 0.25 * t))
        if mood == "upbeat":
            beat = (np.sin(2 * np.pi * 2 * t) > 0.6).astype(float)  # 120 bpm pulse
            x += 0.5 * beat * np.sin(2 * np.pi * _hz(chord[0] - 12) * t)
        out.append(x)
    y = np.concatenate(out)
    # overlap-free loop: chords already fade in/out; normalise softly
    y = y / (np.max(np.abs(y)) + 1e-9) * 0.6
    stereo = np.stack([y, np.roll(y, int(0.012 * SR))], axis=1)
    return (stereo * 32767).astype(np.int16)


def loop_path(mood: str) -> Path:
    mood = mood if mood in PROGRESSIONS else "ambient"
    p = settings.storage_dir / "music" / f"{mood}.wav"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        data = _render(mood)
        tmp = p.with_suffix(".tmp")
        with wave.open(str(tmp), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(data.tobytes())
        tmp.rename(p)
    return p
