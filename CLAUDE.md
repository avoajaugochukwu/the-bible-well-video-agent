# CLAUDE.md — Christian Story Video Agent SOP

The operating SOP, self-contained. Everything an agent needs to run this is in this file.

This repo holds one pipeline — Christian Story — laid out with standard project directory
names (`src/`, `utils/`, `remotion/`, `runs/`) at the repo root. There is no separate
sub-folder for the pipeline and no cross-pipeline `shared/` folder to keep in sync.

## What this project does

Generate a scene-by-scene spiritual transformation video for the Christian Story channel (faith-based,
character-driven narratives focused on personal transformation and God's work in daily life)
from a script that already exists in Baserow. **This pipeline never writes scripts, and never
writes back to Baserow at all** — an outside trigger (n8n) owns row selection and closes its
own side of the job the moment it fires the ingest request; this pipeline only reads the row
it's told to process. Script, narration audio, and sound all come from a Baserow row that's
already been marked `script_status=done` and `voice_status=done` by an upstream writing process
(not this repo). This project's job starts after that: break the script into scenes, figure out
which characters recur and are worth tracking across the video, generate one full-body
reference image per tracked character, generate a spiritual image per scene (gpt-image-2,
full-body digital painting, referencing whichever tracked characters that scene calls for),
assemble/render, then push the finished video url back to ClickUp.

Output per run → one rendered video, one ClickUp task updated with the video url.

## Current status

Full pipeline is wired end-to-end via `src/run.py <row_id>` — row_id is a required arg (or the
`row_id` field of an `/ingest` POST body when triggered over HTTP): each stage writes an
artifact into `runs/<row_id>/` and is skipped on rerun if that artifact already exists, so a
failure mid-run resumes exactly where it broke instead of re-paying for completed stages.
`agents/` (character_ledger, character_sheet, scene_compositor — plain importable Python
packages, no subprocess bridge needed since this whole repo is already Python) is where the
character-consistency work lives, separate from `src/scene_engine.py`'s scene-breakdown LLM
calls. There is **no vision-QA anywhere in this pipeline** — whether a generated image actually
matches its character(s) is a human call made off the gallery review, not an automated gate.

Stage order: Baserow read (given row_id) → context → whole-script production dossier →
character ledger + one full-body
reference image per tracked character (`agents/character_ledger`, `agents/character_sheet`) →
whole-film parallel-story direction (`agents/visual_director`) → verbatim narration timing
blocks mapped evenly across that film → per-scene images (`agents/scene_compositor`, gpt-image-2
i2i against each present character's reference sheet, t2i fallback only when a reference is
missing or the edit call is rejected) → download the row's own narration → Whisper+DTW
alignment against that real audio (duration_seconds per scene, so the production UI shows
how many seconds of clip each scene needs before render) → gallery (non-blocking review) →
[production UI review/edit, manual render trigger] → Remotion
Lambda render (narration muxed in via `<Audio>`) → upload the finished mp4 to S3
(`src/s3.py:put_file()`, RAW public link — **never presigned, always S3, that's what gets
shared for review**) → ClickUp push (`src/clickup.py:push_video()`) → `prune_runs()` cleanup.
Baserow is never written back to — read-only, `src/baserow.py:get_row(row_id)` only.

## Inputs

- **A Baserow row id**, handed in explicitly — by `src/run.py <row_id>` on the CLI, or the
  `row_id` field of a POST to `/ingest` (`src/ingest_server.py`) when triggered by n8n. This
  pipeline never scans Baserow for "the next ready row"; the caller already knows which row it
  means and has already closed its own side of the job by the time the request lands.
- Row fields consumed: `title`, `script`, `voice_url` (narration audio — see note below on
  sound), `clickup_url` (the task to push the finished video url onto).
- **Sound**: `voice_url` is narration ONLY — confirmed against a real row, no separate SFX/
  ambience field exists. Building/tagging a sound library is unscoped future work (Phase 6 in
  `HERITAGE_PLAN.md`), deliberately deprioritized to last.

## Agent development philosophy

`agents/CLAUDE.md` is the operating philosophy and standing rules for everything under
`agents/` (story_dossier, character_ledger, character_sheet, visual_director,
scene_compositor) — read that file before touching any of them. Short version: this is a
chat played out in code, not a deterministic pipeline with an LLM bolted on; the fix for a
bad conversation is a better next message, not a new Python gate.

## Hard rules

- **Never write or edit the script.** If a row's `script` field looks wrong, thin, or
  off-topic, stop and flag it — do not rewrite it here. That's the upstream writer's job.
- **Character-consistency and scene-authoring rules live in `agents/CLAUDE.md`.** Narration
  vs. visual lane separation, bridge cues, locked character profiles, compact final image
  prompts, t2i-only, no vision-QA, anti-Jesus-regression — all standing rules for that
  stack are there now, not duplicated here.
- **Baserow is read-only.** `baserow.py` has no write/PATCH function at all — row_id selection
  and "is this job done" bookkeeping both live on the caller's side (n8n), not here.
- ClickUp push is update-existing-task, never create-task — the task already exists (created
  by the same upstream process that writes the script), we're just appending the video url to
  it, same as `space-cluster/front/clickup.py`'s `push_video()`.

## Pipeline stages

```
1 BASEROW    src/baserow.py: get_row(row_id) reads the one row the caller specified —
             no scanning, no gating on video_processed. Read-only.
2 CONTEXT    scene_engine.py:infer_context() — OpenAI gpt-5-mini, reasoning_effort=low.
             Setting/spiritual_theme/emotional_palette for the script, cached in
             context.json and reused by every later stage.
3 DOSSIER    agents/story_dossier:build(script) reads the whole script before casting. It
             separates quoted source facts from abstract casting signals, generates five
             occupation candidates, selects one, then creates concrete body/ethnicity/hair/
             wardrobe design and a plot-free director profile. The casting generator never
             sees source events; its reviewer sees source facts only to catch contradictions.
4 CHARACTERS agents/character_ledger:build(script, context, story_dossier) reads the whole script
             and decides which characters are worth tracking as a recurring visual
             identity — protagonist always, Jesus only if he actually appears, any other
             character only if they recur across multiple beats. Generate -> deterministic
             validate -> retry-with-feedback loop. Then agents/character_sheet:
             generate_all() makes one full-body reference image per tracked character
             (gpt-image-2 t2i, quality=low). characters.json.
5 DIRECTOR   agents/visual_director:build() — two-pass whole-video design. Pass one sees the
             narration but can emit only categorical emotional signals plus alignment anchors.
             Pass two sees only the categorical score, concrete cast, and plot-free dossier
             handoff; it invents a coherent standalone film with an external goal, credible
             institutions, and one ordered story beat per emotional phase. A source-aware
             semantic reviewer catches literal overlap and repeated administrative staging.
             visual-story.json.
6 SCENES     src/scene_engine.py:cut_narration_scenes() uses an LLM to propose visual-change
             boundaries in sentence-aligned chunks, anchors those boundaries losslessly to
             the verbatim narration, and caps long beats at 30 words using natural punctuation
             where possible. Cuts are evenly distributed across the ordered director beats.
             author_story_beat() runs per beat in parallel and sees only the film plan, never
             narration; it returns chronological image_prompt + character_ids shots.
7 IMAGES     agents/scene_compositor:compose_all() — per scene, IN PARALLEL, gpt-image-2
             images.edit() conditioned on every present character's reference image
             (identity from the image, not restated text). Reference images are fetched
             and shrunk once per character, reused across scenes. Plain t2i is the
             fallback only when a reference is missing or the edit call is rejected. NO
             automated vision-QA anywhere in this pipeline — a human reviews the gallery
             (step 8) and judges consistency.
8 ALIGN      scene_engine.py:align_scene_durations() — real word timestamps from the
             hosted Modal whisper service (REMOTION_WHISPER_SERVICE_URL, same one
             senior-finance/finance/remotion calls) + utils/align.py DTW mapped onto each
             scene's verbatim script_snippet. NOT a word-count estimate (tried and
             explicitly rejected — doesn't actually align). NOT local faster-whisper —
             that package was never installed in this repo's .venv. Runs inside
             prepare_pipeline() (part of stages 1-9, before the gallery/Supabase job
             upsert) — not at render time — so every scene's duration_seconds (how many
             seconds of video/image that scene needs) is already known and shown in the
             production UI before a human ever generates or uploads a clip for it.
             Whisper words are cached (whisper-words.json) and reused unchanged by
             render_pipeline() for the caption payload, never re-transcribed.
9 GALLERY    src/gallery.py: scenes + generated image urls -> one gallery.html (grid,
             click-to-expand modal, vanilla JS/CSS) for manual review. See that file.
10 RENDER    remotion/ (standalone Remotion project) on Remotion Lambda (local
             `remotion render` freezes the machine — banned, always deploy:site + render:
             remote). scenes.json is `{scenes, narrationUrl}` — narrationUrl is the row's
             OWN voice_url (already a public S3 url, no rehost needed) muxed in via a plain
             `<Audio src={narrationUrl}>` in HeritageScenes.tsx. Remotion has no character/
             style awareness at all — it just renders whatever image_url each scene carries.
11 S3        src/s3.py:put_file() uploads the rendered mp4 -> RAW public url (bucket is
             public-read) — ALWAYS push the finished video here for review, never hand back
             a presigned link or a local-only file path.
12 CLICKUP   src/clickup.py: push_video() PUTs "🎬 VIDEO: <s3 url>" onto the row's
             clickup_url task description (falls back to a comment on failure), same
             update-existing-task pattern as space-cluster. Last stage — nothing
             writes back to Baserow after this.
```

Steps 1-11 are wired into one `run.py` command (`src/run.py`, Phase 5 in
`HERITAGE_PLAN.md`) — run it with `python3 src/run.py <row_id>` from the repo root, or trigger
it over HTTP via `POST /ingest` (`src/ingest_server.py`, JSON body `{"row_id": ...}`).

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
  - `PERPLEXITY_API_KEY`, `APIFY_TOKEN`, `TTS_ENDPOINT`, `TTS_VOICE` — pre-existing keys,
    not all currently consumed by this pipeline.
- **Krea image-gen token** (`IMAGE_API_TOKEN`) is read by `src/krea.py:krea_edit_photo()` from
  its own hardcoded path in `sleep-stories/.env.local` — unaffected by this repo's layout,
  don't duplicate it into the root `.env`. Still unused — this pipeline's i2i goes through
  gpt-image-2's own `images.edit()` (`src/gpt_image.py:edit_image()`) instead of Krea, so
  this token stays here undisturbed rather than becoming load-bearing.
- **AWS/S3 — bucket is ours, creds are this pipeline's own copy.** The `yt-heritage-media`
  bucket (see `## S3` below) was created fresh for this pipeline and is NOT shared with
  `yt-cold-case-media` or any other bucket. `src/s3.py`'s `_cfg()` reads
  `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_REGION` via `utils/env.py`, from keys
  that live directly in the root `.env` — same underlying AWS account/key as before, just
  physically relocated into the root `.env` instead of a hardcoded path into a sibling
  project's `.env.local`. Not a new IAM user, just where the keys now live.

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

- Bucket: **`yt-heritage-media`** — us-west-2, public-read policy, 7-day lifecycle. Created
  fresh for this pipeline (not shared with `yt-cold-case-media`), same shape/policy mirrored
  exactly from the cold-case bucket.
- `src/s3.py` is `shared/s3.py` copied almost verbatim: same `upload_bytes` /
  `upload_from_url` / `put_file` / `first_uploadable` functions, `BUCKET` swapped to
  `yt-heritage-media` and the default `prefix` swapped from `"cold-case"` to `"heritage"`.
- **Rule: the finished video always goes to S3 as a RAW public url, never presigned, never a
  local-only file path.** `put_file()` only ever returns a raw public link (the bucket is
  public-read) — that's what gets pushed to ClickUp for review.
- **7-day lifecycle** — once render is built, the pushed video url goes dead after a week;
  pull it promptly or re-render.

## Scene generation + character agents (owned elsewhere — read, don't edit here)

`src/scene_engine.py` (scene breakdown + classification) and `src/gallery.py` (review HTML),
plus everything under `agents/`, are their own unit with their own operating rules — see
`agents/CLAUDE.md`. Contract versions on context, character, visual-story, and scene
artifacts force stale cached work to regenerate when any authored interface changes.

## Layout

```
heritage-decoded/
├── src/            pipeline code: run.py (entrypoint), baserow.py, clickup.py, s3.py,
│                   scene_engine.py, gpt_image.py, krea.py, gallery.py
├── agents/         character-consistency agents (plain importable Python packages, no
│                   subprocess bridge — this repo has no cross-language boundary):
│                   character_ledger/ (which characters are worth tracking), character_sheet/
│                   (one full-body reference image per tracked character),
│                   visual_director/ (categorical emotional score + standalone film plan),
│                   scene_compositor/ (per-scene i2i via reference images, t2i fallback)
├── utils/          stdlib-only / low-dependency helpers: env.py (env-var lookup),
│                   llm.py (shared OpenAI structured-JSON caller, used by scene_engine.py
│                   and agents/), align.py (DTW aligner), images.py (image fetcher),
│                   tts.py (TTS client), cleanup.py (prune_runs)
├── remotion/       standalone Remotion project (Lambda render), incl. node_modules/ — no
│                   character/style awareness, just renders each scene's image_url
├── runs/           per-row run artifacts (runs/<row_id>/), pruned after 24h once done
├── .env            all credentials (Baserow, OpenAI, AWS, ClickUp, etc.), one file
├── .venv/          one virtualenv, referenced by src/run.py via a PROJECT_ROOT-style
│                   constant one level up from src/
├── .claude/        slash commands. Commands are discovered from cwd, so any subprocess
│                   call to `claude -p` should explicitly set cwd to this root.
├── scratchpad/     scratch working files
└── HERITAGE_PLAN.md   historical build-log / design record
```

`src/*.py` files that need `utils/` (env, align, images, tts, cleanup) add a small
`sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "utils"))`
near the top rather than converting to a proper Python package — this repo has no
`setup.py`/`pyproject.toml` and several `utils/*.py` files have their own
`if __name__ == "__main__":` self-test blocks that must keep working when run directly
(e.g. `python3 src/scene_engine.py`).

Driven directly: run `python3 src/run.py` in the foreground, one row at a time — no
background daemon.
