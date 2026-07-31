# Christian Story Video Agent

Generates a scene-by-scene spiritual transformation video from a Baserow row
that already has a finished script + narration (`script_status=done`,
`voice_status=done`), then pushes the finished video url to ClickUp.

This pipeline never writes scripts and never writes back to Baserow.

## How to run

Two ways to trigger the same pipeline (`src/run.py`):

### 1. Direct, foreground (one row, terminal)

```
python3 src/run.py <row_id>
```

### 2. HTTP, via n8n

`src/ingest_server.py` exposes `POST /ingest` with JSON body `{"row_id": ...}`.
n8n owns row selection and fires this when a row is ready. Requests queue
FIFO — one job runs at a time, nothing gets dropped under load.

Start the server:

```
python3 src/ingest_server.py
```

Ingest only **prepares** now (`prepare_pipeline()`): Baserow read -> scene
breakdown -> multi-lane images -> gallery, then it stops and writes a `ready`
job row to Supabase for human review — it no longer renders automatically.
Render (`render_pipeline()`: narration download -> Whisper+DTW align ->
Remotion Lambda render -> upload to S3 -> push video url to ClickUp) is a
separate manual step, fired from the production review UI (`web/`, see
below) once scenes have been reviewed/edited. `python3 src/run.py <row_id>`
on its own still chains prepare+render unattended, for back-compat.

Each row's artifacts land in `runs/<row_id>/`. If a run fails partway, rerun
the same command — completed stages are skipped, so it resumes where it
broke instead of redoing work.

## Production review UI

`web/` is a separate Next.js app (own `package.json`) for reviewing a
prepared job before render: per-scene prompt edit + regenerate, generate a
video from a scene's image, attach a Pexels image/video, then Render when
ready. It talks to `src/ingest_server.py`'s API (never directly to
OpenAI/Supabase/Pexels/video-gen) through one server-side proxy route, so the
shared secret never reaches the browser.

**Live**: https://the-bible-well-production-ui-production.up.railway.app

For local dev instead (rarely needed — everything above runs live):

```
cd web && npm run dev      # UI, localhost:3000
python3 src/ingest_server.py   # API it talks to, localhost:8080
```

`web/.env.local` needs `PIPELINE_API_URL` (the ingest_server address) and
`INGEST_SECRET` (shared with the Python side) — see the deployed service's
own vars under Railway deployment below for the live equivalents.

## Where things end up

- **Video**: uploaded to S3 (`yt-heritage-media` bucket), raw public url,
  7-day lifecycle — pull it promptly.
- **ClickUp**: the row's `clickup_url` task gets `🎬 VIDEO: <s3 url>`
  prepended to its description (or a comment, if the description update
  fails).

## Credentials

All in repo-root `.env` (Baserow, OpenAI, AWS/S3, ClickUp, Whisper service).
See `CLAUDE.md` for the full list and field-by-field details.

## More detail

`CLAUDE.md` has the full stage-by-stage SOP, Baserow field contract, S3/
ClickUp specifics, and the multi-lane image routing rules.

## Video-gen API

Scenes are still images (gpt-image-2) by default, assembled into a slideshow
by Remotion. The production UI can optionally turn one scene's image into a
short video clip (`src/video_gen.py`), which then renders in place of the
still for that scene. In-house image-to-video service (async submit->poll,
`VIDEO_GEN_URL`/`VIDEO_GEN_TOKEN` in `.env`):

- API: https://avoajaugochukwu--open-source-video-gen-web.modal.run
- Docs (Swagger): https://avoajaugochukwu--open-source-video-gen-web.modal.run/docs

## Railway deployment

Both pieces run live in the **ui-helpers** Railway project, both deploying
from `main` on `avoajaugochukwu/the-bible-well-video-agent`:

- **`src/ingest_server.py`** (the API): service **the-bible-well-video-agent**
  (id `b169301e-10ed-42aa-ac16-2ea1c091f8e6`) — not the empty
  `the bible well video agent` (with spaces) service in the same project,
  that one is an unused stub. Root directory: repo root.
  URL: https://the-bible-well-video-agent-production.up.railway.app
- **`web/`** (the UI): service **the-bible-well-production-ui**
  (id `9dc016b6-b178-49e9-b330-a6ef610d766f`). Root directory: `/web`
  (isolated monorepo app, same repo). Its `PIPELINE_API_URL` points at the
  API service above; `INGEST_SECRET` matches the API service's value.
  URL: https://the-bible-well-production-ui-production.up.railway.app

All credentials this repo's `.env` needs are set as Railway variables on the
API service, including the production-UI additions (`SUPABASE_URL`,
`SUPABASE_SECRET_KEY`, `SUPABASE_DB_URL`, `VIDEO_GEN_URL`, `VIDEO_GEN_TOKEN`,
`PEXELS_API_KEY`) — set 2026-07-31.
