# Session: Agent-ify the pipeline + recurring full-figured characters

Started: 2026-07-25

## Goal

Revamp this pipeline to be more intelligent by adopting the agentic patterns used in
the sibling `military/` repo (tool-calling loops, generate→validate→retry-with-feedback,
vision-QA gates, critique passes) — and replace the current stick-figure image style with
**recurring, full-figured characters** that stay visually consistent scene to scene.

## Confirmed: current image-gen model

- **Not Krea.** `src/krea.py` exists (calls a custom Modal-hosted wrapper at
  `avoajaugochukwu--open-source-image-gen-web.modal.run`, supports `krea_edit_photo()`
  with `reference_images` for img2img) but **it is never called anywhere in the pipeline**
  — no importer besides its own `__main__` self-test.
- Actual generator in use: `src/asset_selector.py:route()` → `gpt_image.generate_image()`
  (imported as `scene_assets`, i.e. **gpt-image-2**), single lane, no branching.
- Style is a hardcoded `_STYLE FIX PREFIX` string (`asset_selector.py:12-22`) —
  "muted, hand-drawn monochrome stick-figure whiteboard-doodle" — applied to every scene
  regardless of `scene_type`.

## Confirmed gaps

1. **Docs vs. code drift.** `CLAUDE.md` describes a 4-lane router (archival photo / stock /
   generated map-graphic / Krea painting, `asset_selector.py:route()`) with `scene_type`-keyed
   `STYLE_PREFIXES` and a separate `GRAPHIC_STYLE`. None of that exists in the actual file —
   it's 61 lines, one lane (gpt-image-2), one fixed style prefix. The multi-lane design was
   either never built or was ripped out; `CLAUDE.md` needs a rewrite once we know the new shape.

