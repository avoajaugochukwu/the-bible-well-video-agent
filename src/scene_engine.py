"""Build timed narration scenes for a separately directed visual story.

Narration is divided into verbatim spoken-length blocks without considering its
visual nouns. A whole-film plan from agents/visual_director is expanded into the
same number of chronological shots. The shot author never receives narration,
preventing literal caption illustration while preserving exact timing text.
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
from llm import call_llm_json   # utils: shared OpenAI structured-JSON caller

PROMPT_CONTRACT_VERSION = 10
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
    """Homestead-style agent cut with lossless anchoring and local fallback."""
    from concurrent.futures import ThreadPoolExecutor

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


def _assign_snippets_to_beats(
    script: str,
    snippets: list[str],
    story_beats: list[dict],
) -> dict[int, list[tuple[int, str]]]:
    """Distribute timing blocks evenly across the ordered parallel story.

    Narration anchors are retained for auditing but deliberately do not determine
    visual cuts. Depending on source nouns here would reconnect the two lanes and
    can also starve late film beats when a long narration sentence crosses an
    anchor. Balanced chronological allocation gives every film beat screen time.
    """
    del script
    if len(snippets) < len(story_beats):
        raise ValueError(
            "parallel story has more beats than available narration timing blocks"
        )
    assigned = {beat["beat_number"]: [] for beat in story_beats}
    base, remainder = divmod(len(snippets), len(story_beats))
    cursor = 0
    for beat_index, beat in enumerate(story_beats):
        count = base + (1 if beat_index < remainder else 0)
        for offset in range(count):
            snippet_index = cursor + offset
            assigned[beat["beat_number"]].append(
                (snippet_index + 1, snippets[snippet_index])
            )
        cursor += count
    return assigned


def _shot_schema(character_ids: list[str], count: int) -> dict:
    return {
        "name": "parallel_story_shots",
        "schema": {
            "type": "object",
            "properties": {
                "shots": {
                    "type": "array",
                    "minItems": count,
                    "maxItems": count,
                    "items": {
                        "type": "object",
                        "properties": {
                            "hero_subject": {"type": "string"},
                            "image_prompt": {"type": "string"},
                            "character_ids": {
                                "type": "array",
                                "items": (
                                    {"type": "string", "enum": character_ids}
                                    if character_ids
                                    else {"type": "string"}
                                ),
                            },
                            **_CLASSIFICATION_PROPERTIES,
                        },
                        "required": [
                            "hero_subject",
                            "image_prompt",
                            "character_ids",
                            "scene_type",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["shots"],
            "additionalProperties": False,
        },
    }


def author_story_beat(
    visual_story: dict,
    story_beat: dict,
    characters: list[dict],
    shot_count: int,
) -> list[dict]:
    """Plan consecutive shots from one director beat without seeing narration."""
    if shot_count <= 0:
        return []
    allowed_ids = set(story_beat.get("character_ids") or [])
    character_ids = [c["id"] for c in characters if c["id"] in allowed_ids]
    cast = "\n".join(
        f'- id "{c["id"]}", role "'
        f'{"protagonist" if c["id"] == "protagonist" else "recurring supporting character"}'
        f'": {c["appearance"]}'
        for c in characters
        if c["id"] in allowed_ids
    )
    locations = json.dumps(visual_story.get("recurring_locations") or [], indent=2)
    beat = json.dumps(
        {k: v for k, v in story_beat.items() if k != "narration_anchor"},
        indent=2,
    )
    system = f"""
You are the shot planner for one beat in a coherent Christian animated short film.
You do not receive the narration and must not reconstruct it. Plan exactly
{shot_count} consecutive still-image shots that advance the locked movie beat below.

WHOLE FILM:
Title: {visual_story.get("film_title", "")}
Parallel story: {visual_story.get("parallel_story", "")}
External goal: {visual_story.get("external_goal", "")}
Protagonist arc: {visual_story.get("protagonist_arc", "")}
Movie style: {visual_story.get("movie_style", "")}

RECURRING LOCATIONS:
{locations}

LOCKED STORY BEAT:
{beat}

TRACKED CAST:
{cast}

