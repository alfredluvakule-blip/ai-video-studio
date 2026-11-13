"""Luvakule AI Brain / Director Mode.

The AI writer is replaced by a scripted stand-in (FakeWriter) that answers the
agents' real prompts with JSON, the way Gemini does. Everything else (timing,
prompts, checks, activity log, approval, memory, rendering) is the real code.
"""
import io
import re
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.brain import agents, llm, timing
from app.main import app

NUMBER_WORDS = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
                "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty"]


class FakeWriter:
    name = "fake"
    label = "Test writer"

    def __init__(self, long_first=False, fail_storyboard=False):
        self.prompts: list[str] = []
        self.long_first = long_first
        self.fail_storyboard = fail_storyboard

    def available(self):
        return True

    def complete(self, prompt: str) -> str:
        import json

        self.prompts.append(prompt)
        if "You are the Film Director" in prompt:
            lo, hi = map(int, re.search(r"between (\d+) and (\d+) chapters", prompt).groups())
            n = max(lo, min(hi, 5))
            return json.dumps({
                "title": "Counting with Baby Amani", "logline": "Baby Amani teaches children to count from 1 to 20.",
                "audience": "children aged 2-6", "goal": "Count from one to twenty", "style": "animation",
                "visual_style": "bright 3D animated movie look, soft rounded shapes, pastel colours", "tone": "joyful",
                "camera_language": "gentle moves, close-ups on each number", "narration_style": "children",
                "music_mood": "upbeat", "is_song": False,
                "characters": [{"name": "Baby Amani", "role": "teacher", "appearance": "one-year-old girl, round cheeks, short curly black hair",
                                "clothing": "yellow dungarees with a star", "personality": "playful", "voice": "giggly"},
                               {"name": "Toto the Parrot", "role": "helper", "appearance": "small green parrot", "clothing": "red bow tie",
                                "personality": "silly", "voice": "squeaky"}],
                "locations": [{"name": "Playroom", "description": "a sunny playroom with wooden number blocks", "lighting": "warm morning light"},
                              {"name": "Garden", "description": "a flower garden with a picket fence", "lighting": "soft daylight"}],
                "chapters": [{"title": f"Part {i + 1}", "summary": f"Numbers part {i + 1}", "weight": 1 + (i == 0)} for i in range(n)],
                "assumptions": ["3D cartoon look"], "questions": [],
            })
        if "You are the Scriptwriter" in prompt:
            out = []
            fixing = "Shorten these scenes" in prompt
            for n, words in re.findall(r"Scene (\d+): [\d.]+ seconds, at most (\d+) words", prompt):
                n, words = int(n), int(words)
                count = NUMBER_WORDS[(n - 1) % 20]
                text = f"Look, this is number {count}! Let us say {count} together."
                if self.long_first and not fixing and n == 1:
                    text = " ".join(["very"] * (words * 3)) + " long"
                out.append({"number": n, "narration": " ".join(text.split()[:max(words, 3)]) if not (self.long_first and n == 1 and not fixing) else text,
                            "dialogue": "Toto the Parrot: Squawk!" if n % 4 == 0 else ""})
            return json.dumps(out)
        if "You are the Storyboard Artist" in prompt:
            if self.fail_storyboard:
                raise RuntimeError("Gemini free-tier limit reached")
            out = []
            for n in re.findall(r"^(\d+)\. \(", prompt, re.M):
                n = int(n)
                out.append({"number": n, "title": f"Number {n}", "characters": ["Baby Amani"] + (["Toto the Parrot"] if n % 4 == 0 else []),
                            "location": "Playroom" if n < 20 else "Garden", "action": f"Amani holds up {n % 20 or 20} wooden blocks and claps",
                            "expression": "big smile", "shot": ["close_up", "medium", "wide"][n % 3],
                            "movement": ["dolly_in", "pan_left", "crane", "static"][n % 4], "lighting": "warm", "transition": "fade",
                            "sound_effects": "giggle", "music_cue": "bouncy"})
            return json.dumps(out)
        raise AssertionError("unexpected prompt: " + prompt[:200])


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def writer(monkeypatch):
    w = FakeWriter()
    monkeypatch.setattr(llm, "pick_llm", lambda: w)
    return w


