# Heritage Decoded — scene/video generator build plan

Session-scoped tracker. Delete this file once the pipeline ships.

**Status: Phases 1-5 are all done — `heritage/run.py` wires the full pipeline end-to-end
(not yet exercised against a real row, see Phase 5). Phase 6 (SFX/sound) is the ONLY
outstanding phase, and it's explicitly deprioritized/unscoped — nothing above it depends on
it. This file stays until Phase 6 ships.**

Scope reminder: this project generates scenes/images/video only. It never writes scripts —
script and narration audio come from the Baserow row (`voice_url` is narration ONLY, no SFX/
ambience — confirmed by you). Output: rendered video -> S3 -> ClickUp task updated -> Baserow
row marked done.

## Confirmed facts

- Baserow channel option: **"Heritage Decoded"** — same Baserow instance/table (id `2`) and
  creds as `space-cluster` (`BASE_ROW_URL`, `BASEROW_EMAIL`, `BASEROW_PASSWORD`).
- ClickUp list: **"Heritage Decoded"**, id `901113620100`, Team Space, Karl's Workspace.
  `CLICKUP_API` already sits in this repo's root `.env` — no new key needed there.
- Reference art style / image-gen: `ui/stories/sleep-stories` — same self-hosted Modal endpoint
  as `shared/assets.py`'s `krea_photo()` already in THIS repo (model is **Krea**, not z-image —
  the sleep-stories route.ts label is stale). Style prefix "highly detailed digital painting",
  SFW negatives. Sleep-stories' `@fal-ai/client` dep and `FAL_KEY` are dead leftovers, unused.
- `shared/assets.py:krea_photo(prompt)` is directly reusable for heritage — no new client to
  write. Heritage just always routes to `generated` (Krea); no sheet lane (no real people to
  verify), no pexels lane (no stock, per your ask).
- No video prompts exist in sleep-stories — confirmed per your reminder request, nothing to
  remove.
- Movement: `ui/remotion/remotion-test-2` already has a real Ken Burns engine
  (`remotion/scenes/KenBurnsImage.tsx`) + animated card overlays — reusable for the render
  step later. The dynamic/motion-capable generation backend (Phase 3) is explicitly **deferred**
  — nail static images first per your call.
- Space-cluster's locked-down integration pattern to mirror: `.env` keys + one module-level
  `CHANNEL = "..."` constant used as a Baserow filter, pull-only (no `mark_done` writeback until
  render succeeds), push via update-existing-ClickUp-task (not create-task).
- **S3 bucket `yt-heritage-media` created** — us-west-2, public-read policy, 7-day lifecycle,
  same shape as `yt-cold-case-media` (mirrored exactly, verified via `aws s3api`).
- **`heritage/.env` created** — `BASE_ROW_URL`/`BASEROW_EMAIL`/`BASEROW_PASSWORD`/`BASEROW_TABLE_ID`
  copied from `space-cluster/.env` (same Baserow instance/table), plus `ANTHROPIC_API_KEY`
  copied from `sleep-stories/.env.local` for the scene-breakdown LLM call. `shared/env.py`'s
  `_ENV_FILES` now includes `heritage/.env` (same pattern as `cold-case/.env`).
- **Sound/SFX — resolved, deprioritized.** `voice_url` is narration ONLY, no SFX/ambience baked
  in. SFX is a separate future effort: build/tag a sound library for this project and wire it
  into the Remotion render — moved to LAST (after run.py wiring), not blocking anything above it.

## Open / blocked on you

(none right now)

## Correction — the old "Phase 3" was based on a misread, now dropped

Earlier read of "we need it to be a bit more dynamic... build our own... a lot of movement"
as "stand up our own motion-capable image-gen backend." **Wrong on all counts, per you:**
- Current Krea image-gen (`shared/assets.py:krea_photo()`) is sufficient — no new/separate
  image-gen deployment needed, no reference remote project to pull from.
- "Movement" was never about the generation backend — it's a render-time (Remotion) concern.
- What's actually being built instead: a custom per-scene animation (fade+zoom-out → pause →
  rotate → zoom-in+fade-out, crossfading into the next scene) — see new Phase 3 below.

