"""Build timed narration scenes for a separately directed visual story.

Narration is divided into verbatim spoken-length blocks without considering its
visual nouns. A whole-film plan from agents/world_builder (built from
agents/emotion_scout's categorical score) is expanded into the same number of
chronological shots. The shot author never receives narration, preventing
literal caption illustration while preserving exact timing text. Each beat is
staged against a location (agents/location_scout) and, where the occasion
calls for it, a recognition anchor (agents/recognition_director) — both
assigned ahead of authoring so the one shot author call can honor them rather
than guessing at composition on its own.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "..", "utils"))
sys.path.insert(0, ROOT)

import env                     # utils: one .env lookup (checks root .env)
import align                    # utils: Whisper-word <-> verbatim-scene DTW aligner
from llm import call_llm_json   # utils: shared OpenAI structured-JSON caller
from agents.location_scout import client as location_scout
from agents.recognition_director import client as recognition_director
from agents.casting_director import client as casting_director

PROMPT_CONTRACT_VERSION = 21
CONTEXT_CONTRACT_VERSION = 2

CONTEXT_SCHEMA = {
    "name": "story_context",
    "schema": {
        "type": "object",
        "properties": {
            "setting": {"type": "string", "description": "the era and broad real-world social environment implied by the story, with no art-style or rendering language"},
            "spiritual_theme": {"type": "string", "description": "core spiritual transformation theme, e.g. 'faith, surrender, obedience, forgiveness' — read from THIS script, don't default to any one theme"},
            "emotional_palette": {"type": "string", "description": "the chronological emotional experience for the audience, not an art or color specification"},
        },
        "required": ["setting", "spiritual_theme", "emotional_palette"],
        "additionalProperties": False,
    },
}

# Scene types for spiritual journey — all scenes focus on faith transformation.
SCENE_TYPES = ["spiritual_moment", "transformation", "revelation", "decision", "reflection"]

_SCENE_TYPE_PROPERTY = {
    "type": "string",
    "enum": SCENE_TYPES,
    "description": (
        "spiritual_moment: a quiet personal encounter with faith or God's presence. "
        "transformation: a visible change or breakthrough in the protagonist's faith. "
        "revelation: understanding or realization about God or faith. "
        "decision: a choice point where the protagonist chooses faith/obedience. "
        "reflection: internal pondering, prayer, or spiritual contemplation."
    ),
}


def infer_context(script: str) -> dict:
    """Extract spiritual context from the script — setting, theme, emotional tone."""
    context = call_llm_json(
        [
            {"role": "system", "content": (
                "Analyze this Christian faith narrative without designing shots. Extract: "
                "(1) setting — its era and broad real-world social environment, with no art-style "
                "or rendering language; (2) spiritual_theme — its core transformation; "
                "(3) emotional_palette — the sequence of feelings the audience should experience. "
                "These fields feed a separate film director, so describe story meaning rather than "
                "image prompts. Return only the JSON object."
            )},
            {"role": "user", "content": script},
        ],
        CONTEXT_SCHEMA,
        max_completion_tokens=1024,
    )
    context["context_contract_version"] = CONTEXT_CONTRACT_VERSION
    return context


SENTENCES_PER_CHUNK = 8
WORDS_PER_SECOND = 2.5
MAX_SCENE_SECONDS = 12
MAX_SCENE_WORDS = round(WORDS_PER_SECOND * MAX_SCENE_SECONDS)

_SENTENCE_END = re.compile(r"[.!?]+(?:[\"'”’])?(?:\s+|$)")

# Bracketed production cues carry no spoken or visual content.
_PRODUCTION_CUE = re.compile(r"\[(?:music|sfx|pause|sound)\]", re.IGNORECASE)


def strip_production_cues(script: str) -> str:
    return re.sub(r"[ \t]{2,}", " ", _PRODUCTION_CUE.sub("", script)).strip()


def mechanical_split(script: str, sentences_per_scene: int = 4) -> list[str]:
    """Lossless sentence-group fallback and sentence-aligned LLM chunker."""
    bounds = [m.end() for m in _SENTENCE_END.finditer(script)]
    if not bounds or bounds[-1] < len(script):
        bounds.append(len(script))
    starts = [0] + bounds[:-1]
    sentences = [script[s:e] for s, e in zip(starts, bounds) if script[s:e].strip()]
    return [
        "".join(sentences[i:i + sentences_per_scene])
        for i in range(0, len(sentences), sentences_per_scene)
    ]


SNIPPETS_SCHEMA = {
    "name": "narration_visual_beats",
    "schema": {
        "type": "object",
        "properties": {
            "snippets": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string"},
            }
        },
        "required": ["snippets"],
        "additionalProperties": False,
    },
}


def propose_snippets(script: str) -> list[str]:
    """Ask the model only where the narration's natural picture changes."""
    data = call_llm_json(
        [
            {
                "role": "system",
                "content": (
                    "Slice this script into sequential visual beats for a narrated video. "
                    "Cut on VISUAL CHANGE: each beat is one continuous thing a camera could "
                    "show. Evaluate every sentence in priority order:\n"
                    "1. LIST-CUT: visually distinct items in a list each get their own beat.\n"
                    "2. STACCATO/CONTRAST: short rhetorical or contrast sequences stay together "
                    "when they form one dramatic beat.\n"
                    "3. Otherwise, merge the same subject, setting, action, and tone; start a "
                    "new beat when any of those visibly changes.\n"
                    "Do not force beats toward a word count. Never leave a dangling fragment "
                    "ending on a preposition, article, or conjunction. Copy every beat VERBATIM "
                    "from the script, in order, losing no text. "
                    'Return JSON: {"snippets":["...","..."]}.'
                ),
            },
            {"role": "user", "content": script},
        ],
        SNIPPETS_SCHEMA,
        max_completion_tokens=4096,
    )
    return [s for s in data["snippets"] if isinstance(s, str) and s.strip()]


