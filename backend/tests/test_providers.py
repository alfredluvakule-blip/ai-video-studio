"""Provider behaviour with the network mocked: AI pictures, the Gemini writer and the
natural-voice fallback. No real requests are made."""
import io
import json

import httpx
import pytest
from PIL import Image

from app.config import settings
from app.providers import llm, tts, visual


def _png(w=640, h=360) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (30, 120, 200)).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def pollinations(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "pollinations_enabled", True)
    monkeypatch.setattr(settings, "pollinations_interval", 0)
    monkeypatch.setattr(visual.time, "sleep", lambda s: None)
    p = visual.PROVIDERS["pollinations"]
    p._state_path().unlink(missing_ok=True)
    yield p
    p._state_path().unlink(missing_ok=True)


def test_pollinations_writes_picture(pollinations, monkeypatch, tmp_path):
    seen = {}

    def fake_get(url, params=None, **kw):
        seen["url"], seen["params"] = url, params
        return httpx.Response(200, content=_png(), headers={"content-type": "image/jpeg"})

    monkeypatch.setattr(visual.httpx, "get", fake_get)
    assert visual.pick_image_provider().name == "pollinations"
    out = pollinations.image("a lion at dawn, cinematic", "cinematic", 1600, 900, tmp_path / "s.png", seed=42)
    assert Image.open(out).size == (640, 360)
    assert seen["url"].startswith("https://image.pollinations.ai/prompt/a%20lion%20at%20dawn")
    assert seen["params"]["seed"] == 42 and seen["params"]["nologo"] == "true"
    assert max(seen["params"]["width"], seen["params"]["height"]) <= 1280  # request size is capped


def test_pollinations_pauses_after_repeated_failures(pollinations, monkeypatch, tmp_path):
    calls = []

    def failing_get(url, params=None, **kw):
        calls.append(url)
        return httpx.Response(503, text="busy")

    monkeypatch.setattr(visual.httpx, "get", failing_get)
    for _ in range(pollinations.PAUSE_AFTER_FAILURES):
        with pytest.raises(visual.VisualError):
            pollinations.image("x", "cinematic", 640, 360, tmp_path / "s.png")
    assert len(calls) == pollinations.PAUSE_AFTER_FAILURES * pollinations.ATTEMPTS
    assert pollinations.paused_for() > 0
    with pytest.raises(visual.VisualError, match="paused"):  # no more requests while paused
        pollinations.image("x", "cinematic", 640, 360, tmp_path / "s.png")
    assert len(calls) == pollinations.PAUSE_AFTER_FAILURES * pollinations.ATTEMPTS


def test_fallback_chain_ends_with_titlecard(pollinations):
    chain = [p.name for p in visual.fallback_chain("auto")]
    assert chain[0] == "pollinations" and chain[-1] == "titlecard"
    assert [p.name for p in visual.fallback_chain("titlecard")] == ["titlecard"]


