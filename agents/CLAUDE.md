# CLAUDE.md — agents/ (character-consistency stack)

Directory-scoped instructions for `agents/` (`story_dossier`, `character_ledger`,
`character_sheet`, `visual_director`, `scene_compositor`). Root `CLAUDE.md` owns the
overall pipeline SOP (Baserow/ClickUp/S3, stage order, run.py); this file owns how the
agents in this directory are built and how they're allowed to change.

## Ownership

`src/scene_engine.py` (scene breakdown + classification) and `src/gallery.py` (review
HTML) are built and maintained as their own unit, closely coupled to this directory's
narration/visual lane split. `agents/story_dossier`, `agents/visual_director`,
`agents/character_ledger`, `agents/character_sheet`, and `agents/scene_compositor` are
their own unit too. Contract versions on context, character, visual-story, and scene
artifacts force stale cached work to regenerate when any authored interface changes.

## The operating philosophy — read this before writing any agent code

This is a chat, played out in code, not a deterministic pipeline with an LLM bolted on.
Every `agents/*/client.py` call is a conversation turn; the fix for a bad conversation is
a better next message — not a new Python gate. Modeled directly on two sibling repos that
already live this way: `military/agents/` (entity_ledger, checks.py) and
`service/scene-generation-service`'s breakdown-pro path.

**1. Schema is the only reject condition.**
Every LLM call is structurally schema-constrained (OpenAI strict `json_schema` / Pydantic
`extra="forbid"`) so the decoder cannot emit an off-schema response. If it parses, it's
accepted. No "does this look good" second opinion.

**2. No second LLM judges the first LLM's taste.**
One generate call, one deterministic validate, retry the *same* model with fix-required
feedback. A reviewer model grading another model's output is where this repo's retry
loops stopped converging — taste can't be arbitrated by a second non-deterministic system
any better than the first one produced it.

**3. Deterministic Python checks facts, never taste.**
Facts: does this id exist, is this a duplicate, does the reconstructed text match the
source losslessly, does the count match what the schema already requires. Not facts:
word-count floors, "half the beats must be public," recurrence thresholds, string-prefix
dedup heuristics. If a check is guessing whether something is *good*, it's not a fact —
move it into the prompt as guidance for the model making that call, don't code it as a gate.

**4. Every instruction has a scope — global, regional, or scene — and lives at that scope.**
- **Global**: decided once for the whole film/video. Casting, wardrobe, the invented
  world's shape and variety (how many locations, how varied the social domains). Lives in
  the one call that owns the whole picture (story_dossier, visual_director's single
  world-building call).
- **Regional**: applies to a phase, act, or beat-range, not the whole film and not one
  scene. Pacing/tempo/camera-distance per emotional phase is regional.
- **Scene**: affects exactly one shot/one image. The final compositor sentence, one
  beat's specific visible action.
Before writing an instruction, name its scope. A rule that's actually global (e.g. "this
world needs real variety in where it happens") does not belong as a per-scene Python
count-check after the fact — it belongs as one sentence in the global call's prompt,
trusting the model to satisfy it while inventing the whole world at once.