def slice_by_snippets(script: str, snippets: list[str]) -> list[str] | None:
    """Use model text only as cut locators; emitted scenes are original slices."""
    starts = []
    cursor = 0
    for snippet in snippets:
        words = snippet.split()
        if not words:
            continue
        match = re.search(
            r"\s+".join(re.escape(word) for word in words),
            script[cursor:],
        )
        if match is None:
            continue
        start = cursor + match.start()
        starts.append(start)
        cursor += match.end()
    if not starts:
        return None
    starts[0] = 0
    starts = list(dict.fromkeys(starts))
    return [
        script[start:starts[i + 1] if i + 1 < len(starts) else len(script)]
        for i, start in enumerate(starts)
    ]


def cap_segments(
    segments: list[str],
    max_words: int = MAX_SCENE_WORDS,
) -> list[str]:
    """Losslessly split overlong beats, preferring sentence and clause breaks."""
    out = []
    for segment in segments:
        words = list(re.finditer(r"\S+", segment))
        if len(words) <= max_words:
            out.append(segment)
            continue
        char_start = 0
        word_start = 0
        while len(words) - word_start > max_words:
            hard_end = word_start + max_words
            eligible = range(min(word_start + 6, hard_end), hard_end + 1)
            sentence_ends = [
                i for i in eligible
                if re.search(r"[.!?][\"'”’]*$", words[i - 1].group())
            ]
            clause_ends = [
                i for i in eligible
                if re.search(r"[,;:][\"'”’]*$", words[i - 1].group())
            ]
            word_end = (
                sentence_ends[-1]
                if sentence_ends
                else clause_ends[-1]
                if clause_ends
                else hard_end
            )
            char_end = words[word_end].start()
            out.append(segment[char_start:char_end])
            char_start = char_end
            word_start = word_end
        out.append(segment[char_start:])
    if "".join(out) != "".join(segments):
        raise RuntimeError("cap_segments dropped narration text")
    return out


