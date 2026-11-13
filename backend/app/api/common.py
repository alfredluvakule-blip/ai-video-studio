from __future__ import annotations

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Asset, Project, RenderLog, Scene, User, now


def expected_seconds(s: Scene) -> float:
    """Planned length, allowing for narration that runs longer than the set duration."""
    if s.status == "done" and s.clip_seconds:
        return s.clip_seconds
    words = len(s.voiceover.split()) if not s.voice_asset_id else 0
    return max(s.duration, words / 2.5 + 0.8 if words else 0)


def own_project(db: Session, user: User, project_id: str) -> Project:
    p = db.get(Project, project_id)
    if not p or p.user_id != user.id:
        raise HTTPException(404, "Project not found")
    return p


def own_scene(db: Session, user: User, scene_id: str) -> tuple[Scene, Project]:
    s = db.get(Scene, scene_id)
    if not s:
        raise HTTPException(404, "Scene not found")
    return s, own_project(db, user, s.project_id)


def own_asset(db: Session, user: User, asset_id: str | None) -> Asset | None:
    if not asset_id:
        return None
    a = db.get(Asset, asset_id)
    if not a or a.user_id != user.id:
        raise HTTPException(404, "Media not found")
    return a


def storage_used_bytes(db: Session, user: User) -> int:
    uploads = db.query(func.coalesce(func.sum(Asset.size_bytes), 0)).filter(Asset.user_id == user.id).scalar() or 0
    generated = 0
    for p in db.query(Project).filter(Project.user_id == user.id):
        d = settings.storage_dir / "projects" / p.id
        if d.exists():
            generated += sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
    return int(uploads) + generated


def rendered_last_24h(db: Session, user: User) -> float:
    since = now() - timedelta(hours=24)
    return float(
        db.query(func.coalesce(func.sum(RenderLog.output_seconds), 0))
        .filter(RenderLog.user_id == user.id, RenderLog.kind == "scene", RenderLog.created_at >= since)
        .scalar()
        or 0
    )


def render_speed_ratio(db: Session) -> float | None:
    """Measured wall-clock seconds per output second on this server (last 200 scenes)."""
    rows = db.query(RenderLog.output_seconds, RenderLog.wall_seconds).filter(RenderLog.kind == "scene").order_by(RenderLog.id.desc()).limit(200).all()
    out = sum(r[0] for r in rows)
    return (sum(r[1] for r in rows) / out) if out > 0 else None


def scene_dict(s: Scene) -> dict:
    return {
        "id": s.id, "project_id": s.project_id, "position": s.position, "duration": s.duration, "title": s.title,
        "visual_description": s.visual_description, "camera": s.camera, "character": s.character,
        "dialogue": s.dialogue, "voiceover": s.voiceover, "sound_effects": s.sound_effects, "prompt": s.prompt,
        "image_asset_id": s.image_asset_id, "voice_asset_id": s.voice_asset_id, "transition": s.transition,
        "speed": s.speed, "approved": s.approved, "status": s.status, "attempts": s.attempts,
        "clip_seconds": s.clip_seconds, "render_seconds": s.render_seconds, "provider_used": s.provider_used,
        "error": s.error, "has_clip": bool(s.clip_path and s.status == "done"), "has_image": bool(s.image_path),
    }


def progress(p: Project) -> dict:
    counts: dict[str, int] = {}
    for s in p.scenes:
        counts[s.status] = counts.get(s.status, 0) + 1
    total = len(p.scenes)
    return {
        "total": total,
        "done": counts.get("done", 0),
        "rendering": counts.get("rendering", 0),
        "queued": counts.get("queued", 0),
        "failed": counts.get("failed", 0),
        "draft": counts.get("draft", 0),
        "planned_seconds": round(sum(expected_seconds(s) for s in p.scenes), 1),
        "rendered_seconds": round(sum(s.clip_seconds for s in p.scenes if s.status == "done"), 1),
    }


def project_dict(p: Project, with_scenes: bool = False, ratio: float | None = None) -> dict:
    prog = progress(p)
    remaining = sum(expected_seconds(s) for s in p.scenes if s.status in ("queued", "rendering", "draft", "failed"))
    d = {
        "id": p.id, "title": p.title, "mode": p.mode, "prompt": p.prompt, "script": p.script, "style": p.style,
        "aspect": p.aspect, "resolution": p.resolution, "fps": p.fps, "target_seconds": p.target_seconds,
        "scene_seconds": p.scene_seconds, "language": p.language, "voice": p.voice,
        "narration_style": p.narration_style, "music": p.music, "burn_subtitles": p.burn_subtitles,
        "compression": p.compression, "visual_provider": p.visual_provider, "status": p.status,
        "error": p.error, "notes": p.notes or [], "output_seconds": p.output_seconds,
        "has_video": bool(p.output_path), "created_at": p.created_at.isoformat(), "updated_at": p.updated_at.isoformat(),
        "progress": prog,
        "estimate": {
            "remaining_output_seconds": round(remaining, 1),
            "measured_ratio": round(ratio, 3) if ratio else None,
            "estimated_wall_seconds": round(remaining * (ratio or 0.8), 0),
            "basis": "measured on this server" if ratio else "default guess until the first scene renders",
        },
    }
    if with_scenes:
        d["scenes"] = [scene_dict(s) for s in p.scenes]
    return d
