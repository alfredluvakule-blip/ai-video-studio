"""The specialised agents. Each one reads and writes the shared plan (a dict).

AI agents (they call the connected AI writer):
  director      - understands the idea; writes the brief, characters, locations, chapters
  scriptwriter  - narration and dialogue for each scene, sized to the scene's duration
  storyboard    - Storyboard Artist + Cinematographer + Animation Director + Audio cues:
                  what is on screen, shot, camera movement, action, lighting, sound

Rule-based agents (plain code, no AI call, so they cost nothing and are exact):
  characters    - Character Director: fixed looks, reference photos, names used in scenes
  continuity    - checks durations, repeated lines, unknown characters, missing scenes
  audio         - Audio Director: narrator voice, music mood, song limits
  video         - Video Generation Specialist: best connected route and estimate
  editor        - Video Editor: transitions, subtitles, export settings

Every AI agent has a retry limit, so nothing can loop forever.
"""
from __future__ import annotations

import re

from ..pipeline import music
from ..providers import tts
from ..providers.llm import LANG_NAMES, STYLE_HINTS
from . import catalog, prompts, timing
from .llm import Brain, clean

STYLES = list(STYLE_HINTS)
NARRATION_STYLES = list(tts.STYLES)
MUSIC = ["none", *music.MOODS]
BATCH = 15  # scenes per AI call
MAX_REVISIONS = 1  # times the continuity check may send scenes back to the scriptwriter


def _lang(code: str) -> str:
    return LANG_NAMES.get(code, code)


def _fmt_len(seconds: float) -> str:
    m, s = divmod(int(round(seconds)), 60)
    return f"{m} min {s} s" if m and s else f"{m} min" if m else f"{s} s"


def _pick(v, options: list[str], default: str) -> str:
    v = str(v or "").strip().lower().replace(" ", "_").replace("-", "_")
    return v if v in options else default


# ---------------------------------------------------------------- Film Director (AI)

def director(brain: Brain, plan: dict) -> str:
    st = plan["settings"]
    lo, hi = timing.chapter_range(st["target_seconds"])
    who = ""
    if st.get("main_character"):
        who = (f'\nThe user\'s main character: "{st["main_character"]}". Use this person as the main character'
               f'{" (the user also uploaded " + str(len(st.get("reference_asset_ids") or [])) + " reference photo(s) of them)" if st.get("reference_asset_ids") else ""}.')
    style_line = (f"Visual style requested: {st['style']}." if st.get("style") and st["style"] != "auto"
                  else "Choose the visual style that fits best.")
    prompt = f"""You are the Film Director of Luvakule AI, planning a video production before anything is generated.
User's idea: "{st['idea']}"
Length: {_fmt_len(st['target_seconds'])}. Narration language: {_lang(st['language'])}. Format: {st['aspect']}. {style_line}{who}

Understand what the user wants (audience, purpose, tone) and plan the production.
Return ONLY a JSON object with these keys:
"title": a short title,
"logline": one sentence describing the video,
"audience": who it is for,
"goal": what the viewer should learn or feel,
"style": one of {STYLES},
"visual_style": a short art direction repeated in every picture (look, colours, rendering),
"tone": the mood,
"camera_language": how the camera should behave across the video,
"narration_style": one of {NARRATION_STYLES},
"music_mood": one of {MUSIC},
"is_song": true only if the user asked for singing or a song,
"characters": a list of {{"name", "role", "appearance" (fixed physical look: age, face, hair, skin, build), "clothing" (one fixed outfit), "personality", "voice"}},
"locations": a list of {{"name", "description", "lighting"}},
"chapters": between {lo} and {hi} chapters in story order covering the whole video, each {{"title", "summary", "weight"}} where weight is its relative length (1 = average),
"assumptions": short notes on what you decided because the idea did not say,
"questions": only questions that are essential and could not be assumed (usually an empty list).
Write everything in English except where told otherwise."""
    d = brain.ask_json(prompt, dict)
    style = st["style"] if st.get("style") and st["style"] != "auto" else _pick(d.get("style"), STYLES, "cinematic")
    plan["brief"] = {
        "title": clean(d.get("title"), 120) or clean(st["idea"], 60),
        "logline": clean(d.get("logline"), 400),
        "audience": clean(d.get("audience"), 200),
        "goal": clean(d.get("goal"), 400),
        "style": style,
        "visual_style": clean(d.get("visual_style"), 300),
        "tone": clean(d.get("tone"), 120),
        "camera_language": clean(d.get("camera_language"), 300),
        "narration_style": _pick(d.get("narration_style"), NARRATION_STYLES, "neutral"),
        "music_mood": _pick(d.get("music_mood"), MUSIC, "ambient"),
        "is_song": bool(d.get("is_song")),
        "assumptions": [clean(x, 300) for x in (d.get("assumptions") or [])[:8] if clean(x)],
        "questions": [clean(x, 300) for x in (d.get("questions") or [])[:5] if clean(x)],
    }
    plan["characters"] = [
        {"name": clean(c.get("name"), 60), "role": clean(c.get("role"), 120), "appearance": clean(c.get("appearance"), 400),
         "clothing": clean(c.get("clothing"), 300), "personality": clean(c.get("personality"), 200),
         "voice": clean(c.get("voice"), 120), "reference_asset_ids": [], "locked": True}
        for c in (d.get("characters") or [])[:12] if isinstance(c, dict) and clean(c.get("name"))
    ]
    plan["locations"] = [
        {"name": clean(l.get("name"), 80), "description": clean(l.get("description"), 400),
         "lighting": clean(l.get("lighting"), 200), "locked": True}
        for l in (d.get("locations") or [])[:20] if isinstance(l, dict) and clean(l.get("name"))
    ]
    chapters = [c for c in (d.get("chapters") or []) if isinstance(c, dict) and clean(c.get("title"))][:hi]
    if not chapters:
        chapters = [{"title": plan["brief"]["title"], "summary": plan["brief"]["logline"], "weight": 1}]
    _layout(plan, chapters)
    return (f"Planned \"{plan['brief']['title']}\": {len(plan['chapters'])} chapters, {len(plan['scenes'])} scenes, "
            f"{len(plan['characters'])} characters, {len(plan['locations'])} locations, {style} style")