def cut_narration_scenes(
    script: str,
    sentences_per_chunk: int = SENTENCES_PER_CHUNK,
    workers: int = 8,
) -> list[str]:
    """Homestead-style agent cut with lossless anchoring and local fallback. This
    is the ONE place narration gets cut into chronological pieces — every other
    stage (agents/emotion_scout's emotional scoring, scene authoring) consumes
    this exact list by position instead of re-segmenting the same script a second
    time, so there's no gap a second, independent cut could silently open up."""
    from concurrent.futures import ThreadPoolExecutor

    script = strip_production_cues(script)
    chunks = mechanical_split(script, sentences_per_chunk)

    def cut_one(chunk: str) -> list[str]:
        try:
            proposed = propose_snippets(chunk)
            return slice_by_snippets(chunk, proposed) or mechanical_split(chunk)
        except Exception as ex:
            print(f"    scene cut: agent fallback ({ex})", flush=True)
            return mechanical_split(chunk)

    with ThreadPoolExecutor(max_workers=min(workers, len(chunks))) as ex:
        results = list(ex.map(cut_one, chunks))
    segments = cap_segments([segment for result in results for segment in result])
    if "".join(segments) != script:
        raise RuntimeError("cut_narration_scenes does not reconstruct the narration")
    return segments


def _shot_schema() -> dict:
    """Both shot authors are pure renderers now — who is in frame is decided
    upstream by agents/casting_director, so the shot itself carries no
    character_ids field; it is grafted onto the scene from the casting pass."""
    return {
        "name": "story_shot",
        "schema": {
            "type": "object",
            "properties": {
                "hero_subject": {"type": "string"},
                "image_prompt": {"type": "string"},
                "scene_type": _SCENE_TYPE_PROPERTY,
            },
            "required": ["hero_subject", "image_prompt", "scene_type"],
            "additionalProperties": False,
        },
    }


_CAMERA_GUIDANCE = {
    "wide": "Wide/establishing shot: show the full location and the person small within it, emphasizing isolation or environment.",
    "medium": "Medium shot: waist-up or full-body at a natural conversational distance.",
    "close": "Close shot on face and upper body, emphasizing expression.",
    "macro": "Extreme close-up/macro shot on one physical object or hand detail — the face need not be visible; let the object or gesture carry the feeling.",
    "pov": "Point-of-view shot: show only what the person is looking at or reaching toward, from their own eyeline or over their shoulder — not their own face.",
}


def _camera_instruction(emotional_beat: dict) -> str:
    return _CAMERA_GUIDANCE.get(emotional_beat.get("camera_distance"), _CAMERA_GUIDANCE["medium"])