def test_gemini_writer(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_provider", "auto")
    scenes_json = json.dumps([
        {"title": "Clouds", "visual_description": "clouds forming", "camera": "pan_left", "voiceover": "Water rises.",
         "prompt": "towering clouds over a lake"},
        {"title": "Rain", "visual_description": "rain falling", "camera": "zoom_in", "voiceover": "Then it falls.",
         "prompt": "heavy rain on a village"},
    ])
    sent = {}

    def fake_post(url, headers=None, json=None, **kw):
        sent["url"], sent["headers"], sent["body"] = url, headers, json
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": scenes_json}]}}]})

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    assert llm.pick_writer().name == "gemini"
    req = llm.StoryboardRequest(mode="text", prompt="how rain forms", script="", style="educational",
                                target_seconds=20, scene_seconds=10, language="en", narration_style="neutral")
    scenes, _ = llm.WRITERS["gemini"].storyboard(req)
    assert [s["voiceover"] for s in scenes] == ["Water rises.", "Then it falls."]
    assert scenes[0]["camera"] == "pan_left" and scenes[0]["prompt"].startswith("towering clouds")
    assert sent["headers"]["x-goog-api-key"] == "test-key" and "gemini" in sent["url"]

    # with the user's own script, the words stay exactly as written; only the visuals come from the AI
    req.mode, req.script = "script", "Water rises from the sea. Then it falls as rain on the hills."
    req.scene_seconds = 3
    scenes, notes = llm.WRITERS["gemini"].storyboard(req)
    assert " ".join(s["voiceover"] for s in scenes) == req.script
    assert scenes[0]["prompt"].startswith("towering clouds")


def test_gemini_rate_limit_message(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: httpx.Response(429, json={"error": {"details": [{"retryDelay": "3s"}]}}))
    with pytest.raises(llm.WriterError, match="free-tier limit"):
        llm.WRITERS["gemini"].complete("hi")


def test_voice_falls_back_when_natural_voice_cannot_download(monkeypatch, tmp_path):
    piper = tts.ENGINES[0]
    monkeypatch.setattr(settings, "piper_auto_download", True)
    monkeypatch.setattr(settings, "piper_voices_dir", tmp_path / "voices")
    monkeypatch.setattr(type(piper), "available", lambda self: True)
    monkeypatch.setattr(tts, "_failed_downloads", {})
    monkeypatch.setattr(tts, "_offline_until", 0.0)

    def offline(*a, **k):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(tts.httpx, "stream", offline)
    path, engine = tts.synthesize("Hello there.", "en", "female", "neutral", tmp_path / "n.wav")
    assert engine in ("espeak-ng", "flite") and path.exists()
    assert tts._offline_until > 0  # later scenes skip straight to the fallback
    assert not list((tmp_path / "voices").glob("*.part"))


def test_voice_override_and_credit_notes(monkeypatch):
    monkeypatch.setenv("PIPER_VOICE_EN_MALE", "en_US-ryan-high")
    assert tts.wanted_voices("en", "male")[0] == "en_US-ryan-high"
    assert tts.wanted_voices("en", "female")[0] == "en_US-ljspeech-high"

    from types import SimpleNamespace

    from app.tasks import _with_voice_notes

    scenes = [SimpleNamespace(provider_used="pollinations + voice:piper (es_ES-davefx-medium)"),
              SimpleNamespace(provider_used="pollinations + voice:piper (sw_CD-lanfrica-medium)")]
    notes = _with_voice_notes(["Storyboard written by: x"], scenes, "female")
    assert notes[0] == "Storyboard written by: x"
    assert any("es_ES-davefx-medium (male; no female natural voice" in n for n in notes)
    assert any("non-profit, educational" in n for n in notes)


def test_render_uses_ai_pictures_and_labels_fallbacks(pollinations, monkeypatch):
    import threading
    import uuid

    from fastapi.testclient import TestClient

    from app.main import app

    # the pollinations fixture turns time.sleep into a no-op, so wait with an Event instead
    pause = threading.Event().wait
    calls = {"n": 0}

    def flaky_get(url, params=None, **kw):  # first scene gets a picture, the second does not
        calls["n"] += 1
        if "second" in url:
            return httpx.Response(400, text="rejected")
        return httpx.Response(200, content=_png(1280, 720))

    monkeypatch.setattr(visual.httpx, "get", flaky_get)
    with TestClient(app) as c:
        r = c.post("/api/auth/register", json={"email": f"{uuid.uuid4().hex[:8]}@test.io", "password": "password123"})
        h = {"Authorization": f"Bearer {r.json()['token']}"}
        assert any(v["name"] == "pollinations" for v in c.get("/api/meta").json()["visual_providers"])
        pid = c.post("/api/projects", headers=h, json={
            "title": "Pics", "mode": "script", "resolution": 480, "scene_seconds": 3, "music": "none",
            "script": "The first scene shows a lake. The second scene shows a forest.",
        }).json()["id"]
        for _ in range(120):
            p = c.get(f"/api/projects/{pid}", headers=h).json()
            if p["status"] == "storyboard_ready":
                break
            pause(0.25)
        # make the second scene's picture prompt identifiable for the fake service
        s2 = p["scenes"][1]
        c.patch(f"/api/scenes/{s2['id']}", headers=h, json={"prompt": "second scene forest"})
        assert c.post(f"/api/projects/{pid}/render", headers=h, json={"approve_all": True}).status_code == 200
        for _ in range(240):
            p = c.get(f"/api/projects/{pid}", headers=h).json()
            if p["status"] in ("done", "failed"):
                break
            pause(0.25)
        assert p["status"] == "done", p["error"]
        used = [s["provider_used"] for s in p["scenes"]]
        assert used[0].startswith("pollinations")
        assert used[1].startswith("titlecard (fallback: pollinations failed)")


def test_subtitle_lines_keep_short_endings_without_crashing():
    from app.pipeline.render import _chunks

    assert _chunks("one two three four five six seven eight nine ten") == ["one two three four five six seven eight nine ten"]
    words = [f"w{i}" for i in range(18)]
    assert _chunks(" ".join(words)) == [" ".join(words[:8]), " ".join(words[8:])]
