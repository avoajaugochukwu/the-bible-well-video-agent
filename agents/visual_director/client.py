"""Plan one coherent parallel visual story for the whole narration.

Three passes, each sized so its own output never has to scale past the model's
completion-token cap the way one whole-script call used to:
  1. emotional spine — categorical score, one entry per narration snippet,
     chunked and scored IN PARALLEL (each snippet's score depends only on its
     own text, never on another snippet's).
  2. world bible — film_title/cast/locations/goal, decided ONCE in a single
     call. Fixed-size output regardless of script length; this is the only
     place new locations or supporting characters get declared.
  3. story beats — one beat per emotional-spine entry, chunked and authored
     SEQUENTIALLY (unlike the spine, beat-to-beat plot causality means chunk N+1
     has to know what chunk N just did), using only the world bible's ids.
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "utils"))

from llm import call_llm_json


VISUAL_STORY_CONTRACT_VERSION = 13
MAX_ATTEMPTS = 3

# Snippets/beats per model call — a prompt decision, not a throughput knob (same
# reasoning as sleep-stories/agents/scene_director/config.py's CHUNK_SIZE): this
# decides how much surrounding context one call can vary its output against.
# Bounding it also bounds that call's max_completion_tokens naturally, which is
# what a single whole-script call couldn't do once a script ran past ~100 beats.
CHUNK_SIZE = 10
MAX_PARALLEL_CHUNKS = 8

_FROM_STATES = ["withdrawal", "passivity", "fear", "control", "shame", "resentment",
                "grief", "self_reliance"]
_TO_STATES = ["connection", "purposeful_action", "courage", "trust", "acceptance",
              "forgiveness", "hope", "shared_reliance"]


def _chunks(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


# ---------------------------------------------------------------------------
# 1. emotional spine — chunked, parallel (no cross-chunk dependency)
# ---------------------------------------------------------------------------

def _core_transformation_schema() -> dict:
    return {
        "name": "core_transformation",
        "schema": {
            "type": "object",
            "properties": {
                "from_state": {"type": "string", "enum": _FROM_STATES},
                "to_state": {"type": "string", "enum": _TO_STATES},
            },
            "required": ["from_state", "to_state"],
            "additionalProperties": False,
        },
    }


def _infer_core_transformation(snippets: list[str]) -> dict:
    """The one whole-story-scoped judgment in the spine pass — decided once
    over the whole narration, never per chunk, since a per-chunk vote would
    have nothing to reconcile disagreements with."""
    numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(snippets, start=1))
    messages = [
        {
            "role": "system",
            "content": (
                "You are a story analyst. Read the whole narration and choose the single "
                "most accurate core spiritual transformation it depicts: one starting inner "
                "state and one ending inner state, from the two provided enums. Weigh the "
                "whole arc, not just the opening or closing lines."
            ),
        },
        {"role": "user", "content": f"NUMBERED NARRATION SNIPPETS:\n{numbered}"},
    ]
    return call_llm_json(messages, _core_transformation_schema(), max_completion_tokens=1000)


def _spine_schema(count: int) -> dict:
    return {
        "name": "emotional_spine_chunk",
        "schema": {
            "type": "object",
            "properties": {
                "emotional_beats": {
                    "type": "array",
                    "minItems": count,
                    "maxItems": count,
                    "items": {
                        "type": "object",
                        "properties": {
                            "visual_mode": {
                                "type": "string",
                                "enum": ["concrete", "abstract"],
                                "description": (
                                    "concrete if this snippet names a specific real-world "
                                    "event, object, or action a camera could show directly "
                                    "(an invitation, a wedding, a document, someone arriving "
                                    "or leaving); abstract if it is interior reflection, "
                                    "interpretation, or a feeling with no literal referent"
                                ),
                            },
                            "story_pressure": {
                                "type": "string",
                                "enum": [
                                    "stability", "unease", "exposure", "rupture", "low_point",
                                    "challenge", "recognition", "choice", "effort",
                                    "reconnection", "arrival",
                                ],
                            },
                            "emotional_valence": {"type": "string", "enum": ["positive", "mixed", "negative"]},
                            "agency": {"type": "integer", "minimum": 1, "maximum": 5},
                            "social_openness": {"type": "integer", "minimum": 1, "maximum": 5},
                            "tempo": {"type": "string", "enum": ["still", "measured", "active"]},
                            "camera_distance": {"type": "string", "enum": ["wide", "medium", "close", "varied"]},
                            "bridge_cues": {
                                "type": "array",
                                "maxItems": 3,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "cue": {"type": "string"},
                                        "cue_type": {
                                            "type": "string",
                                            "enum": ["tool", "material_or_texture", "physical_gesture", "garment_action"],
                                        },
                                        "evidence": {
                                            "type": "string",
                                            "description": (
                                                "short exact quote from THIS snippet proving "
                                                "the visible cue is physically present and affirmed"
                                            ),
                                        },
                                    },
                                    "required": ["cue", "cue_type", "evidence"],
                                    "additionalProperties": False,
                                },
                                "description": (
                                    "sparse portable visual anchors from this snippet: tools, "
                                    "materials, textures, or garment actions that can live "
                                    "inside a different plot"
                                ),
                            },
                        },
                        "required": [
                            "visual_mode", "story_pressure", "emotional_valence", "agency",
                            "social_openness", "tempo", "camera_distance", "bridge_cues",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["emotional_beats"],
            "additionalProperties": False,
        },
    }


def _validate_spine_chunk(data: dict, snippets: list[str]) -> list[str]:
    problems = []
    beats = data.get("emotional_beats") or []
    if len(beats) != len(snippets):
        problems.append(
            f"emotional_beats must have exactly {len(snippets)} entries, one per "
            f"narration snippet in order — got {len(beats)}"
        )
        return problems
    for snippet, beat in zip(snippets, beats):
        for cue in beat.get("bridge_cues") or []:
            if len((cue.get("cue") or "").split()) > 6:
                problems.append(f"bridge cue {cue.get('cue')!r} is not a compact portable detail")
            evidence = (cue.get("evidence") or "").strip()
            if not evidence:
                problems.append(f"bridge cue {cue.get('cue')!r} has no evidence")
            elif evidence not in snippet:
                # Paraphrase is fine; groundedness is a taste call, not a fact check.
                print(
                    "    director: bridge cue evidence is not exactly verbatim in its "
                    "snippet; keeping it as a semantic locator",
                    flush=True,
                )
    return problems


_SPINE_SYSTEM = (
    "You are a story analyst creating an emotional score for a separate visual film. "
    "Below are the narration's own pre-cut chronological snippets, numbered in order. "
    "Score EVERY numbered snippet, in the same order, with exactly one emotional_beats "
    "entry each — never skip, merge, or compress snippets; a short transitional "
    "snippet still gets its own entry with the closest neutral categorical values "
    "rather than being dropped. Encode story meaning with the categorical fields in "
    "the schema. For visual_mode, judge each snippet on its own: concrete when it "
    "names a specific event, object, or action a camera could show directly as "
    "written, abstract when it is interior reflection or feeling with nothing literal "
    "to film. This is independent of every other field — a concrete snippet can carry "
    "any emotional_valence or story_pressure. For bridge_cues only, extract zero to "
    "three sparse, portable visual "
    "anchors from that snippet: a specific tool, material, tactile texture, repeated "
    "physical gesture, or garment action that could naturally appear inside a "
    "different plot. Every cue must include a short exact evidence quote from THAT "
    "snippet. The evidence must affirm that the physical cue is present or performed. "
    "Do not turn an absent, negated, hypothetical, or figurative object into a cue — "
    "a figurative door, lock, weight, or light only counts if the evidence depicts the "
    "literal physical thing, not the metaphor. Portability is mandatory: never propose "
    "a cue that carries a source event, location, occupation, relationship, "
    "celebration, social status, or complete tableau along with it. "
    "cue is at most six words and must fit exactly one cue_type. Decontextualize it: "
    "a gesture names only the movement; a garment action names only the action and "
    "will use the film character's locked outfit; a material_or_texture names sensory "
    "material rather than an event-bearing document. It must remain usable in an "
    "unrelated profession and location without recreating the narrated situation. "
    "Do not include source events, locations, occupations, relationships, names, "
    "celebrations, religious shorthand, or complete scene descriptions. A garment "
    "cue describes an action such as putting on an outer layer, not a new costume. "
    "Select the closest emotional values without explaining them in prose. This is "
    "one chunk of a longer narration — score only the numbered snippets given here."
)


def _spine_chunk(snippets_chunk: list[str]) -> dict:
    numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(snippets_chunk, start=1))
    messages = [
        {"role": "system", "content": _SPINE_SYSTEM},
        {"role": "user", "content": f"NUMBERED NARRATION SNIPPETS:\n{numbered}"},
    ]
    schema = _spine_schema(len(snippets_chunk))
    token_budget = min(max(2048, 1200 * len(snippets_chunk)), 128000)
    last_problems = []
    for _ in range(MAX_ATTEMPTS):
        if last_problems:
            messages.append({
                "role": "user",
                "content": "Fix the emotional spine:\n" + "\n".join(f"- {p}" for p in last_problems),
            })
        data = call_llm_json(messages, schema, max_completion_tokens=token_budget)
        problems = _validate_spine_chunk(data, snippets_chunk)
        if not problems:
            return data
        messages.append({"role": "assistant", "content": json.dumps(data, ensure_ascii=False)})
        last_problems = problems
    raise RuntimeError(f"visual_director emotional spine chunk failed validation: {last_problems}")


def _build_emotional_spine(snippets: list[str]) -> dict:
    """Score every already-cut narration snippet — never invents its own
    boundaries or count (that drift was the actual cause of scenes not matching
    their own narration's emotional register: two independent segmentations of
    the same script, correlated only by count). One emotional_beats entry per
    snippet, by position, schema-locked to the exact snippet count. Chunked and
    scored in parallel — each snippet's score is independent of every other
    snippet's, so there is nothing for chunks to disagree about at the seams."""
    chunks = _chunks(snippets, CHUNK_SIZE)
    with ThreadPoolExecutor(max_workers=min(len(chunks), MAX_PARALLEL_CHUNKS)) as pool:
        chunk_results = list(pool.map(_spine_chunk, chunks))
    emotional_beats = [beat for result in chunk_results for beat in result["emotional_beats"]]
    for i, beat in enumerate(emotional_beats, start=1):
        beat["beat_number"] = i
    core_transformation = _infer_core_transformation(snippets)
    return {"core_transformation": core_transformation, "emotional_beats": emotional_beats}


