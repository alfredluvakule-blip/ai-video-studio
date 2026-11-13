from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _id() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuthToken(Base):
    __tablename__ = "auth_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    mode: Mapped[str] = mapped_column(String(20), default="text")  # text|image|script
    prompt: Mapped[str] = mapped_column(Text, default="")
    script: Mapped[str] = mapped_column(Text, default="")
    style: Mapped[str] = mapped_column(String(30), default="cinematic")
    aspect: Mapped[str] = mapped_column(String(10), default="16:9")
    resolution: Mapped[int] = mapped_column(Integer, default=720)
    fps: Mapped[int] = mapped_column(Integer, default=25)
    target_seconds: Mapped[int] = mapped_column(Integer, default=60)
    scene_seconds: Mapped[float] = mapped_column(Float, default=10.0)
    language: Mapped[str] = mapped_column(String(10), default="en")
    voice: Mapped[str] = mapped_column(String(40), default="female")
    narration_style: Mapped[str] = mapped_column(String(30), default="neutral")
    music: Mapped[str] = mapped_column(String(30), default="ambient")  # none|ambient|upbeat|calm|asset:<id>
    burn_subtitles: Mapped[bool] = mapped_column(Boolean, default=False)
    compression: Mapped[str] = mapped_column(String(10), default="balanced")  # high|balanced|small
    visual_provider: Mapped[str] = mapped_column(String(30), default="auto")
    status: Mapped[str] = mapped_column(String(20), default="draft")
    # draft|storyboarding|storyboard_ready|rendering|assembling|done|failed
    output_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    audio_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    srt_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    output_seconds: Mapped[float] = mapped_column(Float, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    scenes: Mapped[list["Scene"]] = relationship(
        back_populates="project", order_by="Scene.position", cascade="all, delete-orphan"
    )


class Scene(Base):
    __tablename__ = "scenes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    duration: Mapped[float] = mapped_column(Float, default=10.0)
    title: Mapped[str] = mapped_column(String(200), default="")
    visual_description: Mapped[str] = mapped_column(Text, default="")
    camera: Mapped[str] = mapped_column(String(30), default="zoom_in")
    character: Mapped[str] = mapped_column(Text, default="")
    dialogue: Mapped[str] = mapped_column(Text, default="")
    voiceover: Mapped[str] = mapped_column(Text, default="")
    sound_effects: Mapped[str] = mapped_column(Text, default="")
    prompt: Mapped[str] = mapped_column(Text, default="")
    image_asset_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    voice_asset_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    transition: Mapped[str] = mapped_column(String(20), default="fade")  # cut|fade
    speed: Mapped[float] = mapped_column(Float, default=1.0)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    # draft|queued|rendering|done|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    clip_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    clip_seconds: Mapped[float] = mapped_column(Float, default=0)
    render_seconds: Mapped[float] = mapped_column(Float, default=0)
    provider_used: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    render_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)  # host of the worker rendering it
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    project: Mapped[Project] = relationship(back_populates="scenes")


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(20))  # image|audio|video|music
    filename: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(String(500))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # storyboard|render|assemble
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|done|failed
    message: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class RenderLog(Base):
    """One row per rendered output, used for daily usage limits and stats."""

    __tablename__ = "render_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    project_id: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(20))  # scene|export
    output_seconds: Mapped[float] = mapped_column(Float, default=0)
    wall_seconds: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


# ---------------------------------------------------------------- Luvakule AI Brain
# New tables only: existing projects, scenes and media are untouched, and
# init_db() (create_all) adds these on start-up without a separate migration step.

class BrainPlan(Base):
    """A Director Mode production plan: one idea turned into an editable plan
    (brief, characters, locations, chapters, scenes, prompts, checks, estimate)
    before anything is generated. Approving it creates a normal project."""

    __tablename__ = "brain_plans"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    idea: Mapped[str] = mapped_column(Text, default="")
    settings: Mapped[dict] = mapped_column(JSON, default=dict)  # length, language, style, format, references
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|planning|ready|failed|approved
    stage: Mapped[str] = mapped_column(String(200), default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class AgentRun(Base):
    """One real step an agent took. Written while the work happens, never invented."""

    __tablename__ = "agent_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[str] = mapped_column(String(32), index=True)
    agent: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|done|failed|skipped
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)  # LLM used, or "rules" for code-only steps
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryItem(Base):
    """Project memory: characters, locations, visual style and other facts that
    must stay the same from scene to scene. Locked items are copied word for word
    into every picture prompt that uses them."""

    __tablename__ = "memory_items"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # character|location|style|fact
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    locked: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
