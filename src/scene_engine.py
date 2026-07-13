"""Script -> scene breakdown -> per-scene gpt-image-2 monochrome stick-figure image.
Two stages, both here since every caller needs both in sequence:

  break_into_scenes(script) -> OpenAI chat-completions calls (gpt-5-mini, raw urllib, this
                                repo's house style). Returns
                                [{scene_number, script_snippet, hero_subject,
                                image_prompt, negative_prompt, scene_type}, ...] — every
                                scene is a monochrome stick-figure illustration, no lane routing.

                                Scene-splitting follows mechanical, LLM-free sentence chunking
                                (chunk_script(), ~8 sentences/chunk) feeding ONE combined LLM call
                                per chunk (author_chunk()) that cuts scenes (list-cut / staccato /
                                merge-cap rules) and writes hero_subject + image_prompt together.
  generate_images(scenes)    -> asset_selector.py:route() per scene, IN PARALLEL
                                (gpt-image-2 generation is I/O-bound, scenes are independent).
                                Returns each scene with an added image_url.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "utils"))

import env                     # utils: one .env lookup (checks root .env)
import align                    # utils: Whisper-word <-> verbatim-scene DTW aligner

MODEL = "gpt-5-mini"
OPENAI_API = "https://api.openai.com/v1/chat/completions"

# Fixed quality/SFW negatives appended to every scene's period-specific
# negative — ported verbatim from sleep-stories' scene-image.ts BASE_NEGATIVE
# / SFW_NEGATIVE. Constant, never LLM-generated.
SFW_NEGATIVE = (
    "nsfw, nude, nudity, naked, sexual, sexually explicit, sex, erotic, porn, "
    "suggestive, cleavage, lingerie, fetish, gore, gory, blood, bloody, open "
    "wound, wounds, injury, mutilation, dismemberment, corpse, dead body, "
    "viscera, guts, decapitation, violence, graphic violence, disturbing, horror"
)
BASE_NEGATIVE = (
    f"{SFW_NEGATIVE}, text, caption, watermark, logo, signature, readable text, "
    "legible text, written words, letters, lettering, typography, gibberish text, "
    "illegible writing, visible handwriting, book pages with text, newspaper print, "
    "map labels, street signs, blurry, lowres, deformed hands, extra fingers, "
    "distorted anatomy, oversaturated, grainy, headless, neck crop, cut off head"
)

# Appended to negative_prompt whenever a scene has a supporting character but not
# Jesus — faith-themed image generators default any unspecified secondary
# character into a robed, bearded Jesus look without this.
JESUS_NEGATIVE_BLOCK = "Jesus, biblical robes, bearded man, long hair, ancient tunic, halo"

# Image models (gpt-image-2) routinely render an extra unrequested person in group scenes —
# same class of hallucination as the Jesus regression, just headcount instead of
# identity. The LLM self-reports intended headcount via people_count; code then
# force-appends a deterministic negative_prompt guard rather than trusting the
# image model to respect a bare number mentioned once in the prompt.
COUNT_NEGATIVE_BLOCKS = {
    1: "second person, another person, additional figure, extra man, extra woman, companion, crowd, group of people",
    2: "third person, extra person, additional man, additional woman, additional figure, crowd, group of three or more",
    3: "fourth person, extra person, additional figure, crowd, group of four or more",
}

# Fixed, channel-wide Jesus design — NOT LLM-generated per script, NOT drawn as the
# monochrome stick figure. Distinct on purpose: fuller color/detail so he visually
# stands apart from the anonymous protagonist, matching the reference style (a
# muted-sketch monochrome everyman contrasted with a warmer, fuller-color Jesus).
JESUS_APPEARANCE = (
    "a compassionate hand-drawn ink-sketch man in his early-to-mid 30s with warm olive "
    "skin, flowing shoulder-length dark brown hair worn loose with no head covering of any "
    "kind (no turban, no headscarf, no headgear), a short well-kept beard, gentle warm "
    "eyes, wearing a simple flat tan garment with a flat blue-grey sash draped over one "
    "shoulder, calm reverent bearing, a soft flat golden glow outline around him — "
    "rendered in muted flat color, not the monochrome stick-figure style"
)

# Fixed, channel-wide protagonist design — a single anonymous stick figure that looks
# IDENTICAL in every scene of every video, never LLM-invented or varied per script.
# This is the one deliberate deviation from the old per-script character system: the
# story follows ONE person, drawn so plainly (no ethnicity, no wardrobe, no named
# supporting cast) that "consistency" is free — there's nothing left to drift.
PROTAGONIST_APPEARANCE = (
    "a simple black-ink hand-drawn stick figure: a plain round head outline with two "
    "small dot eyes and a thin simple mouth line (no hair detail beyond a small simple "
    "hairline squiggle), a thin single-stroke neck and torso, thin single-stroke arms and "
    "legs, loose sketchy hand-drawn crosshatch texture on the linework, absolutely no "
    "color fill and no clothing detail on the figure itself — gender-neutral, ageless, "
    "identical in every scene"
)

# Anonymous background/crowd figures (society, a biblical-era village, disciples,
# onlookers) — NOT a named supporting cast. Flat, faceless, interchangeable; the
# camera and story never lingers on them as individuals.
CROWD_APPEARANCE = (
    "flat solid grey-silhouette figures with no facial detail, simplified and "
    "interchangeable, rendered smaller/further back than the protagonist"
)

# Intent-to-visual reference bank, compiled from studying one real Christian-content
# explainer video (frame-by-frame) plus general faith-content visual grammar. This is
# DIRECTIONAL, not a template — see the "INTENT OVER LITERALISM" instruction in
# author_chunk() for the explicit don't-overfit rule given to the model.
CHURCH_GLOSSARY = """
CHURCH-CONTENT INTENT -> VISUAL METAPHOR REFERENCE (a director's mood board, not a
menu — invent freely beyond this list using the same visual grammar: forking paths,
floating icon clusters, light vs. shadow, growth, doors/gates, water, seeds/harvest,
armor, storms/anchors, lamps, shepherd/flock, tables/altars, scales, chains):

- Sunday-only / compartmentalized faith -> a path forking toward a small church/cross
  icon on one side, ordinary errands (shops, a phone) on the other — NOT a literal
  calendar page.
