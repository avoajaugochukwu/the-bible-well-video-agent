"""Plan one coherent parallel visual story for the whole narration."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "utils"))

from llm import call_llm_json


VISUAL_STORY_CONTRACT_VERSION = 11
MAX_ATTEMPTS = 3


def _spine_schema(count: int) -> dict:
    return {
        "name": "emotional_spine",
        "schema": {
            "type": "object",
            "properties": {
                "core_transformation": {
                    "type": "object",
                    "properties": {
                        "from_state": {
                            "type": "string",
                            "enum": [
                                "withdrawal",
                                "passivity",
                                "fear",
                                "control",
                                "shame",
                                "resentment",
                                "grief",
                                "self_reliance",
                            ],
                        },
                        "to_state": {
                            "type": "string",
                            "enum": [
                                "connection",
                                "purposeful_action",
                                "courage",
                                "trust",
                                "acceptance",
                                "forgiveness",
                                "hope",
                                "shared_reliance",
                            ],
                        },
                    },
                    "required": ["from_state", "to_state"],
                    "additionalProperties": False,
                },
                "emotional_beats": {
                    "type": "array",
                    "minItems": count,
                    "maxItems": count,
                    "items": {
                        "type": "object",
                        "properties": {
                            "story_pressure": {
                                "type": "string",
                                "enum": [
                                    "stability",
                                    "unease",
                                    "exposure",
                                    "rupture",
                                    "low_point",
                                    "challenge",
                                    "recognition",
                                    "choice",
                                    "effort",
                                    "reconnection",
                                    "arrival",
                                ],
                            },
                            "emotional_valence": {
                                "type": "string",
                                "enum": ["positive", "mixed", "negative"],
                            },
                            "agency": {"type": "integer", "minimum": 1, "maximum": 5},
                            "social_openness": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 5,
                            },
                            "tempo": {
                                "type": "string",
                                "enum": ["still", "measured", "active"],
                            },
                            "camera_distance": {
                                "type": "string",
                                "enum": ["wide", "medium", "close", "varied"],
                            },
                            "bridge_cues": {
                                "type": "array",
                                "maxItems": 3,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "cue": {"type": "string"},
                                        "cue_type": {
                                            "type": "string",
                                            "enum": [
                                                "tool",
                                                "material_or_texture",
                                                "physical_gesture",
                                                "garment_action",
                                            ],
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
                            "story_pressure",
                            "emotional_valence",
                            "agency",
                            "social_openness",
                            "tempo",
                            "camera_distance",
                            "bridge_cues",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["core_transformation", "emotional_beats"],
            "additionalProperties": False,
        },
    }


def _schema(character_ids: list[str], beat_count: int) -> dict:
    character_item = {"type": "string"}
    return {
        "name": "parallel_visual_story",
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
                            "id": {
                                "type": "string",
                                "description": "unique lowercase role slug",
                            },
                            "name": {
                                "type": "string",
                                "description": "short internal character name or role label",
                            },
                            "role": {
                                "type": "string",
                                "description": "stable role inside the invented film",
                            },
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
                            "setting_type": {
                                "type": "string",
                                "enum": ["shared_public", "private"],
                            },
                            "social_domain": {
                                "type": "string",
                            },
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
                            "id",
                            "name",
                            "setting_type",
                            "social_domain",
                            "institution_type",
                            "visual_identity",
                            "story_function",
                        ],
                        "additionalProperties": False,
                    },
                },
                "story_beats": {
                    "type": "array",
                    "minItems": beat_count,
                    "maxItems": beat_count,
                    "items": {
                        "type": "object",
                        "properties": {
                            "location_id": {"type": "string"},
                            "activity_type": {
                                "type": "string",
                                "description": "plain-language purpose of the activity",
                            },
                            "setting_logic": {
                                "type": "string",
                                "description": (
                                    "why this activity credibly occurs at this location "
                                    "in the film's specific social world"
                                ),
                            },
                            "character_ids": {
                                "type": "array",
                                "items": character_item,
                            },
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
                            "location_id",
                            "activity_type",
                            "setting_logic",
                            "character_ids",
                            "visible_action",
                            "emotional_turn",
                            "bridge_cue",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "film_title",
                "parallel_story",
                "movie_style",
                "external_goal",
                "protagonist_arc",
                "supporting_characters",
                "recurring_locations",
                "story_beats",
            ],
            "additionalProperties": False,
        },
    }


def _validate_spine(data: dict, snippets: list[str]) -> list[str]:
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
                problems.append(
                    f"bridge cue {cue.get('cue')!r} is not a compact portable detail"
                )
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


def _validate(data: dict, character_ids: set[str]) -> list[str]:
    problems = []
    supporting = data.get("supporting_characters") or []
    supporting_ids = [character.get("id") for character in supporting]
    if len(supporting_ids) != len(set(supporting_ids)):
        problems.append("supporting character ids must be unique")
    collisions = set(supporting_ids) & character_ids
    if collisions:
        problems.append(
            f"supporting character ids collide with tracked source cast: {sorted(collisions)}"
        )
    all_character_ids = character_ids | set(supporting_ids)
    locations = data.get("recurring_locations") or []
    location_ids = [loc.get("id") for loc in locations]
    if len(location_ids) != len(set(location_ids)):
        problems.append("recurring location ids must be unique")
    valid_locations = set(location_ids)
    for beat in data.get("story_beats") or []:
        if beat.get("location_id") not in valid_locations:
            problems.append(
                f"a story beat uses unknown location_id {beat.get('location_id')!r}"
            )
        unknown = set(beat.get("character_ids") or []) - all_character_ids
        if unknown:
            problems.append(f"a story beat uses unknown character ids: {sorted(unknown)}")
    return problems


def _validate_bridge_cues(data: dict, emotional_beats: list[dict]) -> list[str]:
    """A director may omit a cue, but may not invent one outside source analysis.
    Beats correspond by position, not by a model-supplied number."""
    story_beats = data.get("story_beats") or []
    problems = []
    for spine_beat, story_beat in zip(emotional_beats, story_beats):
        allowed = {cue.get("cue") for cue in spine_beat.get("bridge_cues") or []}
        cue = (story_beat.get("bridge_cue") or "").strip()
        if cue and cue not in allowed:
            problems.append(f"a story beat uses unapproved bridge_cue {cue!r}")
    return problems


def _build_emotional_spine(snippets: list[str]) -> dict:
    """Score every already-cut narration snippet — never invents its own
    boundaries or count (that drift was the actual cause of scenes not matching
    their own narration's emotional register: two independent segmentations of
    the same script, correlated only by count). One emotional_beats entry per
    snippet, by position, schema-locked to the exact snippet count."""
    numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(snippets, start=1))
    messages = [
        {
            "role": "system",
            "content": (
                "You are a story analyst creating an emotional score for a separate visual film. "
                "Below are the narration's own pre-cut chronological snippets, numbered in order. "
                "Score EVERY numbered snippet, in the same order, with exactly one emotional_beats "
                "entry each — never skip, merge, or compress snippets; a short transitional "
                "snippet still gets its own entry with the closest neutral categorical values "
                "rather than being dropped. Encode story meaning with the categorical fields in "
                "the schema. For bridge_cues only, extract zero to three sparse, portable visual "
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
                "Select the closest emotional values without explaining them in prose."
            ),
        },
        {
            "role": "user",
            "content": f"NUMBERED NARRATION SNIPPETS:\n{numbered}",
        },
    ]
    schema = _spine_schema(len(snippets))
    # Schema size scales with snippet count (no fixed 6-14 cap anymore), so the
    # token budget must scale with it too, or a long script silently burns the
    # whole budget on reasoning with no room left for the actual output.
    token_budget = max(4096, 1000 * len(snippets))
    last_problems = []
    for _ in range(MAX_ATTEMPTS):
        if last_problems:
            messages.append({
                "role": "user",
                "content": "Fix the emotional spine:\n" + "\n".join(f"- {p}" for p in last_problems),
            })
        data = call_llm_json(messages, schema, max_completion_tokens=token_budget)
        problems = _validate_spine(data, snippets)
        if not problems:
            for i, beat in enumerate(data["emotional_beats"], start=1):
                beat["beat_number"] = i
            return data
        messages.append({
            "role": "assistant",
            "content": json.dumps(data, ensure_ascii=False),
        })
        last_problems = problems
    raise RuntimeError(f"visual_director emotional spine failed validation: {last_problems}")


def _profile_for_director(story_dossier: dict) -> dict:
    """Expose only the plot-free production handoff, never source audit details."""
    vibe = story_dossier.get("whole_script_vibe") or {}
    return {
        "whole_script_vibe": {
            "social_class_and_lifestyle": vibe.get("social_class_and_lifestyle"),
        },
        "cinematic_inference": story_dossier.get("cinematic_inference") or {},
        "director_profile": story_dossier.get("director_profile") or {},
    }


def build(
    characters: list[dict],
    narration_snippets: list[str],
    story_dossier: dict | None = None,
) -> dict:
    """Score the already-cut narration snippets, then return the visual-story
    bible with exactly one story beat per snippet."""
    emotional_spine = _build_emotional_spine(narration_snippets)
    emotional_beats = emotional_spine["emotional_beats"]
    character_ids = [c["id"] for c in characters]
    cast = "\n".join(
        f'- id "{c["id"]}", '
        f'{"protagonist" if c["id"] == "protagonist" else "recurring supporting character"}: '
        f'{c["appearance"]}'
        for c in characters
    )
    system = f"""
