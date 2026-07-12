"""Script -> scene breakdown -> per-scene gpt-image-2 flat 2D cartoon image. Two
stages, both here since every caller needs both in sequence:

  break_into_scenes(script) -> OpenAI chat-completions calls (gpt-5-mini, raw urllib, this
                                repo's house style). Returns
                                [{scene_number, script_snippet, hero_subject,
                                image_prompt, negative_prompt, scene_type}, ...] — every
                                scene is a flat 2D cartoon illustration, no lane routing.

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

# Fixed, channel-wide Jesus design — NOT LLM-generated per script. Every Christian
# Story video must render the same Jesus, so this is a constant rather than
# something infer_characters() invents fresh each run.
JESUS_APPEARANCE = (
    "a compassionate 2D cartoon man in his early-to-mid 30s with warm olive skin, flowing "
    "shoulder-length dark brown hair outline worn loose with no head covering of any kind "
    "(no turban, no headscarf, no headgear), a short well-kept beard outline, gentle warm "
    "eyes, wearing a simple flat white garment with a flat red cloak draped over one "
    "shoulder, calm reverent bearing, a simple flat golden glow outline around him"
)

CONTEXT_SCHEMA = {
    "name": "story_context",
    "schema": {
        "type": "object",
        "properties": {
            "setting": {"type": "string", "description": "contemporary setting for the spiritual journey, described in flat 2D whiteboard terms, e.g. 'plain light background with simple 2D outline props — home, workplace, everyday spaces'"},
            "spiritual_theme": {"type": "string", "description": "core spiritual transformation theme, e.g. 'faith, surrender, trust in God, putting God first'"},
            "emotional_palette": {"type": "string", "description": "flat color accent palette for the illustration's fills, e.g. 'warm yellow and blue accents, hopeful tones'"},
        },
        "required": ["setting", "spiritual_theme", "emotional_palette"],
        "additionalProperties": False,
    },
}

CHARACTER_SCHEMA = {
    "name": "story_characters",
    "schema": {
        "type": "object",
        "properties": {
            "protagonist": {
                "type": "object",
                "properties": {
                    "gender": {"type": "string", "description": "A single concrete choice: e.g., 'male' or 'female'."},
                    "ethnicity": {"type": "string", "description": "A single concrete choice: e.g., 'African American', 'East Asian', 'Hispanic', 'Caucasian'."},
                    "age_range": {"type": "string", "description": "e.g. '60s', '70s', 'mid-30s'"},
                    "facial_features": {"type": "string", "description": "Simplified 2D cartoon face details: e.g., 'simple dot eyes, expressive thin mouth line, neat short hair outline, clean-shaven'."},
                    "appearance": {"type": "string", "description": "SPECIFIC modern-2020s clothing in flat-color cartoon terms (e.g. 'solid grey hoodie with clean black outlines', 'flat olive sweater over blue jeans'). No gradients, patterns, or textures. NO robes, tunics, sandals, staffs, or long biblical hair/beards on the protagonist — those read as Jesus, not the viewer. NO NAME."},
                },
                "required": ["gender", "ethnicity", "age_range", "facial_features", "appearance"],
                "additionalProperties": False,
            },
            "jesus_appears": {
                "type": "boolean",
                "description": "true if Jesus is mentioned or directly encountered anywhere in the script, false otherwise. His visual appearance is fixed separately — not something you invent.",
            },
            "supporting_characters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "role": {"type": "string", "description": "their role in the story (e.g. 'friend', 'mentor', 'coworker', 'family member')"},
                        "gender": {"type": "string", "description": "A single concrete choice: e.g., 'male' or 'female'."},
                        "ethnicity": {"type": "string", "description": "A single concrete choice: e.g., 'African American', 'East Asian', 'Hispanic', 'Caucasian'."},
                        "age_range": {"type": "string", "description": "e.g. '20s', 'mid-40s', '60s'"},
                        "hairstyle": {"type": "string", "description": "SPECIFIC simple 2D hairstyle outline, e.g. 'short cropped blonde hair outline', 'neatly styled black bob outline'. NO long biblical hair/beards — that reads as Jesus."},
                        "clothing": {"type": "string", "description": "SPECIFIC modern-2020s flat-color clothing, e.g. 'a solid red sweater with clean black outlines', 'a flat blue blazer'. Never generic ('casual clothes'). No gradients or folds. NO robes, tunics, or sandals."},
                    },
                    "required": ["role", "gender", "ethnicity", "age_range", "hairstyle", "clothing"],
                    "additionalProperties": False,
                },
                "minItems": 2,
                "maxItems": 5,
                "description": "recurring supporting characters (beyond protagonist and Jesus) who share the protagonist's journey — friends, mentors, coworkers, family. The story needs people, not just the protagonist alone with objects.",
            },
        },
        "required": ["protagonist", "jesus_appears", "supporting_characters"],
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
                "You are analyzing a spiritual transformation narrative for a Christian story app "
                "rendered as a clean 2D vector whiteboard animation. Extract the context: (1) setting "
                "— describe the contemporary, everyday setting where this faith journey unfolds (modern "
                "homes, workplaces, daily life) in flat whiteboard terms — a plain light background with "
                "simple 2D outline props, (2) spiritual_theme — the core transformation theme (e.g., "
                "faith, surrender, trust, putting God first), (3) emotional_palette — the flat color "
                "accent palette for the illustration (e.g., warm yellow accents, hopeful blue highlights). "
                "Focus on the spiritual journey, not locations or time periods. Return ONLY the JSON object."
            )},
            {"role": "user", "content": script},
        ],
        CONTEXT_SCHEMA,
        max_completion_tokens=1024,
    )


def infer_characters(script: str) -> dict:
    """Define protagonist, Jesus, and supporting characters for consistent visual rendering
    throughout the story. Protagonist appears in every scene; Jesus/supporting chars only
    when mentioned in the script. Focus on VISUAL FEATURES, not names."""
    result = _chat(
        [
            {"role": "system", "content": (
                "This is a modern explainer video styled as a clean 2D vector whiteboard animation, "
                "where the protagonist ('you' in the script) is the consistent visual anchor in every "
                "scene, experiencing a spiritual journey. The protagonist is the viewer/listener "
                "themselves, drawn as a simple hand-drawn 2D cartoon figure with flat colors and clean "
                "black ink outlines — not a realistic person. Define: (1) the protagonist — describe "
                "their VISUAL APPEARANCE for consistent rendering. You must choose a concrete gender, "
                "ethnicity, realistic age range (20s, 30s, 40s, 50s - pick ONE typical age for this "
                "audience), and simplified cartoon facial features (e.g., simple dot eyes, an expressive "
                "thin mouth line, a neat short hair outline) so the image generator renders the same "
                "identifiable flat-cartoon face every scene — never a vague or generic look. Also pick a "
                "SPECIFIC modern flat-color clothing item (e.g. 'a solid grey hoodie with clean outlines', "
                "'a flat olive sweater') worn consistently, with no gradients, patterns, or textures. This "
                "is a faith-themed video, which strongly biases image generators toward rendering EVERYONE "
                "as a robed, barefoot, biblical-looking figure — counter that explicitly: the protagonist "
                "must read as a normal person in simple 2020s cartoon clothing, NEVER robes, tunics, "
                "sandals, or long biblical hair/beard. NO NAME. "
                "(2) jesus_appears — true only if Jesus is mentioned or directly encountered "
                "anywhere in the script. His visual design is fixed separately; do not describe "
                "his appearance. "
                "(3) supporting characters — the story needs PEOPLE, not just the protagonist alone "
                "with objects. Invent AT LEAST 2 recurring supporting characters tied to relationships, "
                "community, guidance, or struggle implied by the script (e.g. a friend, a mentor, a "
                "coworker, a family member) even if the script doesn't name them explicitly. For EACH "
                "you MUST pick a concrete gender, ethnicity, age range, a SPECIFIC simple 2D hairstyle "
                "outline (e.g. 'short cropped blonde hair outline'), and SPECIFIC modern flat-color "
                "clothing (e.g. 'a solid red sweater with clean black outlines') — never generic "
                "('casual clothes', 'a person'), and never gradients or textures. This is CRITICAL: "
                "faith-themed image generators have an extreme bias toward rendering ANY unspecified "
                "secondary character as a long-haired, bearded Jesus in robes — concrete cartoon "
                "hairstyle + clothing on every supporting character is what prevents that. "
                "NO NAMES on anyone. Return ONLY JSON."
            )},
            {"role": "user", "content": script},
        ],
        CHARACTER_SCHEMA,
        max_completion_tokens=2048,
    )

    # Ensure protagonist always has features, even if LLM returns empty
    if not result.get("protagonist"):
        result["protagonist"] = {
            "gender": "male",
            "ethnicity": "Caucasian",
            "age_range": "60s-70s",
            "facial_features": "simple dot eyes, short cropped hair outline, a friendly expressive mouth line",
            "appearance": "a solid grey hoodie with clean black outlines over flat blue jeans — no robes or biblical clothing"
        }

    # Jesus's look is a fixed constant, never LLM-invented — only whether he's in
    # this story at all is decided per script.
    result["jesus"] = {"appearance": JESUS_APPEARANCE} if result.pop("jesus_appears", False) else None

    # Ensure at least 2 supporting characters, even if the LLM returns too few
    supporting = result.get("supporting_characters") or []
    fallback_supporting = [
        {"role": "friend", "gender": "female", "ethnicity": "Hispanic", "age_range": "30s",
         "hairstyle": "shoulder-length black hair outline", "clothing": "a solid olive sweater with clean black outlines"},
        {"role": "mentor", "gender": "male", "ethnicity": "African American", "age_range": "50s",
         "hairstyle": "short grey hair outline", "clothing": "a solid brown cardigan over a flat collared shirt"},
    ]
    for fb in fallback_supporting:
        if len(supporting) >= 2:
            break
        supporting.append(fb)
    result["supporting_characters"] = supporting
    return result


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


def author_chunk(context: dict, chunk: str, characters: dict | None = None) -> list[dict]:
    """ONE combined call, ~SENTENCES_PER_CHUNK sentences: cut this chunk into
    visual-beat scenes AND author every per-scene field for each, together.
    Characters dict (protagonist, Jesus, supporting) is passed in for consistent
    visual rendering — protagonist appears in EVERY scene as the story's anchor."""
    characters = characters or {}
    protagonist = characters.get("protagonist") or {}
    jesus = characters.get("jesus") or {}
    supporting = characters.get("supporting_characters", []) or []

    # Build character descriptions for the LLM — features only, no names
    char_context = "CHARACTERS (VISUAL FEATURES - EVERYONE LOOKS DIFFERENT):\n"
    if protagonist:
        char_context += (
            f"PROTAGONIST (appears in EVERY scene with these features): {protagonist.get('ethnicity', 'a')} "
            f"{protagonist.get('gender', 'person')}, {protagonist.get('age_range', 'adult')}, with "
            f"{protagonist.get('facial_features', 'a friendly expression')}, wearing "
            f"{protagonist.get('appearance', 'modern casual appearance')}. ANTI-BIBLICAL MANDATE: whenever the "
            f"protagonist is shown, restate their SPECIFIC modern clothing item above — never leave it to "
            f"'a person' or 'a figure', which defaults to a robed biblical look in this generator. NEVER "
            f"robes, tunics, sandals, staffs, or long biblical hair/beard on the protagonist. FACE MANDATE: "
            f"always show their head and face clearly and expressively — never crop out their head, never "
            f"cut off their face at the neck, and never hide them behind a flat anonymous silhouette.\n"
        )
    if jesus:
        char_context += f"JESUS (ONLY when script explicitly says 'Jesus' or 'he' in teaching context. DISTINCTIVE appearance - no one else looks like this): {jesus.get('appearance', 'serene spiritual figure with distinctive presence')}.\n"
    if supporting:
        char_context += "SUPPORTING CHARACTERS (USE THESE PRE-PLANNED PEOPLE VERBATIM — never invent a new character, never change their features):\n"
        for i, c in enumerate(supporting):
            char_context += (
                f"- {c.get('role', f'character_{i}')}: {c.get('ethnicity', 'a')} {c.get('gender', 'person')}, "
                f"{c.get('age_range', 'adult')}, {c.get('hairstyle', 'modern hairstyle')}, wearing "
                f"{c.get('clothing', 'modern clothing')}.\n"
            )

    system = (
        f"GLOBAL VISUAL CONTEXT (Christian Story App):\n"
        f"Setting: {context.get('setting', 'modern times')}\n"
        f"Spiritual Theme: {context.get('spiritual_theme', 'faith and transformation')}\n"
        f"Emotional Palette: {context.get('emotional_palette', 'peaceful and reflective')}\n\n"
        f"{char_context}\n"
        "You are a visual director designing a clean 2D vector cartoon storyboard for a "
        "Christian story app — every scene features the protagonist as a simple, "
        "hand-drawn character with bold black ink outlines, flat colors, and simplified "
        "shapes on a plain, solid, light-colored background. The style must look like a "
        "clean digital whiteboard doodle, never a photorealistic or 3D-rendered painting. "
        "The protagonist is the VISUAL ANCHOR in EVERY scene — they must appear in every "
        "scene showing their spiritual journey, emotional state, and transformation. You "
        "are given one chunk of script. Break it into visual beats, and author every field "
        "for each, in one pass. Every scene's hero_subject MUST feature the protagonist.\n\n"
        "## CRITICAL MANDATE: ANTI-JESUS REGRESSION DEFENSE\n"
        "Faith-based image generators have an extreme bias where ANY secondary character "
        "automatically regresses into a long-haired, bearded Jesus in robes — even a "
        "planned modern friend or coworker. Defend against this:\n"
        "1. Never write a generic secondary term ('another person', 'a man', 'a helper', "
        "or a bare role word like 'the mentor'/'a friend' with nothing else). EVERY TIME "
        "a supporting character appears — not just their first scene — restate their "
        "planned gender, ethnicity, hairstyle, and clothing verbatim from the CHARACTERS "
        "block, in every single image_prompt they're in.\n"
        "2. Never invent a new character. Use ONLY the protagonist, Jesus, and the "
        "pre-planned supporting characters listed above — do not add anyone else.\n"
        f"3. In any scene with a supporting character but NOT Jesus, append "
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
        "## PILLAR 2: HERO_SUBJECT FORMULA (ACTIVE VISUAL METAPHOR WITH SHOWN FACE)\n\n"
        "The script is an intimate, first-person call to reflection (\"you\"), but the imagery must "
        "be ACTIVE, not passive. BANNED HERO_SUBJECTS: sitting on a bed, staring/looking out a "
        "window, holding a coffee mug, standing in a doorway looking sad, or any other static "
        "person-standing-around composition — these are boring and fail to tell a story. ALSO "
        "BANNED: cropping the protagonist's head out of frame, cutting off their face at the neck, "
        "or hiding them in a flat anonymous silhouette — they are a real, emotionally expressive "
        "protagonist whose face must be clearly seen.\n\n"
        "### INTERACTION MANDATE (PRIORITIZE PEOPLE OVER OBJECTS)\n"
        "The story must not be just the protagonist alone with objects — that reads as bland, and "
        "you may NOT wait for the literal script words to say 'friend' or 'relationship' before "
        "using a supporting character. Supporting characters and Jesus are DIRECTORIAL choices you "
        "make even for inward/reflective beats — e.g. a mentor can be shown physically present, "
        "watching with concern, WHILE the protagonist reaches for a symbolic object; that still "
        "satisfies the object-metaphor beat AND adds a person. TARGET RATIO: of ALL the scenes you "
        "output for this chunk, roughly HALF TO TWO-THIRDS should physically include a supporting "
        "character or Jesus alongside the protagonist — NOT every single scene. Genuinely solitary "
        "beats still matter for pacing contrast, so deliberately leave some scenes with the "
        "protagonist alone with a symbolic object, especially private/inward temptation beats. "
        "Before finalizing, COUNT your own scenes with a person: if under half, add one to more of "
        "them; if it's all or nearly all of them, remove the companion from a few and let the "
        "protagonist face those beats alone instead. Also never let more than 2 scenes in a row "
        "pass with the protagonist alone. Prioritize, in this order:\n"
        "1. If the beat touches relationships, community, sharing a burden, learning, or everyday "
        "support, depict the protagonist physically interacting with ONE of the pre-planned "
        "supporting characters: sitting together, a hand of comfort on the shoulder, walking "
        "side by side, studying an object together.\n"
        "2. If the beat is a direct divine encounter, surrender, or mercy moment, depict the "
        "protagonist physically interacting with Jesus: a hand on the shoulder, walking alongside, "
        "reaching out a hand to help them up.\n"
        "3. If the beat is an inward struggle (temptation, doubt, distraction, chasing something "
        "empty) but the frequency floor above isn't yet satisfied, still place a pre-planned "
        "supporting character in the scene as a present witness or companion beside the "
        "protagonist's symbolic action — don't force them into a role the text doesn't support, "
        "just have them physically present and reactive.\n"
        "4. ONLY when the frequency floor is already satisfied by nearby scenes, fall back to the "
        "protagonist alone physically interacting with a concrete, symbolic object — a visual "
        "metaphor, not a mood shot. "
        "Examples of the pattern (invent the specific metaphor from the actual sentence, don't "
        "reuse these verbatim): chasing worldly success -> running up a steep hill toward a "
        "floating, empty golden crown; weighing priorities -> looking at a massive scale balancing "
        "a Bible against a pile of gold coins with a thoughtful expression; surrendering control -> "
        "sitting in a car's driver seat, looking peacefully ahead as a radiant light takes the "
        "steering wheel; carrying past guilt or worry -> straining with a determined expression to "
        "carry a heavy, crumbling stone on their shoulder; hidden pressure or temptation -> standing "
        "amid dark glowing eyes in the shadows while looking up at a shaft of light; breaking free -> "
        "chains made of phone icons or dollar signs shattering around them while they look up with a "
        "hopeful expression. Examples of the people-interaction pattern (rule 1/2 above, invent from "
        "the actual sentence): sharing a burden -> sitting side by side with a supporting character "
        "who has a comforting hand on their shoulder; seeking guidance -> a mentor character pointing "
        "something out while the protagonist listens intently; surrender/mercy -> Jesus placing a hand "
        "on the protagonist's shoulder as they look up with relief.\n"
        "Always incorporate the protagonist's ethnicity, gender, age range, facial features, and "
        "modern clothing from the CHARACTERS block above so the same identifiable person anchors "
        "every scene — never a name, never a generic 'a person'.\n"
        "BANNED IN HERO_SUBJECT: camera/cinematography language (\"POV\", \"zoom\", "
        "\"push-in\", \"wide shot\", \"close-up\", \"tracking shot\", \"dolly\", "
        "\"crane\") and pure mood words with no subject (\"tense\", \"ominous\", "
        "\"peaceful\") — describe the physical metaphor, not the feeling.\n\n"
        "## PILLAR 3: IMAGE PROMPT RULES\n\n"
        "image_prompt IS THE ONLY TEXT SENT TO THE IMAGE GENERATOR — hero_subject is internal "
        "planning only and is NEVER seen by it. Any detail that matters (especially the "
        "protagonist's specific ethnicity, gender, face, and clothing) MUST be written into "
        "image_prompt itself, not just hero_subject.\n"
        "image_prompt: a SHORT (10-18 words) plain description of a simple, flat 2D composition — "
        "the protagonist's head, face, and expressive simplified eyes clearly visible as they "
        "ACTIVELY engage with a concrete symbolic object or action, plus WHERE (modern or "
        "metaphorical setting, always a plain light background) so the image generator renders it "
        "correctly. Never a static/passive composition (no sitting, staring out windows, holding a "
        "drink, standing in a doorway) and never a headless/cropped/silhouetted figure. image_prompt "
        "MUST name the protagonist's ethnicity, gender, facial features, and specific modern "
        "flat-color clothing verbatim from the CHARACTERS block above (e.g. 'a friendly African "
        "American male in a solid grey hoodie with clean outlines') — a bare word like 'a person' or "
        "'a figure' with no face/clothing named defaults this image generator to a robed, biblical "
        "look or a hidden face. Do NOT mention complex lighting, shadow depth, 3D rendering, "
        "photorealism, or atmosphere (no 'moody', 'dark', 'dramatic', 'chiaroscuro', 'candlelit', "
        "'golden-hour', 'eerie', 'atmospheric') and do NOT prescribe a light source, texture, or "
        "camera angle — none of that; a style prefix already sets the flat 2D visual treatment. "
        "Just the metaphor/action + setting cue, plainly.\n"
        "  EXAMPLES (STUDY AND CONFORM — for whatever metaphor THIS sentence actually calls for, "
        "not necessarily these): 'A simple 2D cartoon of a friendly African American male in a solid "
        "grey hoodie, clean black outlines, running up a yellow path toward a flat gold crown icon, "
        "on a plain white background.' 'A 2D cartoon woman with a warm expression in a flat olive "
        "jacket watching a simple scale icon balance a Bible against gold coin shapes.' 'A 2D cartoon "
        "man in a flat denim jacket, determined expression, straining to carry a heavy stone icon on "
        "his shoulder.' 'A 2D cartoon figure's face lit with hope as simple chain-link icons shaped "
        "like phone outlines shatter around them.' 'A 2D cartoon Hispanic female in an olive sweater, "
        "talking to an elderly male mentor with a grey hair outline in a brown cardigan over an open "
        "Bible icon.' 'A 2D cartoon Hispanic female in an olive sweater, comforted by a female friend "
        "with a black bob outline in a blue blazer, hand on her shoulder.' 'A 2D cartoon man in a grey "
        "hoodie walking beside a simply-outlined, robed Jesus figure on a plain background.'\n"
        "  MODERN AND GROUNDED in the setting above — clothing, rooms, and objects should read "
        "as present-day and everyday, simplified into flat 2D shapes and icons. Do NOT name an art "
        "style, medium, camera, or lens — a style prefix is added automatically.\n"
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
        "- negative_prompt: a short comma-separated list (under ~40 words) of modern "
        "clutter/anachronisms most likely to leak in for THIS exact scene (e.g. \"cluttered "
        "background, harsh fluorescent light, cartoonish, headless, cut off face\"). Don't repeat "
        "generic quality terms — those are added automatically.\n"
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
        "Keep the prompts simple, flat, and engaging 2D cartoon compositions, with the character's "
        "face fully visible as they act out the scene. Return ONLY the JSON object described by the schema."
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
    # enforce it in code rather than trust every call to comply.
    if supporting and jesus:
        for s in scenes:
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

    Two-stage, all OpenAI gpt-5-mini at reasoning_effort=low (raw urllib, this repo's
    house style): infer_context() once (skipped if the caller already computed it —
    run.py caches this in context.json for generate_images()'s image QA, so
    it's passed in here rather than re-billed), then chunk_script() (mechanical, no
    LLM) followed by author_chunk() per chunk IN PARALLEL — the scene cut and every
    per-scene field come out of that ONE call per chunk, see author_chunk()'s
    docstring for why splitting and authoring are no longer separate calls. Warns
    (does not raise) if the concatenated snippets don't reconstruct the input
    closely — LLM verbatim-copy mandates are usually but not always followed
    exactly. Per-scene duration is NOT decided here — it comes from real
    narration-audio alignment, see align_scene_durations().
    """
    from concurrent.futures import ThreadPoolExecutor

    context = context or infer_context(script)
    print(f"  context: {context.get('setting', 'modern times')}", flush=True)

    characters = infer_characters(script)
    prot_appearance = characters.get('protagonist', {}).get('appearance', 'undefined')[:30] if characters.get('protagonist') else 'none'
    print(f"  characters: protagonist={prot_appearance}, jesus={'yes' if characters.get('jesus') else 'no'}, supporting={len(characters.get('supporting_characters', []))}", flush=True)

    clean_script = strip_production_cues(script)
    chunks = chunk_script(clean_script, sentences_per_chunk)
    print(f"  -> {len(chunks)} chunks ({sentences_per_chunk} sentences each)", flush=True)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        authored_chunks = list(ex.map(lambda c: author_chunk(context, c, characters), chunks))

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
