# Session: Agent-ify the pipeline + recurring full-body characters

Started: 2026-07-25

## Goal

Revamp this pipeline to be more intelligent by adopting the agentic patterns used in
the sibling `military/` repo (tool-calling loops, generate→validate→retry-with-feedback,
vision-QA gates, critique passes) — and replace the current stick-figure image style with
**recurring, full-body characters** that stay visually consistent scene to scene.

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
- 2026-07-27: Replaced literal narration illustration with a two-lane film architecture.
  `agents/visual_director` first converts narration into a schema-constrained categorical
  emotional score, then a separate call that never sees narration invents a coherent
  everyday-America story with a visible external goal, recurring social locations, and
  6-14 ordered beats. `scene_engine` mechanically creates verbatim 35-55-word narration
  timing blocks, distributes them evenly over the film beats, and asks per-beat shot planners
  that never see narration to create chronological shots. Source character names and
  relationship roles are removed before image generation.
- 2026-07-27: Removed negative-prompt vocabulary from gpt-image-2 requests. Images API has no
  negative-prompt channel; positive structural constraints and a simple story-aware fallback
  replaced the previous list. Live check on `narration_script.txt`: 67 scenes instead of the
  former 221 literal cuts; the film was an independent community-garden restoration spanning
  a civic meeting, farmer's market, garden, home, and supporting faith-community location.
- 2026-07-29: Replaced the fixed 35-55-word narration grouping with the homestead cutting
  architecture: gpt-5-mini proposes visual-change boundaries in eight-sentence chunks, code
  anchors them back to verbatim source slices, and a 30-word maximum prefers sentence and
  clause punctuation before a hard split. This controls image pacing only; the parallel-film
  shot planner still never sees narration. `narration_script_short.txt` produced 35 scenes
  from 575 words; its first ten ranged from 6 to 28 words with no dangling hard-cap cuts.
- 2026-07-29: Locked character profiles no longer carry small persistent accessories.
  `hair_accessory` must be `no hair accessory` and `accessories` must be `no accessories`.
  Jewelry defaults to none unless the source explicitly makes one stable worn item essential.
  This prevents invented handkerchiefs, pocket objects, and similar fragile details from being
  repeated in every generated scene. Eyewear remains available as a facial identity feature.
- 2026-07-29: Added sparse `bridge_cues` to the two-lane director architecture. The
  source-aware emotional pass may extract portable tools, materials, textures, gestures, or
  garment actions; the independent director may select an approved cue where it naturally
  fits the new plot, and the narration-blind shot planner must render it within that beat.
  Deterministic validation rejects invented cues. This anchors the lanes without returning
  to literal scene translation; garment actions must use the locked wardrobe.
  Five early/middle/late gpt-image-2 samples all generated directly with zero moderation
  rejections, including a despair frame shown through head-in-hands body language rather than
  a narrated religious object.
- 2026-07-27: Added `agents/story_dossier` ahead of the character ledger. It separates quoted
  facts from abstract casting signals, independently selects a plausible occupation, and
  commits to concrete body, ethnicity, hair, and reusable wardrobe. Generators remain
  source-blind where literal copying is risky; source-aware semantic reviewers catch
  contradiction and distinctive overlap without activity/location matrices or banned-word
  lists. Fixed all agent retry loops to include the rejected JSON before critique. The final
  Ellen rehearsal is a museum collections story with two valid museum-boardroom decisions;
  all 67 image prompts were checked for narrated wedding/Bible/closet imagery and invented
  marital-status jewelry.
- 2026-07-28: Approved a new locked character-definition standard after testing scenes 1-3.
  Each character is defined by exact demographic, height/build, face geometry, eyes, glasses,
  one deterministic hair design, inner shirt, outer layer plus closure state, bottom,
  footwear, and jewelry. The complete compact profile is repeated in every applicable image
  prompt with only light style direction. The Helen/Clara test was workable; this structured
  profile now replaces free-form appearance prose as the intended pipeline contract.
- 2026-07-28: Implemented the locked profile directly in `agents/character_ledger`.
  The LLM now returns strict `visual_profile` fields for exact demographics, body, face,
  deterministic single-color hair geometry, clothing layers and closure, footwear, jewelry,
  and body-worn accessories. `compile_visual_profile()` deterministically creates the compact
  compatibility `appearance` consumed by the director, character-sheet generator, and scene
  compositor. A focused semantic critic rejects variable hair, event/role clothing, outfit
  alternatives, ambiguous closures, and bags/handheld props before source-consistency review.
- 2026-07-28: Reworked the production compositor to match the approved compact test prompt.
  Final Images API input is now one light 16:9 Pixar-style sentence, scene action, and the
  deterministic complete profile for each visible character; the director's long
  `movie_style` is no longer appended. Character sheets use the same soft-matte style.
  Added character-sheet and compositor contract versions and wired `run.py` to invalidate
  only stale character references/images and rebuild the gallery when either changes.