def author_story_beat(
    visual_story: dict,
    emotional_beat: dict,
    characters: list[dict],
    location: str = "",
    recognition_cue: str = "",
    casting: dict | None = None,
) -> dict:
    """Plan the one shot for an abstract-mode beat directly against the shared
    world bible (locations/style) and this beat's own emotional score. Who is in
    frame is NOT decided here — agents/casting_director already decided it (from
    the world + this beat's stakes, since abstract beats are narration-blind) and
    handed it in as `casting`; this call is a pure renderer of that cast, same as
    author_literal_beat. `location` comes from agents/location_scout's pre-pass,
    not chosen freely here. `recognition_cue` comes from agents/
    recognition_director's pre-pass — empty for ordinary beats, one concrete
    iconic place/object anchor for significant occasions."""
    casting = casting or {"character_ids": ["protagonist"], "staging_note": ""}
    cast_ids = casting.get("character_ids") or []
    staging_note = (casting.get("staging_note") or "").strip()
    in_frame = [c for c in characters if c["id"] in cast_ids]
    cast = "\n".join(
        f'- id "{c["id"]}", role "'
        f'{"protagonist" if c["id"] == "protagonist" else c.get("role") or "recurring supporting character"}'
        f'": {c.get("appearance") or c.get("story_function", "")}'
        for c in in_frame
    ) or "(no tracked character is in this shot — it is entirely about the occasion or the other people in it)"
    locations = json.dumps(visual_story.get("recurring_locations") or [], indent=2)
    cues = [cue.get("cue") for cue in emotional_beat.get("bridge_cues") or []]
    cue_line = (
        "Optionally show at most one of these portable cues naturally, or none: " + ", ".join(cues)
        if cues else ""
    )
    system = f"""
You are the shot planner for one beat in a coherent Christian animated short film
set in one shared everyday-America world. You do not receive the narration and
must not reconstruct it — you receive only this beat's abstract emotional score.
Plan exactly one still-image shot in this world.

WORLD:
Title: {visual_story.get("film_title", "")}
Movie style: {visual_story.get("movie_style", "")}

RECURRING LOCATIONS:
{locations}

CAST IN FRAME (agents/casting_director already decided who appears — render
exactly these tracked characters as the shot's tracked foreground, none other;
do not add another tracked character back in, and if it lists none, the
protagonist does NOT appear and the shot is entirely about the occasion or the
other people in it):
{cast}

STAGING (already decided by the casting pre-pass — honor it exactly; it tells you
whether this is a solo, populated, or two-person shot, and how any crowd is
dressed for the occasion):
{staging_note or "(protagonist alone, an ordinary specific action)"}

THIS BEAT'S EMOTIONAL SCORE: story_pressure={emotional_beat.get("story_pressure")}, emotional_valence={emotional_beat.get("emotional_valence")}, tempo={emotional_beat.get("tempo")}

THIS SHOT'S LOCATION (already decided, do not change or invent a different
place): {location or "(none assigned — pick the best fit from RECURRING LOCATIONS)"}

{f"RECOGNITION ANCHOR (this location/occasion is significant — feature this specific place/object detail prominently): {recognition_cue}" if recognition_cue else ""}

{cue_line}

Give the protagonist, when she is in frame, an ordinary specific physical action
fitting the location and moment (driving, cooking, shopping, working, walking
briskly) rather than a static pose whenever the beat allows it. Anonymous
figures fill out the shot per STAGING above; keep them as background texture
that never outweighs the tracked characters in CAST IN FRAME, unless CAST IN
FRAME is empty, in which case those figures are the shot's subject.

Every stable physical, wardrobe, jewelry, relationship-status, or occupational
identity detail must come from CAST IN FRAME. Do not invent unlisted identity
markers; specificity comes from action, body language, framing, and the world.

THIS BEAT'S EMOTIONAL STAKES (why this moment actually matters to this person
right now): {emotional_beat.get("emotional_stakes") or "(none given)"}

EXPRESSION FOR THIS SHOT (render this exactly — overt and legible in a single
still frame, never a default pleasant or neutral resting expression unless it
genuinely calls for calm): {emotional_beat.get("expression_directive") or "an expression matching this beat's own emotional score"}

CAMERA FRAMING FOR THIS SHOT: {_camera_instruction(emotional_beat)}

image_prompt is 25-45 words and describes only what the image generator should render:
specific location, visible action, people and body language, time of day, and framing.
Refer to recurring cast by role, never by given name. Their visual appearance is
injected later. Use no written signs or readable page content. Do not add an art style;
the whole-film movie style is injected later.

Faith is shown through behavior, relationship, service, reconciliation, prayerful
posture, and changed choices. Religious objects are not shorthand for an inner state.

Return exactly one shot.
""".strip()
    return call_llm_json(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": "Plan the shot."},
        ],
        _shot_schema(),
        max_completion_tokens=2048,
    )