# ---------------------------------------------------------------------------
# 2. world bible — one call, fixed-size output, decides every id that can exist
# ---------------------------------------------------------------------------

def _world_bible_schema() -> dict:
    return {
        "name": "world_bible",
        "schema": {
            "type": "object",
            "properties": {
                "film_title": {"type": "string"},
                "parallel_story": {
                    "type": "string",
                    "description": "2-4 sentence plot summary of the invented visual story",
                },
                "movie_style": {
                    "type": "string",
                    "description": "visual-only cinematic direction for a stylized 3D animated feature",
                },
                "external_goal": {
                    "type": "string",
                    "description": (
                        "concrete, visually playable real-world goal; progress should be "
                        "visible through action rather than paperwork or approvals"
                    ),
                },
                "protagonist_arc": {
                    "type": "string",
                    "description": "beginning, pressure, choice, and changed ending",
                },
                "supporting_characters": {
                    "type": "array",
                    "maxItems": 4,
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "unique lowercase role slug"},
                            "name": {"type": "string", "description": "short internal character name or role label"},
                            "role": {"type": "string", "description": "stable role inside the invented film"},
                            "story_function": {
                                "type": "string",
                                "description": (
                                    "why this foreground person recurs and how their relationship "
                                    "with the protagonist changes"
                                ),
                            },
                        },
                        "required": ["id", "name", "role", "story_function"],
                        "additionalProperties": False,
                    },
                },
                "recurring_locations": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 8,
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"},
                            "setting_type": {"type": "string", "enum": ["shared_public", "private"]},
                            "social_domain": {"type": "string"},
                            "institution_type": {
                                "type": "string",
                                "description": (
                                    "plain-language real institution or environment, "
                                    "e.g. corporate headquarters, city hall, family home"
                                ),
                            },
                            "visual_identity": {"type": "string"},
                            "story_function": {"type": "string"},
                        },
                        "required": [
                            "id", "name", "setting_type", "social_domain",
                            "institution_type", "visual_identity", "story_function",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "film_title", "parallel_story", "movie_style", "external_goal",
                "protagonist_arc", "supporting_characters", "recurring_locations",
            ],
            "additionalProperties": False,
        },
    }