def _user(client):
    r = client.post("/api/auth/register", json={"email": f"{uuid.uuid4().hex[:8]}@test.io", "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _photo(client, h) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 150, 100)).save(buf, "PNG")
    r = client.post("/api/media", headers=h, files={"file": ("baby.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _wait(client, h, plan_id, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        d = client.get(f"/api/director/plans/{plan_id}", headers=h).json()
        if d["status"] in ("ready", "failed"):
            return d
        time.sleep(0.2)
    raise AssertionError(f"plan stuck: {d['status']} {d['stage']}")


def test_timing_adds_up():
    for target in timing.LENGTH_PRESETS:
        n = timing.scene_count(target, 10)
        d = timing.scene_durations(target, n)
        assert round(sum(d), 1) == target and len(d) == n
        counts = timing.split_scenes(n, [2, 1, 1, 0.5])
        assert sum(counts) == n and (min(counts) >= 1 or n < 4)
    scenes = [{"duration": x} for x in (3, 7, 12.5, 30)]
    timing.rebalance(scenes, 360)
    assert timing.total(scenes) == 360


def test_director_needs_a_connected_ai_writer(client, monkeypatch):
    monkeypatch.setattr(llm, "pick_llm", lambda: None)
    h = _user(client)
    r = client.post("/api/director/plans", headers=h, json={"idea": "A video about rain"})
    assert r.status_code == 503 and "GEMINI_API_KEY" in r.json()["detail"]
    assert client.get("/api/brain/status").json()["writer"]["available"] is False


def test_six_minute_baby_numbers_plan(client, writer):
    """The acceptance example, up to the point where generation would start."""
    h = _user(client)
    ref = _photo(client, h)
    r = client.post("/api/director/plans", headers=h, json={
        "idea": "Create a six-minute 3D educational video featuring my baby teaching children numbers from 1 to 20.",
        "target_seconds": 360, "language": "en", "main_character": "Amani, my one-year-old daughter",
        "reference_asset_ids": [ref],
    })
    assert r.status_code == 200, r.text
    d = _wait(client, h, r.json()["id"])
    assert d["status"] == "ready", d["error"]
    plan = d["plan"]

    # 1-6: understood, script, storyboard, prompts, references, durations
    assert plan["brief"]["title"] == "Counting with Baby Amani" and plan["brief"]["style"] == "animation"
    assert len(plan["scenes"]) == 36
    assert timing.total(plan["scenes"]) == 360
    assert round(sum(c["seconds"] for c in plan["chapters"]), 1) == 360
    assert all(s["narration"] and s["action"] for s in plan["scenes"])
    spoken = " ".join(s["narration"] for s in plan["scenes"])
    assert all(w in spoken for w in NUMBER_WORDS)
    amani = next(c for c in plan["characters"] if c["name"] == "Baby Amani")
    assert amani["reference_asset_ids"] == [ref]
    for s in plan["scenes"]:
        assert s["image_prompt"] != s["video_prompt"]  # a different prompt for each kind of generator
        assert "yellow dungarees with a star" in s["image_prompt"]  # locked look copied into every prompt
        assert s["camera"] in {"zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "static"}
    assert plan["scenes"][1]["video_prompt"].startswith("Crane shot")
    # 7-9: audio, recommended route, estimate
    assert plan["audio"]["music_mood"] == "upbeat" and plan["audio"]["narration_style"] == "children"
    assert plan["recommendation"]["route"] == "titlecard"  # no AI picture source is on in tests; it says so
    assert any("copy a face" in x for x in plan["recommendation"]["reasons"])
    assert plan["estimate"]["cost_usd"] == 0 and plan["estimate"]["scenes"] == 36
    # Real activity only: one row per step that ran, with the AI calls it made.
    acts = d["activity"]
    agents_seen = {a["agent"] for a in acts}
    assert {"Film Director", "Scriptwriter", "Storyboard Artist", "Character Director", "Prompt Engineer",
            "Audio Director", "Video Editor", "Video Generation Specialist", "Continuity Checker"} <= agents_seen
    assert all(a["status"] == "done" for a in acts)
    assert sum(a["llm_calls"] for a in acts) == len(writer.prompts) == d["llm_calls"]
    assert all(a["llm_calls"] == 0 for a in acts if a["provider"].startswith("rules"))


def test_continuity_check_sends_long_narration_back_once(client, monkeypatch):
    w = FakeWriter(long_first=True)
    monkeypatch.setattr(llm, "pick_llm", lambda: w)
    h = _user(client)
    r = client.post("/api/director/plans", headers=h, json={"idea": "Count to three", "target_seconds": 30})
    d = _wait(client, h, r.json()["id"])
    revisions = [a for a in d["activity"] if a["action"].startswith("Revision")]
    assert len(revisions) == agents.MAX_REVISIONS == 1
    assert "1" in revisions[0]["action"]
    assert len(d["plan"]["scenes"][0]["narration"].split()) < 40


def test_failed_agent_is_reported_and_can_be_filled_later(client, monkeypatch):
    w = FakeWriter(fail_storyboard=True)
    monkeypatch.setattr(llm, "pick_llm", lambda: w)
    h = _user(client)
    r = client.post("/api/director/plans", headers=h, json={"idea": "Count to three", "target_seconds": 30})
    d = _wait(client, h, r.json()["id"])
    assert d["status"] == "ready"
    failed = [a for a in d["activity"] if a["status"] == "failed"]
    assert failed and "limit" in failed[0]["detail"]
    assert any("Nothing described on screen" in c["text"] for c in d["plan"]["checks"])
    # nothing was invented for the scenes the storyboard artist could not design
    assert all(s["action"] == "" for s in d["plan"]["scenes"])

    w.fail_storyboard = False
    assert client.post(f"/api/director/plans/{d['id']}/fill", headers=h).status_code == 200
    d2 = _wait(client, h, d["id"])
    assert all(s["action"] for s in d2["plan"]["scenes"])
    assert not any("Nothing described" in c["text"] for c in d2["plan"]["checks"])
    assert d2["llm_calls"] > d["llm_calls"]


def test_edit_plan_approve_render_and_memory(client, writer):
    h = _user(client)
    r = client.post("/api/director/plans", headers=h, json={"idea": "Baby counts to three", "target_seconds": 30, "resolution": 480})
    d = _wait(client, h, r.json()["id"])
    plan = d["plan"]
    assert len(plan["scenes"]) == 3

    # edit: change outfit, lengthen a scene, then fit back to the requested length
    chars = plan["characters"]
    chars[0]["clothing"] = "a red raincoat"
    scenes = plan["scenes"]
    scenes[0]["duration"] = 20
    r = client.patch(f"/api/director/plans/{d['id']}", headers=h, json={"characters": chars, "scenes": scenes})
    assert r.status_code == 200, r.text
    p2 = r.json()["plan"]
    assert timing.total(p2["scenes"]) == 40
    assert any("add up to" in c["text"] for c in p2["checks"])
    assert "a red raincoat" in p2["scenes"][0]["image_prompt"]
    p3 = client.patch(f"/api/director/plans/{d['id']}", headers=h, json={"fit_to_length": True}).json()["plan"]
    assert timing.total(p3["scenes"]) == 30 and not any("add up to" in c["text"] for c in p3["checks"])

    # approve: becomes a normal project, storyboard ready, nothing rendered yet
    r = client.post(f"/api/director/plans/{d['id']}/approve", headers=h)
    assert r.status_code == 200, r.text
    pid = r.json()["project_id"]
    assert client.post(f"/api/director/plans/{d['id']}/approve", headers=h).status_code == 409
    proj = client.get(f"/api/projects/{pid}", headers=h).json()
    assert proj["status"] == "storyboard_ready" and len(proj["scenes"]) == 3
    assert proj["scenes"][0]["prompt"] == p3["scenes"][0]["image_prompt"]
    assert "AI Director" in proj["notes"][0]

    mem = client.get(f"/api/projects/{pid}/memory", headers=h).json()
    kinds = {m["kind"] for m in mem["items"]}
    assert {"character", "location", "style"} <= kinds and mem["plan_id"] == d["id"]
    amani = next(m for m in mem["items"] if m["name"] == "Baby Amani")

    # render the approved plan to a real MP4 through the existing pipeline
    assert client.post(f"/api/projects/{pid}/render", headers=h, json={"approve_all": True}).status_code == 200
    t0 = time.time()
    while time.time() - t0 < 180:
        proj = client.get(f"/api/projects/{pid}", headers=h).json()
        if proj["status"] in ("done", "failed"):
            break
        time.sleep(0.5)
    assert proj["status"] == "done", proj["error"]
    assert 28 <= proj["output_seconds"] <= 40

    # a locked character's new outfit reaches every scene that shows them, and they re-render
    r = client.patch(f"/api/memory/{amani['id']}", headers=h, json={"clothing": "green pyjamas"})
    assert r.status_code == 200 and r.json()["scenes_updated"] == 3
    proj = client.get(f"/api/projects/{pid}", headers=h).json()
    assert all("green pyjamas" in s["prompt"] and s["status"] == "draft" for s in proj["scenes"])

    # other users cannot see the plan or the memory
    other = _user(client)
    assert client.get(f"/api/director/plans/{d['id']}", headers=other).status_code == 404
    assert client.get(f"/api/projects/{pid}/memory", headers=other).status_code == 404
    assert client.patch(f"/api/memory/{amani['id']}", headers=other, json={"locked": False}).status_code == 404


def test_dropped_connection_is_retried_then_explained(monkeypatch):
    import httpx

    from app.providers import llm as pl

    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise httpx.ConnectError("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol")

    monkeypatch.setattr(pl.httpx, "post", boom)
    monkeypatch.setattr(pl.time, "sleep", lambda s: None)
    with pytest.raises(pl.NetworkError) as e:
        pl.post_json("Google Gemini", "https://example.invalid", json={})
    assert len(calls) == 3
    assert "not a problem with your key" in str(e.value)

    ok = httpx.Response(200, json={"ok": True})
    seq = iter([httpx.ReadError("cut off"), ok])

    def flaky(*a, **k):
        x = next(seq)
        if isinstance(x, Exception):
            raise x
        return x

    monkeypatch.setattr(pl.httpx, "post", flaky)
    assert pl.post_json("Google Gemini", "https://example.invalid").status_code == 200


def test_brain_switches_to_another_writer_when_one_cannot_be_reached(monkeypatch):
    from app.providers.llm import NetworkError

    class Down(FakeWriter):
        name, label = "down", "Unreachable writer"

        def complete(self, prompt):
            raise NetworkError("Could not connect")

    backup = FakeWriter()
    monkeypatch.setattr(llm, "available_llms", lambda: [Down(), backup])
    monkeypatch.setattr(llm, "pick_llm", lambda: llm.available_llms()[0])
    b = llm.Brain()
    # pick_llm builds a fresh Down each call above, so give Brain the list explicitly
    b.writer, b.backups = Down(), [backup]
    plan = {"settings": {"idea": "count to three", "target_seconds": 30, "scene_seconds": 10, "language": "en",
                         "style": "auto", "aspect": "16:9", "voice": "female", "main_character": "", "reference_asset_ids": []}}
    agents.director(b, plan)
    assert b.writer is backup and b.switched and plan["brief"]["title"]


def _mock_stream(monkeypatch, handler):
    """Route the Gemini writer's httpx.stream calls to a handler, like a real server would answer."""
    import contextlib

    import httpx

    from app.providers import llm as pl

    @contextlib.contextmanager
    def stream(method, url, **kw):
        kw.pop("timeout", None)
        with httpx.Client(transport=httpx.MockTransport(handler)) as c:
            with c.stream(method, url, **kw) as r:
                yield r

    monkeypatch.setattr(pl.httpx, "stream", stream)
    monkeypatch.setattr(pl.time, "sleep", lambda s: None)


def _sse(*texts, thought=None) -> bytes:
    import json

    out = []
    if thought:
        out.append({"candidates": [{"content": {"parts": [{"text": thought, "thought": True}]}}]})
    out += [{"candidates": [{"content": {"parts": [{"text": t}]}}]} for t in texts]
    return "".join(f"data: {json.dumps(c)}\r\n\r\n" for c in out).encode()


def test_gemini_follows_a_retired_model_to_its_replacement(monkeypatch):
    import httpx

    from app.providers import llm as pl

    urls = []

    def handler(req):
        urls.append(str(req.url))
        assert ":streamGenerateContent" in str(req.url) and req.headers["x-goog-api-key"]
        if "old-flash" in str(req.url):
            return httpx.Response(404, text='{"error":{"code":404,"message":"This model models/old-flash is no longer '
                                            'available to new users. Please update your code to use models/new-flash for the latest"}}')
        return httpx.Response(200, content=_sse('[{"a"', ': 1}]', thought="thinking..."))

    _mock_stream(monkeypatch, handler)
    monkeypatch.setattr(pl.settings, "gemini_model", "old-flash")
    monkeypatch.setattr(pl.settings, "gemini_api_key", "test-key")
    w = pl.GeminiWriter()
    assert w.complete("hi") == '[{"a": 1}]'  # pieces joined, the model's thoughts left out
    assert "old-flash" in urls[0] and "new-flash" in urls[1]
    w.complete("again")
    assert "new-flash" in urls[2]  # remembered, no second 404


def test_gemini_survives_a_dropped_connection(monkeypatch):
    import httpx

    from app.providers import llm as pl

    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) < 3:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        return httpx.Response(200, content=_sse("[]"))

    _mock_stream(monkeypatch, handler)
    monkeypatch.setattr(pl.settings, "gemini_api_key", "test-key")
    assert pl.GeminiWriter().complete("hi") == "[]" and len(calls) == 3

    calls.clear()

    def always_down(req):
        calls.append(1)
        raise httpx.RemoteProtocolError("Server disconnected without sending a response.")

    _mock_stream(monkeypatch, always_down)
    with pytest.raises(pl.NetworkError) as e:
        pl.GeminiWriter().complete("hi")
    assert len(calls) == pl.GeminiWriter.NET_ATTEMPTS and "not a problem with your key" in str(e.value)