def author_literal_beat(
    snippet: str,
    emotional_beat: dict,
    characters: list[dict],
    location: str = "",
    recognition_cue: str = "",
    local_context: str = "",
    casting: dict | None = None,
) -> dict:
    """Plan the one shot for a beat whose narration names a concrete,
    visualizable event — the literal counterpart to author_story_beat's
    world shot. Still narration-blind to the WHOLE script and the invented
    world (it cannot drift onto the wrong story), but now sees `local_context`
    — the full text of every sibling snippet sharing this beat's own
    contiguous location run, not just this one isolated fragment. Confirmed
    bug this fixes (2026-08-03): `cut_narration_scenes` can chop one
    continuous sentence ("The church was full... white roses... People smiled
    like they were witnessing something holy") into several 2-8 word
    fragments; authoring each in total isolation left the model with no way to
    know it was even a wedding, let alone that showing the actual couple at
    the altar might fit better than the protagonist standing static in her
    everyday outfit for every single fragment. `location` comes from
    agents/location_scout's pre-pass, not chosen freely here, so a run of
    beats describing one continuous event (e.g. a wedding) holds one place
    instead of drifting to a different room mid-event. `recognition_cue` comes
    from agents/recognition_director's pre-pass — empty for ordinary beats, one
    concrete iconic anchor for significant occasions."""
    casting = casting or {"character_ids": ["protagonist"], "staging_note": ""}
    cast_ids = casting.get("character_ids") or []
    staging_note = (casting.get("staging_note") or "").strip()
    in_frame = [c for c in characters if c["id"] in cast_ids]
    cast = "\n".join(
        f'- id "{c["id"]}", role "'
        f'{"protagonist" if c["id"] == "protagonist" else "recurring supporting character"}'
        f'": {c["appearance"]}'
        for c in in_frame
    ) or "(no tracked character is in this shot — it is entirely about the occasion or the other people in it)"
    system = f"""
You are the shot planner for one beat of a Christian animated short film. This
beat's narration names a concrete, visualizable event — plan exactly one
still-image shot grounded in what this narration describes.

NARRATION FOR THIS BEAT:
{snippet}

CAST IN FRAME (agents/casting_director already decided who appears — render exactly
these tracked characters as the shot's tracked foreground, none other; do not add
another tracked character back in, and if it lists none, the protagonist does NOT
appear and the shot is entirely about the occasion or the other people in it):
{cast}

STAGING (already decided by the casting pre-pass — honor it exactly; it tells you
whether this is a solo, two-person, or populated group shot and who anchors it):
{staging_note or "(protagonist alone, an ordinary specific action)"}

THIS BEAT'S EMOTIONAL SCORE: story_pressure={emotional_beat.get("story_pressure")}, emotional_valence={emotional_beat.get("emotional_valence")}, tempo={emotional_beat.get("tempo")}

THIS SHOT'S LOCATION (already decided, do not change or invent a different
place unless this narration's own words clearly move to somewhere else):
{location or "(none assigned — infer the best fit from this narration)"}

{f"RECOGNITION ANCHOR (this location/occasion is significant — feature this specific place/object detail prominently): {recognition_cue}" if recognition_cue else ""}

{f'''THIS BEAT IS ONE FRAGMENT OF A LONGER CONTINUOUS SCENE — here is the full
surrounding passage, for context only (this fragment's own narration above is
still the ONE thing this specific shot must be grounded in; do not treat the
whole passage below as this shot's own content to illustrate):
{local_context}
Use this to understand what the whole scene actually is (a wedding, a
funeral, a meeting) so your choice of subject and props is consistent with it
and with every other beat cut from the same passage — never invent an object
or event with its own strong meaning (a casket, a ring box, a diploma) unless
the passage above actually names or clearly implies it. (Who is in the shot is
already fixed by CAST IN FRAME and STAGING above — use this passage only to
ground the subject and props, not to reconsider who appears.)''' if local_context else ""}

Do not transcribe the sentence into a shot-for-shot recreation of every named
noun and action — that reads as illustration, not cinema. Instead pick ONE
specific, telling visual moment or detail that captures this beat's real
substance: a gesture, an object, a look, an environment, or an instant just
before/after the literal action, seen from a deliberate angle. The image must
still be clearly grounded in this narration, not a different event — never
invent a prop or object carrying its own strong narrative weight (a casket, a
wheelchair, a ring box, a diploma) unless this beat's own narration or the
surrounding passage actually names or clearly implies it.

Every stable physical, wardrobe, jewelry, relationship-status, or occupational
identity detail must come from CAST IN FRAME. Do not invent unlisted identity
markers to make a character feel more specific; specificity comes from action,
body language, framing, and the scene the narration describes.

Populate the frame per STAGING above — it already fixes who is present and how
any crowd is dressed for the occasion; render that, do not re-derive it. Keep
anonymous figures as background texture that never outweighs the tracked
characters in CAST IN FRAME; when CAST IN FRAME is empty, those anonymous
figures ARE this shot's foreground subject — build the image around them, not
around an absent protagonist. Never render a significant occasion as a generic,
unpopulated room.

THIS BEAT'S EMOTIONAL STAKES (why this moment actually matters to this person
right now): {emotional_beat.get("emotional_stakes") or "(none given)"}

EXPRESSION FOR THIS SHOT (render this exactly — overt and legible in a single
still frame, never a default pleasant or neutral resting expression unless it
genuinely calls for calm): {emotional_beat.get("expression_directive") or "an expression matching this beat's own emotional score"}

CAMERA FRAMING FOR THIS SHOT: {_camera_instruction(emotional_beat)}

image_prompt is 25-45 words and describes only what the image generator should
render: specific location, visible action, people and body language, time of
day, and framing. Refer to recurring cast by role, never by given name. Their
visual appearance is injected later. Use no written signs or readable page
content. Do not add an art style.

Faith is shown through behavior, relationship, service, reconciliation,
prayerful posture, and changed choices. Religious objects are not shorthand
for an inner state.

Return exactly one shot.
""".strip()
    return call_llm_json(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": "Plan the shot."},
        ],
        _shot_schema(),
        max_completion_tokens=2048,
    )


