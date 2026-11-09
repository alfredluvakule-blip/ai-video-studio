"""Runtime configuration, read from environment variables.

Every limit here is shown to users in the dashboard so nothing is hidden.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./studio.db")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    # "celery" uses Redis + Celery workers; "inline" runs jobs in a thread pool
    # inside the API process (handy for local dev and tests).
    queue_backend: str = os.getenv("QUEUE_BACKEND", "celery")
    storage_dir: Path = Path(os.getenv("STORAGE_DIR", "./storage")).resolve()
    secret_key: str = os.getenv("SECRET_KEY", "dev-secret-change-me")
    cors_origins: list[str] = field(
        default_factory=lambda: os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    )

    # Optional Supabase auth: when set, Supabase access tokens (HS256) are accepted.
    supabase_jwt_secret: str | None = os.getenv("SUPABASE_JWT_SECRET") or None

    # ---- Free-usage limits (displayed to users) ----
    max_project_seconds: int = int(os.getenv("MAX_PROJECT_SECONDS", "3600"))  # 60 minutes
    storage_quota_mb: int = int(os.getenv("STORAGE_QUOTA_MB", "5120"))
    # Rendered output seconds per user per day on this (shared) server.
    # Set to 0 to disable the cap, e.g. on a self-hosted machine.
    daily_render_seconds: int = int(os.getenv("DAILY_RENDER_SECONDS", "3600"))
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "200"))
    self_hosted: bool = _bool("SELF_HOSTED", False)

    # ---- Providers ----
    llm_provider: str = os.getenv("LLM_PROVIDER", "auto")  # auto|ollama|huggingface|template
    ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2")
    hf_token: str | None = os.getenv("HF_TOKEN") or None
    hf_llm_model: str = os.getenv("HF_LLM_MODEL", "meta-llama/Llama-3.1-8B-Instruct")
    hf_image_model: str = os.getenv("HF_IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell")
    comfyui_url: str | None = os.getenv("COMFYUI_URL") or None
    comfyui_image_workflow: str | None = os.getenv("COMFYUI_IMAGE_WORKFLOW") or None
    comfyui_video_workflow: str | None = os.getenv("COMFYUI_VIDEO_WORKFLOW") or None
    piper_bin: str = os.getenv("PIPER_BIN", "piper")
    piper_voices_dir: Path = Path(os.getenv("PIPER_VOICES_DIR", "./voices")).resolve()
    whisper_model: str = os.getenv("WHISPER_MODEL", "base")

    ffmpeg: str = os.getenv("FFMPEG_BIN", "ffmpeg")
    ffprobe: str = os.getenv("FFPROBE_BIN", "ffprobe")
    render_threads: int = int(os.getenv("RENDER_THREADS", "0"))  # 0 = ffmpeg auto


settings = Settings()
settings.storage_dir.mkdir(parents=True, exist_ok=True)
