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
blocks mapped evenly across that film → per-scene images (`agents/scene_compositor`, gpt-image-2 t2i
only for now — i2i against a character's reference sheet is cut, bring it back if t2i-only
consistency doesn't hold up in testing) → gallery (non-blocking review) →
download the row's own narration → Whisper+DTW alignment against that real audio → Remotion
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

## Hard rules

- **Never write or edit the script.** If a row's `script` field looks wrong, thin, or
  off-topic, stop and flag it — do not rewrite it here. That's the upstream writer's job.
- **Narration and visuals are two separate lanes.** Narration is cut into verbatim visual
  pacing beats using the homestead pattern: an LLM proposes boundaries, code anchors them
  losslessly to the source, and a 30-word ceiling prefers sentence or clause boundaries.
  The narration content never supplies scene props, locations, or actions to the shot planner.
  `agents/story_dossier` first separates evidence-backed source facts
  from production inference, chooses one plausible occupation from an abstract character
  profile, and commits to concrete casting. `agents/visual_director` reduces the source to a
  categorical emotional score, then invents a standalone contemporary film with its own
  external goal, recurring social locations, cause-and-effect plot, and resolved ending.
  `src/scene_engine.py` expands each ordered film beat into shots without receiving narration.
  Do not turn narration cuts into per-sentence illustration or source-noun prompting. Show
  emotion through body language and social situation: despair is a woman
  with her head in her hands during lived activity, not the narrated book in her hands.
- **Bridge the two lanes with sparse literal cues.** The source-aware emotional pass may
  extract a few portable tools, materials, textures, gestures, or garment actions from each
  phase. The independent director can select one only where it fits its invented plot, and
  the shot planner carries that selected cue into the beat. This is deliberate visual rhyme,
  not permission to recreate the narrated event, location, relationship, or religious symbol.
  Garment actions always use the locked character outfit rather than inventing another coat.
- **Prefer semantic review to case lists.** Do not add activity-to-building matrices, growing
  banned-word catalogs, or script-specific prompt patches. Source-blind casting/direction
  calls create the new visual world; separate reviewers may see evidence-backed source facts
  only to catch contradiction or distinctive story overlap. Reviewers judge whether settings,
  institutions, professional activity, casting, and story causality make sense in context.
  Every retry must include the rejected JSON before the feedback message.
- **Use affirmative image prompts, not safety vocabulary lists.** The Images API has no
  negative-prompt channel. Do not append `negative_prompt` or banned-word lists to ordinary
  prompt text; that previously caused avoidable gpt-image-2 moderation matches. The compositor
  uses concise renderable direction and positive composition constraints.
- **Recurring, full-body characters — not a stock-figure default.** Every script gets its
  own character ledger, built once up front by `agents/character_ledger:build(script, context)`:
  the protagonist is always tracked, Jesus only if he actually appears, any other character
  only if they recur across multiple beats (never a one-off mention). Each tracked character
  gets one full-body reference image (`agents/character_sheet:generate_all()`, gpt-image-2
  t2i, `quality=low`). `src/scene_engine.py`'s scene authoring then tags every scene with which
  tracked characters (`character_ids`) are visually present, and `agents/scene_compositor`
  generates that scene's image referencing them by name/appearance. No fixed per-channel
  design and no stick figures — that was the old model, fully retired.
- **Characters are locked production specifications, not loose prose.** The approved
  character-profile standard names every stable visual decision: exact age, ethnicity,
  height, build, skin tone, face shape, cheek structure, eye color/shape, nose, lips,
  age markers, glasses, deterministic hair color/cut/length/part/finish, inner shirt,
  outer layer and exact closure state, bottom, and footwear. Hair accessories and wearable
  non-jewelry accessories are always explicitly absent: small persistent objects are fragile
  continuity details, not identity. Jewelry also defaults to none and is allowed only when the
  source explicitly makes one stable worn item identity- or plot-critical. Eyewear is allowed
  because it materially defines the face. Bags and handheld objects remain scene props.
  Avoid variable traits such as unspecified bobs or salt-and-pepper patterns. Repeat the
  complete compact profile in every image prompt where that character appears; keep style
  direction light and let the image model handle rendering. Names remain internal and are
  removed before Images API calls because common names can trigger public-figure matching.
- **Final image prompts stay compact.** `agents/scene_compositor` sends exactly a short
  16:9 animated-film style sentence, the authored visible scene action, and the complete
  deterministic compiled profile for each visible tracked character. It does not append
  `visual_story.movie_style`; that longer direction remains planning context for the shot
  author only. `COMPOSITOR_CONTRACT_VERSION` invalidates images when this final prompt
  construction changes.
- **No automated vision-QA, anywhere.** Whether a generated image matches its expected
  character(s) is a human call made off the gallery review (`src/gallery.py`), not a gpt-4o
  vision gate — keeps cost down; this is a story pipeline, not a verification pipeline.
- **t2i only, for now.** `agents/scene_compositor` generates every scene via gpt-image-2
  text-to-image — `src/krea.py`'s img2img (`krea_edit_photo()`, conditioned on a character's
  reference sheet) is cut from the pipeline on purpose. Testing methodology: run a batch,
  look at `gallery.html`, judge whether t2i-only character consistency holds up. If it
  doesn't, i2i comes back as a whole-pipeline direction (not a per-scene fix) — not before.
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
7 IMAGES     agents/scene_compositor:compose_all() — per scene, IN PARALLEL, gpt-image-2 t2i
             only (for now). The final prompt is light style + visible action + the complete
             compiled locked profile for every character_id, with names removed. NO automated vision-QA anywhere in
             this pipeline — a human reviews the gallery (step 8) and judges consistency.
             i2i (src/krea.py:krea_edit_photo(), reference_images = a character's reference
             sheet) is cut from the pipeline — a future whole-pipeline direction if t2i-only
             consistency doesn't hold up, not a per-scene fix.
8 GALLERY    src/gallery.py: scenes + generated image urls -> one gallery.html (grid,
             click-to-expand modal, vanilla JS/CSS) for manual review. See that file.
9 ALIGN      scene_engine.py:align_scene_durations() — real word timestamps from the
             hosted Modal whisper service (REMOTION_WHISPER_SERVICE_URL, same one
             senior-finance/finance/remotion calls) + utils/align.py DTW mapped onto each
             scene's verbatim script_snippet. NOT a word-count estimate (tried and
             explicitly rejected — doesn't actually align). NOT local faster-whisper —
             that package was never installed in this repo's .venv.
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
  don't duplicate it into the root `.env`. Currently unused (i2i is cut from the pipeline for
  now, see "Hard rules" above) — this stays here for when it comes back.
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

`src/scene_engine.py` (scene breakdown + classification) and `src/gallery.py` (review HTML)
are built and maintained as their own unit. `agents/visual_director`,
`agents/character_ledger`, `agents/character_sheet`, and `agents/scene_compositor` are their
own unit too. Contract versions on context, character, visual-story, and scene artifacts force
stale cached work to regenerate when any authored interface changes.

**Anti-Jesus regression bias (known gpt-image-2 failure mode):** faith-themed image generators
default ANY unspecified secondary character into a long-haired, bearded Jesus in robes. Every
non-Jesus character must carry an explicit concrete gender, ethnicity, hairstyle, and ordinary
modern clothing in `agents/character_ledger`'s per-character `appearance` field — a bare
"a person"/"a figure" is what triggers the regression. Do not counter this with a negative
prompt list; use concrete positive character descriptions.

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
│                   scene_compositor/ (per-scene t2i; i2i is cut for now)
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
