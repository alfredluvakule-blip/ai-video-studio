from __future__ import annotations

import mimetypes
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from PIL import Image
from sqlalchemy.orm import Session

from .. import auth
from ..config import settings
from ..db import get_db
from ..models import Asset, Scene, User
from ..pipeline import ffmpeg as ff
from .common import own_asset, own_project, storage_used_bytes

router = APIRouter(prefix="/api/media")

KINDS = {
    "image": {".jpg", ".jpeg", ".png", ".webp", ".bmp"},
    "audio": {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"},
    "video": {".mp4", ".mov", ".webm", ".mkv"},
}


def _kind(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    for k, exts in KINDS.items():
        if ext in exts:
            return k
    raise HTTPException(415, f"Unsupported file type {ext or '(none)'}")


def _dict(a: Asset) -> dict:
    return {"id": a.id, "kind": a.kind, "filename": a.filename, "size_bytes": a.size_bytes,
            "project_id": a.project_id, "created_at": a.created_at.isoformat()}


@router.post("")
async def upload(
    file: UploadFile = File(...),
    project_id: str | None = Form(None),
    purpose: str | None = Form(None),  # "music" marks audio as a background track
    user: User = Depends(auth.current_user),
    db: Session = Depends(get_db),
):
    kind = _kind(file.filename or "")
    if project_id:
        own_project(db, user, project_id)
    if storage_used_bytes(db, user) > settings.storage_quota_mb * 1e6:
        raise HTTPException(507, "Storage quota is full. Delete old projects or media.")
    d = settings.storage_dir / "uploads" / user.id
    d.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", file.filename or "upload")[-80:]
    path = d / f"{uuid.uuid4().hex[:12]}_{safe}"
    limit = settings.max_upload_mb * 1024 * 1024
    size = 0
    with path.open("wb") as fh:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                fh.close()
                path.unlink(missing_ok=True)
                raise HTTPException(413, f"File is larger than {settings.max_upload_mb} MB")
            fh.write(chunk)
    # Verify the file really is what its extension says.
    try:
        if kind == "image":
            with Image.open(path) as im:
                im.verify()
        else:
            if not ff.probe_streams(path):
                raise ValueError("no media streams")
    except Exception:
        path.unlink(missing_ok=True)
        raise HTTPException(422, "The file could not be read as " + kind)
    a = Asset(user_id=user.id, project_id=project_id, kind="music" if (kind == "audio" and purpose == "music") else kind,
              filename=file.filename or safe, path=str(path), size_bytes=size)
    db.add(a)
    db.commit()
    return _dict(a)


@router.get("")
def list_media(kind: str | None = None, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    q = db.query(Asset).filter(Asset.user_id == user.id)
    if kind:
        q = q.filter(Asset.kind == kind)
    return [_dict(a) for a in q.order_by(Asset.created_at.desc()).limit(500)]


@router.delete("/{asset_id}")
def delete_media(asset_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    a = own_asset(db, user, asset_id)
    in_use = db.query(Scene).filter((Scene.image_asset_id == a.id) | (Scene.voice_asset_id == a.id)).count()
    if in_use:
        raise HTTPException(409, f"Used by {in_use} scene(s). Remove it from those scenes first.")
    Path(a.path).unlink(missing_ok=True)
    db.delete(a)
    db.commit()
    return {"ok": True}


@router.get("/{asset_id}/file")
def media_file(asset_id: str, token: str | None = Query(None), creds=Depends(auth.bearer), db: Session = Depends(get_db)):
    if creds:
        user = auth.user_from_token(db, creds.credentials)
    elif token:
        user = auth.user_from_token(db, token)
    else:
        raise HTTPException(401, "Not signed in")
    a = own_asset(db, user, asset_id)
    return FileResponse(a.path, media_type=mimetypes.guess_type(a.path)[0])
