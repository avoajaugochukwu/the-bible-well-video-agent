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
matches its character(s) is a human call made off the production UI review, not an automated gate.

Stage order: Baserow read (given row_id) → context → whole-script production dossier →
character ledger + one full-body
reference image per tracked character (`agents/character_ledger`, `agents/character_sheet`) →
whole-film parallel-story direction (`agents/visual_director`) → verbatim narration timing
blocks mapped evenly across that film → per-scene images (`agents/scene_compositor`, gpt-image-2
i2i against each present character's reference sheet, t2i fallback only when a reference is
missing or the edit call is rejected) → download the row's own narration → Whisper+DTW
alignment against that real audio (duration_seconds per scene, so the production UI shows
how many seconds of clip each scene needs before render) →
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
  ambience field exists. Building/tagging a sound library is unscoped future work,
  deliberately deprioritized to last.

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
5 DIRECTOR   agents/visual_director:build() — three-pass whole-video design, chunked so no
             single call's output has to scale past the model's completion-token cap. Pass
             one scores every narration snippet with categorical emotional signals only, in
             chunks of CHUNK_SIZE scored IN PARALLEL (each snippet judged on its own text,
             no cross-chunk dependency). Pass two, ONE call, decides the whole world once —
             film_title, external_goal, supporting_characters, recurring_locations — using
             the categorical score, concrete cast, and plot-free dossier handoff; nothing
             else can be introduced after this. Pass three authors one story beat per
             emotional-spine entry, in chunks of CHUNK_SIZE processed SEQUENTIALLY (unlike
             pass one, plot causality means each chunk must know what the last one did) —
             each chunk carries forward a model-authored rolling story_recap plus a
             deterministic location-use tally, and only the final chunk is told to resolve
             the external goal. visual-story.json.
6 SCENES     src/scene_engine.py:cut_narration_scenes() uses an LLM to propose visual-change
             boundaries in sentence-aligned chunks, anchors those boundaries losslessly to
             the verbatim narration, and caps long beats at 30 words using natural punctuation
             where possible. Cuts are evenly distributed across the ordered director beats.
             Each beat carries a visual_mode tag (concrete/abstract) from the director's
             emotional-spine pass, scored from that beat's own narration text. _pick_shot()
             routes on that tag: concrete beats get author_literal_beat() (sees only its own
             snippet, never the invented parallel film); abstract beats get
             author_story_beat() (parallel-world shot, sees only the film plan, never
             narration) — author_story_beat() still runs for every beat regardless, since it
             needs continuity across its own invented plot even for beats ultimately
             rendered literally. Both return chronological image_prompt + character_ids shots.
7 IMAGES     agents/scene_compositor:compose_all() — per scene, IN PARALLEL, gpt-image-2
             images.edit() conditioned on every present character's reference image
             (identity from the image, not restated text). Reference images are fetched
             and shrunk once per character, reused across scenes. Plain t2i is the
             fallback only when a reference is missing or the edit call is rejected. NO
             automated vision-QA anywhere in this pipeline — a human reviews the images in
             the production UI (web/) and judges consistency.
8 ALIGN      scene_engine.py:align_scene_durations() — real word timestamps from the
             hosted Modal whisper service (REMOTION_WHISPER_SERVICE_URL, same one
             senior-finance/finance/remotion calls) + utils/align.py DTW mapped onto each
             scene's verbatim script_snippet. NOT a word-count estimate (tried and
             explicitly rejected — doesn't actually align). NOT local faster-whisper —
             that package was never installed in this repo's .venv. Runs inside
             prepare_pipeline() (part of stages 1-9, before the Supabase job
             upsert) — not at render time — so every scene's duration_seconds (how many
             seconds of video/image that scene needs) is already known and shown in the
             production UI before a human ever generates or uploads a clip for it.
             Whisper words are cached (whisper-words.json) and reused unchanged by
             render_pipeline() for the caption payload, never re-transcribed.
