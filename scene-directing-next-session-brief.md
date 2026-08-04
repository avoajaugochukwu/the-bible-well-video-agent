# Scene-directing next-session brief

Written 2026-08-03, end of a session that restructured the character-consistency/scene
generation stack into small single-responsibility agents, then validated the result against
the Hannah script and fixed everything the validation surfaced. Read this whole file before
touching `agents/` or `src/scene_engine.py` — it's the only record of what changed and why;
the old brief this file replaces is gone.

**Nothing in this session has been committed.** Everything below is still working-tree
changes. Do not commit or push without an explicit ask — unchanged standing rule.

## What changed — the agent roster

`agents/visual_director` and `agents/scene_compositor` are deleted. In their place:

| Module | Job | Contract version |
|---|---|---|
| `agents/emotion_scout` | Per-beat categorical score (story_pressure/valence/tempo/camera_distance) **plus** `emotional_stakes` (why this moment matters) and `expression_directive` (one overt, legible physical direction — tears, hands to head, open laughter) | `EMOTION_SCOUT_CONTRACT_VERSION = 1` |
| `agents/world_builder` | Invents the one shared film world (title, style, cast, locations) from emotion_scout's score. Unchanged logic from the old visual_director's second pass. | `WORLD_BUILDER_CONTRACT_VERSION = 1` |
| `agents/location_scout` | One location per beat, extracted from `scene_engine.py`'s old inline `assign_locations()`. Grandeur-matching (a wedding gets a real venue, not a folding-chair room) plus **sequential chunking with cross-chunk continuity carry-forward** (see bug #2 below) | `LOCATION_SCOUT_CONTRACT_VERSION = 3` |
| `agents/recognition_director` | Proposes ONE iconic visual anchor per significant beat — architecture OR people/attire (a bride and groom at the altar, mourners in black), empty for ordinary beats | `RECOGNITION_DIRECTOR_CONTRACT_VERSION = 2` |
| `agents/recognition_reviewer` | Post-hoc: rewrites `image_prompt` only when a significant occasion doesn't already read as iconic | `RECOGNITION_REVIEWER_CONTRACT_VERSION = 2` |
| `agents/drama_reviewer` | Post-hoc: rewrites `image_prompt` only when the rendered expression is too subdued for the beat's own stakes | `DRAMA_REVIEWER_CONTRACT_VERSION = 2` |
| `agents/scene_renderer` | Renamed from `scene_compositor`, same i2i/t2i logic, `RENDERER_CONTRACT_VERSION` (was `COMPOSITOR_CONTRACT_VERSION`) | `= 6` |

`agents/story_dossier`, `agents/character_ledger`, `agents/character_sheet`,
`agents/character_wardrobe` are unchanged.

**The recognition_reviewer/drama_reviewer pair is a deliberate, user-approved exception to
`agents/CLAUDE.md` rule 2** ("no second LLM judges the first LLM's taste") — flagged to the
user before building, they chose to build it anyway. There's a dated carve-out note in
`agents/CLAUDE.md` explaining the narrow scope both reviewers are held to (may only ADD one
detail to an existing prompt, must return it unchanged verbatim when no change is needed,
never re-author subject/action/characters/framing). If they stop converging the way that rule
predicts, the fix is pushing their judgment upstream into the pre-pass agents, not a third
reviewer — say so explicitly rather than reaching for another reviewer.

`src/scene_engine.py`'s `author_literal_beat`/`author_story_beat` (the shot planners) are
still where `character_ids` gets decided — that logic was never a separate `agents/` module
and still isn't. `PROMPT_CONTRACT_VERSION` is now 20.

Stage order (`src/run.py`): baserow → context → dossier → characters → `emotion_scout.score()`
→ `world_builder.build()` → `break_into_scenes()` (internally: `location_scout.assign()` →
`recognition_director.assign()` → local_context computed → shot authors) →
`recognition_reviewer.review()` → `drama_reviewer.review()` → wardrobe → images
(`scene_renderer`) → align → render/S3/ClickUp. `docs/architecture.md`'s stage table is now
1-13 (was 1-12) — REVIEW is the new stage 7.

## Three real bugs found by actually running the pipeline, and how they were fixed

Don't assume the restructuring above is correct on paper — every one of these was invisible
until a live 20-scene run against the Hannah script surfaced it. **Rebuild a similar disposable
harness next session before trusting any further prompt change** — the ones used this session
(`round3_hannah.py`, `round4_grid.py`) lived only in this session's scratchpad, not committed,
gone now. Shape: cache `context`/`story_dossier`/`characters` (a JSON blob keyed by script
hash, since those three stages are unaffected by scene-authoring changes and cost real money to
regenerate), always run everything downstream fresh (that's the actual code under test), cap at
~20 scenes, generate real images, dump an HTML page to eyeball the result.

1. **`location_scout` silently returned empty locations.** Root cause: a flat
   `max_completion_tokens=2048` was too tight once the grandeur-matching instruction asked for
   richer venue descriptions, and unlike every sibling module, `location_scout` had no
   retry-with-validation loop at all. Fixed: scaled token budget (`min(max(2048, 400*n),
   32000)`) + a real `MAX_ATTEMPTS` retry loop with a `_validate()` fact-check (count match,
   non-empty).

2. **Cross-chunk location continuity break.** Even after fix #1, one continuous scene (a
   single sentence in the script, chopped into 7 tiny snippets by `cut_narration_scenes`) got
   split across a chunk boundary (chunk 2 = snippets 9-16, chunk 3 = snippets 17-20) and
   silently renamed mid-scene — "St. Luke's Episcopal Church" for the snippets in one chunk,
   "St. Agnes Episcopal Church" for the rest — because chunk 3's LLM call had zero memory it
   was the same event. Fixed: `location_scout.assign()` now runs chunks **sequentially** (no
   more `ThreadPoolExecutor`), carrying the previous chunk's last snippet + its assigned
   location forward as explicit context into the next chunk's prompt. `location_scout`'s own
   `__main__` self-test now specifically forces `CHUNK_SIZE=1` to prove continuity survives a
   boundary.

