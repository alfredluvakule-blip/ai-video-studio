"""Thin, logged wrappers around the ffmpeg / ffprobe binaries."""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from ..config import settings

log = logging.getLogger(__name__)

RES = {  # (short side) -> landscape width, height
    480: (854, 480),
    720: (1280, 720),
    1080: (1920, 1080),
}

CRF = {"high": 18, "balanced": 23, "small": 28}


class FFmpegError(RuntimeError):
    pass


def dimensions(resolution: int, aspect: str) -> tuple[int, int]:
    w, h = RES.get(resolution, RES[720])
    if aspect == "9:16":
        return h, w
    if aspect == "1:1":
        return h, h
    return w, h


def run(args: list[str], timeout: int = 3600) -> None:
    cmd = [settings.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *args]
    if settings.render_threads:
        cmd[1:1] = ["-threads", str(settings.render_threads)]
    log.debug("ffmpeg %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise FFmpegError(proc.stderr.strip()[-2000:] or f"ffmpeg exited {proc.returncode}")


def probe_duration(path: str | Path) -> float:
    proc = subprocess.run(
        [settings.ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise FFmpegError(proc.stderr.strip() or "ffprobe failed")
    return float(json.loads(proc.stdout)["format"]["duration"])


def probe_streams(path: str | Path) -> list[dict]:
    proc = subprocess.run(
        [settings.ffprobe, "-v", "error", "-show_streams", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise FFmpegError(proc.stderr.strip() or "ffprobe failed")
    return json.loads(proc.stdout).get("streams", [])


def available() -> bool:
    try:
        subprocess.run([settings.ffmpeg, "-version"], capture_output=True, timeout=10, check=True)
        return True
    except Exception:
        return False
