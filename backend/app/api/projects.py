from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import auth, moderation, queue
from ..config import settings
from ..db import get_db
from ..models import Asset, Job, Project, Scene, User
from ..pipeline.render import project_dir
from ..schemas import ProjectIn, ProjectPatch, RenderIn, ReorderIn, SceneIn, ScenePatch, SplitIn
from .common import (
    expected_seconds, own_asset, own_project, own_scene, project_dict, render_speed_ratio, rendered_last_24h, scene_dict,
    storage_used_bytes,
)

router = APIRouter(prefix="/api")

# Changing any of these makes an already-rendered clip stale.
RENDER_FIELDS = {"duration", "visual_description", "camera", "voiceover", "prompt", "image_asset_id",
                 "voice_asset_id", "transition", "speed", "title"}
PROJECT_RENDER_FIELDS = {"style", "aspect", "resolution", "fps", "language", "voice", "narration_style",
                         "compression", "visual_provider"}


def _moderate(*texts: str) -> list[str]:
    try:
        return moderation.check(*texts)
    except moderation.ContentBlocked as e:
        raise HTTPException(422, str(e))


def _invalidate(scene: Scene) -> None:
    if scene.status in ("done", "failed"):
        scene.status = "draft"
    scene.clip_seconds = 0


def _reindex(p: Project) -> None:
    for i, s in enumerate(sorted(p.scenes, key=lambda s: s.position)):
        s.position = i


def _media_user(token: str | None, db: Session, creds=None) -> User:
    if creds:
        return auth.user_from_token(db, creds.credentials)
    if token:
        return auth.user_from_token(db, token)
    raise HTTPException(401, "Not signed in")


# ---------------------------------------------------------------- projects

