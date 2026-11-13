"""Prompt engineer: structured scene data -> prompts for each kind of generator.

Users never have to write these. Each target gets its own format, because a
still-picture model and a video model want different things:

* image  - one still frame (Pollinations / FLUX, SDXL): subject, setting, framing,
           lighting, style; no motion words, no written text in the picture.
* video  - a moving shot (text- or image-to-video models): camera movement first,
           then subject and action over time, setting, lighting, style, length.

Locked characters and locations are copied word for word into every prompt that
uses them, which is what keeps them looking the same from scene to scene.
"""
from __future__ import annotations

from ..providers.llm import STYLE_HINTS

SHOTS = {
    "extreme_wide": "extreme wide shot",
    "wide": "wide shot",
    "medium": "medium shot",
    "close_up": "close-up",
    "extreme_close_up": "extreme close-up",
    "over_the_shoulder": "over-the-shoulder shot",
    "aerial": "aerial view",
    "low_angle": "low-angle shot",
    "high_angle": "high-angle shot",
}

MOVEMENTS = {
    "static": "Locked-off static camera",
    "dolly_in": "Slow dolly in towards the subject",
    "dolly_out": "Slow dolly out, revealing the surroundings",
    "pan_left": "Smooth pan left",
    "pan_right": "Smooth pan right",
    "tilt_up": "Slow tilt up",
    "tilt_down": "Slow tilt down",
    "tracking": "Tracking shot following the subject",
    "crane": "Crane shot rising above the scene",
    "aerial": "Aerial drone shot gliding over the scene",
    "zoom_in": "Slow zoom in",
    "zoom_out": "Slow zoom out",
}

# What today's renderer can do with a still picture (camera motion over the frame).
RENDER_CAMERA = {
    "static": "static", "dolly_in": "zoom_in", "dolly_out": "zoom_out", "pan_left": "pan_left",
    "pan_right": "pan_right", "tilt_up": "pan_up", "tilt_down": "pan_down", "tracking": "pan_right",
    "crane": "pan_up", "aerial": "zoom_out", "zoom_in": "zoom_in", "zoom_out": "zoom_out",
}

NEGATIVE = "text, letters, watermark, logo, extra fingers, deformed hands, distorted face, blurry"


def _people(scene: dict, characters: dict[str, dict]) -> list[str]:
    out = []
    for name in scene.get("characters") or []:
        c = characters.get(str(name).lower())
        if c:
            look = ", ".join(x for x in (c.get("appearance"), c.get("clothing")) if x)
            out.append(f"{c['name']} ({look})" if look else c["name"])
        else:
            out.append(str(name))
    return out


def _place(scene: dict, locations: dict[str, dict]) -> str:
    loc = locations.get(str(scene.get("location") or "").lower())
    if loc:
        return f"{loc['name']}: {loc.get('description', '')}".strip(": ")
    return str(scene.get("location") or "")


def image_prompt(scene: dict, brief: dict, characters: dict[str, dict], locations: dict[str, dict]) -> str:
    style = STYLE_HINTS.get(brief.get("style", ""), "")
    parts = [
        SHOTS.get(scene.get("shot", ""), "medium shot"),
        " and ".join(_people(scene, characters)),
        scene.get("action", ""),
        scene.get("expression", ""),
        f"in {_place(scene, locations)}" if _place(scene, locations) else "",
        scene.get("lighting", ""),
        brief.get("visual_style", ""),
        style,
        "consistent character design, no written words",
    ]
    return ", ".join(p.strip().rstrip(".") for p in parts if p and p.strip())[:1500]


def video_prompt(scene: dict, brief: dict, characters: dict[str, dict], locations: dict[str, dict]) -> str:
    style = STYLE_HINTS.get(brief.get("style", ""), "")
    people = " and ".join(_people(scene, characters))
    subject = ". ".join(x for x in (people, scene.get("action", ""), scene.get("expression", "")) if x)
    lines = [
        f"{MOVEMENTS.get(scene.get('movement', ''), 'Gentle camera movement')}, {SHOTS.get(scene.get('shot', ''), 'medium shot')}.",
        f"{subject}." if subject else "",
        f"Setting: {_place(scene, locations)}." if _place(scene, locations) else "",
        f"Lighting: {scene['lighting']}." if scene.get("lighting") else "",
        f"Style: {', '.join(x for x in (brief.get('visual_style', ''), style) if x)}.",
        f"Natural, smooth motion; keep faces and clothing unchanged. About {round(float(scene.get('duration') or 5))} seconds.",
    ]
    return " ".join(l for l in lines if l)[:2000]


def build(plan: dict) -> None:
    """(Re)build prompts and the renderer camera for every scene whose prompt the user did not edit by hand."""
    brief = plan.get("brief", {})
    characters = {c["name"].lower(): c for c in plan.get("characters", []) if c.get("name")}
    locations = {l["name"].lower(): l for l in plan.get("locations", []) if l.get("name")}
    for s in plan.get("scenes", []):
        s["camera"] = RENDER_CAMERA.get(s.get("movement", ""), "zoom_in")
        if not s.get("prompt_edited"):
            s["image_prompt"] = image_prompt(s, brief, characters, locations)
        s["video_prompt"] = video_prompt(s, brief, characters, locations)
        s["negative_prompt"] = NEGATIVE
