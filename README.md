# AI Video Studio

A free-first, self-hostable studio that turns an idea, a script, or a set of photos into a narrated,
subtitled MP4 of up to **60 minutes**. Scenes are storyboarded, reviewed and approved, rendered in the
background (in parallel, resumable after crashes), and stitched with FFmpeg.

> **Honest status.** Everything listed under *Works today* runs end to end and was tested by producing
> real MP4 files (including a 60-minute, 495-scene project with a worker killed mid-render).
> Items under *Planned* are not built yet and the UI labels them as planned.

## Works today

| Area | What happens |
|---|---|
| Text → Video | Prompt → storyboard (scenes, camera, narration, prompts) → render → MP4 |
| Script → Video | Your script is split into timed scenes; your words are never rewritten |
| Image → Video | Each uploaded photo becomes an animated scene (zoom / pan camera moves) |
| Uploaded clips | A scene can use your own video clip (trimmed, speed-adjusted, looped to fit) |
| Storyboard | Scene #, duration, visual description, camera, characters, dialogue, voice-over, SFX notes, reference media, AI prompt; edit + approve per scene |
| Long form | Up to 60 min / hundreds of scenes; render all, approved only, or selected batches; progress is saved per scene |
| Recovery | Celery `acks_late` + idempotent tasks; a restarted worker re-queues everything unfinished; **Resume** button |
| Failed scenes | Shown with the error; retry/regenerate one scene without touching the rest |
| Narration | Local TTS: Piper (neural, optional), eSpeak NG (100+ languages incl. **Kiswahili**), Flite (English). Male/female voices, 6 narration styles. Upload your own recording per scene |
| Subtitles | Timed SRT from the narration (or Whisper for uploaded recordings, if installed); optional burn-in |
| Music | Original background music synthesised locally (4 moods), or your own licensed track; automatically ducked under the voice |
| Editor | Timeline with video, voice, music and subtitle tracks; drag-and-drop reorder, trim, split, merge, speed (0.25×–4×, slow motion), fade/cut transitions, camera moves, delete, regenerate; only changed scenes re-render |
| Export | H.264/AAC MP4, 480p/720p/1080p, 16:9 / 9:16 / 1:1, 24/25/30 fps, 3 compression levels, separate `.m4a` audio and `.srt` |
| Projects | Save, resume, duplicate, delete, download; private per user |
| Media library | Upload/verify/delete images, video, audio, music; storage quota |
| Free usage | No payments anywhere. Limits (60 min/project, storage quota, daily render minutes on a shared server) are shown in the dashboard; `SELF_HOSTED=true` removes the daily cap |
| Safety | Auth (PBKDF2 passwords, hashed tokens, optional Supabase JWTs), per-user isolation, upload type/size checks, keyword content screen |

## What the AI parts need

The pipeline is modular; each stage picks the best available provider and **tells the user which one it used**.

| Stage | Free/local AI provider | Always-available fallback |
|---|---|---|
| Script & storyboard | Ollama (any local LLM) or Hugging Face Inference (free tier, `HF_TOKEN`) | Rule-based splitter: uses your script/prompt as is and **never invents narration** |
| Scene images | ComfyUI on your GPU (SDXL workflow included) or Hugging Face text-to-image | Title-card renderer (CPU, clearly marked "not AI") |
| Scene motion | Stable Video Diffusion through ComfyUI (workflow included, needs [VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite)) | Ken Burns camera motion with FFmpeg |
| Voice | Piper neural voices | eSpeak NG / Flite |
| Subtitles for recordings | faster-whisper | none (recording still plays) |

Without a GPU, Ollama or an HF token the app still produces real videos: your photos or title cards,
animated with camera moves, narrated by local TTS, with music and subtitles. Generating *new imagery*
from text needs one of the AI providers above. Hugging Face's free tier has rate limits; your own GPU does not.

## Run it

```bash
cp .env.example .env          # optional settings
docker compose up --build     # web on :3000, API on :8000
```

Without Docker (needs Python 3.11+, Node 20+, FFmpeg, espeak-ng, PostgreSQL, Redis):

```bash
cd backend && pip install -r requirements.txt
export DATABASE_URL=postgresql+psycopg2://postgres@localhost/studio
uvicorn app.main:app --port 8000 &
celery -A app.worker worker -Q default,render --concurrency 2 &
cd ../frontend && npm install && npm run dev
```

For quick local hacking, `QUEUE_BACKEND=inline` runs jobs inside the API process and the default
`DATABASE_URL` is SQLite, so Redis and Postgres are optional.

### Turn on the AI providers

* **Ollama** (local LLM): install Ollama, `ollama pull llama3.2`, set `OLLAMA_URL`.
* **Hugging Face** (free tier): create a token at huggingface.co, set `HF_TOKEN`.
* **ComfyUI** (your GPU): run ComfyUI, put `sd_xl_base_1.0.safetensors` and `svd_xt.safetensors` in its models folder,
  set `COMFYUI_URL`, `COMFYUI_IMAGE_WORKFLOW=/workflows/sdxl_image.json` and optionally
  `COMFYUI_VIDEO_WORKFLOW=/workflows/svd_img2vid.json`. Any API-format workflow works if it uses the
  `{{PROMPT}} {{NEGATIVE}} {{WIDTH}} {{HEIGHT}} {{SEED}} {{IMAGE}} {{FRAMES}} {{FPS}}` placeholders.
* **Piper voices**: download `.onnx` + `.onnx.json` voices (e.g. `en_US-amy-medium`, `sw_CD-lanfrica-medium`) into `voices/`.

The ComfyUI and Hugging Face integrations are written against their public APIs but were not exercised
in the build sandbox (no GPU, no outbound access to Hugging Face).

## Measured performance (4 vCPU, no GPU, 480p, 3 worker processes)

* 495-scene, 63-minute project: scenes rendered in ~4.5 min, final assembly (concat + music ducking + audio export) ~3.5 min.
* The dashboard shows estimates based on the render speed measured on your own server.

## Architecture

```
frontend/  Next.js 15 + Tailwind (dashboard, create flows, storyboard, timeline editor, library, settings)
backend/
  app/main.py            FastAPI app
  app/api/               auth, projects, scenes, media, usage, providers
  app/models.py          users, tokens, projects, scenes, assets, jobs, render log (PostgreSQL / SQLite)
  app/tasks.py           storyboard, render_scene, assemble, recover (idempotent)
  app/worker.py          Celery + Redis (acks_late, recovery on start)
  app/pipeline/render.py per-scene render (motion, narration, fades) and FFmpeg concat assembly
  app/pipeline/music.py  original music synthesis
  app/providers/         llm.py, visual.py, tts.py, stt.py — pluggable providers
comfyui/                 example API-format workflows (SDXL still, SVD image-to-video)
```

Each scene is encoded with identical parameters, so the final video is concatenated without re-encoding:
long projects stitch quickly and one failed scene never forces a full re-render.

## Tests

```bash
cd backend && python -m pytest -q   # renders real MP4s with FFmpeg + eSpeak
```

## Planned (not built yet)

* AI sound-effect generation (AudioLDM / Stable Audio Open via ComfyUI) — SFX text is stored per scene today
* Extra overlay tracks (image and text overlays) in the editor
* Supabase Storage backend (Supabase **auth** tokens already work)
* Model-based content moderation (today: keyword screen + upload validation)
* Native mobile app (the web app is responsive)
* Voice cloning; character-consistency tooling beyond shared character descriptions/seeds