def _layout(plan: dict, chapters: list[dict]) -> None:
    """Turn chapters into empty scene slots whose durations add up exactly to the target."""
    st = plan["settings"]
    n = timing.scene_count(st["target_seconds"], st["scene_seconds"])
    counts = timing.split_scenes(n, [_weight(c.get("weight")) for c in chapters])
    durations = timing.scene_durations(st["target_seconds"], n)
    plan["chapters"], plan["scenes"] = [], []
    k = 0
    for ci, (c, cnt) in enumerate(zip(chapters, counts)):
        if cnt == 0:
            continue
        ch = {"id": f"c{ci + 1}", "title": clean(c.get("title"), 120), "summary": clean(c.get("summary"), 600)}
        ch_scenes = []
        for _ in range(cnt):
            k += 1
            ch_scenes.append({"number": k, "chapter_id": ch["id"], "duration": durations[k - 1], "title": "",
                              "narration": "", "dialogue": "", "characters": [], "location": "", "action": "",
                              "expression": "", "shot": "medium", "movement": "dolly_in", "lighting": "",
                              "transition": "fade", "sound_effects": "", "music_cue": ""})
        ch["seconds"] = timing.total(ch_scenes)
        plan["chapters"].append(ch)
        plan["scenes"].extend(ch_scenes)


def _weight(v) -> float:
    try:
        return min(10.0, max(0.1, float(v)))
    except (TypeError, ValueError):
        return 1.0


def batches(plan: dict) -> list[tuple[dict, list[dict]]]:
    """(chapter, scenes) groups of at most BATCH scenes, never crossing a chapter."""
    out = []
    for ch in plan["chapters"]:
        scs = [s for s in plan["scenes"] if s["chapter_id"] == ch["id"]]
        for i in range(0, len(scs), BATCH):
            out.append((ch, scs[i : i + BATCH]))
    return out


