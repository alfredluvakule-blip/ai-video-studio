"""Background work. Each function is idempotent and keeps all state in the
database, so a crashed worker, a restart, or a user pressing "Resume" simply
picks up the scenes that are not finished yet."""
from __future__ import annotations

import logging
import socket
import time
import traceback
from datetime import timedelta

from sqlalchemy import update

from . import queue
from .db import session_scope
from .models import Asset, Job, Project, RenderLog, Scene, now
from .pipeline import render
from .providers.llm import StoryboardRequest, pick_writer

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
STALE_AFTER = timedelta(minutes=20)


def _job(db, job_id: str | None, **fields):
    if not job_id:
        return
    job = db.get(Job, job_id)
    if job:
        for k, v in fields.items():
            setattr(job, k, v)


def storyboard(project_id: str, job_id: str | None = None) -> None:
    with session_scope() as db:
        p = db.get(Project, project_id)
        if not p:
            return
        _job(db, job_id, status="running", message="Writing storyboard")
        p.status = "storyboarding"
        image_ids = [a.id for a in db.query(Asset).filter(Asset.project_id == p.id, Asset.kind.in_(["image", "video"])).order_by(Asset.created_at)]
        req = StoryboardRequest(
            mode=p.mode, prompt=p.prompt, script=p.script, style=p.style, target_seconds=p.target_seconds,
            scene_seconds=p.scene_seconds, language=p.language, narration_style=p.narration_style, image_count=len(image_ids),
        )
    writer = pick_writer()
    try:
        scenes, notes = writer.storyboard(req)
    except Exception as e:
        log.exception("storyboard failed")
        from .providers.llm import TemplateWriter

        scenes, notes = TemplateWriter().storyboard(req)
        notes.insert(0, f"{writer.label} failed ({e}); used the rule-based splitter instead.")
        writer = TemplateWriter()
    with session_scope() as db:
        p = db.get(Project, project_id)
        db.query(Scene).filter(Scene.project_id == p.id).delete()
        for i, s in enumerate(scenes):
            sc = Scene(project_id=p.id, position=i, **s)
            if i < len(image_ids):
                sc.image_asset_id = image_ids[i]
            db.add(sc)
        p.status = "storyboard_ready"
        total = sum(max(float(s["duration"]), len(str(s.get("voiceover", "")).split()) / 2.5 + 0.8) for s in scenes)
        from .config import settings

        if total > settings.max_project_seconds:
            notes.append(
                f"This storyboard is {total / 60:.1f} minutes, over the {settings.max_project_seconds / 60:.0f}-minute "
                "project limit. Delete or shorten scenes (or split it into two projects) before rendering."
            )
        p.notes = [f"Storyboard written by: {writer.label}", *notes]
        _job(db, job_id, status="done", message=f"{len(scenes)} scenes written by {writer.label}")


def render_scene(scene_id: str, job_id: str | None = None) -> None:
    with session_scope() as db:
        sc = db.get(Scene, scene_id)
        if not sc or sc.status == "done":
            return
        # claim the scene; a concurrent worker that already claimed it within STALE_AFTER wins
        if sc.status == "rendering" and sc.render_started_at and _aware(sc.render_started_at) > now() - STALE_AFTER:
            return
        sc.status, sc.render_started_at, sc.attempts, sc.error = "rendering", now(), sc.attempts + 1, None
        sc.claimed_by = socket.gethostname()
        _job(db, job_id, status="running")
        p = db.get(Project, sc.project_id)
        src = db.get(Asset, sc.image_asset_id) if sc.image_asset_id else None
        voice = db.get(Asset, sc.voice_asset_id) if sc.voice_asset_id else None
        db.expunge_all()
    t0 = time.time()
    try:
        res = render.render_scene(sc, p, src, voice)
    except Exception as e:
        log.exception("scene %s failed", scene_id)
        with session_scope() as db:
            s = db.get(Scene, scene_id)
            s.status = "failed"
            s.error = f"{type(e).__name__}: {e}"[-1500:]
            _job(db, job_id, message=f"Scene {s.position + 1} failed")
        _check_project(sc.project_id, job_id)
        return
    wall = time.time() - t0
    with session_scope() as db:
        s = db.get(Scene, scene_id)
        s.status, s.clip_path, s.clip_seconds = "done", str(res.clip), res.seconds
        s.render_seconds, s.image_path = wall, sc.image_path
        s.provider_used = res.provider + (f" + voice:{res.tts_engine}" if res.tts_engine else "")
        db.add(RenderLog(user_id=p.user_id, project_id=p.id, kind="scene", output_seconds=res.seconds, wall_seconds=wall))
    _check_project(sc.project_id, job_id)


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=now().tzinfo)