You are the film director for a Christian transformation video. Narration and
picture are TWO LANES. You are intentionally NOT being shown narration events.
You receive its abstract emotional score plus a whole-script production dossier.
Invent a coherent short film that could stand alone with the sound turned off.

The emotional score controls feeling and pacing only. It is not a plot outline.
The production dossier controls casting, social class, professional energy,
wardrobe, and which worlds feel credible. Invent new events and an external plot
inside that world. Do not contradict source facts or ignore the dossier's vibe.

The score also contains sparse bridge_cues. These are deliberate points of contact
between the two lanes. Select a cue only where it belongs naturally in the invented
work or social activity, and record the selected phrase in story_beat.bridge_cue.
It may guide a tool, material, tactile detail, gesture, or garment action across
that beat's shots. Do not reconstruct the source event around it. Garment actions
must use the tracked character's locked clothing rather than inventing another coat
or outfit. Leave bridge_cue empty when none fits.

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
activity across the world you invent.

A faith-community location may be one part of this world, but never the external
plot's default setting or the film's whole identity. The standalone plot should
still work as human drama without relying on a religious event, ceremony, or prop.

Build one cinematic world with recurring locations, clear geography, time
progression, relationship development, and a beginning, pressure, turning point,
choice, and resolved ending. Keep it reverent and emotionally honest, not preachy,
symbolic, or fantastical. Anonymous coworkers, neighbors, shoppers, congregants,
and community members may populate scenes naturally only as one-off or background
figures. Declare every foreground person who appears across multiple beats or carries
a changing relationship in supporting_characters, then use that id in each applicable
beat's character_ids. A single appearance is one-off — leave them anonymous, don't
declare them. Do not hide a genuinely recurring curator, assistant, client,
coordinator, relative, or colleague inside visible_action as an anonymous role.
Existing tracked cast ids remain valid and must not be re-declared.