def _brief_text(plan: dict) -> str:
    b = plan["brief"]
    cast = "; ".join(f"{c['name']} ({c['role']}): {c['appearance']}; wears {c['clothing']}" for c in plan["characters"])
    places = "; ".join(f"{l['name']}: {l['description']}" for l in plan["locations"])
    return (f"Title: {b['title']}. Logline: {b['logline']}. Audience: {b['audience']}. Goal: {b['goal']}. "
            f"Tone: {b['tone']}. Visual style: {b['visual_style']}. Camera language: {b['camera_language']}.\n"
            f"Characters: {cast or 'none'}.\nLocations: {places or 'none'}.")


def _story_so_far(plan: dict, before: int) -> str:
    prev = [s for s in plan["scenes"] if s["number"] < before and s.get("narration")]
    return " ".join(s["narration"] for s in prev[-3:])[-800:]


def _by_number(items: list, scenes: list[dict]) -> dict[int, dict]:
    """Match AI replies to scene slots by their "number", falling back to order."""
    nums = {s["number"] for s in scenes}
    out: dict[int, dict] = {}
    for i, d in enumerate(x for x in items if isinstance(x, dict)):
        try:
            n = int(d.get("number"))
        except Exception:
            n = -1
        if n not in nums:
            n = scenes[i]["number"] if i < len(scenes) else -1
        if n in nums and n not in out:
            out[n] = d
    return out


# ---------------------------------------------------------------- Scriptwriter (AI)

def scriptwriter(brain: Brain, plan: dict, chapter: dict, scenes: list[dict], fix: list[int] | None = None) -> str:
    st, b = plan["settings"], plan["brief"]
    lang = _lang(st["language"])
    targets = [s for s in scenes if not fix or s["number"] in fix]
    lines = "\n".join(
        f"Scene {s['number']}: {s['duration']:g} seconds, at most {timing.word_budget(s['duration'], st['language'])} words"
        + (f'. Current narration is too long ({len(s["narration"].split())} words): "{s["narration"]}"' if fix else "")
        for s in targets
    )
    song = ("\nThe user asked for a song: write the narration as short, rhythmic, repeatable lyric lines that a "
            "narrator can chant (the voice speaks, it does not sing).") if b.get("is_song") else ""
    prompt = f"""You are the Scriptwriter of Luvakule AI.
{_brief_text(plan)}
Chapter "{chapter['title']}": {chapter['summary']}
Total scenes in the video: {len(plan['scenes'])}. Narration style: {b['narration_style']}.{song}
Story so far (last narration): "{_story_so_far(plan, targets[0]['number'])}"
{"Shorten these scenes so each fits its word limit, keeping the meaning:" if fix else "Write these scenes:"}
{lines}
Return ONLY a JSON array with one object per scene, in order:
{{"number": the scene number, "narration": the voice-over in {lang},
 "dialogue": lines spoken by on-screen characters as "Name: line" (in {lang}), or ""}}.
Narration and dialogue together must stay within the scene's word limit.
Never repeat a line used earlier. Keep facts correct and suitable for the audience."""
    got = _by_number(brain.ask_json(prompt, list), targets)
    for s in targets:
        d = got.get(s["number"])
        if d:
            s["narration"] = clean(d.get("narration"), 3000)
            s["dialogue"] = clean(d.get("dialogue"), 1500)
    missing = [s["number"] for s in targets if s["number"] not in got]
    return f"{'Shortened' if fix else 'Wrote'} narration for scenes {targets[0]['number']}-{targets[-1]['number']}" + (
        f" (no answer for scenes {missing})" if missing else "")


def too_long(plan: dict, scenes: list[dict]) -> list[int]:
    lang = plan["settings"]["language"]
    return [s["number"] for s in scenes
            if len((s["narration"] + " " + s["dialogue"]).split()) > timing.word_budget(s["duration"], lang) * 1.3]


# ---------------------------------------------------------------- Storyboard Artist + Cinematographer + Animation + Audio cues (AI)