Treat the shots as a short sequence inside one movie, not separate illustrations.
If LOCKED STORY BEAT has a non-empty bridge_cue, show that exact portable cue
naturally in one or more shots. It is an intentional point of contact with the
narration, not permission to reconstruct any source event around it.
Every stable physical, wardrobe, jewelry, relationship-status, or occupational
identity detail must come from TRACKED CAST. Do not invent unlisted identity
markers to make a character feel more specific; specificity comes from action,
body language, framing, and the established production world.
Give the sequence a small beginning, development, reaction, and handoff to the next
beat. Each shot must change at least one of action, framing, social focus, or place
within the locked location. Mix environmental wides, active medium shots, relationship
two-shots, reaction close-ups, and useful detail shots. Do not make every shot a lone
portrait of the protagonist.

The world should feel populated and alive. Anonymous neighbors, customers, coworkers,
volunteers, congregants, shoppers, and passersby can appear naturally without
character_ids. character_ids contain only recurring cast members clearly visible in
that shot.

image_prompt is 25-45 words and describes only what the image generator should render:
specific location, visible action, people and body language, time of day, and framing.
Refer to recurring cast by role, never by given name. Their visual appearance is
injected later. Use no written signs or readable page content. Do not add an art style;
the whole-film movie style is injected later.

Faith is shown through behavior, relationship, service, reconciliation, prayerful
posture, and changed choices. Religious objects are not shorthand for an inner state.

Return exactly {shot_count} shots in chronological order.
""".strip()
    data = call_llm_json(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Plan the {shot_count}-shot sequence."},
        ],
        _shot_schema(character_ids, shot_count),
        max_completion_tokens=8192,
    )
    return data["shots"]


def break_into_scenes(
    script: str,
    characters: list[dict],
    sentences_per_chunk: int = SENTENCES_PER_CHUNK,
    workers: int = 8,
    context: dict | None = None,
    visual_story: dict | None = None,
) -> list[dict]:
    """Tile narration verbatim, then plan the parallel film without showing the
    narration to the shot author."""
    from concurrent.futures import ThreadPoolExecutor

    context = context or infer_context(script)
    if not visual_story:
        raise ValueError("break_into_scenes requires the whole-video visual_story plan")
    print(f"  context: {context.get('setting', 'a churchy, faith-practice setting')}", flush=True)

    clean_script = strip_production_cues(script)
    snippets = cut_narration_scenes(
        clean_script,
        sentences_per_chunk=sentences_per_chunk,
        workers=workers,
    )
    story_beats = visual_story.get("story_beats") or []
    if not story_beats:
        raise ValueError("visual_story has no story_beats")
    assignments = _assign_snippets_to_beats(clean_script, snippets, story_beats)
    print(
        f"  -> {len(snippets)} narration scenes mapped across "
        f"{len(story_beats)} director beats",
        flush=True,
    )

    active = [
        (beat, assignments[beat["beat_number"]])
        for beat in story_beats
        if assignments[beat["beat_number"]]
    ]
    with ThreadPoolExecutor(max_workers=min(workers, len(active))) as ex:
        planned = list(
            ex.map(
                lambda item: author_story_beat(
                    visual_story,
                    item[0],
                    characters,
                    len(item[1]),
                ),
                active,
            )
        )

    by_scene_number = {}
    for (beat, slots), shots in zip(active, planned):
        for (scene_number, snippet), shot in zip(slots, shots):
            by_scene_number[scene_number] = {
                "scene_number": scene_number,
                "script_snippet": snippet,
                "director_beat_number": beat["beat_number"],
                "hero_subject": shot["hero_subject"],
                "image_prompt": shot["image_prompt"],
                "scene_type": shot.get("scene_type", "spiritual_moment"),
                "character_ids": shot.get("character_ids", []),
                "prompt_contract_version": PROMPT_CONTRACT_VERSION,
                "visual_story_contract_version": visual_story.get(
                    "visual_story_contract_version"
                ),
            }
    out = [by_scene_number[i] for i in range(1, len(snippets) + 1)]
    print(f"  -> {len(out)} scenes", flush=True)

    # The deterministic narration splitter must preserve every spoken word.
    joined = "".join(s["script_snippet"] for s in out)
    norm = lambda t: re.sub(r"\s+", " ", t).strip()  # noqa: E731
    if norm(joined) != norm(clean_script):
        raise RuntimeError(
            f"break_into_scenes: scene snippets don't reconstruct the input script "
            f"({len(norm(joined))} vs {len(norm(clean_script))} chars) — narration split bug"
        )

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
    — matches remotion/src/HeritageScenes.tsx's optional Scene.duration_frames."""
    return [{
        "scene_number": s["scene_number"],
        "image_url": s["image_url"],
        "duration_frames": round(s["duration_seconds"] * fps),
    } for s in scenes]