def _validate_world_bible(data: dict, character_ids: set[str]) -> list[str]:
    problems = []
    supporting = data.get("supporting_characters") or []
    supporting_ids = [c.get("id") for c in supporting]
    if len(supporting_ids) != len(set(supporting_ids)):
        problems.append("supporting character ids must be unique")
    collisions = set(supporting_ids) & character_ids
    if collisions:
        problems.append(f"supporting character ids collide with tracked source cast: {sorted(collisions)}")
    locations = data.get("recurring_locations") or []
    location_ids = [loc.get("id") for loc in locations]
    if len(location_ids) != len(set(location_ids)):
        problems.append("recurring location ids must be unique")
    return problems


def _profile_for_director(story_dossier: dict) -> dict:
    """Expose only the plot-free production handoff, never source audit details."""
    vibe = story_dossier.get("whole_script_vibe") or {}
    return {
        "whole_script_vibe": {"social_class_and_lifestyle": vibe.get("social_class_and_lifestyle")},
        "cinematic_inference": story_dossier.get("cinematic_inference") or {},
        "director_profile": story_dossier.get("director_profile") or {},
    }


def _score_for_director(spine: dict) -> str:
    """Serialize the score without narration anchors, the only source text retained."""
    score = {
        "core_transformation": spine.get("core_transformation"),
        "emotional_beats": [
            {
                "beat_number": beat.get("beat_number"),
                "story_pressure": beat.get("story_pressure"),
                "emotional_valence": beat.get("emotional_valence"),
                "agency": beat.get("agency"),
                "social_openness": beat.get("social_openness"),
                "tempo": beat.get("tempo"),
                "camera_distance": beat.get("camera_distance"),
                "bridge_cues": [cue.get("cue") for cue in beat.get("bridge_cues") or []],
            }
            for beat in spine.get("emotional_beats") or []
        ],
    }
    return json.dumps(score, ensure_ascii=False, indent=2)


