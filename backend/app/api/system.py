from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from .. import auth, queue
from ..config import settings
from ..db import get_db
from ..models import Job, Project, User
from ..pipeline import ffmpeg as ff
from ..pipeline import music
from ..providers import stt, tts
from ..providers.llm import STYLE_HINTS, WRITERS, pick_writer
from ..providers.visual import PROVIDERS, pick_image_provider
from ..schemas import Credentials
from .common import project_dict, render_speed_ratio, rendered_last_24h, storage_used_bytes

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------- auth

@router.post("/auth/register")
def register(body: Credentials, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(409, "An account with this email already exists")
    user = User(email=body.email, password_hash=auth.hash_password(body.password))
    db.add(user)
    db.commit()
    return {"token": auth.issue_token(db, user), "user": {"id": user.id, "email": user.email}}


@router.post("/auth/login")
def login(body: Credentials, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not auth.verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Wrong email or password")
    return {"token": auth.issue_token(db, user), "user": {"id": user.id, "email": user.email}}


@router.post("/auth/logout")
def logout(creds: HTTPAuthorizationCredentials | None = Depends(auth.bearer), db: Session = Depends(get_db)):
    if creds:
        auth.revoke_token(db, creds.credentials)
    return {"ok": True}


@router.get("/auth/me")
def me(user: User = Depends(auth.current_user)):
    return {"id": user.id, "email": user.email}


# ---------------------------------------------------------------- metadata

@router.get("/meta")
def meta():
    return {
        "styles": list(STYLE_HINTS),
        "aspects": ["16:9", "9:16", "1:1"],
        "resolutions": [480, 720, 1080],
        "fps": [24, 25, 30],
        "languages": tts.LANGUAGES,
        "voices": ["female", "male"],
        "narration_styles": list(tts.STYLES),
        "music": ["none", *music.MOODS],
        "cameras": ["zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "static"],
        "transitions": ["fade", "cut"],
        "visual_providers": visual_choices(),
        "limits": limits(),
    }


def visual_choices() -> list[dict]:
    """Picture sources a project can choose from on this server."""
    auto = pick_image_provider()
    out = [{"name": "auto", "label": f"Automatic: {auto.short}", "note": auto.note, "is_ai": auto.is_ai}]
    out += [{"name": v.name, "label": v.short, "note": v.note, "is_ai": v.is_ai} for v in PROVIDERS.values() if v.available()]
    return out


def limits() -> dict:
    return {
        "max_project_minutes": settings.max_project_seconds / 60,
        "storage_quota_mb": settings.storage_quota_mb,
        "daily_render_minutes": (settings.daily_render_seconds / 60) if settings.daily_render_seconds and not settings.self_hosted else None,
        "max_upload_mb": settings.max_upload_mb,
        "self_hosted": settings.self_hosted,
        "paid_services": "This server never charges you and uses no paid service. Free online services it can use (Pollinations pictures, and Gemini or Hugging Face if you add your own key) are governed by that provider's own free-tier limits.",
    }


@router.get("/providers")
def providers():
    writer = pick_writer()
    image = pick_image_provider()
    comfy = PROVIDERS["comfyui"]
    return {
        "writers": [{"name": w.name, "label": w.label, "available": w.available(), "active": w.name == writer.name} for w in WRITERS.values()],
        "visuals": [
            {"name": v.name, "label": v.label, "available": v.available(), "is_ai": v.is_ai, "active": v.name == image.name, "note": v.note}
            for v in PROVIDERS.values()
        ],
        "video_model": {
            "name": "svd",
            "label": "Stable Video Diffusion via ComfyUI",
            "available": comfy.video_available(),
            "note": "Needs a GPU running ComfyUI with COMFYUI_URL and COMFYUI_VIDEO_WORKFLOW set. Without it, each scene is a still picture animated with camera motion (Ken Burns), not a generated video clip.",
        },
        "tts": tts.status(),
        "whisper": {"available": stt.available(), "model": settings.whisper_model},
        "ffmpeg": ff.available(),
        "queue": queue.health(),
        "planned": [
            "Optional paid AI video clips (text-to-video models), with the cost shown before anything renders",
            "AI sound-effect generation (AudioLDM / Stable Audio Open via ComfyUI)",
            "Multi-track overlays (image/text overlays on extra video tracks)",
            "Supabase Storage backend for media",
            "Model-based content moderation",
            "Mobile app (the web app is responsive in the meantime)",
            "Voice cloning from uploaded samples",
        ],
    }


@router.get("/usage")
def usage(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    used = storage_used_bytes(db, user)
    projects = db.query(Project).filter(Project.user_id == user.id).all()
    ratio = render_speed_ratio(db)
    return {
        "limits": limits(),
        "storage_used_mb": round(used / 1e6, 1),
        "storage_quota_mb": settings.storage_quota_mb,
        "rendered_last_24h_minutes": round(rendered_last_24h(db, user) / 60, 2),
        "projects": len(projects),
        "videos_completed": sum(1 for p in projects if p.output_path),
        "minutes_exported": round(sum(p.output_seconds for p in projects) / 60, 1),
        "render_speed_ratio": round(ratio, 3) if ratio else None,
    }


@router.get("/jobs")
def jobs(active: bool = False, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    q = db.query(Job).filter(Job.user_id == user.id)
    if active:
        q = q.filter(Job.status.in_(["queued", "running"]))
    out = []
    ratio = render_speed_ratio(db)
    for j in q.order_by(Job.created_at.desc()).limit(30):
        p = db.get(Project, j.project_id)
        out.append({
            "id": j.id, "kind": j.kind, "status": j.status, "message": j.message, "error": j.error,
            "created_at": j.created_at.isoformat(), "project": project_dict(p, ratio=ratio) if p else None,
        })
    return out
