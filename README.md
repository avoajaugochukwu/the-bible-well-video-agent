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

Once a job is ingested (either path), the whole pipeline runs unattended —
no manual steps in between:

```
Baserow read -> scene breakdown -> multi-lane images -> gallery (review only)
  -> download narration -> Whisper+DTW align -> Remotion Lambda render
  -> upload to S3 -> push video url to ClickUp
```

Each row's artifacts land in `runs/<row_id>/`. If a run fails partway, rerun
the same command — completed stages are skipped, so it resumes where it
broke instead of redoing work.

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

## Video-gen API (not currently used)

This pipeline generates still images (gpt-image-2) assembled into a slideshow
by Remotion — no motion/video model is called anywhere in it today. If that
changes, the in-house video-gen service is:

- API: https://avoajaugochukwu--open-source-video-gen-web.modal.run
- Docs (Swagger): https://avoajaugochukwu--open-source-video-gen-web.modal.run/docs