def _check_project(project_id: str, job_id: str | None) -> None:
    """When every scene is finished, hand over to assembly (exactly once)."""
    with session_scope() as db:
        scenes = db.query(Scene).filter(Scene.project_id == project_id).all()
        done = sum(s.status == "done" for s in scenes)
        failed = [s for s in scenes if s.status == "failed"]
        pending = [s for s in scenes if s.status in ("queued", "rendering")]
        _job(db, job_id, message=f"{done}/{len(scenes)} scenes rendered")
        if pending:
            return
        if failed:
            p = db.get(Project, project_id)
            p.status = "failed"
            p.error = f"{len(failed)} scene(s) failed. Fix or regenerate them, then press Resume."
            _job(db, job_id, status="failed", error=p.error)
            return
        if any(s.status != "done" for s in scenes):  # a batch finished; the rest are not rendered yet
            p = db.get(Project, project_id)
            if p.status == "rendering":
                p.status = "storyboard_ready"
            _job(db, job_id, status="done", message=f"Batch finished: {done}/{len(scenes)} scenes rendered")
            return
        claimed = db.execute(
            update(Project).where(Project.id == project_id, Project.status == "rendering").values(status="assembling")
        ).rowcount
    if claimed:
        queue.enqueue("assemble", project_id, job_id)


def assemble(project_id: str, job_id: str | None = None) -> None:
    with session_scope() as db:
        p = db.get(Project, project_id)
        if not p:
            return
        scenes = [s for s in p.scenes]
        if not scenes or any(s.status != "done" for s in scenes):
            p.status = "failed"
            p.error = "Not every scene is rendered yet."
            return
        _job(db, job_id, status="running", message="Stitching scenes, mixing music and subtitles")
        music_asset = db.get(Asset, p.music.split(":", 1)[1]) if p.music.startswith("asset:") else None
        voices = {s.id: db.get(Asset, s.voice_asset_id) for s in scenes if s.voice_asset_id}
        db.expunge_all()
    try:
        t0 = time.time()
        subs, t = [], 0.0
        for s in scenes:
            v = voices.get(s.id)
            narr = max(0.0, s.clip_seconds - render.NARRATION_LEAD - 0.5)
            if s.voiceover.strip() and not v:
                try:
                    narr = render.ff.probe_duration(render.scene_dir(s) / "narration.wav")
                except Exception:
                    pass
            subs += render.scene_subtitles(s, t, narr, v.path if v else None, p.language)
            t += s.clip_seconds
        out = render.assemble(p, scenes, subs, music_asset)
        wall = time.time() - t0
    except Exception as e:
        log.exception("assembly failed")
        with session_scope() as db:
            pp = db.get(Project, project_id)
            pp.status, pp.error = "failed", f"Assembly failed: {e}"[-1500:]
            _job(db, job_id, status="failed", error=pp.error)
        return
    with session_scope() as db:
        pp = db.get(Project, project_id)
        pp.status, pp.error = "done", None
        pp.notes = _with_voice_notes(pp.notes or [], scenes, pp.voice)
        pp.output_path, pp.audio_path, pp.srt_path = str(out["video"]), str(out["audio"]), str(out["srt"])
        pp.output_seconds = out["seconds"]
        db.add(RenderLog(user_id=pp.user_id, project_id=pp.id, kind="export", output_seconds=out["seconds"], wall_seconds=wall))
        _job(db, job_id, status="done", message=f"Video ready ({out['seconds'] / 60:.1f} min)")


def _with_voice_notes(notes: list[str], scenes, gender: str) -> list[str]:
    """Add credit lines and gender notes for the narrator voices a finished video used."""
    import re

    from .providers import tts

    out = [n for n in notes if not n.startswith("Narrator voice:")]
    voices = sorted({m.group(1) for s in scenes for m in [re.search(r"voice:piper \(([^)]+)\)", s.provider_used or "")] if m})
    for v in voices:
        info = tts.VOICE_INFO.get(v, {})
        line = f"Narrator voice: {v}"
        if info.get("gender") and info["gender"] != gender:
            line += f" ({info['gender']}; no {gender} natural voice is available for this language yet)"
        if info.get("credit"):
            line += f". {info['credit']}"
        out.append(line)
    if any("voice:espeak" in (s.provider_used or "") or "voice:flite" in (s.provider_used or "") for s in scenes) and voices:
        out.append("Narrator voice: some scenes used the basic eSpeak voice because the natural voice was not available.")
    elif any("voice:espeak" in (s.provider_used or "") for s in scenes):
        out.append("Narrator voice: the basic eSpeak voice was used because no natural voice was available. "
                   "Check Settings to see why.")
    return out


def recover(starting_up: bool = True) -> int:
    """Re-queue work interrupted by a crash or restart. Safe to call any time.

    Run one worker per host (container): when a worker starts, any scene still marked
    "rendering" by this host belonged to a previous, dead worker process.
    """
    n = 0
    host = socket.gethostname()
    with session_scope() as db:
        cutoff = now() - STALE_AFTER
        stuck = db.query(Scene).filter(Scene.status.in_(["queued", "rendering"])).all()
        ids = [
            s.id for s in stuck
            if s.status == "queued"
            or not s.render_started_at
            or _aware(s.render_started_at) < cutoff
            or (starting_up and s.claimed_by == host)
        ]
        for s in stuck:
            if s.id in ids and s.status == "rendering":
                s.status, s.render_started_at = "queued", None
        assembling = [p.id for p in db.query(Project).filter(Project.status == "assembling")]
    for sid in ids:
        queue.enqueue("render_scene", sid, None)
        n += 1
    for pid in assembling:
        queue.enqueue("assemble", pid, None)
        n += 1
    return n


TASKS = {"storyboard": storyboard, "render_scene": render_scene, "assemble": assemble}
