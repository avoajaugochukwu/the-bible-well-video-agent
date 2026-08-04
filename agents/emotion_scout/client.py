"""Emotion scout agent: scores every already-cut narration snippet with the
categorical emotional spine (story_pressure/valence/tempo/camera_distance/
bridge_cues), one entry per snippet, in order — never invents its own
boundaries or count (see agents/CLAUDE.md's narration/visual lane-split rule).

Split out of the old agents/visual_director (that module's pass 1) so the
"how does this beat feel" judgment is its own diagnosable unit, separate from
agents/world_builder's "what world does this happen in" judgment.

Also carries the emotional_stakes/expression_directive fields (new): the
categorical score alone produced "too calm and collected" output — a
low/negative valence doesn't by itself tell a shot author to render tears or
a hand pressed to the forehead. Each beat now gets one concrete sentence
naming the real stakes behind the feeling, plus one concrete, overt physical/
facial direction that must be legible in a single still frame.
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "utils"))

from llm import call_llm_json

EMOTION_SCOUT_CONTRACT_VERSION = 2
MAX_ATTEMPTS = 3

# Snippets/beats per model call — a prompt decision, not a throughput knob (same
# reasoning as sleep-stories/agents/scene_director/config.py's CHUNK_SIZE): this
# decides how much surrounding context one call can vary its output against.
# Larger than agents/location_scout's or agents/recognition_director's CHUNK_SIZE
# (8) on purpose: this call's per-snippet output is smaller (categorical fields
# + two short sentences) than a location/recognition string, so more snippets
# fit one call's completion-token budget without the per-chunk context window
# growing unmanageably.
CHUNK_SIZE = 10
MAX_PARALLEL_CHUNKS = 8

_FROM_STATES = ["withdrawal", "passivity", "fear", "control", "shame", "resentment",
                "grief", "self_reliance"]
_TO_STATES = ["connection", "purposeful_action", "courage", "trust", "acceptance",
              "forgiveness", "hope", "shared_reliance"]


def _chunks(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


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
                            "camera_distance": {
                                "type": "string",
                                "enum": ["wide", "medium", "close", "macro", "pov"],
                                "description": (
                                    "wide: full location, person small within it, isolation/"
                                    "environment. medium: waist-up, conversational distance. "
                                    "close: face and upper body, expression. macro: extreme "
                                    "close-up on one physical object or hand detail, no face "
                                    "needed — use when this snippet's strongest carrier is a "
                                    "small physical action (a bridge_cue tool/material/gesture/"
                                    "garment action). pov: shows only what the person is looking "
                                    "at/reaching toward from their own eyeline, their face absent "
                                    "— use when this snippet is about noticing or fixating on "
                                    "something."
                                ),
                            },
                            "emotional_stakes": {
                                "type": "string",
                                "description": (
                                    "one concrete sentence naming why THIS specific moment "
                                    "matters to this person right now — the real longing, "
                                    "fear, hope, or cost behind the feeling (e.g. 'she has "
                                    "waited years for a marriage she was promised would come, "
                                    "and every wedding she attends measures her own wait "
                                    "against it'). Never a category label or restatement of "
                                    "story_pressure/emotional_valence in other words — name "
                                    "the actual human stakes."
                                ),
                            },
                            "expression_directive": {
                                "type": "string",
                                "description": (
                                    "one concrete, overt physical/facial direction for this "
                                    "beat, legible in a single still frame — never a subdued "
                                    "or neutral resting expression unless the beat's own "
                                    "valence is genuinely calm. Bold joy is open laughter, "
                                    "head back, a wide unguarded smile. Grief or longing is "
                                    "visible tears, a hand pressed to the forehead or over the "
                                    "mouth, shoulders curled in. Shame is eyes down, arms drawn "
                                    "close. Any beat of prayer, deep faith, hope against "
                                    "silence, spiritual longing, or quiet desperation reads as "
                                    "OVERT WEEPING — visible tears on the cheeks, glistening or "
                                    "closed eyes, a trembling or crumpling face, hands clasped "
                                    "hard or pressed to the mouth — never a serene, composed, "
                                    "or gently smiling prayer face. Match the intensity to how "
                                    "large this moment actually is for this person — do not "
                                    "soften it."
                                ),
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
                            "social_openness", "tempo", "camera_distance", "emotional_stakes",
                            "expression_directive", "bridge_cues",
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
                    "    emotion_scout: bridge cue evidence is not exactly verbatim in its "
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
    "any emotional_valence or story_pressure. For emotional_stakes, name the real, "
    "specific human reason this moment matters to this person right now — not a "
    "restatement of the categorical fields, the actual longing/fear/hope/cost behind "
    "them. For expression_directive, give one overt, concrete physical or facial "
    "direction that would be legible in a single still frame and matches how large "
    "this moment genuinely is — bold joy reads as open laughter or a wide unguarded "
    "smile, grief or longing reads as visible tears or a hand pressed to the head, "
    "shame reads as eyes down and arms drawn in. Any beat of prayer, deep faith, hope "
    "against silence, spiritual longing, or quiet desperation reads as overt weeping — "
    "visible tears, glistening or closed eyes, a trembling face, hands clasped hard — "
    "never a serene or gently smiling prayer face. Do not default to a calm, pleasant, "
    "or neutral resting expression unless the beat's own valence is genuinely calm. "
    "For bridge_cues only, extract zero to "
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
    "Select the closest emotional values without explaining them in prose. For "
    "camera_distance, vary the choice across snippets rather than defaulting to medium "
    "or close every time — favor wide for isolation/environment beats, macro for beats "
    "carried by a small physical object or gesture, pov for beats about noticing or "
    "fixating on something, close for emotional expression, medium otherwise. This is "
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
    raise RuntimeError(f"emotion_scout spine chunk failed validation: {last_problems}")


def score(snippets: list[str]) -> dict:
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
    return {
        "core_transformation": core_transformation,
        "emotional_beats": emotional_beats,
        "emotion_scout_contract_version": EMOTION_SCOUT_CONTRACT_VERSION,
    }


if __name__ == "__main__":
    sample = score([
        "She had waited eleven years for a wedding invitation with her own name on it.",
        "Her sister's wedding was in two weeks, and she still had no date.",
    ])
    assert len(sample["emotional_beats"]) == 2, sample
    for beat in sample["emotional_beats"]:
        assert beat.get("emotional_stakes"), beat
        assert beat.get("expression_directive"), beat
    print("ok  emotion_scout.score() -> stakes + expression_directive present per beat")