- Prayer / talking to God -> figure kneeling or hands cupped together, a soft warm
  glow rising from the hands or a faint upward light shaft.
- Scripture / "the Word" -> a simple open book glowing softly, or light spilling from
  its pages — never legible text on the page.
- Checking phone before praying -> figure reaching for a glowing phone icon beside
  the bed, phone brighter/closer than everything else in frame.
- The enemy / temptation / sin's pull -> a shadow-silhouette version of the
  protagonist looming behind or reaching toward them.
- Carrying guilt, shame, or burden -> figure straining under a heavy stone or
  sack icon on their back.
- Breakthrough / freedom -> chain-link icons shattering around the figure as they
  look upward.
- Surrender / giving God control -> figure in a car's passenger seat while Jesus
  (or a radiant light) holds the steering wheel.
- Obedience before understanding -> figure taking a single step onto a lit path that
  only illuminates one step ahead, the rest in shadow.
- Chasing money / status / validation -> figure running toward a floating cluster of
  coins, cash, and a trophy icon.
- Chasing approval / social media -> figure surrounded by floating thumbs-up / heart
  / like-button icons.
- Peace vs. anxiety -> figure standing calmly at the center of a storm, swirling
  dark clouds and debris held back at a clear boundary around them.
- Faith as an anchor -> figure holding a simple anchor icon while waves/wind icons
  swirl past them.
- Small, faithful beginnings -> figure planting a single glowing seed into open
  ground.
- Spiritual growth over time -> a small glowing sprout growing into a full tree
  across a sequence, or rings on a tree stump.
- Harvest / reward for faithfulness -> figure holding a basket overflowing with
  glowing fruit or grain.
- Being called / purpose -> figure standing at a crossroads where one path glows and
  the others stay dim.
- Wilderness / hard season -> figure walking alone across a bare, muted-color desert
  or empty plain, one small light on the horizon.
- Community / fellowship -> a small circle of anonymous grey-silhouette figures
  seated or standing around the protagonist, no individual faces.
- Shepherd and flock -> a shepherd-icon figure with a staff beside a small cluster of
  simple sheep icons.
- Armor of God / spiritual protection -> figure with simple flat icon pieces (shield,
  helmet outline) floating into place around them.
- Light vs. darkness -> a hard visual split down the frame, warm light filling one
  half and cool shadow filling the other, the figure standing at the boundary.
- Narrow path vs. wide path -> two forking roads, one narrow and softly lit, one wide
  and crowded with anonymous grey-silhouette figures.
- Grace / undeserved gift -> a glowing gift or open hand extended toward the figure
  from off-frame or from Jesus.
- Forgiveness -> a heavy dark icon (stone, chain, weight) dissolving into light
  particles near the figure's chest.
- Identity in God vs. the world's labels -> figure standing between a cracked mirror
  showing a distorted reflection and a calm, plain reflection.
- Doubt / fear -> figure small in frame, surrounded by looming oversized shadow
  shapes that don't quite touch them.
- Joy / peace / patience (fruit of the Spirit) -> soft glowing particles or blossoms
  drifting around a calm, still figure.
- Testimony / sharing faith -> figure with a small glowing light stepping toward a
  cluster of anonymous grey-silhouette figures, offering it outward.
- Baptism / new life -> figure emerging from a simple flat-color water shape, old
  shadow self left behind at the water's edge.
- Fasting / self-denial -> figure turning away from a table of food icons toward a
  single light source.
- Legacy / generational faith -> a small line of progressively smaller anonymous
  silhouette figures walking the same lit path.
- Rest / sabbath -> figure seated still while a cluster of clock/task/notification
  icons hover just out of reach, unanswered.
- Idols of comfort/success -> figure bowing toward a small floating icon (a house,
  a trophy, a screen) as if it were an altar.