**5. Concatenation is for identity, not for structure.**
Only two things get glued into a final prompt by code, ever: the character's locked
visual profile (so the same character reads the same way every time) and whatever raw
context a call genuinely needs carried forward (e.g. the director's tone/world blurb, fed
as context into each scene call — same as breakdown-pro's `NARRATIVE CONTEXT:` injection).
Internal labels — role slugs like `protagonist`, ids, contract-version bookkeeping — never
ride along into a string a model or a human reads as content. If a piece of text needs
constructing from parts, prefer having a model write it as one shaped output field over
Python string-concatenation assembling it — a model asked to write one visual sentence
won't accidentally narrate its own scaffolding the way an f-string will.

**When something's wrong, fix order:**
1. Can the prompt say it more specifically, at the right scope?
2. Can one call split into two more targeted calls (global vs. regional vs. scene), or
   can a narrow exception get carved into an existing prompt for the one case that needs it?
3. Only if the guarantee is genuinely objective and structural — not a taste call — does a
   deterministic Python check get added, and it checks a fact, not a heuristic.

Reaching for step 3 to solve a step-1 problem is exactly what put this directory where it
was found on 2026-07-29's audit: a stack of second-opinion LLM calls and ratio-guessing
Python gates trying to deterministically pin down something that was never going to
converge that way. A new hard rule is the wrong instinct; a sharper prompt or a scoped
exception is the right one.

## Standing rules specific to this stack

- **Narration and visuals are two separate lanes.** Narration is cut into verbatim visual
  pacing beats using the homestead pattern: an LLM proposes boundaries, code anchors them
  losslessly to the source, and a 30-word ceiling prefers sentence or clause boundaries.
  The narration content never supplies scene props, locations, or actions to the shot
  planner. `agents/story_dossier` first separates evidence-backed source facts from
  production inference, chooses one plausible occupation from an abstract character
  profile, and commits to concrete casting. `agents/visual_director` reduces the source to
  a categorical emotional score, then invents a standalone contemporary film with its own
  external goal, recurring social locations, cause-and-effect plot, and resolved ending.
  `src/scene_engine.py` expands each ordered film beat into shots without receiving
  narration. Do not turn narration cuts into per-sentence illustration or source-noun
  prompting. Show emotion through body language and social situation: despair is a woman
  with her head in her hands during lived activity, not the narrated book in her hands.
- **Bridge the two lanes with sparse literal cues.** The source-aware emotional pass may
  extract a few portable tools, materials, textures, gestures, or garment actions from
  each phase. The independent director can select one only where it fits its invented
  plot, and the shot planner carries that selected cue into the beat. This is deliberate
  visual rhyme, not permission to recreate the narrated event, location, relationship, or
  religious symbol. Garment actions always use the locked character outfit rather than
  inventing another coat.
- **Use affirmative image prompts, not safety vocabulary lists.** The Images API has no
  negative-prompt channel. Do not append `negative_prompt` or banned-word lists to
  ordinary prompt text; that previously caused avoidable gpt-image-2 moderation matches.
  The compositor uses concise renderable direction and positive composition constraints.
- **Recurring, full-body characters — not a stock-figure default.** Every script gets its
  own character ledger, built once up front by `agents/character_ledger:build(script,
  context)`: the protagonist is always tracked, Jesus only if he actually appears, any
  other character only if they recur across multiple beats (never a one-off mention).
  Each tracked character gets one full-body reference image
  (`agents/character_sheet:generate_all()`, gpt-image-2 t2i, `quality=low`).
  `src/scene_engine.py`'s scene authoring then tags every scene with which tracked
  characters (`character_ids`) are visually present, and `agents/scene_compositor`
  generates that scene's image referencing them by name/appearance. No fixed per-channel
  design and no stick figures.
- **Characters are locked production specifications, not loose prose.** The approved
  character-profile standard names every stable visual decision: exact age, ethnicity,
  height, build, skin tone, face shape, cheek structure, eye color/shape, nose, lips, age
  markers, glasses, deterministic hair color/cut/length/part/finish, inner shirt, outer
  layer and exact closure state, bottom, and footwear. Hair accessories and wearable
  non-jewelry accessories are always explicitly absent: small persistent objects are
  fragile continuity details, not identity. Jewelry also defaults to none and is allowed
  only when the source explicitly makes one stable worn item identity- or plot-critical.
  Eyewear is allowed because it materially defines the face. Bags and handheld objects
  remain scene props. Avoid variable traits such as unspecified bobs or salt-and-pepper
  patterns. Repeat the complete compact profile in every image prompt where that character
  appears; keep style direction light and let the image model handle rendering. Names
  remain internal and are removed before Images API calls because common names can
  trigger public-figure matching.
- **Final image prompts stay compact, and role labels are structure, not content.** The
  final Images API input is a short 16:9 style sentence, the authored visible scene
  action, and the complete deterministic compiled profile for each visible character —
  written as one model-authored sentence per rule 5 above, never Python-glued from role
  labels (`"the protagonist is..."`) plus appearance fields. `visual_story.movie_style` is
  planning context for the shot author only, never appended to the final compositor
  prompt. `COMPOSITOR_CONTRACT_VERSION` invalidates images when final prompt construction
  changes.
- **No automated vision-QA, anywhere.** Whether a generated image matches its expected
  character(s) is a human call made off the gallery review (`src/gallery.py`), not a
  gpt-4o vision gate — keeps cost down; this is a story pipeline, not a verification
  pipeline.
- **i2i by default, t2i as fallback only.** `agents/scene_compositor` generates each scene
  via gpt-image-2's own `images.edit()`, conditioned on every present tracked character's
  reference image (`src/gpt_image.py:edit_image()`) — identity comes from the image, not
  restated appearance text, so there is nothing for a role label to leak into. Reference
  images are downloaded and shrunk once per character (`utils/images.py:shrink_for_upload()`,
  longest edge capped, re-encoded as JPEG — cuts edit-call input size by ~60x in practice)
  and reused across every scene that character appears in. Falls back to plain t2i
  (`gpt_image.py:generate_image()`, full appearance text via `build_fallback_prompt`) only
  when a present character has no usable reference image, or the edit call itself is
  rejected. `src/krea.py`'s own img2img (`krea_edit_photo()`) remains unused — this pipeline
  now does i2i through gpt-image-2's own edit endpoint instead.

**Anti-Jesus regression bias (known gpt-image-2 failure mode):** faith-themed image
generators default ANY unspecified secondary character into a long-haired, bearded Jesus
in robes. Every non-Jesus character must carry an explicit concrete gender, ethnicity,
hairstyle, and ordinary modern clothing in `agents/character_ledger`'s per-character
`appearance` field — a bare "a person"/"a figure" is what triggers the regression. Do not
counter this with a negative prompt list; use concrete positive character descriptions.