def storyboard(brain: Brain, plan: dict, chapter: dict, scenes: list[dict]) -> str:
    names = [c["name"] for c in plan["characters"]]
    places = [l["name"] for l in plan["locations"]]
    prev = next((s for s in reversed(plan["scenes"]) if s["number"] < scenes[0]["number"] and s.get("action")), None)
    prev_txt = (f'Previous scene ({prev["number"]}): {prev["shot"]} at {prev["location"]}, {prev["action"]}'
                if prev else "This is where the video starts.")
    listing = "\n".join(f"{s['number']}. ({s['duration']:g} s) narration: {s['narration'] or '(none)'}"
                        + (f" | dialogue: {s['dialogue']}" if s["dialogue"] else "") for s in scenes)
    prompt = f"""You are the Storyboard Artist of Luvakule AI, working with the Cinematographer, the Animation Director and the Audio Director.
{_brief_text(plan)}
Chapter "{chapter['title']}": {chapter['summary']}
{prev_txt}
Design each scene below. Use only these character names: {names or 'none'}; and these location names: {places or 'none'}.
Keep continuity: same outfits and looks, no unexplained jumps in place, vary the shots (do not use the same shot more than twice in a row).
Return ONLY a JSON array with one object per scene, in order:
{{"number": the scene number, "title": at most 6 words, "characters": [names on screen], "location": one location name,
 "action": what happens on screen including body movement (walking, pointing, jumping, dancing...), timed to the narration,
 "expression": facial expressions, "shot": one of {list(prompts.SHOTS)}, "movement": one of {list(prompts.MOVEMENTS)},
 "lighting": the light, "transition": "cut" or "fade" into the next scene, "sound_effects": sound effects or "",
 "music_cue": how the music should feel here}}
Scenes:
{listing}"""
    got = _by_number(brain.ask_json(prompt, list), scenes)
    for s in scenes:
        d = got.get(s["number"])
        if not d:
            continue
        s["title"] = clean(d.get("title"), 80)
        s["characters"] = [clean(x, 60) for x in (d.get("characters") or []) if clean(x)][:6] if isinstance(d.get("characters"), list) else []
        s["location"] = clean(d.get("location"), 80)
        s["action"] = clean(d.get("action"), 600)
        s["expression"] = clean(d.get("expression"), 200)
        s["shot"] = _pick(d.get("shot"), list(prompts.SHOTS), "medium")
        s["movement"] = _pick(d.get("movement"), list(prompts.MOVEMENTS), "dolly_in")
        s["lighting"] = clean(d.get("lighting"), 200)
        s["transition"] = "cut" if str(d.get("transition", "")).lower() == "cut" else "fade"
        s["sound_effects"] = clean(d.get("sound_effects"), 300)
        s["music_cue"] = clean(d.get("music_cue"), 200)
    missing = [s["number"] for s in scenes if s["number"] not in got]
    return f"Designed shots for scenes {scenes[0]['number']}-{scenes[-1]['number']}" + (
        f" (no answer for scenes {missing})" if missing else "")


# ---------------------------------------------------------------- rule-based agents

def characters(plan: dict) -> str:
    """Character Director: unique names, fixed looks, the user's reference photos, names in scenes."""
    st = plan["settings"]
    seen, cast = set(), []
    for c in plan["characters"]:
        if c["name"].lower() not in seen:
            seen.add(c["name"].lower())
            cast.append(c)
    plan["characters"] = cast
    refs = list(st.get("reference_asset_ids") or [])
    main = None
    if refs and cast:
        main = cast[0]
        words = (st.get("main_character") or "").split()
        if words:
            first = words[0].lower().strip(",.")
            main = next((c for c in cast if first in c["name"].lower()), cast[0])
        main["reference_asset_ids"] = refs
    lookup = {c["name"].lower(): c["name"] for c in cast}
    for s in plan["scenes"]:
        s["characters"] = [lookup.get(n.lower(), n) for n in s["characters"]]
    used = {n for s in plan["scenes"] for n in s["characters"]}
    unused = [c["name"] for c in cast if c["name"] not in used] if used else []  # before the storyboard, nobody is placed yet
    return (f"{len(cast)} characters with fixed looks" + (f", reference photos attached to {main['name']}" if main else "")
            + (f"; not on screen in any scene: {', '.join(unused)}" if unused else ""))


