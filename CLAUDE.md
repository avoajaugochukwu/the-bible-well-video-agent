# CLAUDE.md — Christian Story Video Agent SOP

The operating SOP, self-contained. Everything an agent needs to run this is in this file.

This repo holds one pipeline — Christian Story — laid out with standard project directory
names (`src/`, `utils/`, `remotion/`) at the repo root. There is no separate
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
`row_id` field of an `/ingest` POST body when triggered over HTTP). **Nothing is kept on
local disk** — see `docs/architecture.md`'s "State and resume". `agents/` (story_dossier,
character_ledger, character_sheet, character_wardrobe, visual_director, scene_compositor —
plain importable Python packages, no subprocess bridge needed since this whole repo is
already Python) is where the character-consistency work lives, separate from
`src/scene_engine.py`'s scene-breakdown LLM calls. There is **no vision-QA anywhere in this
pipeline** — whether a generated image actually matches its character(s) is a human call
made off the production UI review, not an automated gate.

Stage order: Baserow read → context → whole-script production dossier → character ledger +
one full-body reference image per tracked character → whole-film parallel-story direction →
verbatim narration timing blocks → **wardrobe variants for significant recurring contexts
(a wedding, a work uniform), then a hard human-approval gate before any scene image
generates** → per-scene images (i2i against each present character's base or wardrobe-variant
reference, t2i fallback only when a reference is missing or the edit call is rejected) →
Whisper+DTW alignment against the row's own narration → [production UI review/edit, manual
render trigger] → Remotion Lambda render → upload to S3 (RAW public link — **never
presigned**) → ClickUp push. Baserow is never written back to — read-only,
`src/baserow.py:get_row(row_id)` only. Full stage-by-stage detail (including the
wardrobe-approval gate's exact mechanics) and the state/resume contract:
**see `docs/architecture.md`.**

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

## Docs

- **`docs/architecture.md`** — the full numbered pipeline-stage breakdown (Baserow through
  ClickUp, including the wardrobe stage and its human-approval gate) and the state/resume
  contract (what's durable, what's in-memory, what each payload gate guards). Read this
  before changing stage order, `src/run.py`, or `src/supabase_jobs.py`.
- **`docs/changelog/`** — one dated file per month (e.g. `2026-08.md`), a prose build-log
  of what changed and why. Add an entry here for any non-trivial change, same spirit as
  the old `session.md` (now retired).
- **`agents/CLAUDE.md`** — the character-consistency stack's own operating philosophy and
  standing rules (see below).
- **`src/CLAUDE.md`**, **`web/AGENTS.md`**, **`remotion/CLAUDE.md`** — directory-scoped
  instructions for their own trees.

## Scene generation + character agents (owned elsewhere — read, don't edit here)

`src/scene_engine.py` (scene breakdown + classification), plus everything under `agents/`,
are their own unit with their own operating rules — see
`agents/CLAUDE.md`.

## Layout

```
the-bible-well/
├── src/            pipeline code: run.py (entrypoint: prepare_cast_and_scenes/
│                   prepare_images_and_align/render_pipeline), ingest_server.py (HTTP API,
│                   see its ROUTES list), baserow.py, clickup.py, s3.py, supabase_jobs.py,
│                   video_gen.py, scene_engine.py, gpt_image.py
├── agents/         character-consistency agents (plain importable Python packages, no
│                   subprocess bridge — this repo has no cross-language boundary):
│                   story_dossier/ (casting + plot-free director profile), character_ledger/
│                   (which characters are worth tracking), character_sheet/ (one full-body
│                   reference image per tracked character + per-variant reference images),
│                   character_wardrobe/ (which contexts need their own outfit variant),
│                   visual_director/ (categorical emotional score + standalone film plan),
│                   scene_compositor/ (per-scene i2i via reference images, t2i fallback)
├── utils/          stdlib-only / low-dependency helpers: env.py (env-var lookup),
│                   llm.py (shared OpenAI structured-JSON caller, used by scene_engine.py
│                   and agents/), align.py (DTW aligner), images.py (image fetcher),
│                   pexels.py (Pexels search), tts.py (TTS client)
├── remotion/       standalone Remotion project (Lambda render), incl. node_modules/ — no
│                   character/style awareness, just renders each scene's image_url/video_url
├── web/            production review UI (Next.js) — queue + per-scene edit view + character
│                   wardrobe review, talks to ingest_server.py through its own server-side
│                   proxy. See README.md.
├── docs/           architecture.md (full stage breakdown + state/resume contract),
│                   changelog/ (one dated file per month — see CLAUDE.md's "Docs" section)
├── .env            all credentials (Baserow, OpenAI, AWS, ClickUp, Supabase, etc.), one file
├── .venv/          one virtualenv, referenced by src/run.py via a PROJECT_ROOT-style
│                   constant one level up from src/
└── Dockerfile, docker-entrypoint.sh   one image, one Railway service — see README.md
```

`src/*.py` files that need `utils/` (env, align, images, tts) add a small
`sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "utils"))`
near the top rather than converting to a proper Python package — this repo has no
`setup.py`/`pyproject.toml` and several `utils/*.py` files have their own
`if __name__ == "__main__":` self-test blocks that must keep working when run directly
(e.g. `python3 src/scene_engine.py`).

CLI usage is direct and one row at a time: `python3 src/run.py <row_id>` in the foreground.
The deployed service (`src/ingest_server.py`) is a persistent HTTP server with two FIFO
worker queues (prepare, render) so a slow render never blocks a new `/ingest` call.
