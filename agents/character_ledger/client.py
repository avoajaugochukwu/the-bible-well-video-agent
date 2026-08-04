"""Character ledger agent: read the whole script once, decide which characters are
worth tracking as a recurring, visually-consistent identity across scenes (not every
mentioned person — only the protagonist, Jesus if he actually appears, and any
supporting character who recurs across multiple beats). Generate -> deterministic
validate -> retry-with-feedback loop, same shape as military/agents/entity_ledger.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "utils"))

from llm import call_llm_json  # utils/

MAX_ATTEMPTS = 5
CHARACTER_CONTRACT_VERSION = 16

_VISUAL_PROFILE_PROPERTIES = {
    "age": {"type": "integer", "description": "one exact production age"},
    "gender": {"type": "string"},
    "ethnicity": {"type": "string", "description": "one concrete ethnicity, not open casting"},
    "height": {"type": "string", "description": "one exact height in feet and inches"},
    "build": {"type": "string", "description": "one concrete neutral body build"},
    "skin_tone": {"type": "string"},
    "face_shape": {"type": "string"},
    "cheek_structure": {"type": "string"},
    "eye_description": {"type": "string", "description": "exact eye color and shape"},
    "nose_description": {"type": "string"},
    "lip_description": {"type": "string"},
    "age_markers": {"type": "string", "description": "specific facial age detail or explicit none"},
    "eyewear": {"type": "string", "description": "exact eyewear or explicit no eyewear"},
    "hair_color": {"type": "string", "description": "one uniform exact color"},
    "hair_texture": {"type": "string"},
    "hair_length": {
        "type": "string",
        "enum": [
            "very short (buzzed or cropped)",
            "short (above chin)",
            "medium (chin to shoulder)",
            "long (past shoulders)",
        ],
    },
    "haircut": {
        "type": "string",
        "description": (
            "one commonly recognized style name, easy to redraw the same way every time "
            "(e.g. ponytail, bun, bob, pixie cut, loose waves, buzz cut, fade, afro, "
            "cornrows) — not a vague catch-all and not a measurement"
        ),
    },
    "hair_part": {"type": "string", "description": "exact side and placement"},
    "hair_end_shape": {"type": "string", "description": "exact blunt, tapered, feathered, curled, or other end geometry"},
    "hair_position": {"type": "string", "description": "exact loose, tucked, tied, braided, or other placement state"},
    "hair_accessory": {
        "type": "string",
        "enum": ["no hair accessory"],
        "description": "locked absence; small hair accessories are too fragile for scene continuity",
    },
    "inner_top": {"type": "string", "description": "neckline, fabric, color, and garment type"},
    "outer_layer": {"type": "string", "description": "color, fabric, and garment type"},
    "outer_layer_closure": {
        "type": "string",
        "enum": ["fully open", "fully closed", "pullover (no closure)"],
    },
    "bottom": {"type": "string", "description": "one simple exact trouser or skirt design"},
    "footwear": {"type": "string"},
    "jewelry": {
        "type": "string",
        "description": (
            "explicit no jewelry unless the script itself makes one stable worn item "
            "identity- or plot-critical"
        ),
    },
    "accessories": {
        "type": "string",
        "enum": ["no accessories"],
        "description": "locked absence; small personal objects are scene props, not character identity",
    },
}

_VISUAL_PROFILE_SCHEMA = {
    "type": "object",
    "properties": _VISUAL_PROFILE_PROPERTIES,
    "required": list(_VISUAL_PROFILE_PROPERTIES),
    "additionalProperties": False,
}

_SCHEMA = {
    "name": "character_ledger",
    "schema": {
        "type": "object",
        "properties": {
            "characters": {
                "type": "array",
                "minItems": 1,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "short lowercase slug, unique, e.g. 'protagonist', 'jesus', 'pastor_daniel'"},
                        "name": {"type": "string", "description": "their name, or a short descriptor if unnamed (e.g. 'the pastor')"},
                        "role": {"type": "string", "description": "one short phrase, their narrative role"},
                        "visual_profile": {
                            **_VISUAL_PROFILE_SCHEMA,
                            "description": (
                                "Locked production specification for every stable visible trait. "
                                "Every field is one exact choice, with no alternatives."
                            ),
                        },
                        "casting_basis": {
                            "type": "string",
                            "description": (
                                "one sentence explaining how the whole-script dossier informed "
                                "the inferred visual design and wardrobe"
                            ),
                        },
                    },
                    "required": [
                        "id",
                        "name",
                        "role",
                        "visual_profile",
                        "casting_basis",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["characters"],
        "additionalProperties": False,
    },
}

def _director_cast_schema(character_ids: list[str]) -> dict:
    count = len(character_ids)
    return {
        "name": "director_supporting_cast",
        "schema": {
            "type": "object",
            "properties": {
                "characters": {
                    "type": "array",
                    "minItems": count,
                    "maxItems": count,
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "enum": character_ids},
                            "name": {"type": "string"},
                            "role": {"type": "string"},
                            "visual_profile": _VISUAL_PROFILE_SCHEMA,
                            "casting_basis": {"type": "string"},
                        },
                        "required": [
                            "id",
                            "name",
                            "role",
                            "visual_profile",
                            "casting_basis",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["characters"],
            "additionalProperties": False,
        },
    }


_SYSTEM = (
    "You are building a character ledger for visually consistent, full-body "
    "illustrated Christian story video. Read the whole script and identify ONLY the "
    "characters worth tracking as a recurring visual identity across scenes:\n"
    "- The protagonist is ALWAYS included, with id exactly 'protagonist'.\n"
    "- Jesus is included ONLY if the script actually depicts him appearing/speaking as "
    "a character — not just mentioned in passing or prayer.\n"
    "- Any other character is included ONLY if they recur across multiple beats of the "
    "script, not a single one-off mention. Do not include background/crowd figures or "
    "unnamed onlookers.\n"
    "visual_profile is the locked production design, not suggestive prose. Fill every field "
    "with exactly one concise choice. Do not use alternatives, ranges, 'or', optional details, "
    "open casting, or decisions deferred to production. Choose one exact age and height. "
    "Choose a single uniform hair color unless the source explicitly requires otherwise. "
    "hair_length is one of the schema's fixed categories; haircut names one commonly "
    "recognized style (ponytail, bun, bob, pixie cut, loose waves, buzz cut, fade, afro, "
    "cornrows, etc. — whatever fits this character) that redraws the same way every time. "
    "If two-tone or graying, name both colors and where each falls (e.g. 'ash-brown with soft "
    "gray at the temples'), not just the dominant color. Clothing must name the inner top, "
    "outer layer, one simple bottom, and footwear; outer_layer_closure is one of the schema's "
    "fixed states. Set hair_accessory to exactly 'no hair accessory'. Set accessories to exactly "
    "'no accessories': pocket items, handheld objects, bags, and other small additions are "
    "scene props and must never be locked onto a character. Use 'no jewelry' unless the script "
    "explicitly makes one stable worn item identity- or plot-critical. Give the cast a real "
    "spread of clothing color across inner_top and outer_layer — real wardrobes include "
    "blues, greens, reds, warm neutrals, and patterns, not just gray, beige, tan, and olive. "
    "Age alone is never a reason to default a character into a muted or drab palette. "
    "Preserve credible family "
    "resemblance when the script establishes relatives. Keep the profile reusable and free "
    "of names, story events, relationships, occupation, religion, emotional history, locations, "
    "and scene props. 'Full-body' is framing, never body size. Body shape must not encode age, "
    "occupation, faith, competence, or emotion. Describe each field with enough concrete visual "
    "detail that an artist could redraw the same person from it alone, and make every tracked "
    "character clearly visually distinct from every other tracked character in this ledger — "
    "no two characters sharing near-identical age, coloring, and build.\n"
    "Return ONLY the JSON object described by the schema."
)


def compile_visual_profile(profile: dict) -> str:
    """Compile the structured character contract into one compact prompt fragment."""
    return (
        f"{profile.get('age')}-year-old {profile.get('ethnicity')} "
        f"{profile.get('gender')}, {profile.get('height')}, {profile.get('build')}, "
        f"{profile.get('skin_tone')}; {profile.get('face_shape')} face, "
        f"{profile.get('cheek_structure')}, {profile.get('eye_description')}, "
        f"{profile.get('nose_description')}, {profile.get('lip_description')}, "
        f"{profile.get('age_markers')}, {profile.get('eyewear')}; "
        f"{profile.get('hair_color')} {profile.get('hair_texture')} hair, "
        f"{profile.get('hair_length')}, {profile.get('haircut')}, "
        f"{profile.get('hair_part')}, {profile.get('hair_end_shape')}, "
        f"{profile.get('hair_position')}, {profile.get('hair_accessory')}; wears "
        f"{profile.get('inner_top')}, {profile.get('outer_layer')} "
        f"{profile.get('outer_layer_closure')}, {profile.get('bottom')}, "
        f"{profile.get('footwear')}, {profile.get('jewelry')}."
        f" {profile.get('accessories')}."
    )


def compile_identity_profile(profile: dict) -> str:
    """Same fields as compile_visual_profile, minus clothing — the part of a
    locked profile that must stay IDENTICAL across every wardrobe variant
    (agents/character_wardrobe generates per-context clothing separately). Used
    to anchor a variant's i2i prompt with concrete age/build/face/hair text
    alongside the reference-image conditioning, instead of relying on a bare
    'same build' instruction — a generic instruction with no concrete text
    backing it is exactly what let body weight drift between variants."""
    return (
        f"{profile.get('age')}-year-old {profile.get('ethnicity')} "
        f"{profile.get('gender')}, {profile.get('height')}, {profile.get('build')}, "
        f"{profile.get('skin_tone')}; {profile.get('face_shape')} face, "
        f"{profile.get('cheek_structure')}, {profile.get('eye_description')}, "
        f"{profile.get('nose_description')}, {profile.get('lip_description')}, "
        f"{profile.get('age_markers')}, {profile.get('eyewear')}; "
        f"{profile.get('hair_color')} {profile.get('hair_texture')} hair, "
        f"{profile.get('hair_length')}, {profile.get('haircut')}, "
        f"{profile.get('hair_part')}, {profile.get('hair_end_shape')}, "
        f"{profile.get('hair_position')}, {profile.get('hair_accessory')}."
        f" {profile.get('accessories')}."
    )


def _materialize_appearances(data: dict) -> dict:
    return {
        "characters": [
            {
                **character,
                "appearance": compile_visual_profile(character.get("visual_profile") or {}),
            }
            for character in data.get("characters") or []
        ]
    }


def _profile_contract_problems(character: dict) -> list[str]:
    """Shared per-character objective check: no required field left empty."""
    char_id = character.get("id")
    profile = character.get("visual_profile") or {}
    empty_fields = [
        field for field in _VISUAL_PROFILE_PROPERTIES
        if not str(profile.get(field, "")).strip()
    ]
    if empty_fields:
        return [f"character '{char_id}' has empty visual_profile fields: {empty_fields}"]
    return []


def _validate(data: dict) -> list[str]:
    problems = []
    chars = data.get("characters") or []
    if not chars:
        problems.append("characters is empty")
        return problems
    ids = [c.get("id") for c in chars]
    if "protagonist" not in ids:
        problems.append("no character with id 'protagonist' — the protagonist must always be included")
    if len(ids) != len(set(ids)):
        problems.append("duplicate character ids — every id must be unique")
    for c in chars:
        problems.extend(_profile_contract_problems(c))
    return problems


def _validate_director_cast(
    data: dict,
    expected_ids: set[str],
) -> list[str]:
    problems = []
    characters = data.get("characters") or []
    ids = [character.get("id") for character in characters]
    if set(ids) != expected_ids or len(ids) != len(expected_ids):
        problems.append(
            f"director supporting cast ids must be exactly {sorted(expected_ids)}"
        )
    for character in characters:
        problems.extend(_profile_contract_problems(character))
    return problems


def build_director_cast(
    visual_story: dict,
    existing_characters: list[dict],
    story_dossier: dict | None = None,
) -> list[dict]:
    """Lock visual identities for recurring people invented by the director."""
    declarations = visual_story.get("supporting_characters") or []
    if not declarations:
        return []
    expected_ids = [character["id"] for character in declarations]
    existing = [
        {
            "id": character.get("id"),
            "role": character.get("role"),
            "appearance": character.get("appearance"),
        }
        for character in existing_characters
    ]
    film_handoff = {
        "film_title": visual_story.get("film_title"),
        "supporting_characters": declarations,
        "recurring_locations": visual_story.get("recurring_locations") or [],
    }
    messages = [
        {
            "role": "system",
            "content": (
                "You are casting recurring supporting characters for an already-directed "
                "animated film. Return one locked visual profile for every declared id and no "
                "others. Make each person visually distinct from the existing cast while fitting "
                "the film world and declared role. Every profile field is one exact choice: "
                "exact age, demographic, height/build, face geometry, deterministic single-color "
                "hair design (hair_length is one of the schema's fixed categories; haircut names "
                "one commonly recognized style — ponytail, bun, bob, pixie cut, buzz cut, fade, "
                "afro, cornrows, etc. — that redraws the same way every time), and one reusable "
                "modern outfit (outer_layer_closure is one of the schema's fixed states). Set "
                "hair_accessory to exactly 'no hair accessory' and accessories to exactly "
                "'no accessories'. Use 'no jewelry' unless the declaration explicitly requires "
                "one stable identity-critical item. Do not add bags, pocket objects, handheld "
                "props, event costumes, alternate outfits, or story actions. Give this cast a real "
                "spread of clothing color — blues, greens, reds, warm neutrals, patterns — never "
                "default every character to gray, beige, tan, or olive regardless of age. Describe each field "
                "with enough concrete visual detail to be redrawable, and make sure no new "
                "character shares near-identical age, coloring, and build with another new "
                "character or with anyone in the existing cast. Return only JSON."
            ),
        },
        {
            "role": "user",
            "content": (
                f"FILM:\n{json.dumps(film_handoff, ensure_ascii=False, indent=2)}\n\n"
                f"EXISTING CAST:\n{json.dumps(existing, ensure_ascii=False, indent=2)}\n\n"
                "PRODUCTION VIBE:\n"
                f"{json.dumps(story_dossier or {}, ensure_ascii=False, indent=2)}"
            ),
        },
    ]
    last_problems = []
    schema = _director_cast_schema(expected_ids)
    for _ in range(MAX_ATTEMPTS):
        if last_problems:
            messages.append({
                "role": "user",
                "content": (
                    "Fix these supporting-cast problems and return the complete JSON:\n"
                    + "\n".join(f"- {problem}" for problem in last_problems)
                ),
            })
        raw_data = call_llm_json(messages, schema, max_completion_tokens=6144)
        data = _materialize_appearances(raw_data)
        problems = _validate_director_cast(data, set(expected_ids))
        if not problems:
            for character in data["characters"]:
                character["character_contract_version"] = CHARACTER_CONTRACT_VERSION
                character["cast_origin"] = "director"
            return data["characters"]
        messages.append({
            "role": "assistant",
            "content": json.dumps(raw_data, ensure_ascii=False),
        })
        last_problems = problems
    raise RuntimeError(
        "character_ledger.build_director_cast() failed validation after "
        f"{MAX_ATTEMPTS} attempts: {last_problems}"
    )


def build(script: str, context: dict, story_dossier: dict | None = None) -> dict:
    """Return {"characters": [...]} — see _SCHEMA for the exact shape."""
    messages = [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": (
                f"WHOLE-SCRIPT PRODUCTION DOSSIER:\n{story_dossier or {}}\n\n"
                f"SCRIPT:\n{script}"
            ),
        },
    ]
    last_problems: list[str] = []
    for attempt in range(MAX_ATTEMPTS):
        if last_problems:
            messages.append({
                "role": "user",
                "content": "Fix these problems with your previous answer and return the corrected full JSON object:\n"
                           + "\n".join(f"- {p}" for p in last_problems),
            })
        raw_data = call_llm_json(messages, _SCHEMA, max_completion_tokens=6144)
        data = _materialize_appearances(raw_data)
        problems = _validate(data)
        if not problems:
            for character in data["characters"]:
                character["character_contract_version"] = CHARACTER_CONTRACT_VERSION
                character["cast_origin"] = "source"
            return data
        messages.append({
            "role": "assistant",
            "content": json.dumps(raw_data, ensure_ascii=False),
        })
        last_problems = problems
    raise RuntimeError(f"character_ledger.build() failed validation after {MAX_ATTEMPTS} attempts: {last_problems}")


if __name__ == "__main__":
    sample_script = (
        "Maria had always kept her faith quiet, tucked away like a secret. Every morning "
        "she scrolled her phone before she ever thought to pray. Then Pastor Daniel stopped "
        "her after service one Sunday. 'God isn't asking for your Sunday,' he said gently, "
        "'He's asking for your whole week.' The words stayed with Maria all week. By Friday, "
        "she had moved her Bible from the shelf to her nightstand, the first thing she'd see "
        "each morning instead of her phone. Pastor Daniel smiled when she told him the "
        "following Sunday — a small, ordinary victory, but hers."
    )
    sample_context = {"setting": "modern daily life", "spiritual_theme": "surrender", "emotional_palette": "warm"}
    result = build(sample_script, sample_context)
    chars = result["characters"]
    assert any(c["id"] == "protagonist" for c in chars), result
    assert all(len(c["appearance"].split()) >= 15 for c in chars), result
    print(f"ok  character_ledger.build() -> {len(chars)} tracked character(s): {[c['id'] for c in chars]}")