def _build_world_bible(characters: list[dict], story_dossier: dict, emotional_spine: dict) -> dict:
    character_ids = [c["id"] for c in characters]
    cast = "\n".join(
        f'- id "{c["id"]}", '
        f'{"protagonist" if c["id"] == "protagonist" else "recurring supporting character"}: '
        f'{c["appearance"]}'
        for c in characters
    )
    beat_count = len(emotional_spine.get("emotional_beats") or [])
    system = f"""
You are the film director for a Christian transformation video. Narration and
picture are TWO LANES. You are intentionally NOT being shown narration events.
You receive its abstract emotional score plus a whole-script production dossier.
Invent a coherent short film that could stand alone with the sound turned off.

This step decides the WORLD and CAST ONLY — film_title, a short plot summary,
movie_style, the protagonist's concrete external_goal, protagonist_arc,
supporting_characters, and recurring_locations. A later step authors the actual
story_beats using exactly what you declare here, so name every location and
every recurring foreground person now — nothing else can be introduced later.

The emotional score controls feeling and pacing only. It is not a plot outline.
The production dossier controls casting, social class, professional energy,
wardrobe, and which worlds feel credible. Invent new events and an external plot
inside that world. Do not contradict source facts or ignore the dossier's vibe.

Give the protagonist a concrete external goal that creates action and continuity:
winning an account, leading a difficult launch, negotiating a partnership, saving a
small business, completing skilled work, preparing a major presentation, repairing
a consequential relationship, hosting an event, making a journey, or another
grounded undertaking selected from the dossier. Do not default to a familiar story
template merely because it is easy to stage; the goal must grow specifically from
this character's inferred world. Let spiritual change emerge through choices, body
language, work, and relationships.

The external goal must be visually playable. Most progress comes from people doing
consequential work, moving through changing environments, handling customers or
colleagues, making or repairing something, traveling, presenting, or solving real
problems. Administrative steps may appear briefly as obstacles, but cannot become
the story engine or substitute for visible progress.

Use the dossier's primary visual vibe as the film's foundation. "Everyday America"
means credible lived texture inside that specific world: it may be corporate,
office-professional, small-business, hospitality, family, faith, working-class,
creative, or another environment. It does not mean every protagonist becomes a
community organizer. Private rooms may appear when earned, but the film must not
become one person alone in generic rooms. Most beats — well over half — should
involve meaningful interaction in shared or public settings, and no single
recurring location should host anywhere near half the film's runtime; spread
activity across the world you invent. This film will run {beat_count} beats —
give it enough recurring locations and supporting cast to sustain that length
without repeating the same room and the same two people throughout.

A faith-community location may be one part of this world, but never the external
plot's default setting or the film's whole identity. The standalone plot should
still work as human drama without relying on a religious event, ceremony, or prop.

Build one cinematic world with recurring locations, clear geography, time
progression, relationship development, and a beginning, pressure, turning point,
choice, and resolved ending — describe that arc in protagonist_arc and
parallel_story; the beat-by-beat depiction happens in the later authoring step.

Anonymous coworkers, neighbors, shoppers, congregants, and community members may
populate scenes naturally only as one-off or background figures in the later
step. Declare every foreground person who will recur across multiple beats or
carry a changing relationship in supporting_characters now. Existing tracked
cast ids remain valid and must not be re-declared.

Every recurring location names its real institution or environment. Use ordinary
real-world reasoning: the activity, authority, formality, and room must agree.
Do not make institutions interchangeable merely because each one contains
tables and chairs.

Direct this as a family-friendly stylized 3D animated feature with cinematic
composition and expressive full-body character staging. movie_style must contain
visual direction only: composition, lenses/framing, production design, lighting,
texture, and color progression. Do not include audio or sound direction. Shared
locations must span at least three genuinely distinct social domains of the
dossier's world (e.g. not three variations on one workplace) — real variety in
where this world happens and who populates it, not one building or institution
standing in for the whole film.

WHOLE-SCRIPT PRODUCTION DOSSIER:
{json.dumps(_profile_for_director(story_dossier or {}), ensure_ascii=False, indent=2)}

TRACKED CAST:
{cast}

ABSTRACT EMOTIONAL SCORE:
{_score_for_director(emotional_spine)}

Return only the world/cast structured plan — no story_beats.
""".strip()

    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                "Invent the standalone parallel visual story's world and cast from the "
                "abstract score. Do not ask for or reconstruct the source narration."
            ),
        },
    ]
    last_problems = []
    for _ in range(MAX_ATTEMPTS):
        if last_problems:
            messages.append({
                "role": "user",
                "content": "Fix the world bible:\n" + "\n".join(f"- {p}" for p in last_problems),
            })
        data = call_llm_json(messages, _world_bible_schema(), max_completion_tokens=8192)
        problems = _validate_world_bible(data, set(character_ids))
        if not problems:
            return data
        messages.append({"role": "assistant", "content": json.dumps(data, ensure_ascii=False)})
        last_problems = problems
    raise RuntimeError(f"visual_director world bible failed validation: {last_problems}")