def _local_contexts(snippets: list[str], locations: list[str]) -> list[str]:
    """One local_context string per snippet: the full narration text of every
    sibling snippet sharing this snippet's own contiguous location run (empty
    for a single-snippet run — that beat already IS the whole scene, nothing
    to add). Confirmed 2026-08-03: authoring each beat from its own isolated
    fragment alone (some as short as 2-3 words — "white roses", "and baby's
    breath,") gave the shot author no way to know it was even part of a
    wedding, only "just in time" info with no bigger picture to plan against."""
    contexts = [""] * len(snippets)
    start = 0
    for i in range(1, len(locations) + 1):
        if i == len(locations) or locations[i] != locations[start]:
            if i - start > 1:
                joined = " ".join(s.strip() for s in snippets[start:i])
                for j in range(start, i):
                    contexts[j] = joined
            start = i
    return contexts


def break_into_scenes(
    snippets: list[str],
    characters: list[dict],
    visual_story: dict,
    workers: int = 8,
) -> list[dict]:
    """Zip the already-cut verbatim narration snippets 1:1 with agents/
    emotion_scout's emotional-spine beats — guaranteed equal counts, since that
    agent scores every one of these same snippets rather than inventing its own
    boundaries. Each beat's own narration-derived visual_mode picks which single
    author runs for it — concrete beats never need the world-shot author, and
    abstract beats never need the literal author, since there's no shared plot
    state across beats to keep either author "warm" for anymore. A location
    (agents/location_scout) and, where the occasion calls for it, a recognition
    anchor (agents/recognition_director) are assigned to every beat ahead of
    authoring, so a run of beats describing one continuous event holds one
    place instead of each author call picking freely with zero memory of its
    neighbors."""
    from concurrent.futures import ThreadPoolExecutor

    emotional_beats = (visual_story.get("emotional_spine") or {}).get("emotional_beats") or []
    if len(emotional_beats) != len(snippets):
        raise ValueError(
            f"visual_story emotional_spine has {len(emotional_beats)} beats but narration "
            f"was cut into {len(snippets)} snippets — these must match 1:1"
        )

    locations = location_scout.assign(snippets, visual_story)
    recognition_cues = recognition_director.assign(locations, emotional_beats, workers=workers)
    local_contexts = _local_contexts(snippets, locations)
    # Who-is-in-frame is decided here, once, ahead of authoring — for EVERY beat,
    # concrete or abstract — so presence lives in exactly one place and both shot
    # authors are pure renderers of the cast + staging they are handed, never
    # re-deciding it (which defaulted the protagonist into every frame).
    castings = casting_director.assign(
        snippets, characters, locations, local_contexts, emotional_beats, workers=workers
    )

    with ThreadPoolExecutor(max_workers=min(workers * 2, len(snippets) * 2 or 1)) as ex:
        futures = [
            ex.submit(author_literal_beat, snippet, emotional_beat, characters, location, recognition_cue, local_context, casting)
            if emotional_beat.get("visual_mode") == "concrete"
            else ex.submit(author_story_beat, visual_story, emotional_beat, characters, location, recognition_cue, casting)
            for snippet, emotional_beat, location, recognition_cue, local_context, casting in zip(
                snippets, emotional_beats, locations, recognition_cues, local_contexts, castings
            )
        ]
        shots = [f.result() for f in futures]

    out = []
    for i, (snippet, emotional_beat, location, recognition_cue, casting, shot) in enumerate(
        zip(snippets, emotional_beats, locations, recognition_cues, castings, shots), start=1
    ):
        visual_mode = emotional_beat.get("visual_mode")
        # Cast always comes from casting_director now (both authors dropped their
        # own character_ids output).
        character_ids = casting["character_ids"]
        out.append({
            "scene_number": i,
            "script_snippet": snippet,
            "director_beat_number": i,
            "visual_mode": visual_mode,
            "location": location,
            "recognition_cue": recognition_cue,
            "staging_note": casting.get("staging_note", ""),
            "hero_subject": shot["hero_subject"],
            "image_prompt": shot["image_prompt"],
            "scene_type": shot["scene_type"],
            "character_ids": character_ids,
            "prompt_contract_version": PROMPT_CONTRACT_VERSION,
            "visual_story_contract_version": visual_story.get("world_builder_contract_version"),
            "location_scout_contract_version": location_scout.LOCATION_SCOUT_CONTRACT_VERSION,
            "recognition_director_contract_version": recognition_director.RECOGNITION_DIRECTOR_CONTRACT_VERSION,
            "casting_director_contract_version": casting_director.CASTING_DIRECTOR_CONTRACT_VERSION,
        })
    print(f"  -> {len(out)} scenes", flush=True)
    return out