def build_remotion_payload(scenes: list[dict], narration_url: str | None, fps: int = 30,
                            words: list[dict] | None = None) -> dict:
    """{scenes, narrationUrl, words} — remotion/src/Root.tsx's scenes.json shape.
    `narration_url` must be a URL Lambda can fetch (e.g. the row's own voice_url,
    or an S3 rehost) — a local file path won't work for a Lambda render.
    `words` is whisper_words()'s [{word, start, end}, ...] — remotion's
    <Captions> highlights whichever word is currently being spoken."""
    return {"scenes": to_remotion_scenes(scenes, fps), "narrationUrl": narration_url, "words": words or []}


if __name__ == "__main__":
    import gallery as heritage_gallery  # local module, self-test only
    import tts                          # utils: Voice Generator Service  # noqa

    sys.path.insert(0, os.path.join(HERE, ".."))  # repo root, for agents/ below
    from agents.character_ledger import client as character_ledger
    from agents.character_sheet import client as character_sheet
    from agents.scene_compositor import client as scene_compositor
    from agents.story_dossier import client as story_dossier_agent
    from agents.visual_director import client as visual_director

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

    print("Heritage scene_engine self-test: script -> cast -> film plan -> scenes -> images -> narration -> align -> gallery")
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

    print("\n5/9 visual_director.build()...", flush=True)
    visual_story = visual_director.build(
        SAMPLE_SCRIPT,
        context,
        characters,
        story_dossier=story_dossier,
    )

    print("\n6/9 break_into_scenes()...", flush=True)
    scenes = break_into_scenes(
        SAMPLE_SCRIPT,
        characters,
        context=context,
        visual_story=visual_story,
    )
    print(f"  -> {len(scenes)} scenes", flush=True)
    for s in scenes:
        print(f"  scene {s['scene_number']}: {s['script_snippet'][:60]!r}... "
              f"[{s['scene_type']}] chars={s['character_ids']}", flush=True)

    print("\n7/9 scene_compositor.compose_all()...", flush=True)
    scenes = scene_compositor.compose_all(scenes, characters, visual_story)

    narration_path = os.path.join(HERE, "test-narration.mp3")
    print(f"\n8/9 tts.synthesize() -> {narration_path}...", flush=True)
    tts.synthesize(SAMPLE_SCRIPT, narration_path)

    print("\n8b/9 whisper_words() + align_scene_durations() (hosted whisper service + utils/align.py DTW)...",
          flush=True)
    words, total_duration = whisper_words(narration_path)
    scenes = align_scene_durations(scenes, words, total_duration)
    for s in scenes:
        print(f"  scene {s['scene_number']}: {s['duration_seconds']:.2f}s "
              f"(matched={s['matched']})", flush=True)

    gallery_path = os.path.join(HERE, "test-gallery.html")
    print(f"\n9/9 build_gallery() -> {gallery_path}", flush=True)
    heritage_gallery.build_gallery(scenes, gallery_path)

    remotion_scenes_path = os.path.join(HERE, "..", "remotion", "src", "scenes.json")
    payload = build_remotion_payload(scenes, narration_url=None, words=words)  # local mp3 path, unusable by Lambda
    json.dump(payload, open(remotion_scenes_path, "w"), indent=2)
    print(f"      -> {remotion_scenes_path} ({sum(s['duration_frames'] for s in payload['scenes'])} "
          f"total frames @ 30fps, {len(words)} caption words)")

    print(f"\nok  {len(scenes)} scenes, real narration-aligned durations, gallery + "
          f"render scenes.json written")