3. **Content corruption on repeated strings.** Even with the count/non-empty check, repeating
   the same long location string 5-8 times in one array corrupted an em dash or curly
   apostrophe into a stray `\x19` control byte (a decoder artifact, not a prompt problem).
   Fixed: added a `_has_control_chars()` fact-check (any codepoint < 32 except tab/newline) to
   `location_scout`, `recognition_director`, `recognition_reviewer`, and `drama_reviewer` — all
   four share the identical "chunked array of strings, some repeated" shape and were all
   equally exposed.

## The deeper architectural gap the user caught by eye

After bugs 1-3 were fixed, the user watched the actual output and found the real remaining
problem: **the protagonist appeared in every one of 7 church-wedding scenes, standing in the
same outfit, and one beat even hallucinated a casket** — because `author_literal_beat` was
authoring each beat from ONLY that beat's own isolated narration fragment (some as short as
2-3 words: `"white roses"`, `"and baby's breath,"`). A fragment that short cannot tell the
model it's even looking at a wedding, let alone that a wide shot of the actual couple at the
altar might fit one of these beats better than the protagonist standing still yet again.

User's own framing, worth repeating verbatim for how it should generalize: *"if you give
agents just in-time information they miss the big picture"* — local context has to include
enough of the surrounding scene (not the whole script, not full lookahead across the whole
film, but the actual continuous event this beat is part of) for a beat-level decision to be
sane.

Fixed this session:
- `scene_engine.py` gained `_local_contexts()`: groups snippets into contiguous runs by
  identical assigned location (the same grouping `location_scout` already computed), and for
  any run longer than one beat, joins the full text of every snippet in that run and passes it
  into `author_literal_beat` as a new `local_context` param — read-only background, not this
  beat's own content to illustrate.
- `author_literal_beat`'s prompt now explicitly: (a) uses `local_context` to recognize the
  occasion type and stay grounded in it, (b) is told to NEVER invent a prop with its own strong
  narrative weight (a casket, a ring box, a diploma) unless the narration or local_context
  actually names it, (c) **defaults to leaving the protagonist OUT** of a beat whose local
  context describes a shared occasion centered on someone else, rather than defaulting her in
  because she's the film's throughline.
- `recognition_director` expanded from architecture-only anchors to allow people/attire
  anchors too (an officiant, a couple at the altar, guests in bright formalwear vs. mourners in
  black) — inferred from `emotional_stakes`, since that's what actually makes a ceremony scene
  "pop," not just a nicer room.

Confirmed fixed in the round-4 rerun: one location held across all 9 church-wedding beats,
protagonist correctly absent from 4 of them, the actual bride/groom/couple now visible at the
altar in two beats, no more hallucinated objects.

## What's NOT done — flag before building, don't assume

1. **Only validated a 20-scene sample, one script.** The whole pipeline (wardrobe → images →
   align → render) was never run end-to-end since this session's fixes landed. `local_context`
   in particular has only been exercised on ONE multi-beat run (the church wedding) — it's
   never been checked against a *different* kind of long continuous scene (a funeral, a
   confrontation, an ordinary multi-beat conversation) to confirm it generalizes rather than
   having been prompt-engineered to this one example.
2. **Minor, deliberately not fixed:** `recognition_cue` (diagnostic field only — never reaches
   the actual render prompt, `scene_renderer` doesn't read it) sometimes echoes the
   protagonist's script name ("Hannah") instead of "protagonist." Traced to
   `emotion_scout.emotional_stakes`, which sees raw narration and can echo a name straight from
   the script. Low priority since it never reaches image generation, but flag it if the
   production UI ever surfaces `recognitionCue` directly to a non-technical reviewer.
3. **`web/` UI plumbing added, no UI built yet.** `location`/`recognitionCue` were added to
   `src/supabase_jobs.py`'s `build_job_payload()` and `web/lib/types.ts`'s `Scene` interface (so
   the data survives to the production UI's payload), but no actual UI component displays them
   yet. Purely additive/optional fields — safe to leave as-is or build a display for them,
   ask which.
4. **HTML validation artifacts, for reference only, not part of the app:**
   `scene-directing-holy-grail.html` (rounds 1-3, vertical card layout, ~43MB) and
   `scene-directing-grid.html` (round 4 only, grid layout for multi-glance screenshotting,
   ~34MB, the format the user wants going forward — **build new rounds as fresh grid files,
   don't append to the old vertical-card file**). Both are self-contained base64 dumps, not
   meant to be committed as-is — ask before committing either.
5. **Naming is locked, don't re-litigate it.** `emotion_scout`, `world_builder`,
   `location_scout`, `recognition_director`, `recognition_reviewer`, `drama_reviewer`,
   `scene_renderer` were all explicitly chosen by the user via direct questions this session.
   Don't rename anything without being asked again.

## Reference material

- `she-thought-god-forgot-her-script.txt` (repo root) — the Hannah script, unchanged this
  session except for whatever upstream edit already shows in the working tree diff.
- No disposable test harness survives from this session (see "rebuild a similar harness"
  above) — the two used (`round3_hannah.py`, `round4_grid.py`) lived only in scratchpad.