## Phase 1 — scaffolding

- [x] New sibling folder `heritage/` created (third pipeline alongside `true-crime-news/`, `cold-case/`)
- [x] `heritage/.env` with Baserow + Anthropic keys; `shared/env.py` updated to check it
- [x] S3 bucket `yt-heritage-media` created (7-day lifecycle, public-read)
- [x] `heritage/CLAUDE.md` (pattern-match `true-crime-news/CLAUDE.md`)
- [x] `heritage/baserow.py` — `CHANNEL = "Heritage Decoded"`; smoke test pulled a real row (id 1027)
- [x] `heritage/clickup.py` — `push_video()` pattern, `LIST_ID = "901113620100"`; smoke test passed
- [x] `heritage/s3.py` — `BUCKET = "yt-heritage-media"`; smoke test rehosted a test image successfully

## Phase 2 — scene breakdown + test harness (DONE — stopped here per your call)

- [x] `heritage/scene_engine.py` — `break_into_scenes()` (Anthropic `claude-sonnet-5` via raw
      urllib), persona ported from sleep-stories, adapted for Asian history (dynasty/era-locked)
- [x] `heritage/scene_engine.py` — `generate_images()`, each scene's `visual_context` ->
      `shared/assets.py:krea_photo()`, style-prefixed, IN PARALLEL (ThreadPoolExecutor)
- [x] Patched `shared/assets.py:krea_photo()`/`_krea_job()` to accept an optional
      `negative_prompt` param (backward-compatible, default `""` = old behavior unchanged for
      cold-case/true-crime-news callers) — the SFW/period negative list was being computed but
      never sent to Krea; now wired through and verified with a real re-run.
- [x] `heritage/gallery.py` — `build_gallery()`: single self-contained HTML, responsive grid,
      click-to-expand vanilla-JS lightbox (Escape/click-outside/X to close)
- [x] Test run: 4-sentence Tang Dynasty / Silk Road sample -> 4 scenes -> 4/4 Krea images ->
      `heritage/test-gallery.html`. Spot-checked: period-accurate architecture/robes, vivid
      color, no anachronisms.
- [x] **Stopped here** — open `heritage/test-gallery.html` to review the images. Once you're
      happy with the art style, say go and Phase 3 (motion backend, deferred) or Phase 4
      (render) picks up — your call which.

Note: `break_into_scenes()` collapsed sleep-stories' two-call design (separate global-context
summarization + per-chunk persona) into one call — the model infers period/place from the
script directly. Worked correctly in the test; revisit if a longer/messier real script ever
drifts era mid-scene-set.

## Phase 3 — scene animation prototype (in progress)

Custom 4-phase per-scene motion, your spec verbatim: "the image as it fades in is being zoomed
out, then the zoom is paused, then the image rotates slightly, then it is zoomed in/fade out.
while the next one comes in with the same flow." Plus deterministic per-scene variety (seeded
by scene index, not random — Remotion renders must be pure functions of frame, so re-renders
stay reproducible).

- [x] Standalone Remotion project at `heritage/render/` (package.json, Root.tsx, HeritageScenes.tsx,
      scenes.json — `remotion-test-2` untouched)
- [x] 4-phase animation: fade-in+zoom-out (1.0s) -> pause (2.0s) -> rotate ~2-4° (1.5s) ->
      zoom-in+fade-out (1.5s) = 6.0s/scene, scenes overlap by 1.0s for the crossfade — one
      multi-breakpoint `interpolate()` per property (opacity/scale/rotation), pure function of frame
- [x] Variety: deterministic seeded hash by scene index (not `Math.random()` — Remotion needs
      pure/reproducible renders) — start/end zoom ±0.05/±0.04, rotation alternates sign, every
      3rd scene gets a subtler rotation
- [x] Rendered `heritage/render/out/preview.mp4` — 21.0s, 1920x1080, 30fps, 17.8MB, 4 test-gallery
      images reused (no new Krea calls)
