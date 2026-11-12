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


def _opt(name: str) -> str | None:
    """Optional setting. Empty values, and values that are really a stray inline
    comment ("KEY=   # note" in an env file), count as not set."""
    v = (os.getenv(name) or "").strip()
    return None if not v or v.startswith("#") else v


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
    supabase_jwt_secret: str | None = _opt("SUPABASE_JWT_SECRET")

    # ---- Free-usage limits (displayed to users) ----
    max_project_seconds: int = int(os.getenv("MAX_PROJECT_SECONDS", "3600"))  # 60 minutes
    storage_quota_mb: int = int(os.getenv("STORAGE_QUOTA_MB", "5120"))
    # Rendered output seconds per user per day on this (shared) server.
    # Set to 0 to disable the cap, e.g. on a self-hosted machine.
    daily_render_seconds: int = int(os.getenv("DAILY_RENDER_SECONDS", "3600"))
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "200"))
    self_hosted: bool = _bool("SELF_HOSTED", False)

    # ---- Providers ----
    llm_provider: str = os.getenv("LLM_PROVIDER", "auto")  # auto|ollama|gemini|huggingface|template
    ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2")
    # Free Google AI Studio key: Gemini writes storyboards (free tier, rate-limited).
    gemini_api_key: str | None = _opt("GEMINI_API_KEY")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    # Pollinations: free AI images with no account (about one image per 15 seconds).
    pollinations_enabled: bool = _bool("POLLINATIONS", True)
    pollinations_model: str = os.getenv("POLLINATIONS_MODEL", "flux")
    pollinations_interval: float = float(os.getenv("POLLINATIONS_INTERVAL", "16"))
    hf_token: str | None = _opt("HF_TOKEN")
    hf_llm_model: str = os.getenv("HF_LLM_MODEL", "meta-llama/Llama-3.1-8B-Instruct")
    hf_image_model: str = os.getenv("HF_IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell")
    comfyui_url: str | None = _opt("COMFYUI_URL")
    comfyui_image_workflow: str | None = _opt("COMFYUI_IMAGE_WORKFLOW")
    comfyui_video_workflow: str | None = _opt("COMFYUI_VIDEO_WORKFLOW")
    piper_auto_download: bool = _bool("PIPER_AUTO_DOWNLOAD", True)
    piper_voices_dir: Path = Path(os.getenv("PIPER_VOICES_DIR", "./voices")).resolve()
    whisper_model: str = os.getenv("WHISPER_MODEL", "base")

    ffmpeg: str = os.getenv("FFMPEG_BIN", "ffmpeg")
    ffprobe: str = os.getenv("FFPROBE_BIN", "ffprobe")
    render_threads: int = int(os.getenv("RENDER_THREADS", "0"))  # 0 = ffmpeg auto


settings = Settings()
settings.storage_dir.mkdir(parents=True, exist_ok=True)