def whisper_words(narration_path: str) -> tuple[list[dict], float]:
    """narration.mp3 -> ([{word, start, end} in seconds], total_duration_seconds).
    Hosted Modal whisper microservice (REMOTION_WHISPER_SERVICE_URL, POST
    {url}/v1/transcribe, multipart 'file') — same service the sibling
    senior-finance/finance/remotion project's lib/alignment/whisper.ts calls, ported
    from TS fetch/FormData to urllib. No local model, no GPU/CPU transcription cost
    here. Public (no leading underscore) because run.py calls this ONCE per pipeline
    run and feeds the result into both align_scene_durations() and the remotion
    payload's caption words (build_remotion_payload())."""
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
    — matches remotion/src/HeritageScenes.tsx's optional Scene.duration_frames.
    video_url/mode pass through when a scene's active asset is a video (set by
    the production UI, synced in via supabase_jobs before render) — remotion
    renders that clip (looped, muted) instead of the still image_url."""
    out = []
    for s in scenes:
        entry = {
            "scene_number": s["scene_number"],
            "image_url": s["image_url"],
            "duration_frames": round(s["duration_seconds"] * fps),
        }
        if s.get("mode") == "video" and s.get("video_url"):
            entry["video_url"] = s["video_url"]
            entry["mode"] = "video"
        out.append(entry)
    return out


def build_remotion_payload(scenes: list[dict], narration_url: str | None, fps: int = 30,
                            words: list[dict] | None = None) -> dict:
    """{scenes, narrationUrl, words} — remotion/src/Root.tsx's scenes.json shape.
    `narration_url` must be a URL Lambda can fetch (e.g. the row's own voice_url,
    or an S3 rehost) — a local file path won't work for a Lambda render.
    `words` is whisper_words()'s [{word, start, end}, ...] — remotion's
    <Captions> highlights whichever word is currently being spoken."""
    return {"scenes": to_remotion_scenes(scenes, fps), "narrationUrl": narration_url, "words": words or []}


if __name__ == "__main__":
    import baserow                      # local module: download() for real narration mp3

    sys.path.insert(0, os.path.join(HERE, ".."))  # repo root, for agents/ below
    from agents.character_ledger import client as character_ledger
    from agents.character_sheet import client as character_sheet
    from agents.emotion_scout import client as emotion_scout
    from agents.scene_renderer import client as scene_renderer
    from agents.story_dossier import client as story_dossier_agent
    from agents.world_builder import client as world_builder

    SAMPLE_SCRIPT_PATH = os.path.join(HERE, "..", "she-thought-god-forgot-her-script.txt")
    SAMPLE_AUDIO_URL_PATH = os.path.join(HERE, "..", "she-thought-god-forgot-her-audio.txt")
    SAMPLE_SCRIPT = open(SAMPLE_SCRIPT_PATH).read().strip()
    SAMPLE_AUDIO_URL = open(SAMPLE_AUDIO_URL_PATH).read().strip()

    print("Heritage scene_engine self-test: script -> cast -> film plan -> scenes -> images -> narration -> align")
    print(f"sample script: {len(SAMPLE_SCRIPT.split())} words", flush=True)

    print("\n1/7 infer_context()...", flush=True)
    context = infer_context(SAMPLE_SCRIPT)

    print("\n2/9 story_dossier.build()...", flush=True)
    story_dossier = story_dossier_agent.build(SAMPLE_SCRIPT)

    print("\n3/9 character_ledger.build()...", flush=True)
    characters = character_ledger.build(
        SAMPLE_SCRIPT,
        context,
        story_dossier=story_dossier,
    )["characters"]
    print(f"  -> {len(characters)} tracked character(s): {[c['id'] for c in characters]}", flush=True)

    print("\n4/9 character_sheet.generate_all()...", flush=True)
    characters = character_sheet.generate_all(characters)

    print("\n4b/9 cut_narration_scenes() (the one narration cut, reused below)...", flush=True)
    snippets = cut_narration_scenes(SAMPLE_SCRIPT)
    print(f"  -> {len(snippets)} verbatim snippets", flush=True)

    print("\n5/9 emotion_scout.score() + world_builder.build()...", flush=True)
    emotional_spine = emotion_scout.score(snippets)
    visual_story = {
        **world_builder.build(characters, story_dossier, emotional_spine),
        "emotional_spine": emotional_spine,
    }

    print("\n6/9 break_into_scenes()...", flush=True)
    scenes = break_into_scenes(
        snippets,
        characters,
        visual_story=visual_story,
    )
    print(f"  -> {len(scenes)} scenes", flush=True)
    for s in scenes:
        print(f"  scene {s['scene_number']}: {s['script_snippet'][:60]!r}... "
              f"[{s['scene_type']}] chars={s['character_ids']}", flush=True)

    print("\n7/9 scene_renderer.compose_all()...", flush=True)
    scenes = scene_renderer.compose_all(scenes, characters)

    narration_path = os.path.join(HERE, "test-narration.mp3")
    print(f"\n8/9 downloading real narration ({SAMPLE_AUDIO_URL}) -> {narration_path}...", flush=True)
    baserow.download(SAMPLE_AUDIO_URL, narration_path)

    print("\n8b/9 whisper_words() + align_scene_durations() (hosted whisper service + utils/align.py DTW)...",
          flush=True)
    words, total_duration = whisper_words(narration_path)
    scenes = align_scene_durations(scenes, words, total_duration)
    for s in scenes:
        print(f"  scene {s['scene_number']}: {s['duration_seconds']:.2f}s "
              f"(matched={s['matched']})", flush=True)

    remotion_scenes_path = os.path.join(HERE, "..", "remotion", "src", "scenes.json")
    payload = build_remotion_payload(scenes, narration_url=None, words=words)  # local mp3 path, unusable by Lambda
    json.dump(payload, open(remotion_scenes_path, "w"), indent=2)
    print(f"      -> {remotion_scenes_path} ({sum(s['duration_frames'] for s in payload['scenes'])} "
          f"total frames @ 30fps, {len(words)} caption words)")

    print(f"\nok  {len(scenes)} scenes, real narration-aligned durations, "
          f"render scenes.json written")
