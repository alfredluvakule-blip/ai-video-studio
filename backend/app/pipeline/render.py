"""Scene rendering and final assembly.

Every scene is rendered to its own MP4 with identical codec parameters
(H.264 yuv420p + AAC 48 kHz stereo, same size and fps). That lets the final
assembly use FFmpeg's concat demuxer with stream copy, so a 60-minute,
360-scene project is stitched in seconds and a failed scene can be
re-rendered without touching the others.
"""
from __future__ import annotations

import logging
import re
import shutil
import time
import zlib
from dataclasses import dataclass
from pathlib import Path

from ..config import settings
from ..models import Asset, Project, Scene
from ..providers import stt, tts
from ..providers.visual import ComfyUIProvider, PROVIDERS, fallback_chain
from . import ffmpeg as ff
from . import music

log = logging.getLogger(__name__)

AUDIO_ARGS = ["-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]
NARRATION_LEAD = 0.3  # seconds of silence before narration starts
FADE = 0.4


def project_dir(project_id: str) -> Path:
    d = settings.storage_dir / "projects" / project_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def scene_dir(scene: Scene) -> Path:
    d = project_dir(scene.project_id) / "scenes" / scene.id
    d.mkdir(parents=True, exist_ok=True)
    return d


def video_args(project: Project) -> list[str]:
    return [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(ff.CRF.get(project.compression, 23)),
        "-pix_fmt", "yuv420p", "-r", str(project.fps), "-video_track_timescale", "90000",
    ]


@dataclass
class SceneResult:
    clip: Path
    seconds: float
    narration_seconds: float
    provider: str
    tts_engine: str | None


def _motion_filter(camera: str, frames: int, w: int, h: int, fps: int, speed: float) -> str:
    p = f"min(1,on/{max(1, frames - 1)}*{speed:.3f})"  # motion progress 0..1
    centre_x, centre_y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    z, x, y = "1", centre_x, centre_y
    if camera == "zoom_in":
        z = f"1+0.18*{p}"
    elif camera == "zoom_out":
        z = f"1.18-0.18*{p}"
    elif camera in ("pan_left", "pan_right", "pan_up", "pan_down"):
        z = "1.15"
        if camera == "pan_right":
            x = f"(iw-iw/zoom)*{p}"
        elif camera == "pan_left":
            x = f"(iw-iw/zoom)*(1-{p})"
        elif camera == "pan_down":
            y = f"(ih-ih/zoom)*{p}"
        else:
            y = f"(ih-ih/zoom)*(1-{p})"
    # Upscale 2x before zoompan to avoid the well-known zoompan jitter.
    return (
        f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
        f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={fps},setsar=1"
    )


def _fit_filter(w: int, h: int) -> str:
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"


def _narration(scene: Scene, project: Project, voice_asset: Asset | None, d: Path) -> tuple[Path | None, float, str | None]:
    if voice_asset:
        out = d / "narration.wav"
        ff.run(["-i", voice_asset.path, "-ar", "48000", "-ac", "2", str(out)])
        return out, ff.probe_duration(out), "upload"
    text = scene.voiceover.strip()
    if not text:
        return None, 0.0, None
    raw = d / "narration_raw.wav"
    _, engine = tts.synthesize(text, project.language, project.voice, project.narration_style, raw)
    out = d / "narration.wav"
    ff.run(["-i", str(raw), "-ar", "48000", "-ac", "2", str(out)])
    raw.unlink(missing_ok=True)
    return out, ff.probe_duration(out), engine


def render_scene(scene: Scene, project: Project, source_asset: Asset | None, voice_asset: Asset | None) -> SceneResult:
    w, h = ff.dimensions(project.resolution, project.aspect)
    fps = project.fps
    d = scene_dir(scene)

    narration, nsec, engine = _narration(scene, project, voice_asset, d)
    seconds = round(max(1.0, scene.duration, nsec + NARRATION_LEAD + 0.5 if narration else 0), 2)
    frames = int(round(seconds * fps))
    speed = max(0.25, min(4.0, scene.speed or 1.0))

    provider = ""
    visual_in: list[str]
    vf: str
    if source_asset and source_asset.kind == "video":
        provider = "upload:video"
        visual_in = ["-stream_loop", "-1", "-i", source_asset.path]
        vf = f"setpts=PTS/{speed},{_fit_filter(w, h)},fps={fps}"
    else:
        still = d / "still.png"
        if source_asset and source_asset.kind == "image":
            still = Path(source_asset.path)
            provider = "upload:image"
        else:
            # A new seed per render attempt, so "Regenerate" gives a different picture.
            seed = zlib.crc32(f"{scene.id}:{scene.attempts}".encode()) % 2**31 or 1
            failed: list[str] = []
            for prov in fallback_chain(project.visual_provider):
                try:
                    still = prov.image(scene.prompt or scene.visual_description, project.style, int(w * 1.25), int(h * 1.25),
                                       d / "still.png", caption=scene.title or scene.visual_description, seed=seed)
                except Exception as e:  # try the next source, and say so on the scene
                    log.warning("visual provider %s failed: %s", prov.name, e)
                    failed.append(prov.name)
                    continue
                provider = prov.name + (f" (fallback: {', '.join(failed)} failed)" if failed else "")
                break
            else:
                raise RuntimeError(f"no picture source worked ({', '.join(failed)})")
        scene.image_path = str(still)

        comfy: ComfyUIProvider = PROVIDERS["comfyui"]  # type: ignore[assignment]
        if project.visual_provider in ("auto", "comfyui") and comfy.video_available():
            try:
                clip = comfy.clip_from_image(still, seconds, fps, w, h, d / "svd.mp4")
                provider += "+svd"
                # SVD clips are a few seconds long: slow them gently, then loop.
                visual_in = ["-stream_loop", "-1", "-i", str(clip)]
                vf = f"setpts=PTS*1.5/{speed},{_fit_filter(w, h)},fps={fps}"
            except Exception as e:
                log.warning("SVD failed, using camera motion instead: %s", e)
                visual_in = ["-loop", "1", "-framerate", str(fps), "-i", str(still)]
                vf = _motion_filter(scene.camera, frames, w, h, fps, speed)
        else:
            visual_in = ["-loop", "1", "-framerate", str(fps), "-i", str(still)]
            vf = _motion_filter(scene.camera, frames, w, h, fps, speed)

    if scene.transition == "fade":
        vf += f",fade=t=in:st=0:d={FADE},fade=t=out:st={seconds - FADE:.3f}:d={FADE}"

    if narration:
        audio_in = ["-i", str(narration)]
        delay_ms = int(NARRATION_LEAD * 1000)
        af = f"[1:a]adelay={delay_ms}|{delay_ms},apad,atrim=0:{seconds},asetpts=N/SR/TB[a]"
    else:
        audio_in = ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        af = f"[1:a]atrim=0:{seconds},asetpts=N/SR/TB[a]"

    out = d / "clip.mp4"
    tmp = d / "clip.tmp.mp4"
    ff.run(
        [
            *visual_in,
            *audio_in,
            "-filter_complex", f"[0:v]{vf},trim=0:{seconds},setpts=PTS-STARTPTS,format=yuv420p[v];{af}",
            "-map", "[v]", "-map", "[a]",
            "-t", str(seconds),
            *video_args(project),
            *AUDIO_ARGS,
            "-movflags", "+faststart",
            str(tmp),
        ]
    )
    tmp.replace(out)
    return SceneResult(out, ff.probe_duration(out), nsec, provider, engine)


# ---------------------------------------------------------------- subtitles

def _ts(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def _chunks(text: str, max_words: int = 8) -> list[str]:
    words = re.sub(r"\s+", " ", text).strip().split(" ")
    out = [words[i : i + max_words] for i in range(0, len(words), max_words)]
    if len(out) > 1 and len(out[-1]) < 3:  # avoid one-word orphan lines
        out[-2] += out.pop()
    return [" ".join(c) for c in out if c]


def build_srt(entries: list[tuple[float, float, str]]) -> str:
    lines = []
    for i, (a, b, t) in enumerate(entries, 1):
        lines += [str(i), f"{_ts(a)} --> {_ts(b)}", t, ""]
    return "\n".join(lines)


def scene_subtitles(scene: Scene, start: float, narration_seconds: float, voice_path: str | None, language: str) -> list[tuple[float, float, str]]:
    """Timed subtitle lines for one scene, offset to its start in the final video."""
    if voice_path and stt.available():
        return [(start + a, start + b, t) for a, b, t in stt.transcribe(Path(voice_path), language)]
    text = scene.voiceover.strip()
    if not text or narration_seconds <= 0:
        return []
    parts = _chunks(text)
    total_words = sum(len(p.split()) for p in parts)
    t = start + NARRATION_LEAD
    out = []
    for p in parts:
        dur = narration_seconds * len(p.split()) / total_words
        out.append((t, t + dur, p))
        t += dur
    return out


# ---------------------------------------------------------------- assembly

def assemble(project: Project, scenes: list[Scene], subtitles: list[tuple[float, float, str]], music_asset: Asset | None) -> dict:
    d = project_dir(project.id)
    work = d / "work"
    work.mkdir(exist_ok=True)

    listing = work / "concat.txt"
    listing.write_text("".join(f"file '{Path(s.clip_path).as_posix()}'\n" for s in scenes))
    body = work / "body.mp4"
    ff.run(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(body)])
    total = ff.probe_duration(body)

    srt = d / "subtitles.srt"
    srt.write_text(build_srt(subtitles), encoding="utf-8")

    music_src: Path | None = None
    if music_asset:
        music_src = Path(music_asset.path)
    elif project.music in music.MOODS:
        music_src = music.loop_path(project.music)

    final_tmp = work / "final.tmp.mp4"
    args = ["-i", str(body)]
    if music_src:
        args += ["-stream_loop", "-1", "-i", str(music_src)]
        # Duck the music under narration with a sidechain compressor.
        fc = (
            "[1:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=0.22,"
            f"afade=t=in:d=2,afade=t=out:st={max(0, total - 3):.2f}:d=3,atrim=0:{total:.3f}[m];"
            "[0:a]asplit=2[n][key];"
            "[m][key]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=400[duck];"
            "[n][duck]amix=inputs=2:duration=first:normalize=0[a]"
        )
        vmap = "0:v"
        if project.burn_subtitles and subtitles:
            fc += f";[0:v]subtitles='{_escape(srt)}':force_style='FontSize=18,Outline=2'[v]"
            vmap = "[v]"
        args += ["-filter_complex", fc, "-map", vmap, "-map", "[a]"]
    else:
        if project.burn_subtitles and subtitles:
            args += ["-vf", f"subtitles='{_escape(srt)}':force_style='FontSize=18,Outline=2'"]
        args += ["-map", "0:v", "-map", "0:a"]
        args += ["-c:a", "copy"]
    if project.burn_subtitles and subtitles:
        args += video_args(project)
    else:
        args += ["-c:v", "copy"]
    if music_src:
        args += AUDIO_ARGS
    args += ["-t", f"{total:.3f}", "-movflags", "+faststart", str(final_tmp)]
    ff.run(args, timeout=6 * 3600)

    slug = re.sub(r"[^a-z0-9]+", "-", project.title.lower()).strip("-")[:50] or "video"
    final = d / f"{slug}.mp4"
    for old in d.glob("*.mp4"):
        old.unlink(missing_ok=True)
    final_tmp.replace(final)

    audio = d / f"{slug}.m4a"
    ff.run(["-i", str(final), "-vn", "-c:a", "copy", str(audio)])
    shutil.rmtree(work, ignore_errors=True)
    return {"video": final, "audio": audio, "srt": srt, "seconds": ff.probe_duration(final)}


def _escape(p: Path) -> str:
    return p.as_posix().replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def estimate_seconds(scene_seconds: float, ratio: float | None) -> float:
    """Wall-clock estimate from measured render speed on this server."""
    return scene_seconds * (ratio if ratio else 0.8)


def timed(fn, *a, **kw):
    t0 = time.time()
    r = fn(*a, **kw)
    return r, time.time() - t0