# ---------------------------------------------------------------------------
# 3. story beats — chunked, SEQUENTIAL (plot causality needs the prior chunk)
# ---------------------------------------------------------------------------

def _beat_chunk_schema(location_ids: list[str], character_ids_all: list[str], count: int) -> dict:
    return {
        "name": "story_beats_chunk",
        "schema": {
            "type": "object",
            "properties": {
                "story_beats": {
                    "type": "array",
                    "minItems": count,
                    "maxItems": count,
                    "items": {
                        "type": "object",
                        "properties": {
                            "location_id": {"type": "string", "enum": location_ids},
                            "activity_type": {"type": "string", "description": "plain-language purpose of the activity"},
                            "setting_logic": {
                                "type": "string",
                                "description": (
                                    "why this activity credibly occurs at this location "
                                    "in the film's specific social world"
                                ),
                            },
                            "character_ids": {"type": "array", "items": {"type": "string", "enum": character_ids_all}},
                            "visible_action": {"type": "string"},
                            "emotional_turn": {"type": "string"},
                            "bridge_cue": {
                                "type": "string",
                                "description": (
                                    "one selected portable cue from the corresponding emotional "
                                    "beat, naturally integrated into this new plot, or empty string"
                                ),
                            },
                        },
                        "required": [
                            "location_id", "activity_type", "setting_logic", "character_ids",
                            "visible_action", "emotional_turn", "bridge_cue",
                        ],
                        "additionalProperties": False,
                    },
                },
                "story_recap": {
                    "type": "string",
                    "description": (
                        "2-4 sentence cumulative summary of the whole plot through the end "
                        "of THIS chunk's beats — what's happened, current relationship/goal "
                        "state — so the next chunk can continue causally without re-reading "
                        "every prior beat"
                    ),
                },
            },
            "required": ["story_beats", "story_recap"],
            "additionalProperties": False,
        },
    }