@router.get("/projects")
def list_projects(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    ratio = render_speed_ratio(db)
    ps = db.query(Project).filter(Project.user_id == user.id).order_by(Project.updated_at.desc()).all()
    return [project_dict(p, ratio=ratio) for p in ps]


@router.post("/projects")
def create_project(body: ProjectIn, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    warnings = _moderate(body.title, body.prompt, body.script)
    if body.mode == "image" and not body.asset_ids:
        raise HTTPException(422, "Upload at least one photo for Image-to-Video")
    if body.mode != "image" and not (body.prompt.strip() or body.script.strip()):
        raise HTTPException(422, "Enter a prompt or a script")
    if body.music.startswith("asset:"):
        own_asset(db, user, body.music.split(":", 1)[1])
    data = body.model_dump(exclude={"asset_ids"})
    p = Project(user_id=user.id, **data, notes=warnings)
    db.add(p)
    db.flush()
    for aid in body.asset_ids:
        a = own_asset(db, user, aid)
        a.project_id = p.id
    db.commit()
    job = Job(user_id=user.id, project_id=p.id, kind="storyboard", message="Queued")
    db.add(job)
    p.status = "storyboarding"
    db.commit()
    queue.enqueue("storyboard", p.id, job.id)
    return project_dict(p, with_scenes=True)


@router.get("/projects/{project_id}")
def get_project(project_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    return project_dict(own_project(db, user, project_id), with_scenes=True, ratio=render_speed_ratio(db))


@router.patch("/projects/{project_id}")
def patch_project(project_id: str, body: ProjectPatch, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    p = own_project(db, user, project_id)
    data = body.model_dump(exclude_unset=True)
    _moderate(data.get("title", ""), data.get("prompt", ""), data.get("script", ""))
    if str(data.get("music", "")).startswith("asset:"):
        own_asset(db, user, data["music"].split(":", 1)[1])
    stale = any(k in PROJECT_RENDER_FIELDS and getattr(p, k) != v for k, v in data.items())
    for k, v in data.items():
        setattr(p, k, v)
    if stale:
        for s in p.scenes:
            _invalidate(s)
        if p.status == "done":
            p.status = "storyboard_ready"
    db.commit()
    return project_dict(p, with_scenes=True)


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    p = own_project(db, user, project_id)
    for a in db.query(Asset).filter(Asset.project_id == p.id):
        a.project_id = None  # uploads stay in the media library
    db.query(Job).filter(Job.project_id == p.id).delete()
    db.delete(p)
    db.commit()
    shutil.rmtree(settings.storage_dir / "projects" / project_id, ignore_errors=True)
    return {"ok": True}


@router.post("/projects/{project_id}/duplicate")
def duplicate_project(project_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    p = own_project(db, user, project_id)
    cols = {c.name for c in Project.__table__.columns} - {"id", "created_at", "updated_at", "output_path", "audio_path", "srt_path", "output_seconds", "error", "status"}
    q = Project(**{c: getattr(p, c) for c in cols})
    q.title = f"{p.title} (copy)"
    q.status = "storyboard_ready" if p.scenes else "draft"
    db.add(q)
    db.flush()
    scols = {c.name for c in Scene.__table__.columns} - {"id", "project_id", "clip_path", "image_path", "status", "clip_seconds", "render_seconds", "provider_used", "error", "attempts", "render_started_at", "updated_at"}
    for s in p.scenes:
        db.add(Scene(project_id=q.id, **{c: getattr(s, c) for c in scols}))
    db.commit()
    return project_dict(q, with_scenes=True)


@router.post("/projects/{project_id}/storyboard")
def regenerate_storyboard(project_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    p = own_project(db, user, project_id)
    if p.status in ("rendering", "assembling", "storyboarding"):
        raise HTTPException(409, "Wait for the current job to finish")
    job = Job(user_id=user.id, project_id=p.id, kind="storyboard", message="Queued")
    db.add(job)
    p.status = "storyboarding"
    db.commit()
    queue.enqueue("storyboard", p.id, job.id)
    return {"job_id": job.id}


@router.post("/projects/{project_id}/render")
def render(project_id: str, body: RenderIn, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    p = own_project(db, user, project_id)
    if not p.scenes:
        raise HTTPException(409, "Generate a storyboard first")
    if p.status in ("assembling", "storyboarding"):
        raise HTTPException(409, "Wait for the current job to finish")
    total = sum(expected_seconds(s) for s in p.scenes)
    if total > settings.max_project_seconds + 1:
        raise HTTPException(422, f"Project is {total / 60:.1f} min; the limit is {settings.max_project_seconds / 60:.0f} min")
    ids = set(body.scene_ids) if body.scene_ids else None
    targets = [s for s in p.scenes if (ids is None or s.id in ids) and (body.force or s.status in ("draft", "failed"))]
    if body.approve_all:
        for s in p.scenes:
            s.approved = True
    unapproved = [s.position + 1 for s in targets if not s.approved]
    if unapproved:
        raise HTTPException(422, f"Approve scenes {unapproved[:10]} first (or use 'Approve all & render')")
    planned = sum(expected_seconds(s) for s in targets)
    if settings.daily_render_seconds and not settings.self_hosted:
        used = rendered_last_24h(db, user)
        if used + planned > settings.daily_render_seconds:
            left = max(0, settings.daily_render_seconds - used)
            raise HTTPException(429, f"Free daily render limit: {left / 60:.1f} min left today on this server. "
                                     "Render a smaller batch, try tomorrow, or self-host for no limit.")
    if storage_used_bytes(db, user) > settings.storage_quota_mb * 1e6:
        raise HTTPException(507, "Storage quota is full. Delete old projects or media.")

    job = Job(user_id=user.id, project_id=p.id, kind="render", message=f"0/{len(p.scenes)} scenes rendered")
    db.add(job)
    for s in targets:
        s.status, s.error, s.render_started_at = "queued", None, None
    p.status, p.error = "rendering", None
    p.output_path = p.audio_path = p.srt_path = None
    db.commit()
    if targets:
        for s in targets:
            queue.enqueue("render_scene", s.id, job.id)
    else:  # everything already rendered: just assemble
        from ..tasks import _check_project

        _check_project(p.id, job.id)
    return {"job_id": job.id, "queued_scenes": len(targets)}


@router.post("/projects/{project_id}/resume")
def resume(project_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    """Continue an interrupted or partially failed render: re-queues everything not finished."""
    p = own_project(db, user, project_id)
    if p.status == "assembling":
        queue.enqueue("assemble", p.id, None)
        return {"queued_scenes": 0, "assembling": True}
    return render(project_id, RenderIn(approve_all=False), user, db)


@router.post("/projects/{project_id}/approve-all")
def approve_all(project_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    p = own_project(db, user, project_id)
    for s in p.scenes:
        s.approved = True
    db.commit()
    return project_dict(p, with_scenes=True)


@router.get("/projects/{project_id}/download/{kind}")
def download(project_id: str, kind: str, token: str | None = Query(None), creds=Depends(auth.bearer), db: Session = Depends(get_db), inline: bool = False):
    user = _media_user(token, db, creds)
    p = own_project(db, user, project_id)
    path = {"video": p.output_path, "audio": p.audio_path, "srt": p.srt_path}.get(kind)
    if not path or not Path(path).exists():
        raise HTTPException(404, "Not rendered yet")
    media = {"video": "video/mp4", "audio": "audio/mp4", "srt": "application/x-subrip"}[kind]
    return FileResponse(path, media_type=media, filename=None if inline else Path(path).name)


# ---------------------------------------------------------------- scenes

@router.post("/projects/{project_id}/scenes")
def add_scene(project_id: str, body: SceneIn, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    p = own_project(db, user, project_id)
    _moderate(body.visual_description, body.voiceover, body.prompt)
    own_asset(db, user, body.image_asset_id)
    own_asset(db, user, body.voice_asset_id)
    pos = body.position if body.position is not None else len(p.scenes)
    for s in p.scenes:
        if s.position >= pos:
            s.position += 1
    s = Scene(project_id=p.id, **body.model_dump(exclude={"position"}), position=pos)
    s.prompt = s.prompt or s.visual_description
    db.add(s)
    if p.status in ("draft", "done"):
        p.status = "storyboard_ready"
    db.commit()
    return scene_dict(s)


@router.patch("/scenes/{scene_id}")
def patch_scene(scene_id: str, body: ScenePatch, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    s, p = own_scene(db, user, scene_id)
    if s.status in ("queued", "rendering"):
        raise HTTPException(409, "This scene is rendering; edit it when it finishes")
    data = body.model_dump(exclude_unset=True)
    _moderate(data.get("visual_description", ""), data.get("voiceover", ""), data.get("prompt", ""), data.get("dialogue", ""))
    own_asset(db, user, data.get("image_asset_id"))
    own_asset(db, user, data.get("voice_asset_id"))
    stale = any(k in RENDER_FIELDS and getattr(s, k) != v for k, v in data.items())
    for k, v in data.items():
        setattr(s, k, v)
    if stale:
        _invalidate(s)
        if p.status == "done":
            p.status = "storyboard_ready"
    db.commit()
    return scene_dict(s)


@router.delete("/scenes/{scene_id}")
def delete_scene(scene_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    s, p = own_scene(db, user, scene_id)
    if s.status in ("queued", "rendering"):
        raise HTTPException(409, "This scene is rendering")
    p.scenes.remove(s)
    db.delete(s)
    _reindex(p)
    if p.status == "done":
        p.status = "storyboard_ready"
    db.commit()
    shutil.rmtree(project_dir(p.id) / "scenes" / scene_id, ignore_errors=True)
    return {"ok": True}


@router.post("/projects/{project_id}/reorder")
def reorder(project_id: str, body: ReorderIn, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    p = own_project(db, user, project_id)
    by_id = {s.id: s for s in p.scenes}
    if set(body.scene_ids) != set(by_id):
        raise HTTPException(422, "scene_ids must list every scene exactly once")
    for i, sid in enumerate(body.scene_ids):
        by_id[sid].position = i
    if p.status == "done":
        p.status = "storyboard_ready"  # reordering only needs a re-stitch, clips stay valid
    db.commit()
    db.refresh(p)
    return project_dict(p, with_scenes=True)


@router.post("/scenes/{scene_id}/split")
def split_scene(scene_id: str, body: SplitIn, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    s, p = own_scene(db, user, scene_id)
    words = s.voiceover.split()
    frac = (body.at_seconds / s.duration) if body.at_seconds else 0.5
    frac = min(0.9, max(0.1, frac))
    cut = max(1, int(len(words) * frac)) if len(words) > 1 else 0
    for o in p.scenes:
        if o.position > s.position:
            o.position += 1
    new = Scene(
        project_id=p.id, position=s.position + 1, duration=round(s.duration * (1 - frac), 2), title=f"{s.title} (2)",
        visual_description=s.visual_description, camera=s.camera, character=s.character, prompt=s.prompt,
        voiceover=" ".join(words[cut:]), image_asset_id=s.image_asset_id, transition=s.transition, speed=s.speed,
        approved=s.approved, sound_effects=s.sound_effects,
    )
    s.voiceover = " ".join(words[:cut]) if cut else s.voiceover
    s.duration = round(s.duration * frac, 2)
    _invalidate(s)
    db.add(new)
    if p.status == "done":
        p.status = "storyboard_ready"
    db.commit()
    db.refresh(p)
    return project_dict(p, with_scenes=True)


@router.post("/scenes/{scene_id}/merge-next")
def merge_next(scene_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    s, p = own_scene(db, user, scene_id)
    nxt = next((o for o in p.scenes if o.position == s.position + 1), None)
    if not nxt:
        raise HTTPException(422, "This is the last scene")
    if {s.status, nxt.status} & {"queued", "rendering"}:
        raise HTTPException(409, "Wait for these scenes to finish rendering")
    s.duration = min(120, s.duration + nxt.duration)
    s.voiceover = f"{s.voiceover} {nxt.voiceover}".strip()
    s.dialogue = f"{s.dialogue} {nxt.dialogue}".strip()
    _invalidate(s)
    p.scenes.remove(nxt)
    db.delete(nxt)
    _reindex(p)
    if p.status == "done":
        p.status = "storyboard_ready"
    db.commit()
    db.refresh(p)
    return project_dict(p, with_scenes=True)


@router.post("/scenes/{scene_id}/regenerate")
def regenerate_scene(scene_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    s, p = own_scene(db, user, scene_id)
    s.approved = True
    db.commit()
    return render(p.id, RenderIn(scene_ids=[s.id], force=True), user, db)


@router.get("/scenes/{scene_id}/{kind}")
def scene_media(scene_id: str, kind: str, token: str | None = Query(None), creds=Depends(auth.bearer), db: Session = Depends(get_db)):
    user = _media_user(token, db, creds)
    s, _ = own_scene(db, user, scene_id)
    path = {"clip": s.clip_path, "image": s.image_path}.get(kind)
    if not path or not Path(path).exists():
        raise HTTPException(404, "Not available yet")
    return FileResponse(path, media_type="video/mp4" if kind == "clip" else None)
