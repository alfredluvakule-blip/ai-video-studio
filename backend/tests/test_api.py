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


def test_scene_uses_uploaded_photo_and_video(client, tmp_path):
    """A photo or video uploaded on a storyboard scene is used in the final video,
    and an uploaded video keeps its own sound."""
    h = _user(client)
    r = client.post("/api/projects", headers=h, json={
        "title": "My own footage", "mode": "script", "resolution": 480, "scene_seconds": 3,
        "script": "This is my village at sunrise. Here children walk to school.",
    })
    pid = r.json()["id"]
    p = _wait(client, h, pid, {"storyboard_ready"})
    s0, s1 = p["scenes"][:2]

    photo, clip = tmp_path / "village.png", tmp_path / "school.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=green:s=320x240", "-frames:v", "1", str(photo)], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=320x240:d=2", "-f", "lavfi", "-i",
                    "sine=frequency=440:d=2", "-shortest", "-pix_fmt", "yuv420p", str(clip)], check=True)
    ids = []
    for f, mime in ((photo, "image/png"), (clip, "video/mp4")):
        r = client.post("/api/media", headers=h, data={"project_id": pid}, files={"file": (f.name, f.read_bytes(), mime)})
        assert r.status_code == 200, r.text
        ids.append(r.json()["id"])
    assert client.patch(f"/api/scenes/{s0['id']}", headers=h, json={"image_asset_id": ids[0]}).status_code == 200
    assert client.patch(f"/api/scenes/{s1['id']}", headers=h, json={"image_asset_id": ids[1], "voiceover": ""}).status_code == 200

    client.post(f"/api/projects/{pid}/render", headers=h, json={"approve_all": True})
    p = _wait(client, h, pid, {"done", "failed"})
    assert p["status"] == "done", p["error"]
    by_id = {s["id"]: s for s in p["scenes"]}
    assert by_id[s0["id"]]["provider_used"].startswith("upload:image")
    assert by_id[s1["id"]]["provider_used"].startswith("upload:video")

    # the video scene kept its own sound (a 440 Hz tone), so it is not silent
    from app.models import Scene
    from app.db import SessionLocal
    clip_path = SessionLocal().get(Scene, s1["id"]).clip_path
    vol = subprocess.run(["ffmpeg", "-i", clip_path, "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True).stderr
    mean = float(vol.split("mean_volume:")[1].split("dB")[0])
    assert mean > -40, vol

    # with a voice-over too, the narrator and the video's sound are mixed
    client.patch(f"/api/scenes/{s1['id']}", headers=h, json={"voiceover": "Here children walk to school."})
    client.post(f"/api/projects/{pid}/render", headers=h, json={"approve_all": True})
    p = _wait(client, h, pid, {"done", "failed"})
    assert p["status"] == "done", p["error"]

    # an asset in use cannot be deleted from the library
    assert client.delete(f"/api/media/{ids[1]}", headers=h).status_code == 409


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


def test_invite_code_controls_signup(client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "signup_code", "village-2026")
    assert client.get("/api/meta").json()["limits"]["signup_code_required"] is True
    creds = {"email": "friend@test.io", "password": "password123"}
    assert client.post("/api/auth/register", json=creds).status_code == 403
    assert client.post("/api/auth/register", json={**creds, "invite_code": "wrong"}).status_code == 403
    r = client.post("/api/auth/register", json={**creds, "invite_code": "village-2026"})
    assert r.status_code == 200, r.text
    # signing in never needs the code
    assert client.post("/api/auth/login", json=creds).status_code == 200
