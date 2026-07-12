# CLAUDE.md — Christian Story Video Agent SOP

The operating SOP, self-contained. Everything an agent needs to run this is in this file.

This repo holds one pipeline — Christian Story — laid out with standard project directory
names (`src/`, `utils/`, `remotion/`, `runs/`) at the repo root. There is no separate
sub-folder for the pipeline and no cross-pipeline `shared/` folder to keep in sync.

## What this project does

Generate a scene-by-scene spiritual transformation video for the Christian Story channel (faith-based,
character-driven narratives focused on personal transformation and God's work in daily life)
from a script that already exists in Baserow. **This pipeline never writes scripts.** Script, narration
audio, and sound all come from a Baserow row that's already been marked `script_status=done`
and `voice_status=done` by an upstream writing process (not this repo). This project's job
starts after that: break the script into scenes, generate a spiritual image per scene
(Krea, high-quality digital painting), assemble/render, then push the finished video url back to ClickUp and mark the Baserow
row `video_processed=done`.

Output per run → one rendered video, one ClickUp task updated with the video url, one Baserow
row flipped to done.

## Current status

Full pipeline is wired end-to-end via `src/run.py` — one command, no CLI args: each stage
writes an artifact into `runs/<row_id>/` and is skipped on rerun if that artifact already
exists, so a failure mid-run resumes exactly where it broke instead of re-paying for completed
stages.
`src/asset_selector.py`'s archival lane checks a Turso-backed `blocked_domains` list
(read-only; `TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN` in root `.env`, table shared with
`military`/`footage-collector`) before attempting a vision-QA fetch, in addition to the static
`BLOCKED_HOST_SUBSTRINGS` list. This pipeline only reads that table — it never flags a domain
onto it.

Stage order: Baserow pull → scene breakdown → multi-lane images (archival/stock/graphic/Krea)
→ gallery (non-blocking review) →
download the row's own narration → Whisper+DTW alignment against that real audio → Remotion
Lambda render (narration muxed in via `<Audio>`) → upload the finished mp4 to S3
(`src/s3.py:put_file()`, RAW public link — **never presigned, always S3, that's what gets
shared for review**) → ClickUp push (`src/clickup.py:push_video()`) → Baserow `mark_done`
(`src/baserow.py`) → `prune_runs()` cleanup.

## Inputs

- **A Baserow row**, channel = `"Christian Story"` (single_select value on the shared Baserow
  instance/table, id `2` — same instance space-cluster uses). No CLI args, no manual brief —
  `src/baserow.py:next_ready()` pulls the lowest-id ready row automatically, same pattern
  as `space-cluster/front/baserow.py`.
- Row fields consumed: `title`, `script`, `voice_url` (narration audio — see note below on
  sound), `clickup_url` (the task to push the finished video url onto).
- **Sound**: `voice_url` is narration ONLY — confirmed against a real row, no separate SFX/
  ambience field exists. Building/tagging a sound library is unscoped future work (Phase 6 in
  `HERITAGE_PLAN.md`), deliberately deprioritized to last.

## Hard rules

- **Never write or edit the script.** If a row's `script` field looks wrong, thin, or
  off-topic, stop and flag it — do not rewrite it here. That's the upstream writer's job.
- **Multi-lane assets, routed by `src/asset_selector.py:route()`.** Each scene is classified
  (`scene_type` + `named_entity`, authored alongside `visual_context`/`negative_prompt` in
  `scene_engine.py`) and routed to the lane that fits it — real archival photo/painting/map/
  document (Google Images via Serper + GPT-4o vision QA gate, ported from the sibling
  `military/` repo's `lib/collect/{serper,identify}.ts`), modern stock photo (Pexels, no
  vision QA), an OpenAI-generated map/document graphic (`gpt-image-1`/`gpt-image-2`, same
  `1536x864`/`quality:low` the military repo uses — legible text is the whole point of this
  lane), or Krea AI painting as the fallback when no real/generated asset applies. There is no
  identity-verification bar for real people (no case photos here) — the vision QA judges
  era/nation/rendering-type only, same stance as military's `identify.ts`.
- **Art style is NOT fixed globally anymore.** Krea-lane prompts get a `scene_type`-keyed style
  prefix (`asset_selector.py:STYLE_PREFIXES`) — dramatic digital painting for
  historical/geographic scenes, clean modern photography for `modern_scientific` ones — never
  one blanket prefix over every scene. Archival/stock photos get no style prefix (they're
  real). Map/document graphics get their own parchment/aged-paper prompt style
  (`asset_selector.py:GRAPHIC_STYLE`), matching the reference app (`ui/stories/sleep-stories`)
  only for the Krea lane specifically.
- Pull-only until render succeeds: `baserow.py` never calls `mark_done()` speculatively — only
  after a finished video is actually in S3 and pushed to ClickUp (once that stage is built).
- ClickUp push is update-existing-task, never create-task — the task already exists (created
  by the same upstream process that writes the script), we're just appending the video url to
  it, same as `space-cluster/front/clickup.py`'s `push_video()`.

## Pipeline stages

```
1 BASEROW    src/baserow.py: next_ready() pulls the lowest-id "Christian Story" row
             with script_status=done, voice_status=done, video_processed!=done.
2 SCENES     src/scene_engine.py: LLM scene breakdown of the row's script — OpenAI
             gpt-5-mini, reasoning_effort=low. Three small calls, not one mega-call:
             infer_context() once (pins era/place/palette so every batch stays consistent)
             -> propose_snippets() once over the whole script (pure text-splitting, one
             scene per VISUAL CHANGE, ~4-12s/~10-30 words each, list-cut + staccato rules,
             merge cap ~25 words/12s — same density model as the sibling
             `service/scene-generation-service`'s `breakdown-pro` endpoint) -> author_batch()
             per 8-snippet batch IN PARALLEL (visual_context + negative_prompt, strict
             json_schema structured output). See scene_engine.py for the current contract.
3 IMAGES     Each scene's visual_context -> src/krea.py:krea_photo(), with "highly
             detailed digital painting, " prepended to the prompt (extracted from the old
             `shared/assets.py` — same Krea-calling machinery, no new image client here).
4 GALLERY    src/gallery.py: scenes + generated image urls -> one gallery.html (grid,
             click-to-expand modal, vanilla JS/CSS) for manual review. See that file.
5 ALIGN      scene_engine.py:align_scene_durations() — real word timestamps from the
             hosted Modal whisper service (REMOTION_WHISPER_SERVICE_URL, same one
             senior-finance/finance/remotion calls) + utils/align.py DTW mapped onto each
             scene's verbatim script_snippet. NOT a word-count estimate (tried and
             explicitly rejected — doesn't actually align). NOT local faster-whisper —
             that package was never installed in this repo's .venv.
6 RENDER     remotion/ (standalone Remotion project) on Remotion Lambda (local
             `remotion render` freezes the machine — banned, always deploy:site + render:
             remote). scenes.json is `{scenes, narrationUrl}` — narrationUrl is the row's
             OWN voice_url (already a public S3 url, no rehost needed) muxed in via a plain
             `<Audio src={narrationUrl}>` in HeritageScenes.tsx.
7 S3         src/s3.py:put_file() uploads the rendered mp4 -> RAW public url (bucket is
             public-read) — ALWAYS push the finished video here for review, never hand back
             a presigned link or a local-only file path.
8 CLICKUP    src/clickup.py: push_video() PUTs "🎬 VIDEO: <s3 url>" onto the row's
             clickup_url task description (falls back to a comment on failure), same
             update-existing-task pattern as space-cluster.
9 BASEROW    src/baserow.py: mark_done(row_id) flips video_processed=done, once the
             video is actually live in S3 + pushed to ClickUp.
```

Steps 1-9 are wired into one `run.py` command (`src/run.py`, Phase 5 in
`HERITAGE_PLAN.md`) — run it with `python3 src/run.py` from the repo root, no args.

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
- **Krea image-gen token** (`IMAGE_API_TOKEN`) is read by `src/krea.py:krea_photo()` from
  its own hardcoded path in `sleep-stories/.env.local` — unaffected by this repo's layout,
  don't duplicate it into the root `.env`.
- **AWS/S3 — bucket is ours, creds are this pipeline's own copy.** The `yt-heritage-media`
  bucket (see `## S3` below) was created fresh for this pipeline and is NOT shared with
  `yt-cold-case-media` or any other bucket. `src/s3.py`'s `_cfg()` reads
  `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_REGION` via `utils/env.py`, from keys
  that live directly in the root `.env` — same underlying AWS account/key as before, just
  physically relocated into the root `.env` instead of a hardcoded path into a sibling
  project's `.env.local`. Not a new IAM user, just where the keys now live.

## Baserow

Table id `2` (shared instance, same one `space-cluster` uses). Fields this pipeline reads/writes:

| field              | type          | meaning                                              |
|--------------------|---------------|-------------------------------------------------------|
| `channel`          | single_select | must equal `"Christian Story"`, option id `67`        |
| `script`           | text          | the script, verbatim — never edited by this pipeline   |
| `script_status`    | single_select | gate: must be `"done"`                                 |
| `voice_url`        | text          | narration audio url (mp3), narration ONLY, no SFX      |
| `voice_status`     | single_select | gate: must be `"done"`                                 |
| `clickup_url`      | text          | ClickUp task to push the finished video url onto       |
| `video_processed`  | single_select | gate: must NOT be `"done"`; this pipeline sets it       |

- `src/baserow.py:CHANNEL_OPTION_ID = 67` is hardcoded. This Baserow instance's
  `single_select_equal` filter takes the select option's numeric **id**, not its display
  string — passing the string silently no-ops the filter (returns rows from every channel,
  unfiltered, no error). Option ids are stable once created; re-check
  `/api/database/fields/table/2/` if this field is ever rebuilt from scratch.
- `next_ready()` returns the lowest-id row matching all three gates.
- `mark_done(row_id)` PATCHes `video_processed="done"` — only call this after the video is
  genuinely in S3 and the ClickUp task updated, never speculatively.

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

## Scene generation (owned elsewhere — read, don't edit here)

`src/scene_engine.py` (scene breakdown + classification), `src/asset_selector.py` (multi-lane
image routing) and `src/gallery.py` (review HTML) are built and maintained as their own unit —
this doc deliberately doesn't duplicate their internals since they're still evolving. Read
those files directly for the current contract.

**Anti-Jesus regression bias (known Krea failure mode):** faith-themed image generators default
ANY unspecified secondary character into a long-haired, bearded Jesus in robes. Every non-Jesus
character (protagonist and supporting cast) must carry an explicit concrete gender, ethnicity,
modern hairstyle, and modern clothing in both `infer_characters()`'s planning stage and every
`image_prompt` — a bare "a person"/"a figure" is what triggers the regression. Scenes with a
supporting character but no Jesus get `Jesus, biblical robes, bearded man, long hair, ancient
tunic, halo` appended to `negative_prompt`. See `CHARACTER_SCHEMA` / `author_chunk()` in
`src/scene_engine.py`.

## Layout

```
heritage-decoded/
├── src/            pipeline code: run.py (entrypoint), baserow.py, clickup.py, s3.py,
│                   scene_engine.py, asset_selector.py, krea.py, gallery.py
├── utils/          stdlib-only / low-dependency helpers: env.py (env-var lookup),
│                   align.py (DTW aligner), images.py (image fetcher), tts.py (TTS
│                   client), cleanup.py (prune_runs)
├── remotion/       standalone Remotion project (Lambda render), incl. node_modules/
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
