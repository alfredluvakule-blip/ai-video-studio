"""Luvakule AI Brain: Director Mode plans, agent activity and project memory."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from .. import auth, moderation, queue
from ..brain import agents, catalog, director, llm, prompts, timing
from ..config import settings
from ..db import get_db
from ..models import AgentRun, BrainPlan, MemoryItem, User
from ..providers import tts
from .common import own_asset, own_project, render_speed_ratio

router = APIRouter(prefix="/api")

Style = Literal["auto", "realistic", "cinematic", "cartoon", "animation", "educational", "documentary", "storytelling"]


class PlanIn(BaseModel):
    idea: str = Field(min_length=3, max_length=4000)
    target_seconds: int = Field(60, ge=10, le=3600)
    scene_seconds: float = Field(10, ge=3, le=30)
    language: str = Field("en", max_length=10)
    style: Style = "auto"
    aspect: Literal["16:9", "9:16", "1:1"] = "16:9"
    resolution: Literal[480, 720, 1080] = 720
    voice: Literal["female", "male"] = "female"
    main_character: str = Field("", max_length=600)
    reference_asset_ids: list[str] = Field(default_factory=list, max_length=10)


class BriefPatch(BaseModel):
    title: str | None = Field(None, max_length=120)
    logline: str | None = Field(None, max_length=400)
    audience: str | None = Field(None, max_length=200)
    goal: str | None = Field(None, max_length=400)
    style: Literal["realistic", "cinematic", "cartoon", "animation", "educational", "documentary", "storytelling"] | None = None
    visual_style: str | None = Field(None, max_length=300)
    tone: str | None = Field(None, max_length=120)
    camera_language: str | None = Field(None, max_length=300)
    narration_style: str | None = None
    music_mood: str | None = None


class CharacterIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    role: str = Field("", max_length=120)
    appearance: str = Field("", max_length=400)
    clothing: str = Field("", max_length=300)
    personality: str = Field("", max_length=200)
    voice: str = Field("", max_length=120)
    reference_asset_ids: list[str] = Field(default_factory=list, max_length=10)
    locked: bool = True


class LocationIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field("", max_length=400)
    lighting: str = Field("", max_length=200)
    locked: bool = True


class PlanScene(BaseModel):
    chapter_id: str
    duration: float = Field(ge=1, le=120)
    title: str = Field("", max_length=80)
    narration: str = Field("", max_length=3000)
    dialogue: str = Field("", max_length=1500)
    characters: list[str] = Field(default_factory=list, max_length=6)
    location: str = Field("", max_length=80)
    action: str = Field("", max_length=600)
    expression: str = Field("", max_length=200)
    shot: str = "medium"
    movement: str = "dolly_in"
    lighting: str = Field("", max_length=200)
    transition: Literal["cut", "fade"] = "fade"
    sound_effects: str = Field("", max_length=300)
    music_cue: str = Field("", max_length=200)
    image_prompt: str = Field("", max_length=1500)
    prompt_edited: bool = False


class PlanPatch(BaseModel):
    brief: BriefPatch | None = None
    characters: list[CharacterIn] | None = Field(None, max_length=12)
    locations: list[LocationIn] | None = Field(None, max_length=20)
    scenes: list[PlanScene] | None = Field(None, max_length=720)
    fit_to_length: bool = False


class MemoryIn(BaseModel):
    kind: Literal["character", "location", "style", "fact"] = "fact"
    name: str = Field(min_length=1, max_length=200)
    description: str = Field("", max_length=2000)
    locked: bool = True


class MemoryPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    appearance: str | None = Field(None, max_length=400)  # characters only
    clothing: str | None = Field(None, max_length=300)  # characters only
    locked: bool | None = None


def _own_plan(db: Session, user: User, plan_id: str) -> BrainPlan:
    bp = db.get(BrainPlan, plan_id)
    if not bp or bp.user_id != user.id:
        raise HTTPException(404, "Plan not found")
    return bp


def _plan_dict(db: Session, bp: BrainPlan, full: bool = True) -> dict:
    d = {
        "id": bp.id, "idea": bp.idea, "settings": bp.settings, "status": bp.status, "stage": bp.stage, "error": bp.error,
        "provider": bp.provider, "llm_calls": bp.llm_calls, "project_id": bp.project_id,
        "title": (bp.plan or {}).get("brief", {}).get("title") or bp.idea[:60],
        "scene_count": len((bp.plan or {}).get("scenes", [])),
        "created_at": bp.created_at.isoformat(), "updated_at": bp.updated_at.isoformat(),
    }
    if full:
        d["plan"] = bp.plan or {}
        d["activity"] = [
            {"id": r.id, "agent": r.agent, "action": r.action, "status": r.status, "provider": r.provider,
             "llm_calls": r.llm_calls, "detail": r.detail, "started_at": r.started_at.isoformat(),
             "finished_at": r.finished_at.isoformat() if r.finished_at else None}
            for r in db.query(AgentRun).filter(AgentRun.plan_id == bp.id).order_by(AgentRun.id)
        ]
    return d


def _moderate(*texts: str) -> None:
    try:
        moderation.check(*texts)
    except moderation.ContentBlocked as e:
        raise HTTPException(422, str(e))


# ---------------------------------------------------------------- status

@router.get("/brain/status")
def brain_status():
    return {
        "writer": llm.status(),
        "routes": catalog.routes(),
        "length_presets": timing.LENGTH_PRESETS,
        "max_seconds": settings.max_project_seconds,
        "languages": tts.LANGUAGES,
        "styles": ["auto", *agents.STYLES],
        "shots": list(prompts.SHOTS),
        "movements": list(prompts.MOVEMENTS),
        "narration_styles": agents.NARRATION_STYLES,
        "music": agents.MUSIC,
    }


# ---------------------------------------------------------------- Director Mode plans

@router.post("/director/plans")
def create_plan(body: PlanIn, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    _moderate(body.idea, body.main_character)
    if body.target_seconds > settings.max_project_seconds:
        raise HTTPException(422, f"The longest video is {settings.max_project_seconds // 60} minutes")
    for aid in body.reference_asset_ids:
        a = own_asset(db, user, aid)
        if a.kind != "image":
            raise HTTPException(422, "Reference files must be photos")
    if not llm.pick_llm():
        raise HTTPException(503, llm.NO_LLM_HELP)
    bp = BrainPlan(user_id=user.id, idea=body.idea.strip(), settings=body.model_dump(), plan={}, status="queued", stage="Waiting to start")
    db.add(bp)
    db.commit()
    queue.enqueue("director_plan", bp.id, False)
    return _plan_dict(db, bp)


@router.get("/director/plans")
def list_plans(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    rows = db.query(BrainPlan).filter(BrainPlan.user_id == user.id).order_by(BrainPlan.created_at.desc()).limit(100)
    return [_plan_dict(db, bp, full=False) for bp in rows]


@router.get("/director/plans/{plan_id}")
def get_plan(plan_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    return _plan_dict(db, _own_plan(db, user, plan_id))


@router.patch("/director/plans/{plan_id}")
def edit_plan(plan_id: str, body: PlanPatch, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    bp = _own_plan(db, user, plan_id)
    if bp.status != "ready":
        raise HTTPException(409, "This plan can be edited once it is ready (and before it is approved)")
    plan = dict(bp.plan)
    if body.brief:
        b = body.brief.model_dump(exclude_unset=True)
        if "narration_style" in b and b["narration_style"] not in agents.NARRATION_STYLES:
            raise HTTPException(422, "Unknown narration style")
        if "music_mood" in b and b["music_mood"] not in agents.MUSIC:
            raise HTTPException(422, "Unknown music mood")
        plan["brief"] = {**plan["brief"], **b}
    if body.characters is not None:
        for c in body.characters:
            for aid in c.reference_asset_ids:
                own_asset(db, user, aid)
        plan["characters"] = [c.model_dump() for c in body.characters]
    if body.locations is not None:
        plan["locations"] = [l.model_dump() for l in body.locations]
    if body.scenes is not None:
        if not body.scenes:
            raise HTTPException(422, "A plan needs at least one scene")
        chapters = {c["id"] for c in plan["chapters"]}
        scenes = []
        for i, s in enumerate(body.scenes):
            if s.chapter_id not in chapters:
                raise HTTPException(422, f"Scene {i + 1} belongs to an unknown chapter")
            d = s.model_dump()
            d["shot"] = d["shot"] if d["shot"] in prompts.SHOTS else "medium"
            d["movement"] = d["movement"] if d["movement"] in prompts.MOVEMENTS else "dolly_in"
            d["number"] = i + 1
            scenes.append(d)
        plan["scenes"] = scenes
    if body.fit_to_length:
        timing.rebalance(plan["scenes"], bp.settings["target_seconds"])
    _moderate(*(s.get("narration", "") + " " + s.get("dialogue", "") for s in plan.get("scenes", [])))
    plan["settings"] = bp.settings
    director.refresh(plan, render_speed_ratio(db))
    bp.plan = plan
    flag_modified(bp, "plan")
    db.commit()
    return _plan_dict(db, bp)


@router.post("/director/plans/{plan_id}/fill")
def fill_plan(plan_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    """Ask the agents again for scenes that are still empty (keeps everything else)."""
    bp = _own_plan(db, user, plan_id)
    if bp.status not in ("ready", "failed"):
        raise HTTPException(409, "The plan is busy or already approved")
    if not llm.pick_llm():
        raise HTTPException(503, llm.NO_LLM_HELP)
    bp.status, bp.stage, bp.error = "queued", "Waiting to start", None
    db.commit()
    queue.enqueue("director_plan", bp.id, True)
    return _plan_dict(db, bp)


@router.post("/director/plans/{plan_id}/replan")
def replan(plan_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    """Start the plan again from the idea (replaces the current plan)."""
    bp = _own_plan(db, user, plan_id)
    if bp.status not in ("ready", "failed"):
        raise HTTPException(409, "The plan is busy or already approved")
    if not llm.pick_llm():
        raise HTTPException(503, llm.NO_LLM_HELP)
    bp.status, bp.stage, bp.error, bp.plan = "queued", "Waiting to start", None, {}
    db.commit()
    queue.enqueue("director_plan", bp.id, False)
    return _plan_dict(db, bp)


@router.post("/director/plans/{plan_id}/approve")
def approve_plan(plan_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    bp = _own_plan(db, user, plan_id)
    if bp.status == "approved":
        raise HTTPException(409, "This plan is already a project")
    if bp.status != "ready" or not bp.plan.get("scenes"):
        raise HTTPException(409, "The plan is not ready yet")
    seconds = timing.total(bp.plan["scenes"])
    if seconds > settings.max_project_seconds + 1:
        raise HTTPException(422, f"The plan is {seconds / 60:.1f} min; the limit is {settings.max_project_seconds / 60:.0f} min")
    p = director.approve(db, bp)
    db.commit()
    return {"project_id": p.id, "plan": _plan_dict(db, bp, full=False)}


@router.delete("/director/plans/{plan_id}")
def delete_plan(plan_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    bp = _own_plan(db, user, plan_id)
    if bp.status in ("queued", "planning"):
        raise HTTPException(409, "Wait for the plan to finish first")
    db.query(AgentRun).filter(AgentRun.plan_id == bp.id).delete()
    db.delete(bp)  # an approved plan's project stays
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- project memory

def _mem_dict(m: MemoryItem) -> dict:
    return {"id": m.id, "project_id": m.project_id, "kind": m.kind, "name": m.name, "description": m.description,
            "data": m.data or {}, "locked": m.locked, "updated_at": m.updated_at.isoformat()}


def _own_memory(db: Session, user: User, item_id: str) -> MemoryItem:
    m = db.get(MemoryItem, item_id)
    if not m or m.user_id != user.id:
        raise HTTPException(404, "Memory item not found")
    return m


@router.get("/projects/{project_id}/memory")
def list_memory(project_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    own_project(db, user, project_id)
    rows = db.query(MemoryItem).filter(MemoryItem.project_id == project_id).order_by(MemoryItem.kind, MemoryItem.created_at)
    plan = db.query(BrainPlan).filter(BrainPlan.project_id == project_id).first()
    return {"items": [_mem_dict(m) for m in rows], "plan_id": plan.id if plan else None}


@router.post("/projects/{project_id}/memory")
def add_memory(project_id: str, body: MemoryIn, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    own_project(db, user, project_id)
    m = MemoryItem(user_id=user.id, project_id=project_id, **body.model_dump(), data={})
    db.add(m)
    db.commit()
    return _mem_dict(m)


@router.patch("/memory/{item_id}")
def edit_memory(item_id: str, body: MemoryPatch, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    """Edit a memory item. Changing a locked character's look or a location's description
    updates every scene that uses the old wording, and those scenes will render again."""
    m = _own_memory(db, user, item_id)
    data = body.model_dump(exclude_unset=True)
    swaps: list[tuple[str, str]] = []
    if m.kind == "character":
        d = dict(m.data or {})
        for k in ("appearance", "clothing"):
            if k in data and data[k] != d.get(k):
                if d.get(k):
                    swaps.append((d[k], data[k]))
                d[k] = data[k]
        m.data = d
        flag_modified(m, "data")
        if "appearance" in data or "clothing" in data:
            m.description = "; ".join(x for x in (d.get("appearance"), f"wears {d['clothing']}" if d.get("clothing") else "") if x)
    elif "description" in data and m.description and data["description"] != m.description and m.kind in ("location", "style"):
        swaps.append((m.description, data["description"]))
    for k in ("name", "description", "locked"):
        if k in data and not (k == "description" and m.kind == "character" and ("appearance" in data or "clothing" in data)):
            setattr(m, k, data[k])
    changed = 0
    if swaps and m.locked:
        from .projects import _invalidate

        p = own_project(db, user, m.project_id)
        for sc in p.scenes:
            before = (sc.prompt, sc.character, sc.visual_description)
            for old, new in swaps:
                sc.prompt = sc.prompt.replace(old, new)
                sc.character = sc.character.replace(old, new)
                sc.visual_description = sc.visual_description.replace(old, new)
            if (sc.prompt, sc.character, sc.visual_description) != before:
                _invalidate(sc)
                changed += 1
    db.commit()
    return {**_mem_dict(m), "scenes_updated": changed}


@router.delete("/memory/{item_id}")
def delete_memory(item_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    db.delete(_own_memory(db, user, item_id))
    db.commit()
    return {"ok": True}
