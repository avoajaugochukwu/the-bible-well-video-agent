"""World builder agent: decides the one shared everyday-America world the
picture lane shoots against — film_title, movie_style, supporting_characters,
recurring_locations — from agents/emotion_scout's categorical score and
agents/story_dossier's plot-free production handoff. Fixed-size output
regardless of script length; this is the only place new locations or
supporting characters get declared.

Split out of the old agents/visual_director (that module's pass 2) so
worldbuilding is its own diagnosable unit, separate from agents/emotion_scout's
"how does this beat feel" judgment. No plot is authored here: src/scene_engine.py
shoots each beat independently against this same world, so beat-to-beat
causality/recap machinery doesn't apply.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "utils"))

from llm import call_llm_json

WORLD_BUILDER_CONTRACT_VERSION = 1
MAX_ATTEMPTS = 3


def _schema() -> dict:
    return {
        "name": "world_bible",
        "schema": {
            "type": "object",
            "properties": {
                "film_title": {"type": "string"},
                "movie_style": {
                    "type": "string",
                    "description": "visual-only cinematic direction for a stylized 3D animated feature",
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
            "required": ["film_title", "movie_style", "supporting_characters", "recurring_locations"],
            "additionalProperties": False,
        },
    }


def _validate(data: dict, character_ids: set[str]) -> list[str]:
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


def _score_for_director(emotional_spine: dict) -> str:
    """Serialize the score without narration anchors, the only source text retained."""
    score = {
        "core_transformation": emotional_spine.get("core_transformation"),
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
            for beat in emotional_spine.get("emotional_beats") or []
        ],
    }
    return json.dumps(score, ensure_ascii=False, indent=2)


def build(characters: list[dict], story_dossier: dict, emotional_spine: dict) -> dict:
    character_ids = [c["id"] for c in characters]
    cast = "\n".join(
        f'- id "{c["id"]}", '
        f'{"protagonist" if c["id"] == "protagonist" else "recurring supporting character"}: '
        f'{c["appearance"]}'
        for c in characters
    )
    beat_count = len(emotional_spine.get("emotional_beats") or [])
    system = f"""
You are the visual world-builder for a Christian transformation video. Narration
and picture are TWO LANES. You are intentionally NOT being shown narration events.
You receive its abstract emotional score plus a whole-script production dossier.

Invent ONE consistent everyday-America world for the picture lane to live in —
not a competing plot with its own goal or ending. This step decides film_title,
movie_style, supporting_characters, and recurring_locations only. There is no
story to resolve and no external_goal to track: every beat will later be shot
independently against this same world, so what matters here is that the world is
concrete, varied, and reusable — not that it adds up to a three-act story.

The production dossier controls casting, social class, professional energy,
wardrobe, and which worlds feel credible — ground every location and supporting
character in it. "Everyday America" means credible lived texture inside that
specific world: it may be corporate, office-professional, small-business,
hospitality, family, faith, working-class, creative, or another environment.
Private rooms may appear, but the world must not be one person alone in generic
rooms — most beats will happen in shared or public settings, and no single
recurring location should host anywhere near half the film's runtime, so give it
enough recurring locations ({beat_count} beats total) to keep shots from repeating
the same room and the same two people throughout.

A faith-community location may be one part of this world, but never its default
setting or whole identity.

Declare every foreground person who could recur across multiple beats in
supporting_characters (max 4) — real people with a stable role and story function,
not a cast built to serve a plot. Anonymous coworkers, neighbors, shoppers,
congregants, and community members can populate individual shots later without
being declared here. Existing tracked cast ids remain valid and must not be
re-declared, and every new id/name must also be unmistakably, obviously
different from every tracked cast member's name — never a variant, prefix, or
derivative of one already in TRACKED CAST (if "david" is tracked, do not invent
"sup_david" or any other near-duplicate); pick a genuinely different name so no
one could mistake the two for the same person. The protagonist is this world's
throughline — every location and supporting character should make sense as
somewhere she plausibly is or someone she plausibly knows, not a self-contained
ensemble that could exclude her.

Every recurring location names its real institution or environment. Use ordinary
real-world reasoning: the activity, authority, formality, and room must agree.
Do not make institutions interchangeable merely because each one contains tables
and chairs. Shared locations must span at least three genuinely distinct social
domains of the dossier's world (e.g. not three variations on one workplace) —
real variety in where this world happens and who populates it.

One of recurring_locations must be the protagonist's own regular workplace,
built directly from the dossier's cinematic_inference.protagonist_occupation —
a specific, real workplace room (not a generic "an office"), described concretely
enough that later shots can populate it with anonymous coworkers, clients,
patrons, or customers as background texture. This is an environmental setting,
not a new plot thread: it breaks up "one woman alone in a quiet house" with an
ordinary daily place she goes, nothing more.

Direct this as a family-friendly stylized 3D animated feature with cinematic
composition and expressive full-body character staging. movie_style must contain
visual direction only: composition, lenses/framing, production design, lighting,
texture, and color progression. Do not include audio or sound direction.

WHOLE-SCRIPT PRODUCTION DOSSIER:
{json.dumps(_profile_for_director(story_dossier or {}), ensure_ascii=False, indent=2)}

TRACKED CAST:
{cast}

ABSTRACT EMOTIONAL SCORE:
{_score_for_director(emotional_spine)}

Return only the world/cast structured plan.
""".strip()

    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                "Invent this film's shared world and supporting cast from the abstract "
                "score. Do not ask for or reconstruct the source narration."
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
        data = call_llm_json(messages, _schema(), max_completion_tokens=8192)
        problems = _validate(data, set(character_ids))
        if not problems:
            return {**data, "world_builder_contract_version": WORLD_BUILDER_CONTRACT_VERSION}
        messages.append({"role": "assistant", "content": json.dumps(data, ensure_ascii=False)})
        last_problems = problems
    raise RuntimeError(f"world_builder failed validation: {last_problems}")


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
    assert not _validate(sample, {"protagonist"})
    collide = {**sample, "supporting_characters": [{"id": "protagonist", "name": "x", "role": "y", "story_function": "z"}]}
    assert _validate(collide, {"protagonist"})
    print("ok  world_builder structural validation")