9 RENDER     remotion/ (standalone Remotion project) on Remotion Lambda. Renders whatever
             image_url/video_url each scene carries, narration muxed in via `<Audio>`. See
             `remotion/CLAUDE.md` for render mechanics (banned-local-render rule,
             scenes.json shape, OffthreadVideo).
10 S3        src/s3.py:put_file() uploads the rendered mp4 -> RAW public url (bucket is
             public-read) — ALWAYS push the finished video here for review, never hand back
             a presigned link or a local-only file path.
11 CLICKUP   src/clickup.py: push_video() PUTs "🎬 VIDEO: <s3 url>" onto the row's
             clickup_url task description (falls back to a comment on failure), same
             update-existing-task pattern as space-cluster. Last stage — nothing
             writes back to Baserow after this.
```

`src/run.py` exposes this as two calls: `prepare_pipeline(row_id)` (stages 1-9, script through
narration alignment — what `POST /ingest` enqueues) and `render_pipeline(row_id)` (stages 9-11, fired
manually from the production UI's Render button once a human has reviewed/edited the job).
`python3 src/run.py <row_id>` on the CLI runs both back-to-back for a plain unattended pass.
See `README.md` for the production UI (`web/`) and Railway deployment. Credentials, and the
Baserow/ClickUp/S3/Supabase/video-gen integration details, live in `src/CLAUDE.md`.

## Scene generation + character agents (owned elsewhere — read, don't edit here)

`src/scene_engine.py` (scene breakdown + classification), plus everything under `agents/`,
are their own unit with their own operating rules — see
`agents/CLAUDE.md`. Contract versions on context, character, visual-story, and scene
artifacts force stale cached work to regenerate when any authored interface changes.

## Layout

```
the-bible-well/
├── src/            pipeline code: run.py (entrypoint: prepare_pipeline/render_pipeline),
│                   ingest_server.py (HTTP API, see its ROUTES list), baserow.py, clickup.py,
│                   s3.py, supabase_jobs.py, video_gen.py, scene_engine.py, gpt_image.py
├── agents/         character-consistency agents (plain importable Python packages, no
│                   subprocess bridge — this repo has no cross-language boundary):
│                   story_dossier/ (casting + plot-free director profile), character_ledger/
│                   (which characters are worth tracking), character_sheet/ (one full-body
│                   reference image per tracked character), visual_director/ (categorical
│                   emotional score + standalone film plan), scene_compositor/ (per-scene
│                   i2i via reference images, t2i fallback)
├── utils/          stdlib-only / low-dependency helpers: env.py (env-var lookup),
│                   llm.py (shared OpenAI structured-JSON caller, used by scene_engine.py
│                   and agents/), align.py (DTW aligner), images.py (image fetcher),
│                   pexels.py (Pexels search), tts.py (TTS client), cleanup.py (prune_runs)
├── remotion/       standalone Remotion project (Lambda render), incl. node_modules/ — no
│                   character/style awareness, just renders each scene's image_url/video_url
├── web/            production review UI (Next.js) — queue + per-scene edit view, talks to
│                   ingest_server.py through its own server-side proxy. See README.md.
├── runs/           per-row run artifacts (runs/<row_id>/), pruned after 24h once done
├── .env            all credentials (Baserow, OpenAI, AWS, ClickUp, Supabase, etc.), one file
├── .venv/          one virtualenv, referenced by src/run.py via a PROJECT_ROOT-style
│                   constant one level up from src/
├── Dockerfile, docker-entrypoint.sh   one image, one Railway service — see README.md
└── session.md      prose build-log / design record
```

`src/*.py` files that need `utils/` (env, align, images, tts, cleanup) add a small
`sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "utils"))`
near the top rather than converting to a proper Python package — this repo has no
`setup.py`/`pyproject.toml` and several `utils/*.py` files have their own
`if __name__ == "__main__":` self-test blocks that must keep working when run directly
(e.g. `python3 src/scene_engine.py`).

CLI usage is direct and one row at a time: `python3 src/run.py <row_id>` in the foreground.
The deployed service (`src/ingest_server.py`) is a persistent HTTP server with two FIFO
worker queues (prepare, render) so a slow render never blocks a new `/ingest` call.
