"""Plan one coherent parallel visual story for the whole narration."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "utils"))

from llm import call_llm_json


VISUAL_STORY_CONTRACT_VERSION = 9
MAX_ATTEMPTS = 3


EMOTIONAL_SPINE_SCHEMA = {
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
                "minItems": 6,
                "maxItems": 14,
                "items": {
                    "type": "object",
                    "properties": {
                        "beat_number": {"type": "integer"},
                        "narration_anchor": {
                            "type": "string",
                            "description": "short verbatim phrase locating this region in the narration",
                        },
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
                                            "short exact narration quote proving the visible "
                                            "cue is physically present and affirmed"
                                        ),
                                    },
                                },
                                "required": ["cue", "cue_type", "evidence"],
                                "additionalProperties": False,
                            },
                            "description": (
                                "sparse portable visual anchors from this narration phase: "
                                "tools, materials, textures, or garment actions that can live "
                                "inside a different plot"
                            ),
                        },
                    },
                    "required": [
                        "beat_number",
                        "narration_anchor",
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

PLAN_REVIEW_SCHEMA = {
    "name": "visual_story_review",
    "schema": {
        "type": "object",
        "properties": {
            "approved": {"type": "boolean"},
            "issues": {
                "type": "array",
                "maxItems": 8,
                "items": {"type": "string"},
            },
        },
        "required": ["approved", "issues"],
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
                            "beat_number": {"type": "integer"},
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
                            "beat_number",
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


def _validate_spine(data: dict, script: str) -> list[str]:
    problems = []
    beats = data.get("emotional_beats") or []
    numbers = [beat.get("beat_number") for beat in beats]
    if numbers != list(range(1, len(beats) + 1)):
        problems.append("emotional beat numbers must be contiguous and start at 1")
    for beat in beats:
        anchor = (beat.get("narration_anchor") or "").strip()
        if not anchor:
            problems.append(f"emotional beat {beat.get('beat_number')} has no narration anchor")
        elif anchor not in script:
            # Quoting normalization can make an otherwise useful anchor inexact.
            print(
                f"    director: beat {beat.get('beat_number')} anchor is not exactly verbatim; "
                "keeping it as a semantic locator",
                flush=True,
            )
        for cue in beat.get("bridge_cues") or []:
            if len((cue.get("cue") or "").split()) > 6:
                problems.append(
                    f"emotional beat {beat.get('beat_number')} bridge cue "
                    f"{cue.get('cue')!r} is not a compact portable detail"
                )
            evidence = (cue.get("evidence") or "").strip()
            if not evidence:
                problems.append(
                    f"emotional beat {beat.get('beat_number')} bridge cue "
                    f"{cue.get('cue')!r} has no evidence"
                )
            elif evidence not in script:
                # Same tolerance as narration_anchor above: paraphrase is fine,
                # _review_bridge_cues is the real groundedness check.
                print(
                    f"    director: beat {beat.get('beat_number')} bridge cue evidence "
                    "is not exactly verbatim; keeping it as a semantic locator",
                    flush=True,
                )
    return problems


def _review_bridge_cues(data: dict, script: str) -> list[str]:
    """Reject negated and figurative cues that exact substring checks cannot."""
    proposed = [
        {
            "beat_number": beat.get("beat_number"),
            "bridge_cues": beat.get("bridge_cues") or [],
        }
        for beat in data.get("emotional_beats") or []
    ]
    review = call_llm_json(
        [
            {
                "role": "system",
                "content": (
                    "Audit visual bridge cues against their quoted narration evidence. "
                    "Approve only tangible things or directly visible physical actions that "
                    "the evidence AFFIRMS are present: tools, materials, textures, gestures, "
                    "or garment actions. Reject anything absent, avoided, imagined, "
                    "hypothetical, or negated. Reject figurative doors, locks, weight, light, "
                    "or other metaphors unless the evidence depicts the physical thing. "
                    "Reject cues that add an object not stated in the evidence. A cue may "
                    "shorten the exact wording but cannot change its meaning. PORTABILITY IS "
                    "MANDATORY: reject a cue that carries a source event, location, occupation, "
                    "relationship, celebration, social status, or complete tableau. A physical "
                    "gesture contains only the movement, not the room or emotional explanation. "
                    "A garment action contains only the action and must not lock a source outfit. "
                    "A material_or_texture describes sensory material, not an invitation or other "
                    "event-bearing document. Return concise beat-numbered corrections."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"NARRATION:\n{script}\n\n"
                    "PROPOSED CUES:\n"
                    f"{json.dumps(proposed, ensure_ascii=False, indent=2)}"
                ),
            },
        ],
        PLAN_REVIEW_SCHEMA,
        max_completion_tokens=2048,
    )
    if review.get("approved"):
        return []
    return review.get("issues") or ["bridge cue reviewer rejected the cues"]


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
    public_locations = {
        loc.get("id") for loc in locations if loc.get("setting_type") == "shared_public"
    }
    if len(public_locations) < 3:
        problems.append("the film needs at least three recurring shared/public locations")
    public_domains = {
        loc.get("social_domain")
        for loc in locations
        if loc.get("id") in public_locations
    }
    if len(public_domains) < 3:
        problems.append("shared/public locations must span at least three social domains")
    beats = data.get("story_beats") or []
    numbers = [beat.get("beat_number") for beat in beats]
    if numbers != list(range(1, len(beats) + 1)):
        problems.append("story beat numbers must be contiguous and start at 1")
    valid_locations = set(location_ids)
    for beat in beats:
        if beat.get("location_id") not in valid_locations:
            problems.append(
                f"beat {beat.get('beat_number')} uses unknown location_id "
                f"{beat.get('location_id')!r}"
            )
        unknown = set(beat.get("character_ids") or []) - all_character_ids
        if unknown:
            problems.append(
                f"beat {beat.get('beat_number')} uses unknown character ids: {sorted(unknown)}"
            )
    for supporting_id in supporting_ids:
        appearances = sum(
            supporting_id in (beat.get("character_ids") or [])
            for beat in beats
        )
        if appearances < 2:
            problems.append(
                f"supporting character {supporting_id!r} appears in only {appearances} "
                "beat(s); only recurring foreground roles belong in supporting_characters"
            )
    public_beats = sum(beat.get("location_id") in public_locations for beat in beats)
    if beats and public_beats * 2 < len(beats):
        problems.append(
            f"only {public_beats}/{len(beats)} story beats use shared/public locations; "
            "at least half must"
        )
    if beats:
        busiest = max(
            (sum(beat.get("location_id") == loc_id for beat in beats) for loc_id in location_ids),
            default=0,
        )
        if busiest * 2 > len(beats):
            problems.append("more than half the story beats use one location")
    return problems


def _validate_bridge_cues(data: dict, emotional_beats: list[dict]) -> list[str]:
    """A director may omit a cue, but may not invent one outside source analysis."""
    allowed = {
        beat.get("beat_number"): {
            cue.get("cue")
            for cue in beat.get("bridge_cues") or []
        }
        for beat in emotional_beats
    }
    problems = []
    for beat in data.get("story_beats") or []:
        cue = (beat.get("bridge_cue") or "").strip()
        if cue and cue not in allowed.get(beat.get("beat_number"), set()):
            problems.append(
                f"beat {beat.get('beat_number')} uses unapproved bridge_cue {cue!r}"
            )
    return problems


def _build_emotional_spine(script: str) -> dict:
    """Reduce the narration to an abstract score before any visual story is invented."""
    messages = [
        {
            "role": "system",
            "content": (
                "You are a story analyst creating an emotional score for a separate visual film. "
                "Read the Christian narration and divide its progression into 6-14 chronological "
                "phases. Preserve one short verbatim narration_anchor per phase solely for later "
                "alignment. Encode story meaning with the categorical fields in the schema. "
                "For bridge_cues only, extract zero to three sparse, portable visual anchors "
                "from that phase: a specific tool, material, tactile texture, repeated physical "
                "gesture, or garment action that could naturally appear inside a different plot. "
                "Every cue must include a short exact evidence quote from the narration. The "
                "evidence must affirm that the physical cue is present or performed. Do not turn "
                "an absent, negated, hypothetical, or figurative object into a cue. "
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
            "content": f"NARRATION:\n{script}",
        },
    ]
    last_problems = []
    for _ in range(MAX_ATTEMPTS):
        if last_problems:
            messages.append({
                "role": "user",
                "content": "Fix the emotional spine:\n" + "\n".join(f"- {p}" for p in last_problems),
            })
        data = call_llm_json(messages, EMOTIONAL_SPINE_SCHEMA, max_completion_tokens=4096)
        problems = _validate_spine(data, script)
        if not problems:
            problems = _review_bridge_cues(data, script)
        if not problems:
            return data
        messages.append({
            "role": "assistant",
            "content": json.dumps(data, ensure_ascii=False),
        })
        last_problems = problems
    raise RuntimeError(f"visual_director emotional spine failed validation: {last_problems}")


def _review_plan(
    data: dict,
    story_dossier: dict,
    emotional_spine: dict | None = None,
) -> list[str]:
    """General semantic review without encoding a catalog of institution rules."""
    approved_bridge_cues = [
        {
            "beat_number": beat.get("beat_number"),
            "bridge_cues": [
                cue.get("cue")
                for cue in beat.get("bridge_cues") or []
            ],
        }
        for beat in (emotional_spine or {}).get("emotional_beats") or []
    ]
    review = call_llm_json(
        [
            {
                "role": "system",
                "content": (
                    "Review a proposed parallel visual film against its production dossier. "
                    "Approve only if: the protagonist and wardrobe fit the whole-script vibe; "
                    "the external plot feels specific rather than a generic civic template; "
                    "the external goal grows from the inferred professional or distinctive "
                    "social world rather than promoting background faith/community texture "
                    "into the main plot without a character-specific reason; "
                    "the film is genuinely parallel and does not replay source events, "
                    "celebrations, locations, or plot actions; sparse APPROVED BRIDGE CUES may "
                    "be reused as tools, materials, textures, gestures, or garment actions, "
                    "but must be natural to the invented plot rather than recreate the source; "
                    "each stated activity credibly belongs in its chosen real institution; "
                    "locations are not treated as interchangeable rooms; scenes provide varied "
                    "action rather than repeated meetings and paperwork. When a professional "
                    "world offers hands-on, customer-facing, field, travel, production, or "
                    "problem-solving action, administrative confrontation, negotiation, and "
                    "presentation should not become multiple similar turning points; compress "
                    "them and dramatize progress through the work itself. Most progress is "
                    "visible through consequential activity in changing environments, with "
                    "administration only an obstacle rather than the dramatic spine; and the "
                    "plot has clear cause, pressure, choice, and resolution. Do not demand literal narration "
                    "events or props. Source facts are supplied only to detect distinctive "
                    "overlap or contradiction; do not ask the parallel film to include them, "
                    "Every foreground person who appears in multiple beats or carries a changing "
                    "relationship is declared in supporting_characters and referenced by id. "
                    "Anonymous people are genuinely one-off or background-only; "
                    "and do not reject an ordinary generic detail merely because both stories "
                    "could contain it. Report concise actionable issues."
                ),
            },
            {
                "role": "user",
                "content": (
                    "PRODUCTION DOSSIER:\n"
                    f"{json.dumps(_profile_for_director(story_dossier), ensure_ascii=False, indent=2)}\n\n"
                    "SOURCE FACTS (overlap/contradiction audit only):\n"
                    f"{json.dumps(story_dossier.get('source_facts') or {}, ensure_ascii=False, indent=2)}\n\n"
                    "APPROVED BRIDGE CUES:\n"
                    f"{json.dumps(approved_bridge_cues, ensure_ascii=False, indent=2)}\n\n"
                    "PROPOSED FILM:\n"
                    f"{json.dumps(data, ensure_ascii=False, indent=2)}"
                ),
            },
        ],
        PLAN_REVIEW_SCHEMA,
        max_completion_tokens=2048,
    )
    if review.get("approved"):
        return []
    return review.get("issues") or ["semantic reviewer rejected the visual story"]


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
    script: str,
    context: dict,
    characters: list[dict],
    story_dossier: dict | None = None,
) -> dict:
    """Read the whole script and return the visual-story bible."""
    emotional_spine = _build_emotional_spine(script)
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
become one person alone in generic rooms. At least half the beats should involve
meaningful interaction in shared or public settings.

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
beat's character_ids. Do not hide a recurring curator, assistant, client, coordinator,
relative, or colleague inside visible_action as an anonymous role. Existing tracked
cast ids remain valid and must not be re-declared.

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
locations must span at least three credible parts of the dossier's world. Do not
let one building or institution become the whole film.

WHOLE-SCRIPT PRODUCTION DOSSIER:
{json.dumps(_profile_for_director(story_dossier or {}), ensure_ascii=False, indent=2)}

TRACKED CAST:
{cast}

ABSTRACT EMOTIONAL SCORE:
{_score_for_director(emotional_spine)}

Return exactly one story_beat for every numbered emotional beat, preserving the
beat numbers. Each visible_action must advance the invented external plot. Across
the full plan, alternate public action, relationship moments, environmental
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
            max_completion_tokens=8192,
        )
        problems = _validate(data, set(character_ids))
        if not problems:
            problems = _validate_bridge_cues(data, emotional_beats)
        if not problems:
            problems = _review_plan(
                data,
                story_dossier or {},
                emotional_spine,
            )
        if not problems:
            anchors = {
                beat["beat_number"]: beat["narration_anchor"]
                for beat in emotional_beats
            }
            for beat in data["story_beats"]:
                beat["narration_anchor"] = anchors[beat["beat_number"]]
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
