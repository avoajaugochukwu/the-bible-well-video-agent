# CLAUDE.md — src/ (pipeline integrations)

Directory-scoped instructions for `src/` — the Baserow/ClickUp/S3 integration details and
credentials that don't need to live in root `CLAUDE.md`. Root `CLAUDE.md` owns the overall
SOP and pipeline stage list; `agents/CLAUDE.md` owns the character-consistency stack.

## Runtime

CLI usage is direct and one row at a time: `python3 src/run.py <row_id>` in the foreground.
The deployed service (`src/ingest_server.py`) is a persistent HTTP server with two FIFO
worker queues (prepare, render) so a slow render never blocks a new `/ingest` call — see its
`ROUTES` list for what the API can do.

Nothing is written to local disk: there is no `runs/` directory and no stage-artifact cache.
The Supabase job row is the only durable state, so a failed prepare re-runs in full (see root
`CLAUDE.md`'s "State and resume"). Scratch files (the narration mp3, generated PNGs, the
rendered mp4 before upload) go through `tempfile` and are always unlinked.

`src/*.py` files that need `utils/` (env, align, images, tts) add a small
`sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "utils"))`
near the top rather than converting to a proper Python package — this repo has no
`setup.py`/`pyproject.toml` and several `utils/*.py` files have their own
`if __name__ == "__main__":` self-test blocks that must keep working when run directly
(e.g. `python3 src/scene_engine.py`).

## Credentials

- **repo-root `.env`** (this pipeline's only env file, checked by `utils/env.py`'s
  `_ENV_FILES` list):
  - `BASE_ROW_URL`, `BASEROW_EMAIL`, `BASEROW_PASSWORD`, `BASEROW_TABLE_ID` — copied from
    `space-cluster/.env`, same Baserow instance/table (id `2`) and creds.
  - `OPENAI_API_KEY` — for `scene_engine.py`'s scene-breakdown LLM calls (gpt-5-mini).
  - `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` — for `src/s3.py` (see
    AWS/S3 note below).
  - `CLICKUP_API` (ClickUp personal token, `pk_...`, no "Bearer" prefix).
  - `REMOTION_WHISPER_SERVICE_URL` — hosted Modal whisper transcription microservice,
    `scene_engine.py:whisper_words()` POSTs the narration file to `{url}/v1/transcribe`.
    Same service `senior-finance/finance/remotion` calls; no local model/GPU needed.
  - `SUPABASE_URL`, `SUPABASE_SECRET_KEY` — `src/supabase_jobs.py`'s PostgREST calls against
    the `bible_well_jobs` table (same Supabase project `military` uses, this pipeline's own
    table).
  - `VIDEO_GEN_URL`, `VIDEO_GEN_TOKEN` — `src/video_gen.py`'s in-house image-to-video Modal API.
  - `PEXELS_API_KEY` — `utils/pexels.py` search.
  - `PERPLEXITY_API_KEY`, `APIFY_TOKEN`, `TTS_ENDPOINT`, `TTS_VOICE` — pre-existing keys,
    not all currently consumed by this pipeline.
- **AWS/S3 — bucket is ours, creds are this pipeline's own copy.** `src/s3.py`'s `_cfg()`
  reads `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_REGION` via `utils/env.py`, from
  keys that live directly in the root `.env`.

## Baserow

Table id `2` (shared instance, same one `space-cluster` uses). Read-only from this pipeline's
side — `src/baserow.py` has exactly one call, `get_row(row_id)`, no write/PATCH function exists.
Fields consumed:

| field              | type          | meaning                                              |
|--------------------|---------------|-------------------------------------------------------|
| `script`           | text          | the script, verbatim — never edited by this pipeline   |
| `voice_url`        | text          | narration audio url (mp3), narration ONLY, no SFX      |
| `clickup_url`      | text          | ClickUp task to push the finished video url onto       |

- `channel`/`script_status`/`voice_status`/`video_processed` are read by nobody here — this
  pipeline doesn't scan or gate on them, since the caller (n8n) already picked the row_id it
  hands us. Whatever process owns those fields upstream is out of this repo's scope.
- If `run.py`/`get_row(row_id)` is handed a row whose `script` or `voice_url` is actually empty,
  it raises immediately rather than silently no-op'ing — there's no other row to fall back to.

## ClickUp

- List: **"Christian Story"**, id `901113620100`, in "Team Space", workspace "Karl's
  Workspace" — same ClickUp account/token as `space-cluster`.
- `src/clickup.py:push_video(clickup_url, video_url)`: GET task -> prepend
  `"🎬 VIDEO: <url>"` to its description -> PUT task; falls back to POST-ing a comment if the
  description PUT fails. Never raises into the caller — returns `True`/`False` so a ClickUp
  hiccup never blocks the pipeline.
- The task to update comes from the Baserow row's own `clickup_url` field — this pipeline
  never creates a new ClickUp task, only appends to one that already exists.

## S3

- Bucket: **`yt-bible-well-media`** (`src/s3.py:BUCKET`) — us-west-2, public-read policy,
  7-day lifecycle. Created fresh for this pipeline, not shared with any other project's
  bucket. `upload_bytes`/`upload_from_url`/`upload_media`/`put_file`/`first_uploadable` all
  key under the `"bible-well"` prefix.
- **Rule: the finished video always goes to S3 as a RAW public url, never presigned, never a
  local-only file path.** `put_file()` only ever returns a raw public link (the bucket is
  public-read) — that's what gets pushed to ClickUp for review.
- **7-day lifecycle** — once render is built, the pushed video url goes dead after a week;
  pull it promptly or re-render.

## Production-UI API (`src/ingest_server.py`, `src/supabase_jobs.py`, `src/video_gen.py`)

- `supabase_jobs.py` is the one place Python constructs `bible_well_jobs.payload`, matching
  `web/lib/types.ts`'s `Job` shape by hand (camelCase) — no shared schema between the two
  languages, keep them in sync manually.
- Per-scene asset history (`imageHistory`/`videoHistory`) is append-only — regenerate/Pexels
  pick/video-gen/upload never overwrites a prior entry, only adds one and moves the active
  pointer (`activateAsset`), so the UI can always pick an older one back. `upsert_scenes()`
  is the one function that rewrites the whole scene list (prepare_pipeline calls it twice);
  it merges rather than overwrites, so an image a human regenerated while the job was still
  `preparing` survives, as do the `renderUrl`/`clickupPushedAt` gates.
- Payload fields beyond `web/lib/types.ts`'s visible `Job`: `characters` (the locked ledger,
  read back by the regenerate-image route) and `clickupPushedAt` (the push-once gate).
- `video_gen.py` is an async submit/poll client (`POST /generate` -> `job_id`,
  `GET /status/{job_id}` -> `video.url` when done) for an in-house image-to-video Modal API.
