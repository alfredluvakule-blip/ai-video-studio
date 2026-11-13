"""Video Generation Specialist's knowledge: which ways of making a scene are
really connected on this server, which to use, and what it will cost.

Only connected routes are recommended. Paid video models are listed so the user
can see the option, but they are marked "not connected" and are never called:
no adapter for them exists yet, and nothing that costs money runs without the
user agreeing to the price first.
"""
from __future__ import annotations

from ..config import settings
from ..providers.visual import PROVIDERS

PAID_VIDEO_MODELS = [
    {"name": "veo", "label": "Google Veo"},
    {"name": "kling", "label": "Kling"},
    {"name": "runway", "label": "Runway"},
    {"name": "seedance", "label": "Seedance"},
]


def routes() -> list[dict]:
    """Every scene route with what it can really do here. Ordered best first."""
    comfy = PROVIDERS["comfyui"]
    out = [
        {
            "name": "comfyui_video", "label": "AI video clips on your own GPU (ComfyUI + Stable Video Diffusion)",
            "connected": comfy.video_available(), "motion": "generated video", "text_to_video": False,
            "image_to_video": True, "reference_images": False, "audio": False, "cost_per_second": 0.0,
            "note": "Needs an NVIDIA GPU running ComfyUI. Makes a short moving clip from each scene's picture.",
        },
        {
            "name": "comfyui", "label": "AI pictures on your own GPU (ComfyUI)", "connected": PROVIDERS["comfyui"].available(),
            "motion": "camera motion over a still picture", "text_to_video": False, "image_to_video": False,
            "reference_images": False, "audio": False, "cost_per_second": 0.0, "note": "Needs a GPU running ComfyUI.",
        },
        {
            "name": "huggingface", "label": "AI pictures (Hugging Face free tier)", "connected": PROVIDERS["huggingface"].available(),
            "motion": "camera motion over a still picture", "text_to_video": False, "image_to_video": False,
            "reference_images": False, "audio": False, "cost_per_second": 0.0, "note": "Needs a free HF_TOKEN. Rate-limited.",
        },
        {
            "name": "pollinations", "label": "AI pictures (Pollinations, free)", "connected": PROVIDERS["pollinations"].available(),
            "motion": "camera motion over a still picture", "text_to_video": False, "image_to_video": False,
            "reference_images": False, "audio": False, "cost_per_second": 0.0,
            "note": f"Free, no account. About one picture every {settings.pollinations_interval:.0f} seconds. "
                    "It cannot copy a face from a photo, so characters are kept alike by describing them the same way every time.",
        },
        {
            "name": "photo", "label": "Your own photo or video for the scene", "connected": True,
            "motion": "camera motion over your photo, or your clip", "text_to_video": False, "image_to_video": False,
            "reference_images": True, "audio": False, "cost_per_second": 0.0,
            "note": "Upload a photo or clip on any scene in the storyboard to use it instead of an AI picture.",
        },
        {
            "name": "titlecard", "label": "Text cards (no AI)", "connected": True, "motion": "camera motion over a text card",
            "text_to_video": False, "image_to_video": False, "reference_images": False, "audio": False, "cost_per_second": 0.0,
            "note": "Always available fallback.",
        },
    ]
    for m in PAID_VIDEO_MODELS:
        out.append({
            "name": m["name"], "label": f"{m['label']} (paid AI video clips)", "connected": False, "paid": True,
            "motion": "generated video", "cost_per_second": None,
            "note": "Not connected. Paid per second of video. Luvakule AI does not call it; connecting it is a later step, "
                    "and it will show the price and ask before generating anything.",
        })
    return out


def recommend(plan: dict) -> dict:
    """Pick the best connected route for the plan and say why, in plain words."""
    rs = {r["name"]: r for r in routes()}
    brief = plan.get("brief", {})
    if rs["comfyui_video"]["connected"]:
        best = rs["comfyui_video"]
        why = "A GPU with ComfyUI is connected, so each scene can be a short generated video clip."
    else:
        best = next((rs[n] for n in ("comfyui", "huggingface", "pollinations") if rs[n]["connected"]), rs["titlecard"])
        why = ("No AI video model is connected, so each scene will be an AI picture with camera motion, "
               "which is free.") if best["name"] != "titlecard" else (
               "No AI picture source is connected, so scenes will be text cards. Turn on Pollinations (free) for AI pictures.")
    reasons = [why]
    if any(c.get("reference_asset_ids") for c in plan.get("characters", [])):
        reasons.append("Your reference photos are saved with the character. None of the connected picture sources can "
                       "copy a face from a photo, so the character is kept alike by its fixed description. "
                       "To show the real person, upload their photo on the scenes where they appear.")
    if brief.get("is_song"):
        reasons.append("The narrator voice speaks the lyrics; it cannot sing. Singing needs a music or singing-voice "
                       "service, which is not connected.")
    if float(plan.get("settings", {}).get("target_seconds", 0)) > 600:
        reasons.append("Long video: every scene is made separately and then joined, so a failed scene can be redone on its own.")
    return {
        "route": best["name"], "label": best["label"], "reasons": reasons,
        "connected": [r["label"] for r in rs.values() if r["connected"]],
        "not_connected": [r["label"] for r in rs.values() if not r["connected"]],
    }


def estimate(plan: dict, render_ratio: float | None) -> dict:
    scenes = plan.get("scenes", [])
    seconds = sum(float(s.get("duration") or 0) for s in scenes)
    route = plan.get("recommendation", {}).get("route", "pollinations")
    picture_wait = len(scenes) * settings.pollinations_interval if route == "pollinations" else 0
    render = seconds * (render_ratio or 0.8)
    return {
        "scenes": len(scenes),
        "video_seconds": round(seconds, 1),
        "cost_usd": 0.0,
        "cost_note": "Free: the recommended route uses no paid service.",
        "ai_writer_calls": int(plan.get("usage", {}).get("llm_calls", 0)),
        "ai_writer_note": "AI writer calls used to make this plan (free with Gemini, within its limits; paid from your Anthropic credit with Claude).",
        "estimated_minutes": round((picture_wait + render) / 60, 1),
        "time_basis": ("measured render speed on this server" if render_ratio else "a default guess until the first scene renders")
        + (f", plus about {settings.pollinations_interval:.0f} s per AI picture" if picture_wait else ""),
    }