Faith is expressed through conduct, service, reconciliation, community, prayerful
body language, and changed choices. Religious books, paperwork, signs, and decorative
symbols are not visual shorthand for spirituality. For example, a woman lacking hope
at a meeting is shown through her posture and disconnection from the people around her,
not by placing a devotional object in her hands.

Every recurring location names its real institution or environment, and every beat
states its activity plus a short setting_logic. Use ordinary real-world reasoning:
the activity, authority, formality, and room must agree. Do not make institutions
interchangeable merely because each one contains tables and chairs.

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

Return exactly one story_beat for every numbered emotional beat below, in the same
order. Each visible_action must advance the invented external plot. Across the
full plan, alternate public action, relationship moments, environmental
establishing shots, and quiet reactions so the film feels directed rather than
formulaic.

Return only the structured visual-story plan.
""".strip()

    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                "Invent the standalone parallel visual story from the abstract score. "
                "Do not ask for or reconstruct the source narration."
            ),
        },
    ]
    # Same scaling concern as the spine call above — story_beats count now
    # matches the snippet count exactly, no fixed cap, so the budget must scale.
    token_budget = max(8192, 1200 * len(emotional_beats))
    last_problems = []
    for _ in range(MAX_ATTEMPTS):
        if last_problems:
            messages.append({
                "role": "user",
                "content": (
                    "Revise the complete plan to fix these structural problems:\n"
                    + "\n".join(f"- {p}" for p in last_problems)
                ),
            })
        data = call_llm_json(
            messages,
            _schema(character_ids, len(emotional_beats)),
            max_completion_tokens=token_budget,
        )
        problems = _validate(data, set(character_ids))
        if not problems:
            problems = _validate_bridge_cues(data, emotional_beats)
        if not problems:
            for i, beat in enumerate(data["story_beats"], start=1):
                beat["beat_number"] = i
            data["emotional_spine"] = emotional_spine
            data["visual_story_contract_version"] = VISUAL_STORY_CONTRACT_VERSION
            return data
        messages.append({
            "role": "assistant",
            "content": json.dumps(data, ensure_ascii=False),
        })
        last_problems = problems
    raise RuntimeError(
        f"visual_director.build() failed validation after {MAX_ATTEMPTS} attempts: "
        f"{last_problems}"
    )


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
                "bridge_cues": [
                    cue.get("cue")
                    for cue in beat.get("bridge_cues") or []
                ],
            }
            for beat in spine.get("emotional_beats") or []
        ],
    }
    return json.dumps(score, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    sample = {
        "recurring_locations": [
            {"id": "hall", "setting_type": "shared_public", "social_domain": "neighborhood life", "institution_type": "community center"},
            {"id": "market", "setting_type": "shared_public", "social_domain": "local commerce", "institution_type": "open-air market"},
            {"id": "garden", "setting_type": "shared_public", "social_domain": "outdoor leisure", "institution_type": "public garden"},
        ],
        "story_beats": [
            {
                "beat_number": i,
                "location_id": ("hall", "market", "garden")[(i - 1) % 3],
                "activity_type": "informal public activity",
                "setting_logic": "The activity naturally uses this shared neighborhood place.",
                "character_ids": ["protagonist"],
            }
            for i in range(1, 7)
        ],
    }
    assert not _validate(sample, {"protagonist"})
    print("ok  visual-director structural validation")