2. **No character-consistency mechanism at all.**
   - No seed parameter anywhere (krea.py has none; gpt-image-2 lane doesn't set one either).
   - No reference-image conditioning is wired in (krea.py *has* `krea_edit_photo(reference_images=...)`
     but it's unused).
   - `scene_engine.py` used to have `infer_characters()`/`CHARACTER_SCHEMA` — **removed**
     (comment at scene_engine.py:427 says consistency is now "structural, not [LLM-generated]").
   - What's left: two hardcoded text blocks (`PROTAGONIST_APPEARANCE`, `JESUS_APPEARANCE`)
     injected into the scene-authoring LLM's instructions, telling it to describe the
     protagonist "identically" every time. That's a *text* consistency hint feeding a
     *stochastic* image model with no visual anchor — no guarantee two scenes render the same
     face/body/outfit.

3. **Zero agentic loops in this repo**, vs. `military/`'s patterns:
   - No tool-calling loop (military: `agents/search_term` uses OpenAI Responses tool loop to
     verify a search query before committing).
   - No generate→validate→feedback→retry loop (military: `entity_ledger`, `graphics_director`,
     `search_term` all retry failed items with the validator's error fed back into the prompt).
   - No vision-QA gate on output (military: `identify.ts` runs gpt-4o vision to check a
     candidate image actually matches before accepting it — nothing here checks a generated
     image against its prompt/character sheet before it goes in the gallery).
   - No critique/self-revision pass (military: `lib/agent/run.ts` critique loop, model decides
     when to stop revising).
   - Everything in `scene_engine.py`/`asset_selector.py` is one-shot: call LLM once, call
     image API once, done. No verification step exists anywhere in the image pipeline.

4. **No prior art for "recurring generated character" in either repo.** `military/` never
   generates character images — all its photography comes from Google Image search + vision-QA
   identification of *real* photos; the only generated images there are abstract map/data
   graphics (no people). So the "keep a generated character consistent across N generated
   scenes" problem is new — nothing to port directly, only patterns to adapt (e.g. identify.ts's
   vision-QA-gate idea, applied to "does this generated image match the character sheet?"
   instead of "does this photo match the real entity?").

## Candidate approach (not yet decided — for discussion)

- Generate one **character sheet** image (or a few reference angles) per recurring character,
  up front, per script — via `krea_edit_photo(reference_images=...)` (img2img/style-transfer,
  already exists, currently unused) or a seed if the underlying model supports one.
- Feed that reference image into every subsequent scene generation involving that character
  (img2img conditioning), instead of relying on repeated text description alone.
- Add a vision-QA gate (gpt-4o, same shape as military's `identify.ts`) that checks a generated
  scene image against the character sheet and re-generates on mismatch — a real agentic
  retry loop, replacing the current one-shot call.
- Decide whether `asset_selector.py`'s multi-lane design (as described in `CLAUDE.md`) gets
  actually built, or whether `CLAUDE.md` gets corrected to match the single-lane reality and
  the multi-lane idea gets folded into this revamp.

## Decisions (2026-07-25)

- **Generation flow**: gpt-image-2 text-to-image first pass → vision-QA check (does the
  generated scene match the character sheet/reference?) → if mismatch, repair via Krea
  `krea_edit_photo()` img2img (reference_images=character sheet) rather than regenerating
  blind from text again. Not a straight switch to Krea — a hybrid t2i-then-i2i-repair loop.
- **Scope**: single character-generation lane only, not the full multi-lane router
  (archival/stock/graphic) described (but never built) in `CLAUDE.md`. Multi-lane stays
  out of scope for this revamp.
- **Sequencing**: clean up and align the project first (fix `CLAUDE.md` drift, remove/resolve
  stick-figure-era code and docs, decide what to do with unused `krea.py` machinery now that
  it's back in scope) before building the new character-consistency pipeline. Use subagents
  generously during cleanup to save time.

## Open questions for user

- One protagonist only, or multiple recurring named characters per script?
- Exact vision-QA gate shape: reuse military's `identify.ts` pass/fail schema style
  (matches/observed/confidence/correctedQuery), or a simpler bespoke check?
- How many i2i repair attempts before giving up / falling back to the raw t2i image?

## Decisions (2026-07-25, revised)

- **No vision-QA anywhere in this app.** Whether a generated scene matches its
  character(s) is a human call made off the gallery review (`src/gallery.py`), not an
  automated gpt-4o vision gate — keeps cost down, this is a story pipeline not a
  verification pipeline. `agents/shared/vision_qa.py` was built, tested live, then
  deleted per this correction — not needed.
- **i2i repair is manually triggered.** `agents/scene_compositor/client.py:repair_one()`
  exists but is never auto-called by `compose_one()`/`compose_all()` — a human decides a
  t2i result is bad and calls it themselves.
- **gpt-image-2 stays at quality="low"** (`src/gpt_image.py:QUALITY`, unchanged) — keep
  generation cheap.
- Priority is spending time on the **character ledger accuracy** (which characters recur,
  where they appear) over any automated QA machinery.

## Phase 1 built (2026-07-25): agents/ package

Full plan: `/Users/avoaja/.claude/plans/stateless-growing-wigderson.md`. Built and
live-tested:
- `utils/llm.py` — extracted `call_llm_json()` from `scene_engine.py` (no behavior change,
  regression-tested against the original).
- `agents/character_ledger/client.py` — `build(script, context)`, generate→validate→retry
  (protagonist always tracked, Jesus only if he appears, supporting cast only if recurring).
- `agents/character_sheet/client.py` — `generate_all(characters)`, one t2i reference image
  per tracked character via `gpt_image.generate_image()`.
- `agents/scene_compositor/client.py` — `compose_all(scenes, characters)` (t2i per scene,
  character descriptions injected into the prompt) + `repair_one()` (manual i2i via
  `krea.krea_edit_photo()`, reference_images = character sheet(s)).

## Phase 2 built (2026-07-25): full wiring, old stick-figure flow retired

- `src/scene_engine.py`: dropped `PROTAGONIST_APPEARANCE`/`JESUS_APPEARANCE` fixed
  constants; `author_chunk()`/`break_into_scenes()` now take a `characters` param (the
  ledger) and emit `character_ids` per scene (schema enum-constrained to the real
  ledger) instead of `people_count`. Removed `generate_images()`/`_backfill_missing_images()`
  (moved to `run.py` + `agents/scene_compositor`).
- `src/asset_selector.py` — **deleted**, fully superseded by `agents/scene_compositor`.
- `src/run.py` — new CHARACTERS stage (`characters.json`) between context and scene
  breakdown; IMAGES stage now calls `agents.scene_compositor.compose_all()`.
- `CLAUDE.md` — rewritten to match: pipeline stage list, Hard rules, Layout, Scene
  generation section, anti-Jesus-regression note all now describe the character-ledger
  flow instead of the old multi-lane/stick-figure design that was mostly doc drift anyway.
- Verified live: full non-image-gen path (`infer_context` → `character_ledger.build` →
  character-aware `break_into_scenes` → `scene_compositor.build_scene_prompt`) runs
  end-to-end with real gpt-5-mini calls, `character_ids` contract holds. Did NOT run a
  live `character_sheet.generate_all()`/`scene_compositor.compose_all()` image-gen pass
  during this verification — those cost real gpt-image-2 calls and weren't necessary to
  confirm the wiring; run `python3 src/run.py <row_id>` for a real end-to-end row.

## Decision (2026-07-25, revised again): i2i is cut, t2i only

Corrected course twice on the same axis:
1. i2i repair is NOT a per-scene "fix this one bad image" step — if t2i-only character
   consistency doesn't hold up, i2i is a whole-pipeline DIRECTION switch, decided by
   testing (run a batch, look at `gallery.html`, judge).
2. Then: don't build i2i at all yet. `agents/scene_compositor` is t2i-only again (no
   `mode` param, no krea import). i2i comes back later, if testing shows t2i-only
   consistency isn't good enough — not before. `src/krea.py` stays in the repo unused,
   ready for that.

**Testing methodology going forward**: run the pipeline, look at the HTML gallery
output, judge character consistency by eye. Once satisfied, this app goes back to
running headless — no UI dependency — same as the pipeline it's replacing (gallery
was always non-blocking, never a gate).

## Not committed to main

All of this work (agents/, the scene_engine.py rewrite, CLAUDE.md rewrite, utils/llm.py,
deleted asset_selector.py, the narration_script.txt style-test artifacts under runs/) is
sitting uncommitted on `main` as working-tree changes only. **Explicitly NOT being
committed/pushed right now** — still the testing/evaluation phase (style-testing against
narration_script.txt, gpt-image-2 moderation-flakiness investigation ongoing). Do not
`git add`/commit any of this without an explicit go-ahead.

## Log

- 2026-07-25: Session opened. Confirmed current model (gpt-image-2, single lane) and gaps
  above.
- 2026-07-25: User decided generation flow (t2i → i2i repair via Krea, manually triggered,
  no vision-QA) and scope (single character lane, not multi-lane router; agents/ built
  before wiring; Remotion untouched — confirmed it has no character dependency).
- 2026-07-25: Phase 1 (agents/ package) built and verified live — see above.