"""

CONTEXT_SCHEMA = {
    "name": "story_context",
    "schema": {
        "type": "object",
        "properties": {
            "setting": {"type": "string", "description": "the faith-practice setting this script actually lives in — could be everyday daily-life scenes (home, commute, workplace), church/worship-life scenes, or scripture-era scenes, whatever this specific script calls for. Described in flat muted-background whiteboard terms, e.g. 'plain muted-color background with simple 2D outline props'. Do not default to generic 'modern lifestyle' framing — read what THIS script is actually about."},
            "spiritual_theme": {"type": "string", "description": "core spiritual transformation theme, e.g. 'faith, surrender, obedience, forgiveness' — read from THIS script, don't default to any one theme"},
            "emotional_palette": {"type": "string", "description": "muted flat color accent palette for the illustration's fills, e.g. 'warm sepia and dusty blue accents, hopeful tones'"},
        },
        "required": ["setting", "spiritual_theme", "emotional_palette"],
        "additionalProperties": False,
    },
}

# Scene types for spiritual journey — all scenes focus on faith transformation.
SCENE_TYPES = ["spiritual_moment", "transformation", "revelation", "decision", "reflection"]

_CLASSIFICATION_PROPERTIES = {
    "scene_type": {
        "type": "string",
        "enum": SCENE_TYPES,
        "description": (
            "spiritual_moment: a quiet personal encounter with faith or God's presence. "
            "transformation: a visible change or breakthrough in the protagonist's faith. "
            "revelation: understanding or realization about God or faith. "
            "decision: a choice point where the protagonist chooses faith/obedience. "
            "reflection: internal pondering, prayer, or spiritual contemplation."
        ),
    },
}


def _chunk_author_schema() -> dict:
    """Scene COUNT is decided by the model per chunk (list-cut/staccato rules mean
    an 8-sentence chunk can yield anywhere from 1 to ~15 scenes) — unlike the old
    fixed-batch schema, there's no known n up front to pin minItems=maxItems to.
    maxItems=20 is a sanity guardrail (an 8-sentence chunk producing more than that
    would mean the split rules broke down), not a real target."""
    return {
        "name": "authored_scenes",
        "schema": {
            "type": "object",
            "properties": {
                "scenes": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 20,
                    "items": {
                        "type": "object",
                        "properties": {
                            "script_snippet": {"type": "string"},
                            "hero_subject": {"type": "string"},
                            "image_prompt": {"type": "string"},
                            "negative_prompt": {"type": "string"},
                            "people_count": {
                                "type": "integer",
                                "enum": [1, 2, 3],
                                "description": (
                                    "Exact number of people (including the protagonist) "
                                    "depicted in image_prompt for this scene — 1 if the "
                                    "protagonist is alone, 2 if with one supporting character "
                                    "or Jesus, 3 if with two others. Must match image_prompt "
                                    "exactly, no more, no fewer."
                                ),
                            },
                            **_CLASSIFICATION_PROPERTIES,
                        },
                        "required": ["script_snippet", "hero_subject",
                                     "image_prompt", "negative_prompt", "scene_type",
                                     "people_count"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["scenes"],
            "additionalProperties": False,
        },
    }


def _post_openai(body: dict) -> dict:
    token = env.require("OPENAI_API_KEY")
    req = urllib.request.Request(
        OPENAI_API,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"OpenAI API {e.code}: {e.read().decode()[:800]}")


def _extract_json(text: str) -> dict:
    """Strip ```json fences if the model added them, then parse — with an outer-brace
    salvage fallback for the rare truncated/chatty response that slips past the
    strict json_schema constraint."""
    t = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.DOTALL)
    if m:
        t = m.group(1)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        i, j = t.find("{"), t.rfind("}")
        if i >= 0 and i < j:
            return json.loads(t[i:j + 1])
        raise


def _chat(messages: list[dict], schema: dict, max_completion_tokens: int = 4096) -> dict:
    """One low-reasoning-effort OpenAI call, strict json_schema structured output
    (grammar-constrained — far more reliable than response_format=json_object for
    getting the exact shape we asked for). Raises on refusal/empty/malformed."""
    body = {
        "model": MODEL,
        "max_completion_tokens": max_completion_tokens,
        "reasoning_effort": "low",
        "response_format": {"type": "json_schema", "json_schema": {**schema, "strict": True}},
        "messages": messages,
    }
    resp = _post_openai(body)
    if resp.get("error"):
        raise RuntimeError(f"OpenAI API error: {resp['error']}")
    choice = (resp.get("choices") or [{}])[0]
    if choice.get("finish_reason") == "content_filter":
        raise RuntimeError(f"OpenAI refused the request (content_filter): {resp}")
    text = (choice.get("message") or {}).get("content") or ""
    if not text.strip():
        raise RuntimeError(f"OpenAI returned no text content: {resp}")
    return _extract_json(text)


def infer_context(script: str) -> dict:
    """Extract spiritual context from the script — setting, theme, emotional tone."""
    return _chat(
        [
            {"role": "system", "content": (
                "You are analyzing a Christian faith narrative for a Christian story app rendered as a "
                "muted, hand-drawn whiteboard-doodle animation — a churchy vibe, not a generic modern-"
                "lifestyle explainer. Extract the context: (1) setting — read what THIS script is actually "
                "about and describe where its beats unfold (could be daily life at home/work/commute, "
                "church and worship life, or scripture-era scenes — don't default to 'modern lifestyle' if "
                "the script leans churchy or scriptural) in flat whiteboard terms — a plain muted-color "
                "background with simple 2D outline props, (2) spiritual_theme — the core transformation "
                "theme (e.g., faith, surrender, obedience, forgiveness — read from THIS script, don't "
                "default to any one theme), (3) emotional_palette — the "
                "muted flat color accent palette for the illustration (e.g., warm sepia accents, dusty "
                "blue highlights). Focus on the spiritual journey, not locations or time periods. Return "
                "ONLY the JSON object."
            )},
            {"role": "user", "content": script},
        ],
        CONTEXT_SCHEMA,
        max_completion_tokens=1024,
    )


# Sentences per mechanical chunk fed to author_chunk() — matches breakdown-pro's
# PRO_SENTENCES_PER_CHUNK. Purely a batching device (keeps each LLM call small
# and cheap at reasoning_effort=low); the real scene cut happens inside
# author_chunk() itself, not here.
SENTENCES_PER_CHUNK = 8

_SENTENCE_END = re.compile(r"[.!?]+(?:[\"'”’])?(?:\s+|$)")

# Bracketed production cues (background music/SFX placeholders left in the script by
# whoever prepped it) carry no visual content — left in, the staccato/negation-cut rule
# in author_chunk() treats a bare "[music]" as its own scene beat and the LLM hallucinates
# imagery for it (e.g. floating musical notes) since there's nothing else to draw on.
_PRODUCTION_CUE = re.compile(r"\[(?:music|sfx|pause|sound)\]", re.IGNORECASE)


def strip_production_cues(script: str) -> str:
    return re.sub(r"[ \t]{2,}", " ", _PRODUCTION_CUE.sub("", script)).strip()


def chunk_script(script: str, sentences_per_chunk: int = SENTENCES_PER_CHUNK) -> list[str]:
    """Mechanical, no LLM: cut the script into sentences, then group into
    ~sentences_per_chunk-sentence chunks. Ports breakdown-pro's ScriptSplitterService
    (script-splitter.service.ts) — there it uses an NLP sentence splitter (compromise);
    here a regex boundary is enough since this is just a batching device, not the
    real scene cut (that happens per-chunk in author_chunk(), same as breakdown-pro).
    Chunk boundaries fall on exact character offsets into `script`, so every chunk —
    and therefore every scene cut from it — stays a verbatim substring of the input."""
    bounds = [m.end() for m in _SENTENCE_END.finditer(script)]
    if not bounds or bounds[-1] < len(script):
        bounds.append(len(script))
    starts = [0] + bounds[:-1]
    sentences = [script[s:e] for s, e in zip(starts, bounds) if script[s:e].strip()]
    return ["".join(sentences[i:i + sentences_per_chunk])
            for i in range(0, len(sentences), sentences_per_chunk)]


def _anchor_snippet(text: str, snippet: str, cursor: int) -> tuple[int, int] | None:
    """Locate snippet in text at or after cursor, whitespace-tolerant. Forward-only
    search (never before cursor) is the whole guarantee: ported from military's
    lib/agent/core.ts anchorSnippet/sliceBySnippets — the same text can never
    anchor twice, so duplicate/backward LLM snippets simply fail to anchor."""
    words = snippet.split()
    if not words:
        return None
    pattern = r"\s+".join(re.escape(w) for w in words)
    m = re.compile(pattern).search(text, cursor)
    return (m.start(), m.end()) if m else None


def _slice_by_snippets(chunk: str, scenes: list[dict]) -> list[dict]:
    """Re-slice every scene's script_snippet from the REAL chunk text using a
    forward-only cursor anchor, instead of trusting the LLM's copy. Structurally
    kills duplicate/overlapping snippets (a scene whose text can't anchor forward
    of the previous scene's end is dropped) and guarantees full, gapless,
    non-overlapping coverage by construction — segments always tile the whole
    chunk, regardless of where each anchor landed."""
    cursor = 0
    starts, kept = [], []
    for s in scenes:
        anchor = _anchor_snippet(chunk, s.get("script_snippet", ""), cursor)
        if anchor is None:
            print(f"  dropping unanchorable scene (duplicate/paraphrased snippet): "
                  f"{s.get('script_snippet', '')[:60]!r}...", flush=True)
            continue
        start, end = anchor
        starts.append(start)
        kept.append(s)
        cursor = end
    if not kept:
        return []
    starts[0] = 0
    ends = starts[1:] + [len(chunk)]
    for s, start, end in zip(kept, starts, ends):
        s["script_snippet"] = chunk[start:end]
    return kept


def author_chunk(context: dict, chunk: str) -> list[dict]:
    """ONE combined call, ~SENTENCES_PER_CHUNK sentences: cut this chunk into
    visual-beat scenes AND author every per-scene field for each, together.
    Protagonist and Jesus are FIXED constants (PROTAGONIST_APPEARANCE,
    JESUS_APPEARANCE) — never LLM-invented per script — so there's no per-script
    character-inference call feeding this anymore; consistency is structural, not
    prompted. This is the one deliberate deviation from the earlier per-script
    wardrobe system: the story follows ONE anonymous person, driven by metaphor,
    not a cast of named supporting characters."""
    char_context = (
        "CHARACTERS (fixed designs — identical in every scene of every script, never vary these):\n"
        f"PROTAGONIST (appears in EVERY scene — the story's sole anchor): {PROTAGONIST_APPEARANCE}.\n"
        f"JESUS (ONLY when the script explicitly names or directly depicts him): {JESUS_APPEARANCE}.\n"
        f"ANONYMOUS OTHERS/CROWD (society, onlookers, a biblical-era crowd — never a named recurring "
        f"character, never individually distinct): {CROWD_APPEARANCE}. This story follows ONE person; "
        "any other figure is background texture, not a companion character.\n"
    )

    system = (
        f"GLOBAL VISUAL CONTEXT (Christian Story App):\n"
        f"Setting: {context.get('setting', 'a churchy, faith-practice setting')}\n"
        f"Spiritual Theme: {context.get('spiritual_theme', 'faith and transformation')}\n"
        f"Emotional Palette: {context.get('emotional_palette', 'muted, peaceful and reflective')}\n\n"
        f"{char_context}\n"
        "You are a visual director designing a muted, hand-drawn monochrome stick-figure "
        "storyboard for a Christian story app — a churchy, whiteboard-doodle vibe, not a "
        "generic modern-lifestyle explainer. The protagonist is drawn as a plain black-ink "
        "stick figure (see fixed design above) on a muted flat-color background; symbolic "
        "objects/icons in the scene may carry color (a glowing phone, gold coins, a cross) "
        "to carry the metaphor, but the figure itself never gets color fill or realistic "
        "detail. Jesus is the one exception — fuller color/detail, deliberately distinct. "
        "The protagonist is the VISUAL ANCHOR in EVERY scene — they must appear in every "
        "scene showing their spiritual journey, emotional state, and transformation. You "
        "are given one chunk of script. Break it into visual beats, and author every field "
        "for each, in one pass. Every scene's hero_subject MUST feature the protagonist.\n\n"
        "## ANTI-JESUS REGRESSION DEFENSE\n"
        "Faith-based image generators have an extreme bias where ANY other figure "
        "automatically regresses into a long-haired, bearded, robed Jesus look — even a "
        "plain anonymous crowd figure. Defend against this:\n"
        "1. Never write a generic secondary term with no design pinned to it beyond what's "
        "in the CHARACTERS block. Any other figure is either explicitly Jesus (use his fixed "
        "design) or an anonymous crowd/onlooker (use the flat grey-silhouette design) — "
        "nothing in between, no invented named character.\n"
        f"2. In any scene with another figure but NOT Jesus, append "
        f"'{JESUS_NEGATIVE_BLOCK}' to that scene's negative_prompt.\n\n"
        "## PILLAR 1: SCENE BREAKING (CUT ON VISUAL CHANGE)\n\n"
        "### CUT ON VISUAL CHANGE, NOT PER SENTENCE (CORE RULE)\n"
        "A new scene is required ONLY when the visual changes. A visual change is ANY "
        "of: a NEW hero subject (the thing on screen would now be a different "
        "photograph), a LIST ITEM (each distinct item in an enumeration), or a REACTION "
        "or STORY BEAT (a cause's effect, a turn in the story, a new place).\n\n"
        "EVALUATE IN THIS ORDER for every sentence:\n"
        "1. FIRST, does it contain an enumeration of distinct visual items (a list, "
        "including bare-adjective / \"ones\" lists)? If YES -> apply THE LIST-CUT RULE "
        "and give EACH item its own scene, EVEN when the items are comma-separated "
        "clauses inside ONE sentence rather than separate sentences. The list-cut "
        "ALWAYS wins; never fold a list into a merge.\n"
        "2. SECOND, AT THE SAME PRIORITY: is this a short emphatic standalone sentence, "
        "or part of a negation/contrast run (\"Not X. Not Y. Z.\")? If YES -> apply THE "
        "STACCATO/NEGATION-CONTRAST RULE and give EACH such beat its own scene — never "
        "fold them into a merge even when consecutive beats share a subject.\n"
        "3. ONLY if there is no list and no staccato/negation run, ask whether the hero "
        "subject is the SAME as the previous sentence. If the same -> MERGE into the "
        "previous scene. If different (or a reaction/new place) -> new scene.\n\n"
        "- MERGE (same subject): \"The bridge stretched across the gorge. Its iron "
        "cables groaned in the wind.\" -> ONE scene (all the bridge).\n"
        "- DO NOT MERGE (subject changes): \"The chef kneaded the dough. Across the "
        "kitchen, the oven roared to life.\" -> TWO scenes.\n\n"
        "THE LIST-CUT RULE OVERRIDES THE MERGE RULE. An enumeration of distinct items "
        "is NOT one subject even if they share a category word — each list item is its "
        "own visual change and gets its own scene, even comma-separated within one "
        "sentence.\n"
        "- \"Tanks. Guns. Men.\" -> THREE scenes.\n"
        "- \"a red roadster, a black sedan, and a rusted pickup\" -> THREE scenes "
        "(shared category \"cars\", but each looks different -> still a list).\n"
        "- List items must each be a CONCRETE, visually distinct subject. Do NOT split "
        "lists of abstract qualities (\"brave, loyal, fierce\") or near-synonyms "
        "(\"soldiers, troops, infantry\") — those stay together.\n\n"
        "ACTION-REACTION SEPARATION: separate a cause from its effect into two distinct "
        "scenes whenever the visual would cut. \"He pulled the trigger. The window "
        "shattered.\" -> TWO scenes.\n\n"
        "STACCATO & NEGATION-CONTRAST PATTERNS (SAME PRIORITY AS LIST-CUT): deliberate "
        "rhetorical cuts — give EACH beat its own scene, never merge even when adjacent "
        "beats share a subject. \"Not gold. Not silver. Salt.\" -> THREE scenes. A "
        "\"Not X.\" negation beat is NEVER merged into the sentence before or after it.\n\n"
        "UPPER BOUND ON MERGING: never merge past roughly ~25 words / ~12 seconds. If a "
        "same-subject run keeps going beyond that, cut anyway at the nearest sentence "
        "boundary. WHEN IN DOUBT, STAY SEPARATE — do not merge unless you're sure the "
        "subject truly carried over.\n\n"
        "NO DANGLING SNIPPETS (HARD RULE): every script_snippet must be a coherent "
        "thought. Outside of list-cut/staccato splits, never cut mid-sentence for any "
        "other reason, and never end a snippet on a dangling preposition, article, or "
        "conjunction (\"the\", \"a\", \"an\", \"and\", \"or\", \"of\", \"to\", \"for\", "
        "\"with\", \"on\", \"in\", \"at\") for those non-list-cut cuts.\n\n"
        "VERBATIM SCRIPT_SNIPPET MANDATE: copy script_snippet CHARACTER-FOR-CHARACTER "
        "from the chunk below — no paraphrasing, no added/removed words or punctuation. "
        "Each script_snippet must be a contiguous substring of the chunk, and together "
        "the script_snippets must cover the ENTIRE chunk with no gaps or overlaps, in "
        "order.\n\n"
        "## PILLAR 2: HERO_SUBJECT FORMULA (INTENT-DRIVEN VISUAL METAPHOR)\n\n"
        "The script is an intimate, first-person call to reflection (\"you\"), but the imagery must "
        "be ACTIVE, not passive. BANNED HERO_SUBJECTS: sitting on a bed, staring/looking out a "
        "window, holding a coffee mug, standing in a doorway looking sad, or any other static "
        "person-standing-around composition — these are boring and fail to tell a story. ALSO "
        "BANNED: cropping the protagonist's head out of frame or cutting off their face at the neck "
        "— they are the emotionally expressive anchor and must stay legible.\n\n"
        "### INTENT OVER LITERALISM (CORE RULE)\n"
        "This is churchy, faith-content material — read what a line MEANS, not just what it "
        "SAYS, and visualize the meaning. Never illustrate the literal surface word when the "
        "underlying intent points somewhere else.\n"
        "  WRONG (literal): \"not only on Sundays\" -> a weekly calendar page. RIGHT (intent): a path "
        "forking toward a small church/cross icon versus everyday errands — Sunday-only faith is "
        "the target, not the day itself.\n"
        "  WRONG (literal): \"the Word\" -> a library or a stack of books. RIGHT (intent): a single "
        "glowing open book, light spilling from its pages.\n"
        "  WRONG (literal): \"the enemy\" -> a monster or villain. RIGHT (intent): a shadow-silhouette "
        "version of the protagonist looming behind them.\n"
        f"{CHURCH_GLOSSARY}\n"
        "The reference bank above is a director's mood board from studying real faith-content "
        "videos, NOT a menu to copy verbatim and NOT exhaustive — most scripts you're given will "
        "say things this bank never anticipated. When a line doesn't match anything listed, invent "
        "a fitting metaphor using the SAME visual grammar (forking paths, floating icon clusters, "
        "light vs. shadow, growth, doors/gates, water, seeds/harvest, armor, storms/anchors, lamps, "
        "shepherd/flock, tables/altars, scales, chains) rather than falling back to a literal, "
        "static illustration of the sentence. One reference video informed this bank and is a "
        "strong indicator of the target style, but DO NOT overfit to it — these prompts must work "
        "for any Christian-content script, not just the one that inspired the bank.\n\n"
        "### ONE PERSON, RARE COMPANY\n"
        "This story follows ONE anonymous protagonist — it is not an ensemble cast. Default to the "
        "protagonist alone with a symbolic object/environment for most beats. Only bring in another "
        "figure when the beat is genuinely a divine encounter (Jesus, using his fixed design) or "
        "needs a crowd/society contrast (anonymous grey-silhouette figures, e.g. a wide crowded path, "
        "a biblical-era village, onlookers) — never a recurring named companion (no 'friend', "
        "'mentor', 'coworker' with a persistent design). When other figures do appear, they are "
        "background texture the camera doesn't linger on individually.\n"
        "BANNED IN HERO_SUBJECT: camera/cinematography language (\"POV\", \"zoom\", "
        "\"push-in\", \"wide shot\", \"close-up\", \"tracking shot\", \"dolly\", "
        "\"crane\") and pure mood words with no subject (\"tense\", \"ominous\", "
        "\"peaceful\") — describe the physical metaphor, not the feeling.\n\n"
        "## PILLAR 3: IMAGE PROMPT RULES\n\n"
        "image_prompt IS THE ONLY TEXT SENT TO THE IMAGE GENERATOR — hero_subject is internal "
        "planning only and is NEVER seen by it. Any detail that matters MUST be written into "
        "image_prompt itself, not just hero_subject.\n"
        "image_prompt: a SHORT (10-18 words) plain description of a simple monochrome stick-figure "
        "composition — refer to the protagonist simply as 'the stick figure' or 'a simple black-ink "
        "stick figure' (their fixed design is applied automatically by a style prefix, so do NOT "
        "restate ethnicity/wardrobe/hair — they have none) as they ACTIVELY engage with a concrete "
        "symbolic object or action, plus WHERE (a muted-color background, plus whatever setting/prop "
        "the metaphor calls for) so the image generator renders it correctly. Never a static/passive "
        "composition (no sitting, staring out windows, holding a drink, standing in a doorway) and "
        "never a headless/cropped figure. If Jesus appears, name him explicitly ('Jesus') so his "
        "fixed fuller-color design applies instead of the stick figure's. Do NOT mention complex "
        "lighting, shadow depth, 3D rendering, photorealism, or atmosphere (no 'moody', 'dark', "
        "'dramatic', 'chiaroscuro', 'candlelit', 'golden-hour', 'eerie', 'atmospheric') and do NOT "
        "prescribe a light source, texture, or camera angle — none of that; a style prefix already "
        "sets the monochrome-figure/muted-background visual treatment. Just the metaphor/action + "
        "setting cue, plainly.\n"
        "  EXAMPLES (STUDY AND CONFORM — for whatever metaphor THIS sentence actually calls for, "
        "not necessarily these): 'A simple black-ink stick figure running up a path toward a floating "
        "gold crown icon, on a muted tan background.' 'A stick figure watching a simple scale icon "
        "balance a glowing book against gold coin shapes.' 'A stick figure straining to carry a heavy "
        "stone icon on its shoulder, muted background.' 'A stick figure's posture lifting with hope as "
        "chain-link icons shatter around it.' 'A stick figure kneeling with hands cupped together, a "
        "soft warm glow rising from its hands.' 'A stick figure standing at a forking path, one side "
        "lit toward a small cross icon, the other leading into a crowd of flat grey-silhouette "
        "figures.' 'A stick figure in a car's passenger seat while Jesus holds the steering wheel, "
        "muted background.'\n"
        "  Rooms/props/objects should read as simple flat 2D shapes and icons, not detailed or "
        "textured. Do NOT name an art style, medium, camera, or lens — a style prefix is added "
        "automatically.\n"
        "  NO LEGIBLE TEXT, EVER: the image generator cannot render real words and always "
        "produces garbled gibberish when asked to — never a placeholder like 'XXX' "
        "either, it still renders as literal glyphs. Books, ledgers, letters, signposts, "
        "and maps are still fair subjects — but ALWAYS describe their surfaces so no "
        "words are legible: blank, faded past reading, turned away from view, or angled/"
        "lit so text can't form. If the text-bearing surface fills a LARGE part of the "
        "frame, go further — a blown-out shaft of light dissolving the page into "
        "brightness, fog/moss swallowing a signpost's face, an extreme close crop on the "
        "object's texture/edge/binding, or the text-bearing face angled fully away from "
        "camera. Do NOT mention text, captions, watermarks, or logos.\n"
        "- negative_prompt: a short comma-separated list (under ~40 words) of clutter/anachronisms "
        "most likely to leak in for THIS exact scene, matched to whichever era it depicts — modern "
        "clutter (phones, cars, fluorescent light) for present-day beats, or modern intrusions "
        "(cars, electronics, modern clothing) for scripture-era beats. Don't repeat generic quality "
        "terms — those are added automatically.\n"
        "- people_count: the exact number of people image_prompt depicts (protagonist "
        "included) — 1 alone, 2 with one companion/Jesus, 3 with two others. Image models "
        "routinely render an extra unrequested person in group scenes, so this count is "
        "enforced in code afterward — it MUST match what image_prompt actually describes.\n"
        "- scene_type: classify as ONE of spiritual_moment (a quiet personal encounter with "
        "faith or God's presence), transformation (a visible change or breakthrough in the "
        "protagonist's faith), revelation (understanding or realization about God or faith), "
        "decision (a choice point where the protagonist chooses faith/obedience), or "
        "reflection (internal pondering, prayer, or spiritual contemplation).\n"
        "SFW MANDATE (ABSOLUTE): family-friendly only. No nudity, sexual content, gore, "
        "blood, wounds, corpses, or graphic violence. Depict any struggle or hardship "
        "bloodlessly and symbolically through the active metaphor itself (a crumbling stone, "
        "shattering chains, a collapsing crown) rather than graphic harm. This overrides "
        "everything else.\n"
        "Keep the prompts simple, monochrome stick-figure compositions driven by intent and metaphor, "
        "not literal illustration. Return ONLY the JSON object described by the schema."
    )
    data = _chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": chunk},
        ],
        _chunk_author_schema(),
        max_completion_tokens=8192,
    )
    scenes = [s for s in data.get("scenes", []) if s.get("script_snippet", "").strip()]
    if not scenes:
        raise RuntimeError(f"author_chunk: no scenes returned for chunk {chunk[:80]!r}...: {data}")

    scenes = _slice_by_snippets(chunk, scenes)
    if not scenes:
        raise RuntimeError(f"author_chunk: no scene snippets anchored in chunk {chunk[:80]!r}...")

    # Deterministic safety net for the anti-Jesus-regression negative_prompt rule —
    # the LLM follows it most but not all of the time (observed ~1/16 misses), so
    # enforce it in code rather than trust every call to comply. Any scene with more
    # than one figure but no explicit Jesus mention risks the "other figure" regressing
    # into a robed Jesus look.
    for s in scenes:
        if s.get("people_count", 1) > 1:
            prompt_l = s.get("image_prompt", "").lower()
            neg_l = s.get("negative_prompt", "").lower()
            if "jesus" not in prompt_l and "jesus" not in neg_l:
                s["negative_prompt"] = (
                    s.get("negative_prompt", "").rstrip(", ") + ", " + JESUS_NEGATIVE_BLOCK
                ).lstrip(", ")

    # Deterministic safety net for phantom extra people (gpt-image-2 hallucinates an
    # unrequested additional person in group scenes) — force the declared
    # people_count into both prompts rather than trust the image model to read
    # a bare number once. Same "code, not prompt-trust" pattern as the Jesus block.
    for s in scenes:
        count = s.get("people_count", 1)
        block = COUNT_NEGATIVE_BLOCKS.get(count)
        if block:
            s["negative_prompt"] = (
                s.get("negative_prompt", "").rstrip(", ") + ", " + block
            ).lstrip(", ")
        word = {1: "one person", 2: "two people", 3: "three people"}.get(count, "one person")
        s["image_prompt"] = (
            s.get("image_prompt", "").rstrip(". ") + f", exactly {word} total, no additional figures"
        )

    return scenes


def break_into_scenes(script: str, sentences_per_chunk: int = SENTENCES_PER_CHUNK,
                       workers: int = 8, context: dict | None = None) -> list[dict]:
    """Script -> [{scene_number, script_snippet, hero_subject,
    image_prompt, negative_prompt, scene_type}, ...].

    One-stage character setup: protagonist and Jesus are FIXED designs
    (PROTAGONIST_APPEARANCE, JESUS_APPEARANCE) — no per-script character-inference
    call anymore, see author_chunk()'s docstring. Otherwise all OpenAI gpt-5-mini at
    reasoning_effort=low (raw urllib, this repo's house style): infer_context() once
    (skipped if the caller already computed it — run.py caches this in context.json
    for generate_images()'s image QA, so it's passed in here rather than re-billed),
    then chunk_script() (mechanical, no LLM) followed by author_chunk() per chunk IN
    PARALLEL — the scene cut and every per-scene field come out of that ONE call per
    chunk, see author_chunk()'s docstring for why splitting and authoring are no
    longer separate calls. Warns (does not raise) if the concatenated snippets don't
    reconstruct the input closely — LLM verbatim-copy mandates are usually but not
    always followed exactly. Per-scene duration is NOT decided here — it comes from
    real narration-audio alignment, see align_scene_durations().
    """
    from concurrent.futures import ThreadPoolExecutor

    context = context or infer_context(script)
    print(f"  context: {context.get('setting', 'a churchy, faith-practice setting')}", flush=True)

    clean_script = strip_production_cues(script)
    chunks = chunk_script(clean_script, sentences_per_chunk)
    print(f"  -> {len(chunks)} chunks ({sentences_per_chunk} sentences each)", flush=True)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        authored_chunks = list(ex.map(lambda c: author_chunk(context, c), chunks))

    out = []
    for authored in authored_chunks:
        for a in authored:
            out.append({
                "scene_number": len(out) + 1,
                "script_snippet": a["script_snippet"],
                "hero_subject": a.get("hero_subject", ""),
                "image_prompt": a["image_prompt"],
                "negative_prompt": a.get("negative_prompt", ""),
                "scene_type": a.get("scene_type", "spiritual_moment"),
            })
    print(f"  -> {len(out)} scenes", flush=True)

    # Coverage is now structurally guaranteed per-chunk by _slice_by_snippets (every
    # scene's script_snippet is a real, cursor-anchored, gapless slice of its chunk),
    # so a mismatch here can only mean chunk_script() itself split incorrectly —
    # that's a real bug, not LLM near-miss drift, so raise instead of warn-and-proceed.
    joined = "".join(s["script_snippet"] for s in out)
    norm = lambda t: re.sub(r"\s+", " ", t).strip()  # noqa: E731
    if norm(joined) != norm(clean_script):
        raise RuntimeError(
            f"break_into_scenes: scene snippets don't reconstruct the input script "
            f"({len(norm(joined))} vs {len(norm(clean_script))} chars) — chunk_script() bug"
        )

    return out


def generate_images(scenes: list[dict], context: dict, workers: int = 8) -> list[dict]:
    """Each scene -> asset_selector.py:route(), IN PARALLEL (every lane — archival
    search, stock search, graphic generation, gpt-image-2 — is I/O-bound, scenes are
    independent). `context` is infer_context()'s output (spiritual context), needed by the
    the image model's vision-QA prompts. A scene's image failure degrades to
    image_url=None rather than aborting the batch. Adds `lane` to every scene
    (which lane actually produced the image, or None if every lane failed).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import asset_selector  # src/ — deferred import, see that module's docstring

    results: list = [None] * len(scenes)
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(asset_selector.route, s, context): i for i, s in enumerate(scenes)}
        for fut in as_completed(futs):
            results[futs[fut]] = fut.result()
            done += 1
            print(f"  ... generated {done}/{len(scenes)} images", flush=True)

    miss = [s["scene_number"] for s in results if not s["image_url"]]
    if miss:
        print(f"  images: {len(results) - len(miss)}/{len(results)} generated, "
              f"{len(miss)} MISSING: {miss}", flush=True)
    else:
        print(f"  images: {len(results)}/{len(results)} generated", flush=True)
    return results


def whisper_words(narration_path: str) -> tuple[list[dict], float]:
    """narration.mp3 -> ([{word, start, end} in seconds], total_duration_seconds).
    Hosted Modal whisper microservice (REMOTION_WHISPER_SERVICE_URL, POST
    {url}/v1/transcribe, multipart 'file') — same service the sibling
    senior-finance/finance/remotion project's lib/alignment/whisper.ts calls, ported
    from TS fetch/FormData to urllib. No local model, no GPU/CPU transcription cost
    here. Public (no leading underscore) because run.py calls this ONCE per pipeline
    run and feeds the result into both align_scene_durations() and
    director.plan_cards()."""
    url = env.require("REMOTION_WHISPER_SERVICE_URL").rstrip("/") + "/v1/transcribe"
    audio = open(narration_path, "rb").read()

    boundary = "----heritage-whisper-boundary"
    filename = os.path.basename(narration_path)
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: audio/mpeg\r\n\r\n"
    ).encode() + audio + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            raw = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"whisper service {url} {e.code}: {e.read().decode()[:500]}")

    words = []
    for w in raw.get("words") or []:
        text = (w.get("word") or w.get("text") or "").strip()
        start, end = w.get("start"), w.get("end")
        if text and isinstance(start, (int, float)) and isinstance(end, (int, float)):
            words.append({"word": text, "start": float(start), "end": float(end)})
    duration = raw.get("duration") or (words[-1]["end"] if words else 0.0)
    return words, duration


def align_scene_durations(scenes: list[dict], words: list[dict], total_duration: float) -> list[dict]:
    """Real narration-audio timing, NOT a word-count guess: Whisper word-level
    timestamps (`words`/`total_duration`, from whisper_words() — computed ONCE
    by the caller, not here) mapped onto each scene's verbatim script_snippet
    via utils/align.py's DTW aligner. Returns scenes with
    'start'/'end'/'duration_seconds' added, all in seconds, contiguous and
    covering the whole narration.
    """
    snippets = [s["script_snippet"] for s in scenes]
    aligned = align.align(words, snippets, total_duration)
    unmatched = [a["scene_number"] for a in aligned if not a["matched"]]
    if unmatched:
        print(f"  align: {len(unmatched)}/{len(scenes)} scenes unmatched against the "
              f"narration audio (estimated timing via neighbours): {unmatched}", flush=True)
    out = []
    for s, a in zip(scenes, aligned):
        out.append({**s, "start": a["start"], "end": a["end"],
                    "duration_seconds": a["end"] - a["start"], "matched": a["matched"]})
    return out


def to_remotion_scenes(scenes: list[dict], fps: int = 30) -> list[dict]:
    """Scenes (with image_url + duration_seconds from align_scene_durations()) ->
    remotion's Scene shape: [{scene_number, image_url, duration_frames}, ...]
    — matches remotion/src/HeritageScenes.tsx's optional Scene.duration_frames."""
    return [{
        "scene_number": s["scene_number"],
        "image_url": s["image_url"],
        "duration_frames": round(s["duration_seconds"] * fps),
    } for s in scenes]


def build_remotion_payload(scenes: list[dict], narration_url: str | None, fps: int = 30,
                            cards: list[dict] | None = None) -> dict:
    """{scenes, narrationUrl, cards} — remotion/src/Root.tsx's scenes.json shape.
    `narration_url` must be a URL Lambda can fetch (e.g. the row's own voice_url,
    or an S3 rehost) — a local file path won't work for a Lambda render.
    `cards` is director.plan_cards()'s output (text-overlay timeline); omit or
    pass None when there are none yet."""
    return {"scenes": to_remotion_scenes(scenes, fps), "narrationUrl": narration_url, "cards": cards or []}


if __name__ == "__main__":
    import gallery as heritage_gallery  # local module, self-test only
    import tts                          # utils: Voice Generator Service  # noqa
    import director as heritage_director  # local module, self-test only

    SAMPLE_SCRIPT = (
        "In the 8th century, the city of Chang'an stood as the beating heart of Tang Dynasty "
        "China, its wide avenues thronged with silk merchants, Buddhist monks, and travelers "
        "from as far as Persia. Along the Silk Road, camel caravans carried bolts of shimmering "
        "silk westward, exchanging them for glass, spices, and silver coin from distant lands. "
        "In the imperial court, poets and scholars debated philosophy beneath painted eaves, "
        "while the emperor's guard stood watch in lacquered armor, gold-trimmed banners rippling "
        "in the wind. Far to the west, at a caravanserai on the edge of the desert, traders "
        "unrolled their wares beneath a vast, star-filled sky, the cool night air carrying the "
        "scent of woodsmoke and distant lands."
    )

    print("Heritage scene_engine self-test: script -> scenes -> images -> narration -> align -> cards -> gallery")
    print(f"sample script: {len(SAMPLE_SCRIPT.split())} words", flush=True)

    print("\n1/6 break_into_scenes()...", flush=True)
    context = infer_context(SAMPLE_SCRIPT)
    scenes = break_into_scenes(SAMPLE_SCRIPT, context=context)
    print(f"  -> {len(scenes)} scenes", flush=True)
    for s in scenes:
        print(f"  scene {s['scene_number']}: {s['script_snippet'][:60]!r}... "
              f"[{s['scene_type']}]", flush=True)

    print("\n2/6 generate_images()...", flush=True)
    scenes = generate_images(scenes, context)

    narration_path = os.path.join(HERE, "test-narration.mp3")
    print(f"\n3/6 tts.synthesize() -> {narration_path}...", flush=True)
    tts.synthesize(SAMPLE_SCRIPT, narration_path)

    print("\n4/6 whisper_words() + align_scene_durations() (hosted whisper service + utils/align.py DTW)...",
          flush=True)
    words, total_duration = whisper_words(narration_path)
    scenes = align_scene_durations(scenes, words, total_duration)
    for s in scenes:
        print(f"  scene {s['scene_number']}: {s['duration_seconds']:.2f}s "
              f"(matched={s['matched']})", flush=True)

    print("\n5/6 director.plan_cards()...", flush=True)
    cards = heritage_director.plan_cards(SAMPLE_SCRIPT, "", scenes, words, total_duration)
    card_kinds = {}
    for c in cards:
        card_kinds[c["kind"]] = card_kinds.get(c["kind"], 0) + 1
    print(f"  -> {len(cards)} cards: " + ", ".join(f"{k}x{n}" for k, n in card_kinds.items()), flush=True)

    gallery_path = os.path.join(HERE, "test-gallery.html")
    print(f"\n6/6 build_gallery() -> {gallery_path}", flush=True)
    heritage_gallery.build_gallery(scenes, gallery_path)

    remotion_scenes_path = os.path.join(HERE, "..", "remotion", "src", "scenes.json")
    payload = build_remotion_payload(scenes, narration_url=None, cards=cards)  # local mp3 path, unusable by Lambda
    json.dump(payload, open(remotion_scenes_path, "w"), indent=2)
    print(f"      -> {remotion_scenes_path} ({sum(s['duration_frames'] for s in payload['scenes'])} "
          f"total frames @ 30fps, {len(cards)} cards)")

    print(f"\nok  {len(scenes)} scenes, real narration-aligned durations, gallery + "
          f"render scenes.json written")