def continuity(plan: dict) -> list[dict]:
    """Checks the whole plan. Returns findings; never changes the story."""
    st = plan["settings"]
    checks: list[dict] = []
    names = {c["name"].lower() for c in plan["characters"]}
    places = {l["name"].lower() for l in plan["locations"]}
    total = timing.total(plan["scenes"])
    if abs(total - st["target_seconds"]) > 0.05:
        checks.append({"level": "warning", "scene": None,
                       "text": f"Scenes add up to {_fmt_len(total)} but you asked for {_fmt_len(st['target_seconds'])}. Use 'Fit to length'."})
    seen: dict[str, int] = {}
    for s in plan["scenes"]:
        n = s["number"]
        if not s["narration"] and not s["dialogue"]:
            checks.append({"level": "warning", "scene": n, "text": "No narration or dialogue yet."})
        if not s["action"]:
            checks.append({"level": "warning", "scene": n, "text": "Nothing described on screen yet."})
        words = len((s["narration"] + " " + s["dialogue"]).split())
        budget = timing.word_budget(s["duration"], st["language"])
        if words > budget * 1.3:
            need = words / timing.words_per_second(st["language"])
            checks.append({"level": "warning", "scene": n,
                           "text": f"Narration is about {need:.0f} s long but the scene is {s['duration']:g} s, so the video will run longer. Shorten it or lengthen the scene."})
        for c in s["characters"]:
            if c.lower() not in names:
                checks.append({"level": "info", "scene": n, "text": f"'{c}' is not in the character list, so their look is not fixed."})
        if s["location"] and s["location"].lower() not in places:
            checks.append({"level": "info", "scene": n, "text": f"'{s['location']}' is not in the location list."})
        key = re.sub(r"\W+", " ", s["narration"].lower()).strip()
        if len(key) > 20:
            if key in seen and not plan["brief"].get("is_song"):
                checks.append({"level": "warning", "scene": n, "text": f"Repeats the narration of scene {seen[key]}."})
            seen.setdefault(key, n)
    for a, b in zip(plan["scenes"], plan["scenes"][1:]):
        if a["location"] and b["location"] and a["location"].lower() != b["location"].lower() and b["chapter_id"] == a["chapter_id"] and b.get("transition") == "cut":
            checks.append({"level": "info", "scene": b["number"],
                           "text": f"Jumps from {a['location']} to {b['location']} with a hard cut; a fade may read better."})
    plan["checks"] = checks
    return checks


def audio(plan: dict) -> str:
    st, b = plan["settings"], plan["brief"]
    lang_ok = st["language"] in tts.LANGUAGES
    plan["audio"] = {
        "narrator": f"{st['voice']} voice in {_lang(st['language'])}" + ("" if lang_ok else " (not supported; English will be used)"),
        "narration_style": b["narration_style"],
        "music_mood": b["music_mood"],
        "music_note": "Original background music made on this computer, lowered automatically under the voice. You can pick your own track later.",
        "sound_effects_note": "Sound effects are written into each scene as notes. Generating them needs a sound service that is not connected yet.",
        "song_note": "The narrator speaks the lyrics; it cannot sing yet." if b.get("is_song") else "",
    }
    return f"Narrator: {plan['audio']['narrator']}, {b['narration_style']} style; music: {b['music_mood']}"


def editor(plan: dict) -> str:
    st = plan["settings"]
    plan["editing"] = {
        "order": "scenes in plan order", "subtitles": "an .srt file always; burned into the picture if you turn it on",
        "aspect": st["aspect"], "resolution": st.get("resolution", 720), "fps": 25,
        "transitions": sum(1 for s in plan["scenes"] if s["transition"] == "fade"),
    }
    return f"{len(plan['scenes'])} scenes in order, {plan['editing']['transitions']} fades, {st['aspect']} {plan['editing']['resolution']}p"


def video(plan: dict, render_ratio: float | None) -> str:
    plan["recommendation"] = catalog.recommend(plan)
    plan["estimate"] = catalog.estimate(plan, render_ratio)
    e = plan["estimate"]
    return f"Recommended: {plan['recommendation']['label']}. Cost ${e['cost_usd']:.2f}; about {e['estimated_minutes']} min to make"