- 2026-07-29: Audited the whole character-consistency stack (story_dossier, character_ledger,
  visual_director, scene_compositor, character_sheet, scene_engine, utils/llm.py, tests/)
  against military/agents/ and service/scene-generation-service's breakdown-pro path.
  Verdict: this repo drifted from its own "prefer semantic review to case lists" rule —
  stacked second-LLM-judge calls on top of generator calls, and a pile of ratio/word-count
  heuristics trying to deterministically pin down story quality. Confirmed a real bug from
  this: `scene_compositor.build_scene_prompt()` Python-glues `"The protagonist is..."` into
  every image prompt — structural noise a model would never volunteer on its own. Wrote
  `NORTH_STAR.md` (the operating philosophy this rework follows) and the plan below.

## Phase: prompt-first de-heuristic rework (planned, not yet executed)

See `NORTH_STAR.md` for the five rules this plan follows. Nothing below is a Python
rewrite — every "cut" is a *relocation* into a prompt at the correct scope (global /
regional / scene, per NORTH_STAR.md rule 4), not a deletion of the judgment itself.

**Cut outright — second-LLM-judge calls (violates rule 2, no code replaces these, the
generating model's own prompt just needs to be good enough that a second opinion isn't
needed):**
- `agents/story_dossier/client.py:_review_casting` (+ `DOSSIER_REVIEW_SCHEMA`)
- `agents/character_ledger/client.py:_review_profile_contract`, `_review`
- `agents/visual_director/client.py:_review_bridge_cues`, `_review_plan`

Each of these currently gates a `MAX_ATTEMPTS` retry loop feeding the same model its own
rejected JSON. Once the judge is gone, the loop either collapses to one call, or retries
only against the objective checks that remain (below).