- [x] **Bug found on first review**: `BASE_SCALE=1.0` meant the "zoomed out" pause/rotate state
      exactly covered the frame edge-to-edge — same footprint as zoomed-in, so rotation had no
      margin to expose and never showed black. Fixed: `BASE_SCALE=0.78`, genuinely insets from
      the frame so black is visibly present during pause/rotate/crossfade.
- [x] **Local rendering is off the table** — `npx remotion render` freezes the user's machine
      (headless Chromium too heavy). Switched to Remotion Lambda: reused this AWS account's
      existing site bucket (`remotionlambda-uswest2-wwdsm4roaj`, us-west-2) and deployed a new
      function (`remotion-render-4-0-486-mem3072mb-disk10240mb-900sec` — none of the 3
      pre-existing functions matched our Remotion version). All rendering now happens on
      Lambda; only the final small mp4 download touches the local machine. Deploy scripts at
      `heritage/render/scripts/{deploy-lambda,deploy-site,render-remote}.mjs`, reusable
      `functionName`/`serveUrl` cached in `heritage/render/.env` (gitignored) so future
      re-renders skip redeploying. ~$0.01/render, ~70s total (deploy+site+render+download).
- [x] Re-rendered with the fix via Lambda -> `heritage/render/out/preview-lambda.mp4` (21.08s,
      17.4MB, confirmed via ffprobe)
- [x] **Misread the original feedback backwards.** You wanted the OPPOSITE of what got built:
      images must bleed full-frame at all times, no edges, no black ever, scenes always
      blended/crossfading with no gap. Reverted properly: `BASE_SCALE` 0.78 -> `1.2` (must stay
      above the scale needed to fully cover a 1920x1080 frame at the max rotation angle used,
      ~1.136 at 4.5°, so rotation never exposes a corner), `startScale`/`endScale` raised to
      ~1.29-1.4 (comfortably above `BASE_SCALE` so phase 1/4 still read as a real zoom pulse
      around an always-full-bleed baseline). Redeployed the Remotion site + re-rendered on
      Lambda — same flow (deploy:site then render:remote), no local Chromium.
- [x] Also nudged `heritage/scene_engine.py`'s persona prompt: favour close/medium shots over
      wide establishing shots (the render zooms/rotates into the image, so bare sky/floor at the
      edges reads worse than a tight, detail-filled subject) — affects future generations, not
      the 4 already-made test images.
- [x] **Second bug, separate from the scale issue**: each scene wrapped its own OPAQUE
      `AbsoluteFill style={{backgroundColor:'black'}}` — that backing wasn't part of the opacity
      animation, so during the overlap the later (higher-stacked) scene's opaque black layer
      occluded the earlier scene's fading image the instant its Sequence went active. Net
      effect: hard cut to black, then fade-in from black — never an actual photo-to-photo
      blend, no matter how the scale/opacity math was tuned. Fixed: removed the per-scene
      opaque backing entirely; only the outer `HeritageScenes` composition owns the ONE shared
      black backdrop now, so overlapping scenes truly alpha-composite against each other.
      Redeployed + re-rendered on Lambda.
- [x] **Third round of feedback — motion structure rewrite, not a constant tweak.** You wanted:
      zoom noticeably bigger, and NO pause ever — zoom and rotation must both run continuously
      for a scene's entire on-screen duration, overlapping the whole time, never freezing while
      the other moves. Rewrote `HeritageScenes.tsx` from discrete phases to two continuous
      `interpolate()` calls (scale and rotation) spanning the full scene duration — no flat
      segments anywhere except the opacity fade edges (which control crossfade visibility, not
      motion). Zoom range widened to `ZOOM_NEAR=1.2` / `ZOOM_FAR=1.85` (both still safely above
      the ~1.136 full-bleed-at-rotation floor), direction (push-in vs pull-out) alternates per
      scene, seeded.
- [x] **Designed for variable scene length now, per your explicit ask** — `Scene.duration_frames`
      is optional (defaults to 6s today), and `computeSceneTimings()`/`computeTotalDurationInFrames()`
      compute Sequence placement + fade/crossfade fractions from each scene's OWN duration, not
      a shared global constant. When Phase 4 wires real narration-driven per-scene durations,
      this file shouldn't need to change.
