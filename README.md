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
| Narration | Natural-sounding Piper neural voices on the CPU (downloaded once, automatically), with eSpeak NG (100+ languages incl. **Kiswahili**) and Flite as fallbacks. Male/female voices, 6 narration styles. Upload your own recording per scene |
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
| Script & storyboard | Ollama (any local LLM), Google Gemini (free key, `GEMINI_API_KEY`) or Hugging Face Inference (free tier, `HF_TOKEN`) | Rule-based splitter: uses your script/prompt as is and **never invents narration** |
| Scene images | ComfyUI on your GPU (SDXL workflow included), Hugging Face text-to-image, or **Pollinations** (free, no account, on by default) | Title-card renderer (CPU, clearly marked "not AI") |
| Scene motion | Stable Video Diffusion through ComfyUI (workflow included, needs [VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite)) | Ken Burns camera motion with FFmpeg |
| Voice | Piper neural voices (local, downloaded once) | eSpeak NG / Flite |
| Subtitles for recordings | faster-whisper | none (recording still plays) |

On a PC without a GPU and with no keys, a script becomes: one AI picture per scene from Pollinations,
animated with camera moves, narrated by a natural Piper voice, with music and subtitles. These are AI
*pictures* with camera motion, not AI-generated video clips; moving AI video needs a GPU (ComfyUI + SVD)
or a paid video model (planned, with the cost shown first). If Pollinations is down or rate-limits,
scenes fall back to title cards and each scene says which source it used.

Privacy: Piper voices run on your machine. Pollinations and Gemini are online services, so scene picture
descriptions (and, for Gemini, your script) are sent to them. Set `POLLINATIONS=false` and leave
`GEMINI_API_KEY` empty to keep everything local.

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
* **Gemini** (free key): create a key at [Google AI Studio](https://aistudio.google.com/apikey) and set
  `GEMINI_API_KEY`. Gemini then writes storyboards from a short prompt and, for your own script, writes a
  picture description for every scene (your narration stays word for word). Free tier, rate-limited.
* **Pollinations** (free, no account): on by default (`POLLINATIONS=true`); about one picture per 15 seconds.
* **Hugging Face** (free tier): create a token at huggingface.co, set `HF_TOKEN`.
* **ComfyUI** (your GPU): run ComfyUI, put `sd_xl_base_1.0.safetensors` and `svd_xt.safetensors` in its models folder,
  set `COMFYUI_URL`, `COMFYUI_IMAGE_WORKFLOW=/workflows/sdxl_image.json` and optionally
  `COMFYUI_VIDEO_WORKFLOW=/workflows/svd_img2vid.json`. Any API-format workflow works if it uses the
  `{{PROMPT}} {{NEGATIVE}} {{WIDTH}} {{HEIGHT}} {{SEED}} {{IMAGE}} {{FRAMES}} {{FPS}}` placeholders.
* **Piper voices**: downloaded automatically into `voices/` the first time a language is used (60-120 MB each).
  Defaults were picked for permissive licences: English `en_US-ljspeech-high` (female, public domain) and
  `en_US-joe-medium` (male, CC0); Spanish `es_ES-davefx-medium` and Portuguese `pt_BR-faber-medium` (CC0);
  French `fr_FR-siwis-medium` (CC BY 4.0, credit needed); Kiswahili `sw_CD-lanfrica-medium` (dataset allows
  non-profit, educational and public-benefit use); Arabic `ar_JO-kareem-medium` (licence not stated).
  Finished videos list the voice used and any credit it needs. Pick another voice with
  `PIPER_VOICE_<LANG>_<GENDER>`, e.g. `PIPER_VOICE_EN_MALE=en_US-ryan-high` (non-commercial licence).
  To work offline, set `PIPER_AUTO_DOWNLOAD=false` and copy `.onnx` + `.onnx.json` files into `voices/`.

Check everything at once with `docker compose exec worker python -m app.selftest`: it speaks a test
sentence, fetches one AI picture and, with a key, asks the AI writer for a short storyboard.

The ComfyUI, Hugging Face, Pollinations, Gemini and Piper integrations are written against their public
APIs and tested with mocked responses; the build sandbox had no GPU and no access to those services.

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

* Optional paid AI video clips from a text-to-video model, with the price shown and confirmed before rendering
* AI sound-effect generation (AudioLDM / Stable Audio Open via ComfyUI) — SFX text is stored per scene today
* Extra overlay tracks (image and text overlays) in the editor
* Supabase Storage backend (Supabase **auth** tokens already work)
* Model-based content moderation (today: keyword screen + upload validation)
* Native mobile app (the web app is responsive)
* Voice cloning; character-consistency tooling beyond shared character descriptions/seeds
