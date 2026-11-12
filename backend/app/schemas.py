from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Style = Literal["realistic", "cinematic", "cartoon", "animation", "educational", "documentary", "storytelling"]
Aspect = Literal["16:9", "9:16", "1:1"]
Camera = Literal["zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "static"]


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=200)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("Enter a valid email address")
        return v


class ProjectIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    mode: Literal["text", "image", "script"] = "text"
    prompt: str = Field("", max_length=4000)
    script: str = Field("", max_length=400_000)
    style: Style = "cinematic"
    aspect: Aspect = "16:9"
    resolution: Literal[480, 720, 1080] = 720
    fps: Literal[24, 25, 30] = 25
    target_seconds: int = Field(60, ge=5, le=3600)
    scene_seconds: float = Field(10, ge=3, le=30)
    language: str = Field("en", max_length=10)
    voice: Literal["female", "male"] = "female"
    narration_style: str = "neutral"
    music: str = "ambient"
    burn_subtitles: bool = False
    compression: Literal["high", "balanced", "small"] = "balanced"
    visual_provider: Literal["auto", "titlecard", "pollinations", "huggingface", "comfyui"] = "auto"
    asset_ids: list[str] = []


class ProjectPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    prompt: str | None = Field(None, max_length=4000)
    script: str | None = Field(None, max_length=400_000)
    style: Style | None = None
    aspect: Aspect | None = None
    resolution: Literal[480, 720, 1080] | None = None
    fps: Literal[24, 25, 30] | None = None
    target_seconds: int | None = Field(None, ge=5, le=3600)
    scene_seconds: float | None = Field(None, ge=3, le=30)
    language: str | None = None
    voice: Literal["female", "male"] | None = None
    narration_style: str | None = None
    music: str | None = None
    burn_subtitles: bool | None = None
    compression: Literal["high", "balanced", "small"] | None = None
    visual_provider: Literal["auto", "titlecard", "pollinations", "huggingface", "comfyui"] | None = None


class SceneIn(BaseModel):
    title: str = ""
    duration: float = Field(10, ge=1, le=120)
    visual_description: str = ""
    camera: Camera = "zoom_in"
    character: str = ""
    dialogue: str = ""
    voiceover: str = ""
    sound_effects: str = ""
    prompt: str = ""
    image_asset_id: str | None = None
    voice_asset_id: str | None = None
    transition: Literal["cut", "fade"] = "fade"
    speed: float = Field(1.0, ge=0.25, le=4)
    position: int | None = None


class ScenePatch(BaseModel):
    title: str | None = None
    duration: float | None = Field(None, ge=1, le=120)
    visual_description: str | None = None
    camera: Camera | None = None
    character: str | None = None
    dialogue: str | None = None
    voiceover: str | None = None
    sound_effects: str | None = None
    prompt: str | None = None
    image_asset_id: str | None = None
    voice_asset_id: str | None = None
    transition: Literal["cut", "fade"] | None = None
    speed: float | None = Field(None, ge=0.25, le=4)
    approved: bool | None = None


class RenderIn(BaseModel):
    scene_ids: list[str] | None = None  # None = every scene that is not rendered yet
    approve_all: bool = False
    force: bool = False  # re-render scenes that are already done


class ReorderIn(BaseModel):
    scene_ids: list[str]


class SplitIn(BaseModel):
    at_seconds: float | None = None