- [x] Redeployed + re-rendered on Lambda (renderId `k7m23emg9m`)
- [x] **Approved.** Rotation bumped 2-4° -> 6-10° (2-3° every 3rd scene) since it read as absent
      next to the wide zoom; `ZOOM_NEAR` raised 1.2 -> 1.34 to stay full-bleed at the larger
      rotation angle. Motion design is DONE.

## Phase 4 — render + assemble (production)

- [x] Render path decided: `heritage/render/` (Remotion) + Lambda, not sleep-stories' ffmpeg
      Modal render — ffmpeg zoompan can't express the rotate phase, Remotion does it natively,
      and Lambda deploy is already live (see Phase 3)
- [x] **Per-scene duration — real Whisper+DTW alignment, not an estimate.** Tried a word-count
      estimate first; you correctly called it out as "stupid, it will not align" — reverted that
      completely (deleted `WORDS_PER_SECOND`/`_estimate_duration_seconds`, nothing carried over)
      and wired real alignment instead:
      - `heritage/scene_engine.py`: new `align_scene_durations(scenes, narration_path)` — Whisper
        word-level timestamps via `faster-whisper` (`_whisper_words()`, CPU, `"base"` model,
        `int8`, same config as `shared/render_app.py`'s Modal render backend, just run locally —
        no GPU needed, `faster-whisper` installed into this repo's `.venv`) mapped onto each
        scene's verbatim `script_snippet` via `shared/align.py`'s existing DTW aligner (the same
        one the true-crime render pipelines already use — reused, not reinvented). Adds
        `start`/`end`/`duration_seconds`/`matched` per scene.
      - `to_remotion_scenes(scenes)` converts real `duration_seconds` + `image_url` into
        `heritage/render`'s `{scene_number, image_url, duration_frames}` shape.
- [x] **Ran for real**: `scene_engine.py`'s self-test now does script -> scenes -> Krea images ->
      TTS narration (`shared/tts.py`) -> Whisper+DTW alignment -> `heritage/render/src/scenes.json`.
      Tang Dynasty sample -> 4 scenes, **all 4 matched=True** against the real narration audio,
      durations 11.5-12.9s each (real speech pacing, nothing like the flat 6s test default) ->
      1502 total frames (~50s). Redeployed the Remotion site + re-rendered on Lambda ->
      `heritage/render/out/preview-lambda.mp4` (38.5MB, renderId `skl2oohtlq`).
- [x] **Silent-render gap closed.** `HeritageScenes.tsx` now takes an optional `narrationUrl`
      prop and renders `<Audio src={narrationUrl}>` inside the shared composition;
      `Root.tsx` reads `narrationUrl` out of `scenes.json` and passes it through
      `defaultProps`; `render-remote.mjs` forwards it in `inputProps`; and
      `scene_engine.py:build_remotion_payload()` writes `{scenes, narrationUrl}` to
      `heritage/render/src/scenes.json`. The render now has a real audio track, not just a
      `matched=True` log line.

## Phase 5 — wire into run.py

- [x] `heritage/run.py`: pull ready row -> scenes -> generate -> render -> S3 -> push ClickUp -> mark Baserow done
- [x] `prune_runs()` cleanup, same as the other two pipelines

`run.py` has been written and sanity-checked (`py_compile` + import only) — it has NOT yet
been executed end-to-end against a real Baserow row. The next real `python3 run.py`
invocation is the first true end-to-end test of the wired driver (real Lambda render, real S3
push, real ClickUp update, real `mark_done`).

## Phase 6 — SFX/sound (LAST, deprioritized)

`voice_url` is narration only, confirmed — no SFX/ambience field exists today. This is a new
build, not a wiring task: build/tag a sound library for this project, then wire selected sounds
into the Remotion render. Explicitly ordered last — nothing above depends on this.

- [ ] Design how sounds get tagged/matched to scenes (not scoped yet)
- [ ] Source or generate the sound library (not scoped yet)
- [ ] Wire into `heritage/render/` (new `<Audio>` layer(s) alongside narration)

## Done

- [ ] Delete this file once shipped
