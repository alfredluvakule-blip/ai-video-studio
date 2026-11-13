"""Director Mode: one idea -> a complete, editable production plan -> a project.

Nothing is generated (no pictures, voice or video) until the user approves the plan.
Each agent step is written to ``agent_runs`` as it starts and finishes, so the
activity panel shows real work only.
"""
from __future__ import annotations

import logging
import re

from sqlalchemy.orm.attributes import flag_modified

from ..db import session_scope
from ..models import AgentRun, BrainPlan, MemoryItem, Project, Scene, now
from . import agents, prompts, timing
from .llm import Brain, BrainUnavailable

log = logging.getLogger(__name__)


class _Run:
    """Records one agent step in the activity log while it happens."""

    def __init__(self, plan_id: str, brain: Brain | None):
        self.plan_id, self.brain = plan_id, brain

    def step(self, agent: str, action: str, fn, ai: bool):
        with session_scope() as db:
            run = AgentRun(plan_id=self.plan_id, agent=agent, action=action, status="running",
                           provider=(self.brain.label if ai and self.brain else "rules (no AI call)"))
            db.add(run)
            db.flush()
            run_id = run.id
            bp = db.get(BrainPlan, self.plan_id)
            bp.stage = f"{agent}: {action}"
        calls0 = self.brain.calls if self.brain else 0
        try:
            detail = fn()
            status, err = "done", None
        except Exception as e:  # recorded, then re-raised for the caller to decide
            log.exception("agent %s failed", agent)
            status, detail, err = "failed", f"{type(e).__name__}: {e}"[:1500], e
        with session_scope() as db:
            run = db.get(AgentRun, run_id)
            run.status, run.detail, run.finished_at = status, str(detail or "")[:4000], now()
            run.llm_calls = (self.brain.calls if self.brain else 0) - calls0
        if err:
            raise err
        return detail


def _save(plan_id: str, plan: dict, brain: Brain | None, **fields) -> None:
    with session_scope() as db:
        bp = db.get(BrainPlan, plan_id)
        if brain:
            plan.setdefault("usage", {})["llm_calls"] = brain.calls + int(plan.get("usage", {}).get("previous_calls", 0))
            bp.llm_calls = plan["usage"]["llm_calls"]
        bp.plan = dict(plan)
        flag_modified(bp, "plan")
        for k, v in fields.items():
            setattr(bp, k, v)


def _gaps(scenes: list[dict]) -> bool:
    return any((not s.get("narration") and not s.get("dialogue")) or not s.get("action") for s in scenes)


def run(plan_id: str, fill_only: bool = False) -> None:
    """Make the plan. With fill_only, only redo the scenes that are still empty."""
    from ..api.common import render_speed_ratio

    with session_scope() as db:
        bp = db.get(BrainPlan, plan_id)
        if not bp or bp.status == "approved":
            return
        for r in db.query(AgentRun).filter(AgentRun.plan_id == plan_id, AgentRun.status == "running"):
            r.status, r.detail, r.finished_at = "failed", "Interrupted (the app restarted); started again.", now()
        bp.status, bp.error, bp.stage = "planning", None, "Starting"
        plan = dict(bp.plan or {})
        plan["settings"] = dict(bp.settings)
        plan.setdefault("usage", {})["previous_calls"] = bp.llm_calls if fill_only else 0
        ratio = render_speed_ratio(db)

    try:
        brain = Brain()
    except BrainUnavailable as e:
        with session_scope() as db:
            db.add(AgentRun(plan_id=plan_id, agent="Film Director", action="Looking for a connected AI writer",
                            status="failed", provider="none", detail=str(e), finished_at=now()))
        _save(plan_id, plan, None, status="failed", error=str(e), stage="")
        return

    r = _Run(plan_id, brain)
    try:
        if not fill_only or not plan.get("brief"):
            r.step("Film Director", "Understanding the idea and planning the production", lambda: agents.director(brain, plan), ai=True)
            r.step("Character Director", "Fixing each character's look and attaching reference photos", lambda: agents.characters(plan), ai=False)
            _save(plan_id, plan, brain, provider=brain.label)
    except Exception as e:
        _save(plan_id, plan, brain, status="failed", stage="", provider=brain.label,
              error=f"The Film Director could not make a plan: {e}")
        return

    for chapter, scenes in agents.batches(plan):
        if fill_only and not _gaps(scenes):
            continue
        span = f"scenes {scenes[0]['number']}-{scenes[-1]['number']}"
        try:
            if not fill_only or any(not s["narration"] and not s["dialogue"] for s in scenes):
                r.step("Scriptwriter", f"Writing narration for {span}", lambda: agents.scriptwriter(brain, plan, chapter, scenes), ai=True)
                for _ in range(agents.MAX_REVISIONS):
                    long = agents.too_long(plan, scenes)
                    if not long:
                        break
                    r.step("Scriptwriter", f"Revision asked by the continuity check: shorten scenes {long}",
                           lambda: agents.scriptwriter(brain, plan, chapter, scenes, fix=long), ai=True)
            r.step("Storyboard Artist", f"Designing shots, camera moves, action and sound for {span}",
                   lambda: agents.storyboard(brain, plan, chapter, scenes), ai=True)
        except Exception:
            pass  # recorded in the activity log; the scenes stay empty and the checks say so
        _save(plan_id, plan, brain)

    def _finish():
        agents.characters(plan)
        prompts.build(plan)
        return f"Wrote a picture prompt and a separate video-model prompt for {len(plan['scenes'])} scenes"

    try:
        r.step("Prompt Engineer", "Writing generator prompts from the storyboard", _finish, ai=False)
        r.step("Audio Director", "Choosing the narrator voice and music", lambda: agents.audio(plan), ai=False)
        r.step("Video Editor", "Planning the order, transitions, subtitles and export", lambda: agents.editor(plan), ai=False)
        r.step("Video Generation Specialist", "Choosing how to make each scene and estimating cost and time",
               lambda: agents.video(plan, ratio), ai=False)
        r.step("Continuity Checker", "Checking durations, characters, places and repeated lines",
               lambda: f"{len(agents.continuity(plan))} things to look at", ai=False)
    except Exception as e:
        _save(plan_id, plan, brain, status="failed", stage="", error=f"Finishing the plan failed: {e}")
        return
    _save(plan_id, plan, brain, status="ready", stage="", provider=brain.label)


