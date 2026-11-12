import json
import subprocess
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _user(client):
    r = client.post("/api/auth/register", json={"email": f"{uuid.uuid4().hex[:8]}@test.io", "password": "password123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _wait(client, h, pid, states, timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        p = client.get(f"/api/projects/{pid}", headers=h).json()
        if p["status"] in states:
            return p
        time.sleep(0.5)
    raise AssertionError(f"timed out, last status {p['status']}: {p.get('error')}")


def test_auth_required(client):
    assert client.get("/api/projects").status_code == 401
    assert client.post("/api/auth/login", json={"email": "nobody@x.io", "password": "wrongpass1"}).status_code == 401


def test_script_to_mp4(client):
    h = _user(client)
    r = client.post("/api/projects", headers=h, json={
        "title": "Hand washing", "mode": "script", "style": "educational", "resolution": 480, "scene_seconds": 4,
        "script": "Wash your hands with soap for twenty seconds. Rinse them under clean running water. Dry them with a clean towel.",
        "music": "calm", "burn_subtitles": True,
    })
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    p = _wait(client, h, pid, {"storyboard_ready"})
    assert len(p["scenes"]) == 3
    assert all(s["voiceover"] for s in p["scenes"])

    # rendering requires approval
    assert client.post(f"/api/projects/{pid}/render", headers=h, json={}).status_code == 422
    assert client.post(f"/api/projects/{pid}/render", headers=h, json={"approve_all": True}).status_code == 200
    p = _wait(client, h, pid, {"done", "failed"})
    assert p["status"] == "done", p["error"]
    assert p["has_video"] and p["output_seconds"] > 5

    video = client.get(f"/api/projects/{pid}/download/video", headers=h)
    assert video.status_code == 200 and len(video.content) > 10_000
    srt = client.get(f"/api/projects/{pid}/download/srt", headers=h).text
    assert "Wash your hands" in srt and "-->" in srt
    audio = client.get(f"/api/projects/{pid}/download/audio", headers=h)
    assert audio.status_code == 200

    # the export is a real H.264/AAC MP4
    from app.models import Project
    from app.db import SessionLocal
    path = SessionLocal().get(Project, pid).output_path
    streams = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", path], capture_output=True, text=True).stdout)["streams"]
    assert {s["codec_name"] for s in streams} == {"h264", "aac"}
    v = next(s for s in streams if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (854, 480)

    # projects are private
    other = _user(client)
    assert client.get(f"/api/projects/{pid}", headers=other).status_code == 404
    assert client.get(f"/api/projects/{pid}/download/video", headers=other).status_code == 404

    # editing one scene re-renders only that scene
    s0 = p["scenes"][0]
    client.patch(f"/api/scenes/{s0['id']}", headers=h, json={"camera": "pan_left", "voiceover": "Always wash your hands."})
    p = client.get(f"/api/projects/{pid}", headers=h).json()
    assert [s["status"] for s in p["scenes"]] == ["draft", "done", "done"]
    r = client.post(f"/api/projects/{pid}/render", headers=h, json={"approve_all": True})
    assert r.json()["queued_scenes"] == 1
    p = _wait(client, h, pid, {"done", "failed"})
    assert p["status"] == "done"


def test_storyboard_edit_ops(client):
    h = _user(client)
    pid = client.post("/api/projects", headers=h, json={
        "title": "Ops", "mode": "text", "prompt": "One. Two three four. Five six.", "target_seconds": 30, "scene_seconds": 10,
    }).json()["id"]
    p = _wait(client, h, pid, {"storyboard_ready"})
    assert len(p["scenes"]) == 3
    ids = [s["id"] for s in p["scenes"]]
    p = client.post(f"/api/scenes/{ids[0]}/split", headers=h, json={}).json()
    assert len(p["scenes"]) == 4
    p = client.post(f"/api/scenes/{ids[0]}/merge-next", headers=h).json()
    assert len(p["scenes"]) == 3
    rev = [s["id"] for s in p["scenes"]][::-1]
    p = client.post(f"/api/projects/{pid}/reorder", headers=h, json={"scene_ids": rev}).json()
    assert [s["id"] for s in p["scenes"]] == rev
    dup = client.post(f"/api/projects/{pid}/duplicate", headers=h).json()
    assert len(dup["scenes"]) == 3 and dup["id"] != pid
    assert client.delete(f"/api/projects/{dup['id']}", headers=h).json()["ok"]


def test_moderation_blocks(client):
    h = _user(client)
    r = client.post("/api/projects", headers=h, json={"title": "x", "mode": "text", "prompt": "explicit sexual video of a child"})
    assert r.status_code == 422


def test_project_length_limit(client):
    h = _user(client)
    r = client.post("/api/projects", headers=h, json={"title": "x", "mode": "text", "prompt": "a", "target_seconds": 4000})
    assert r.status_code == 422


def test_upload_validation(client):
    h = _user(client)
    r = client.post("/api/media", headers=h, files={"file": ("fake.png", b"not an image", "image/png")})
    assert r.status_code == 422
    r = client.post("/api/media", headers=h, files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 415


def test_inline_comment_values_count_as_unset(monkeypatch):
    from app import config

    monkeypatch.setenv("HF_TOKEN", "# free Hugging Face token")
    monkeypatch.setenv("COMFYUI_URL", "   ")
    assert config._opt("HF_TOKEN") is None
    assert config._opt("COMFYUI_URL") is None
    monkeypatch.setenv("HF_TOKEN", "hf_abc")
    assert config._opt("HF_TOKEN") == "hf_abc"