def _validate_bridge_cues(story_beats: list[dict], spine_beats: list[dict]) -> list[str]:
    """A director may omit a cue, but may not invent one outside source analysis.
    Beats correspond by position, not by a model-supplied number. location_id/
    character_ids validity is enforced structurally by the chunk schema's enums
    (rule 1: schema is the only reject condition) — this checks the one thing an
    enum can't: that the chosen cue actually belongs to its matching spine beat."""
    problems = []
    for i, (spine_beat, story_beat) in enumerate(zip(spine_beats, story_beats), start=1):
        allowed = sorted({cue.get("cue") for cue in spine_beat.get("bridge_cues") or []})
        cue = (story_beat.get("bridge_cue") or "").strip()
        if cue and cue not in allowed:
            problems.append(
                f"beat {i}'s bridge_cue {cue!r} is not one of that beat's allowed cues "
                f"({allowed if allowed else 'none for this beat — leave bridge_cue empty'})"
            )
    return problems


def _recap(world_bible: dict, prior_beats: list[dict], prior_recap: str | None) -> str:
    """Rolling continuity carried into the next chunk. Two complementary pieces,
    not one: `prior_recap` is the MODEL's own cumulative synthesis of the whole
    plot so far (what actually matters is a judgment call, so a model writes it,
    per this stack's rule 5 — Python never string-concatenates plot state); the
    last couple of raw beats give exact phrasing/blocking detail a summary would
    smooth over. Static world facts (goal/arc) are repeated every chunk too —
    this, not a shared static context like the parallel spine pass, is what
    plot causality across sequential chunks actually requires."""
    lines = [
        f"Film: {world_bible['film_title']}",
        f"External goal: {world_bible['external_goal']}",
        f"Protagonist arc: {world_bible['protagonist_arc']}",
    ]
    if prior_recap:
        lines.append(f"Story so far: {prior_recap}")
    if prior_beats:
        lines.append("Most recently authored beats — continue causally from here, never repeat them:")
        for b in prior_beats[-3:]:
            lines.append(f"- ({b['location_id']}) {b['visible_action']} — {b['emotional_turn']}")
    return "\n".join(lines)