def refresh(plan: dict, ratio: float | None) -> None:
    """After the user edits the plan: rebuild prompts, checks and the estimate (no AI call)."""
    agents.characters(plan)
    prompts.build(plan)
    for ch in plan.get("chapters", []):
        ch["seconds"] = timing.total([s for s in plan["scenes"] if s["chapter_id"] == ch["id"]])
    agents.audio(plan)
    agents.editor(plan)
    agents.video(plan, ratio)
    agents.continuity(plan)


def _spoken(scene: dict) -> str:
    """What the narrator voice says: the narration, then any dialogue without the speaker names."""
    said = re.sub(r"(?:^|(?<=\s))[^\s:][^:.!?]{0,30}:\s*", "", scene.get("dialogue") or "").strip()
    return " ".join(x for x in (scene.get("narration", "").strip(), said) if x)


def approve(db, bp: BrainPlan) -> Project:
    """Create a normal project from the approved plan. Existing render/editor flows take it from here."""
    plan, st = bp.plan, bp.settings
    b = plan["brief"]
    looks = {c["name"].lower(): c for c in plan.get("characters", [])}
    p = Project(
        user_id=bp.user_id, title=b.get("title") or st["idea"][:60], mode="text", prompt=st["idea"], script="",
        style=b.get("style", "cinematic"), aspect=st["aspect"], resolution=st.get("resolution", 720), fps=25,
        target_seconds=st["target_seconds"], scene_seconds=st["scene_seconds"], language=st["language"],
        voice=st["voice"], narration_style=b.get("narration_style", "neutral"), music=b.get("music_mood", "ambient"),
        status="storyboard_ready",
        notes=[
            f"Planned by the AI Director ({bp.provider}, {bp.llm_calls} AI writer calls). Review each scene, then approve and render.",
            *([plan["audio"]["song_note"]] if plan.get("audio", {}).get("song_note") else []),
            *(["Dialogue is read by the narrator voice; separate character voices are not available yet."]
              if any(s.get("dialogue") for s in plan["scenes"]) else []),
        ],
    )
    db.add(p)
    db.flush()
    for i, s in enumerate(plan["scenes"]):
        who = "; ".join(
            f"{looks[n.lower()]['name']}: {looks[n.lower()]['appearance']}; wears {looks[n.lower()]['clothing']}" if n.lower() in looks else n
            for n in s.get("characters", [])
        )
        visual = ". ".join(x for x in (
            f"{prompts.SHOTS.get(s.get('shot', ''), 'medium shot').capitalize()}, {prompts.MOVEMENTS.get(s.get('movement', ''), '').lower()}",
            s.get("action", ""), s.get("expression", ""),
            f"Location: {s['location']}" if s.get("location") else "", f"Lighting: {s['lighting']}" if s.get("lighting") else "",
        ) if x)
        sound = "; ".join(x for x in (s.get("sound_effects", ""), f"Music: {s['music_cue']}" if s.get("music_cue") else "") if x)
        sc = Scene(project_id=p.id, position=i, duration=float(s["duration"]), title=(s.get("title") or f"Scene {i + 1}")[:200],
                   visual_description=visual, camera=s.get("camera", "zoom_in"), character=who[:4000],
                   dialogue=s.get("dialogue", ""), voiceover=_spoken(s), sound_effects=sound, prompt=s.get("image_prompt", ""),
                   transition=s.get("transition", "fade"))
        db.add(sc)
        db.flush()
        s["scene_id"] = sc.id
    for c in plan.get("characters", []):
        db.add(MemoryItem(user_id=bp.user_id, project_id=p.id, kind="character", name=c["name"],
                          description="; ".join(x for x in (c.get("appearance"), f"wears {c['clothing']}" if c.get("clothing") else "") if x),
                          data={k: c.get(k) for k in ("role", "appearance", "clothing", "personality", "voice", "reference_asset_ids")},
                          locked=bool(c.get("locked", True))))
    for l in plan.get("locations", []):
        db.add(MemoryItem(user_id=bp.user_id, project_id=p.id, kind="location", name=l["name"], description=l.get("description", ""),
                          data={"lighting": l.get("lighting", "")}, locked=bool(l.get("locked", True))))
    db.add(MemoryItem(user_id=bp.user_id, project_id=p.id, kind="style", name="Visual style",
                      description=b.get("visual_style", ""), data={"style": b.get("style"), "tone": b.get("tone"),
                                                                   "camera_language": b.get("camera_language")}, locked=True))
    bp.project_id, bp.status = p.id, "approved"
    bp.plan = dict(plan)
    flag_modified(bp, "plan")
    return p