**Cut as dead code (schema already guarantees these, the Python check can't ever fire):**
- `character_ledger.py` hair_accessory/accessories exact-string checks (enum has one value)
- `scene_engine.py:break_into_scenes` `.get(..., default)` fallbacks for schema-required fields
- `scene_engine.py:_assign_snippets_to_beats`'s unused `script` param (`del script`)

**Relocate into prompts, by scope (violates rule 3/4 as Python code, becomes guidance in
the model's own instructions once moved):**
- `visual_director.py:_validate`'s five ratio checks — all **global** (whole-film shape,
  decided once by the single world-building call, not counted after the fact):
  - "≥3 public locations" / "≥3 distinct social domains" → one sentence in the world-building
    system prompt: invent a world with genuine variety in where it happens and who's in it.
  - "supporting char ≥2 appearances" → a definitional instruction where `supporting_characters`
    is declared: only declare someone if they naturally recur; a single appearance means
    they're one-off, leave them out.
  - "≥half beats public" / "no location >half the beats" → one pacing sentence: most of the
    film happens in shared/public settings; don't let any single location dominate the runtime.
- `character_ledger.py` appearance word-count floor (35 words) and first-40-char dedup
  heuristic — relocate as **scene-adjacent-but-really-global** guidance in the character
  generation prompt: describe each character with enough concrete visual detail to be
  redrawable, and make each character visually distinct from the others in this cast.
  (Not "regional" — a character's visual profile is decided once for the whole film, same
  tier as casting.)

**Fix the confirmed bug (rule 5 — internal labels riding into content text):**
- `scene_compositor.py:build_scene_prompt`/`build_fallback_prompt` — stop Python-gluing
  `"The protagonist is..."` role-label prefixes into the final image prompt. Follow
  `scene_engine.py:author_story_beat`'s existing correct pattern in this same repo: give
  the model appearance/context in its own instructions and let it author the final
  visual-only sentence as one output field, the way breakdown-pro's per-scene calls do.

**Tests to drop alongside their mechanism** (pin the second-judge flow or the taste
heuristics above, not real logic): `test_small_accessories_are_rejected_from_locked_identity`,
`test_director_supporting_role_must_recur`, `test_character_retry_includes_previous_json`,
`test_profile_contract_review_payload_excludes_casting_details`, both tests in
`test_prompt_safety.py`. Everything else in `tests/` tests genuine deterministic logic
(verbatim slicing, lossless reconstruction, chronological beat assignment, id/reference
integrity) and stays.

**Executed 2026-07-29.** All cuts/relocations above landed:
`story_dossier`, `character_ledger`, `visual_director`, `scene_compositor` each lost their
second-LLM-judge call(s); the five visual_director ratio heuristics and character_ledger's
word-count/dedup heuristics were relocated into their generation prompts as global-scope
guidance instead of deleted outright; the confirmed `scene_compositor` role-label leak is
fixed via a model-authored final prompt field (`_author_visual_prompt`, mirrors
`scene_engine.py:author_story_beat`'s existing correct pattern); `script_spans` dropped
entirely from the character schema (dead weight, never consumed downstream); the two dead
`.get(..., default)` fallbacks and the unused `_assign_snippets_to_beats` `script` param
are gone. Test suite trimmed to 12 tests, all passing, all deterministic (no network calls)
— cut the 4 planned tests plus one bonus stale test discovered only by running the suite
(`test_bridge_cue_requires_exact_source_evidence`, pinned a verbatim-reject behavior a
prior session had already downgraded to tolerant, never updated to match). Kept
`test_character_retry_includes_previous_json` against the original plan's classification —
turned out to still validate real surviving behavior (the retry-with-feedback loop against
the objective empty-field check), not the deleted judge call; only its dead review-schema
branch and `script_spans` fixture needed cleanup, not removal. `test_prompt_safety.py`'s
name-scrubbing coverage moved from an incidental assertion on `build_scene_prompt` (now a
real LLM call) to a direct deterministic test of `_anonymize_names` itself.

**Step 6 completed 2026-07-29, later same day**, once OpenAI quota was restored (the
earlier `insufficient_quota` was an account billing issue, unrelated to the rework). Ran a
real, no-cache pass through all four rewritten agents (`scratchpad/verify_rework.py`) on
the Maria/Pastor Daniel sample script. Hit one unrelated pre-existing issue along the way:
`story_dossier.build()`'s first call (untouched by this rework) burned its entire
6144-token budget on reasoning with `gpt-5-mini` and returned zero output text — bumped
`max_completion_tokens` 6144→12288 for that one call so verification could run; this is an
infra/budget fix, not part of the de-heuristic plan.

Results — every stage converged on the first attempt, zero retries anywhere:
- story_dossier picked a concrete, non-stereotyped occupation ("Freelance UX/Service
  Researcher") on its own, no judge call needed.
- character_ledger produced 2 genuinely distinct characters (32yo Latina protagonist vs.
  48yo White male pastor) with no near-duplicate-appearance warning — the removed 40-char
  dedup heuristic wasn't needed; the "make each character distinct" prompt guidance alone
  did the job.
- visual_director invented one supporting character and 5 recurring locations spanning
  genuinely distinct domains (domestic/freelance, civic/community, startup/freelance,
  faith, neighborhood ethnography) — satisfies the relocated "≥3 distinct social domains"
  guidance purely from prompt text, no Python ratio-check ran. 7/9 beats public, busiest
  location used only 3/9 times — both satisfy the relocated pacing guidance the same way.
- scene_compositor's `build_scene_prompt()` produced one natural authored sentence with no
  leaked structural label ("protagonist"/"supporting character" both absent) — the original
  bug this whole audit started from is confirmed fixed.

Target met: the model's own judgment, guided by sharper prompts at the right scope,
satisfied every goal the deleted Python heuristics used to gate — without a second LLM
judging the first, and without a single retry.

## Phase: i2i pivot (2026-07-29, same day)

Moved `agents/scene_compositor` from t2i-with-restated-appearance-text to i2i via
gpt-image-2's own `images.edit()`, conditioned on each present character's own reference
image — deliberately reversing the "t2i only, for now" hard rule now that the audit above
already fixed t2i's biggest failure mode. Backend: gpt-image-2's edit endpoint (not Krea —
`src/krea.py:krea_edit_photo()` stays unused, its token stays parked in
`sleep-stories/.env.local`).

- `utils/images.py:shrink_for_upload()` — new: downscales a reference image (longest edge
  768px) and re-encodes as JPEG (quality 80) before every edit call. Measured live: a
  ~990KB t2i-generated PNG reference shrank to ~14-15KB, roughly 60-65x smaller.
- `src/gpt_image.py:edit_image()` — new: same retry/upload shape as `generate_image()`,
  but calls `client.images.edit(model=..., image=[...], prompt=...)` with a list of
  reference image files instead of pure text.
- `agents/scene_compositor/client.py` — rewritten: `build_scene_prompt()` is now
  deterministic and carries the visible action ONLY, no appearance text at all (nothing
  left for a role label to leak into — the earlier `_author_visual_prompt` LLM-authoring
  step from the de-heuristic rework above is now dead code and was removed, since the
  problem it solved — weaving appearance text in without leaking role labels — no longer
  exists once appearance text isn't in the prompt at all). `_fetch_reference_bytes()`
  downloads+shrinks every tracked character's reference once per `compose_all()` call,
  reused across every scene. `compose_one()` uses i2i (`edit_image`) when every present
  character has a usable reference; otherwise falls back to t2i (`generate_image`, full
  appearance text via the unchanged `build_fallback_prompt`) — same fallback shape as
  before, still deterministic, still no role-label framing.
- Contract version bumped 4→5.

Verified live twice (`scratchpad/verify_i2i.py`): generated a real reference image, then
successfully edited it into a scene via the new path — `generation_method: "edit"`, real
`image_url` returned, ~60x reference-size reduction confirmed. Caught and fixed one
cosmetic bug from the first live run (missing punctuation between the action sentence and
the reference-match instruction, e.g. "...beside her Depict each..." — no period). Second
live run confirmed the fix. Unit test suite (12 tests) still green throughout — none of
them exercised the new i2i path, since it needs real images; only the deterministic
`build_scene_prompt`/`build_fallback_prompt`/`_anonymize_names` pieces are unit-tested.
`agents/CLAUDE.md` and root `CLAUDE.md` (stage list, Layout, credentials note) updated to
describe i2i-by-default instead of t2i-only.