def _location_tally(world_bible: dict, prior_beats: list[dict]) -> str:
    """Deterministic fact (a count), not a judgment — how many times each
    location has already been used, so the next chunk can see the same
    imbalance a human reviewer would and spread activity accordingly instead
    of silently drifting toward whichever location it mentioned most recently."""
    counts = {loc["id"]: 0 for loc in world_bible["recurring_locations"]}
    for b in prior_beats:
        if b["location_id"] in counts:
            counts[b["location_id"]] += 1
    if not prior_beats:
        return ""
    tally = ", ".join(f'{loc_id}={n}' for loc_id, n in counts.items())
    return f"Location use so far ({tally}) — favor under-used locations."


def _author_beat_chunk(
    world_bible: dict,
    character_ids_all: list[str],
    location_ids: list[str],
    spine_chunk: list[dict],
    chunk_index: int,
    total_chunks: int,
    beat_offset: int,
    total_beats: int,
    prior_beats: list[dict],
    prior_recap: str | None,
) -> tuple[list[dict], str]:
    is_final = chunk_index == total_chunks - 1
    locations_desc = "\n".join(
        f'- id "{loc["id"]}" ({loc["institution_type"]}, {loc["social_domain"]}): {loc["visual_identity"]}'
        for loc in world_bible["recurring_locations"]
    )
    supporting_desc = "\n".join(
        f'- id "{c["id"]}", {c["role"]}: {c["story_function"]}'
        for c in world_bible["supporting_characters"]
    ) or "(none)"
    system = f"""
You are the film director continuing an already-cast standalone film for a
Christian transformation video. Narration and picture are TWO LANES — you are
not shown narration events, only this chunk's abstract emotional score.

WORLD AND CAST ALREADY DECIDED — use only these ids, invent no new ones:
Film: {world_bible['film_title']}
Plot summary: {world_bible['parallel_story']}
Movie style: {world_bible['movie_style']}
Recurring locations:
{locations_desc}
Supporting characters:
{supporting_desc}

{_recap(world_bible, prior_beats, prior_recap)}
{_location_tally(world_bible, prior_beats)}

The score also contains sparse bridge_cues. These are deliberate points of contact
between the two lanes. Select a cue only where it belongs naturally in the invented
work or social activity, and record the selected phrase in story_beat.bridge_cue.
It may guide a tool, material, tactile detail, gesture, or garment action across
that beat's shots. Do not reconstruct the source event around it. Garment actions
must use the tracked character's locked clothing rather than inventing another coat
or outfit. Leave bridge_cue empty when none fits.

Faith is expressed through conduct, service, reconciliation, community, prayerful
body language, and changed choices. Religious books, paperwork, signs, and decorative
symbols are not visual shorthand for spirituality. For example, a woman lacking hope
at a meeting is shown through her posture and disconnection from the people around
her, not by placing a devotional object in her hands.

Every beat states its activity_type plus a short setting_logic explaining why that
activity credibly occurs at its chosen location right now. Alternate public action,
relationship moments, environmental establishing shots, and quiet reactions so the
film feels directed rather than formulaic.
{"This is the FINAL chunk of beats — resolve the external_goal and bring the "
 "protagonist_arc to its resolved ending within these beats." if is_final else ""}

THIS CHUNK'S NUMBERED EMOTIONAL BEATS ({beat_offset + 1}-{beat_offset + len(spine_chunk)} of {total_beats}):
{_score_for_director({"core_transformation": None, "emotional_beats": spine_chunk})}

Return exactly one story_beat per numbered beat above, in the same order, plus
an updated story_recap covering the whole plot through this chunk.
""".strip()

    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": "Author this chunk's story beats, continuing the plot above without repeating it.",
        },
    ]
    schema = _beat_chunk_schema(location_ids, character_ids_all, len(spine_chunk))
    token_budget = min(max(2048, 1500 * len(spine_chunk)), 128000)
    last_problems = []
    for _ in range(MAX_ATTEMPTS):
        if last_problems:
            messages.append({
                "role": "user",
                "content": "Fix these story beats:\n" + "\n".join(f"- {p}" for p in last_problems),
            })
        data = call_llm_json(messages, schema, max_completion_tokens=token_budget)
        story_beats = data.get("story_beats") or []
        problems = _validate_bridge_cues(story_beats, spine_chunk)
        if not problems:
            return story_beats, (data.get("story_recap") or "").strip()
        messages.append({"role": "assistant", "content": json.dumps(data, ensure_ascii=False)})
        last_problems = problems
    raise RuntimeError(f"visual_director beat chunk failed validation: {last_problems}")


