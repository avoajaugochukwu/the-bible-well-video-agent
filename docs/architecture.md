# Architecture — the-bible-well pipeline

Full stage-by-stage design and the state/resume contract. Root `CLAUDE.md` owns the
operating SOP, hard rules, and directory layout; `agents/CLAUDE.md` owns the
character-consistency stack's own operating philosophy. This file is the "how it
actually works," kept separate so `CLAUDE.md` stays short.

## State and resume

The container's filesystem is throwaway — Railway has no volume, so a redeploy wipes it.
There is no `runs/` directory and no stage reads or writes a local artifact.

- **The Supabase job row (`bible_well_jobs.payload`) is the only durable state.** Scenes
  are published there before image generation starts and each image lands on its scene
  as it's produced; the character ledger (base reference + wardrobe variants) rides
  along on the same payload (the production UI's regenerate routes need it).
  `render_pipeline()` reads its scenes straight back out (`supabase_jobs.scenes_from_job()`);
  `prepare_images_and_align()` reads the fuller mid-pipeline shape back out
  (`supabase_jobs.full_scenes_from_job()`) — those are the only two read paths.
- **A failed or interrupted `prepare_cast_and_scenes()` re-runs the whole thing, images
  included.** Deliberate: resume happens rarely, and resume-specific skip logic isn't
  worth carrying. Everything upstream of the scene list (context, narration cut,
  dossier, cast, director) is in-memory only, so there is nothing stale and no
  contract-version cache check left anywhere. Wardrobe decide+generate is the one
  exception — see the gate below.
- **Three payload flags are correctness gates, not optimizations.** `renderUrl` stops a
  rerun re-paying for a full Remotion Lambda render; `clickupPushedAt` stops it
  prepending "🎬 VIDEO: …" to the same ClickUp task a second time (`push_video()`
  prepends unconditionally and nothing detects the duplicate); `wardrobeApprovedAt`
  stops a resumed job from re-running `character_wardrobe.decide()` +
  `generate_variants_all()` (real OpenAI spend) after a human has already approved it,
  and is what `ingest_server.py`'s `_ensure_resumed()` checks to tell a crash-stranded
  `preparing` job's phase apart (wardrobe-decide vs. image-generate). All three are set
  the moment the thing they guard has actually happened. `tests/check_render_gates.py`
  pins the first two down.
- **The wardrobe-approval gate is a hard pause, not an optimization.** Nothing spends on
  scene image generation until a human approves the character wardrobe review in the
  production UI (or the CLI auto-approves, see below) — a job sitting in
  `awaiting_wardrobe_approval` is not "stuck," it's correctly idle. `_ensure_resumed()`
  deliberately does nothing to a job in that status.
- **Deferred, not built: an artifact store.** If re-running a whole prepare after a
  failure starts costing real money often enough to notice — that rising retry cost is
  the signal — the escalation is to persist the upstream intermediates outside the
  payload: S3 objects under `bible-well/runs/<row_id>/<name>.json` in the existing
  `yt-bible-well-media` bucket (mind its 7-day lifecycle), or a
  `bible_well_run_artifacts` table. They are deliberately NOT in `payload`:
  `visual-story.json` + `scenes.json` + `whisper-words.json` would take it from ~130KB
  to ~600KB against ~15 full read-modify-writes per run plus 5-second UI polling, and
  Postgres cannot partially update jsonb.

## Pipeline stages

```
1 BASEROW    src/baserow.py: get_row(row_id) reads the one row the caller specified —
             no scanning, no gating on video_processed. Read-only.
2 CONTEXT    scene_engine.py:infer_context() — OpenAI gpt-5-mini, reasoning_effort=low.
             Setting/spiritual_theme/emotional_palette for the script, held in memory and
             passed into every later stage.
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
             (gpt-image-2 t2i, quality=low). Stored on the job payload — the production
             UI's regenerate-image route reads it back from there.
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
             the external goal. In memory only.
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
7 WARDROBE   agents/character_wardrobe:decide() — one whole-film schema-locked call deciding,
             per tracked character, which SIGNIFICANT recurring contexts (a wedding, a work
             uniform) need their own outfit variant; everyday scenes keep the base reference.
             Deterministic fact-check: every scene_number assigned to a character's variant
             must be a scene where that character actually appears. Then
             agents/character_sheet:generate_variants_all() makes one i2i reference image per
             declared variant, off the character's OWN base reference (identity anchored by
             BOTH the reference image and concrete age/build/face/hair text —
             compile_identity_profile() — not just a bare "same build" instruction). This is
             where prepare_cast_and_scenes() stops and publishes — see the gate below.
             [PRODUCTION UI: human reviews/edits/approves the wardrobe]
8 IMAGES     agents/scene_compositor:compose_all() — per scene, IN PARALLEL, gpt-image-2
             images.edit() conditioned on every present character's reference image — their
             base reference, or a wardrobe variant's reference when the wardrobe stage
             assigned that scene one (falls back to base if the variant's image isn't ready).
             Reference images are fetched and shrunk once per character/variant, reused
             across scenes. Plain t2i is the fallback only when a reference is missing or the
             edit call is rejected. NO automated vision-QA anywhere in this pipeline — a human
             reviews the images in the production UI (web/) and judges consistency. Each
             scene records which reference (base or which variant) it actually resolved to,
             for the production UI's per-scene audit display.
9 ALIGN      scene_engine.py:align_scene_durations() — real word timestamps from the
             hosted Modal whisper service (REMOTION_WHISPER_SERVICE_URL, same one
             senior-finance/finance/remotion calls) + utils/align.py DTW mapped onto each
             scene's verbatim script_snippet. NOT a word-count estimate (tried and
             explicitly rejected — doesn't actually align). NOT local faster-whisper —
             that package was never installed in this repo's .venv. Runs inside
             prepare_images_and_align() — not at render time — so every scene's
             duration_seconds (how many seconds of video/image that scene needs) is already
             known and shown in the production UI before a human ever generates or uploads a
             clip for it. The narration mp3 is a tempfile, always unlinked; render_pipeline()
             re-transcribes for its caption payload rather than caching words anywhere.
10 RENDER    remotion/ (standalone Remotion project) on Remotion Lambda. Renders whatever
             image_url/video_url each scene carries, narration muxed in via `<Audio>`. See
             `remotion/CLAUDE.md` for render mechanics (banned-local-render rule,
             scenes.json shape, OffthreadVideo).
11 S3        src/s3.py:put_file() uploads the rendered mp4 -> RAW public url (bucket is
             public-read) — ALWAYS push the finished video here for review, never hand back
             a presigned link or a local-only file path.
12 CLICKUP   src/clickup.py: push_video() PUTs "🎬 VIDEO: <s3 url>" onto the row's
             clickup_url task description (falls back to a comment on failure), same
             update-existing-task pattern as space-cluster. Last stage — nothing
             writes back to Baserow after this.
```

`src/run.py` exposes this as three calls: `prepare_cast_and_scenes(row_id)` (stages
1-7, script through wardrobe — what `POST /ingest` enqueues; ends at
`awaiting_wardrobe_approval`), `prepare_images_and_align(row_id)` (stages 8-9, fired
by the production UI's `POST /jobs/{id}/approve-wardrobe` action once a human has
reviewed the wardrobe, or immediately by the CLI's auto-approve default), and
`render_pipeline(row_id)` (stages 10-12, fired manually from the production UI's
Render button once a human has reviewed/edited the job). `run_pipeline(row_id,
auto_approve_wardrobe=True)` runs all three back-to-back for a plain unattended CLI
pass (`python3 src/run.py <row_id>`) — the deployed `ingest_server.py` never calls
this function, so the production/UI path always hard-pauses at the wardrobe gate
regardless of the CLI's default. See `README.md` for the production UI (`web/`) and
Railway deployment. Credentials, and the Baserow/ClickUp/S3/Supabase/video-gen
integration details, live in `src/CLAUDE.md`.