def _author_story_beats(world_bible: dict, character_ids: list[str], emotional_beats: list[dict]) -> list[dict]:
    location_ids = [loc["id"] for loc in world_bible["recurring_locations"]]
    character_ids_all = list(set(character_ids) | {c["id"] for c in world_bible["supporting_characters"]})
    chunks = _chunks(emotional_beats, CHUNK_SIZE)
    all_beats: list[dict] = []
    story_recap = None
    for i, spine_chunk in enumerate(chunks):
        beats, story_recap = _author_beat_chunk(
            world_bible, character_ids_all, location_ids, spine_chunk,
            chunk_index=i, total_chunks=len(chunks),
            beat_offset=len(all_beats), total_beats=len(emotional_beats),
            prior_beats=all_beats, prior_recap=story_recap,
        )
        all_beats.extend(beats)
    for i, beat in enumerate(all_beats, start=1):
        beat["beat_number"] = i
    return all_beats


# ---------------------------------------------------------------------------

def build(
    characters: list[dict],
    narration_snippets: list[str],
    story_dossier: dict | None = None,
) -> dict:
    """Score the already-cut narration snippets, decide the world/cast once,
    then author exactly one story beat per snippet."""
    emotional_spine = _build_emotional_spine(narration_snippets)
    character_ids = [c["id"] for c in characters]
    world_bible = _build_world_bible(characters, story_dossier or {}, emotional_spine)
    story_beats = _author_story_beats(world_bible, character_ids, emotional_spine["emotional_beats"])
    return {
        **world_bible,
        "story_beats": story_beats,
        "emotional_spine": emotional_spine,
        "visual_story_contract_version": VISUAL_STORY_CONTRACT_VERSION,
    }


if __name__ == "__main__":
    sample = {
        "supporting_characters": [
            {"id": "mira", "name": "Mira", "role": "neighbor", "story_function": "recurring confidante"},
        ],
        "recurring_locations": [
            {"id": "hall", "setting_type": "shared_public", "social_domain": "neighborhood life", "institution_type": "community center"},
            {"id": "market", "setting_type": "shared_public", "social_domain": "local commerce", "institution_type": "open-air market"},
            {"id": "garden", "setting_type": "shared_public", "social_domain": "outdoor leisure", "institution_type": "public garden"},
        ],
    }
    assert not _validate_world_bible(sample, {"protagonist"})
    collide = {**sample, "supporting_characters": [{"id": "protagonist", "name": "x", "role": "y", "story_function": "z"}]}
    assert _validate_world_bible(collide, {"protagonist"})
    print("ok  visual-director world-bible structural validation")
