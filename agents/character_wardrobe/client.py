"""Character wardrobe agent: one whole-film call deciding, per tracked character,
which SIGNIFICANT recurring contexts (a wedding, a job uniform, a funeral) need
their own outfit variant — everyday scenes keep the character's single locked
base outfit. Generate -> deterministic validate -> retry-with-feedback loop, same
shape as agents/character_ledger. Image generation for each declared variant
lives in agents/character_sheet (that module already owns "character+prompt ->
reference image via gpt_image"), not here — this module only decides what's needed.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "utils"))

from llm import call_llm_json  # utils/

MAX_ATTEMPTS = 5
WARDROBE_CONTRACT_VERSION = 2
MAX_VARIANTS_PER_CHARACTER = 7

_CLOTHING_SCHEMA = {
    "type": "object",
    "properties": {
        "inner_top": {"type": "string", "description": "neckline, fabric, color, and garment type"},
        "outer_layer": {"type": "string", "description": "color, fabric, and garment type"},
        "outer_layer_closure": {
            "type": "string",
            "enum": ["fully open", "fully closed", "pullover (no closure)"],
        },
        "bottom": {"type": "string", "description": "one simple exact trouser, skirt, or dress design"},
        "footwear": {"type": "string"},
        "jewelry": {
            "type": "string",
            "description": (
                "explicit 'no jewelry' unless this context genuinely makes one stable "
                "worn item identity- or context-critical (e.g. a wedding ring at a wedding)"
            ),
        },
    },
    "required": ["inner_top", "outer_layer", "outer_layer_closure", "bottom", "footwear", "jewelry"],
    "additionalProperties": False,
}


def _schema(character_ids: list[str], scene_numbers: list[int]) -> dict:
    return {
        "name": "character_wardrobe",
        "schema": {
            "type": "object",
            "properties": {
                "characters": {
                    "type": "array",
                    "minItems": len(character_ids),
                    "maxItems": len(character_ids),
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "enum": character_ids},
                            "variants": {
                                "type": "array",
                                "minItems": 0,
                                "maxItems": MAX_VARIANTS_PER_CHARACTER,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "variant_id": {
                                            "type": "string",
                                            "description": (
                                                "short lowercase slug, unique within this "
                                                "character, e.g. 'wedding_guest'"
                                            ),
                                        },
                                        "context_label": {
                                            "type": "string",
                                            "description": "short human-readable phrase, e.g. 'Wedding guest'",
                                        },
                                        "clothing_profile": _CLOTHING_SCHEMA,
                                        "scene_numbers": {
                                            "type": "array",
                                            "minItems": 1,
                                            "items": {"type": "integer", "enum": scene_numbers},
                                        },
                                    },
                                    "required": [
                                        "variant_id",
                                        "context_label",
                                        "clothing_profile",
                                        "scene_numbers",
                                    ],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["id", "variants"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["characters"],
            "additionalProperties": False,
        },
    }


_SYSTEM = (
    "You are deciding wardrobe variants for tracked characters in a visually "
    "consistent, full-body illustrated Christian story video. Each character "
    "already has ONE locked everyday outfit (their base reference image), used by "
    "default in every scene. Your ONLY job is to decide which SIGNIFICANT, "
    "recurring wardrobe contexts appear across this film's scene list and need "
    "their OWN outfit — not every scene, only ones where the everyday base "
    "outfit would visibly break the scene. The base is a deliberately versatile, "
    "put-together, smart-casual-to-semi-formal outfit, so depart from it in two "
    "directions:\n"
    "- DRESSIER for any formal or celebratory occasion the character is present "
    "at, even only as a guest or attendee (a wedding, a funeral, a graduation, a "
    "baptism, a party, a work uniform) — if the scene list puts this character at "
    "such an occasion across one or more scenes, give them an outfit that matches "
    "it rather than leaving them in everyday clothes at a wedding.\n"
    "- MORE RELAXED for genuinely at-home, off-duty, or comfort scenes where the "
    "put-together base would look overdressed (slouching at home, waking up, "
    "sick in bed, doing chores) — a simple loungewear / hoodie / comfortable "
    "at-home variant.\n"
    "Do not invent a variant for a passing one-scene detail, and do not create "
    "one just because the location changed if the everyday outfit still "
    "plausibly fits it (the character's own kitchen, garden, or porch, dressed "
    "normally, is not a wardrobe-changing context). A character "
    "may have ZERO variants if their base outfit fits every scene they appear in.\n"
    "Each variant is a complete, concrete, one-choice clothing profile: inner "
    "top, outer layer with exact closure state, one simple bottom, footwear, and "
    "jewelry ('no jewelry' unless the context itself makes one item "
    "context-critical). Only clothing differs between variants — never restate "
    "or change face, hair, age, or build; those stay locked from the base "
    "reference image. variant_id is a short lowercase slug unique within that "
    "character. context_label is a short human-readable phrase a production "
    "reviewer will read (e.g. 'Wedding guest'). scene_numbers lists every scene "
    "this variant applies to — you may only assign a character a scene where "
    "they are already listed as present, and each of a character's scenes may "
    "belong to at most one variant; any scene left uncovered uses the everyday "
    "base outfit.\n"
    "Return ONLY the JSON object described by the schema."
)


def compile_wardrobe_profile(profile: dict) -> str:
    """Compile one variant's clothing_profile into a compact prompt fragment —
    exact analogue of character_ledger.compile_visual_profile, clothing-only."""
    return (
        f"wears {profile.get('inner_top')}, {profile.get('outer_layer')} "
        f"{profile.get('outer_layer_closure')}, {profile.get('bottom')}, "
        f"{profile.get('footwear')}, {profile.get('jewelry')}."
    )


def _compact_scene(scene: dict) -> dict:
    return {
        "scene_number": scene["scene_number"],
        "character_ids": scene.get("character_ids") or [],
        "script_snippet": (scene.get("script_snippet") or "")[:200],
        "image_prompt": (scene.get("image_prompt") or "")[:200],
    }


def _validate(data: dict, character_ids: list[str], scenes_by_number: dict) -> list[str]:
    problems = []
    chars = data.get("characters") or []
    ids = [c.get("id") for c in chars]
    if set(ids) != set(character_ids) or len(ids) != len(character_ids):
        problems.append(f"characters ids must be exactly {sorted(character_ids)}")
    for character in chars:
        cid = character.get("id")
        variants = character.get("variants") or []
        variant_ids = [v.get("variant_id") for v in variants]
        if len(variant_ids) != len(set(variant_ids)):
            problems.append(f"character '{cid}' has duplicate variant_id values: {variant_ids}")
        seen_scenes: set[int] = set()
        for variant in variants:
            vid = variant.get("variant_id")
            for n in variant.get("scene_numbers") or []:
                scene = scenes_by_number.get(n)
                if scene is None:
                    problems.append(f"character '{cid}' variant '{vid}' references scene {n}, which does not exist")
                    continue
                if cid not in (scene.get("character_ids") or []):
                    problems.append(
                        f"character '{cid}' variant '{vid}' is assigned scene {n}, but that "
                        f"scene's character_ids does not include '{cid}'"
                    )
                if n in seen_scenes:
                    problems.append(f"character '{cid}' scene {n} is assigned to more than one variant")
                seen_scenes.add(n)
    return problems


def decide(characters: list[dict], scenes: list[dict], story_dossier: dict | None = None) -> list[dict]:
    """Returns `characters`, each extended with a `variants` list (variant_id,
    context_label, clothing_profile, outfit_prompt, scene_numbers,
    wardrobe_contract_version)."""
    character_ids = [c["id"] for c in characters]
    scenes_by_number = {s["scene_number"]: s for s in scenes}
    scene_numbers = sorted(scenes_by_number)
    roster = [{"id": c["id"], "name": c.get("name"), "role": c.get("role")} for c in characters]
    compact_scenes = [_compact_scene(s) for s in scenes]
    messages = [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": (
                f"TRACKED CHARACTERS:\n{json.dumps(roster, ensure_ascii=False, indent=2)}\n\n"
                f"WHOLE-SCRIPT VIBE:\n"
                f"{json.dumps((story_dossier or {}).get('whole_script_vibe') or {}, ensure_ascii=False)}\n\n"
                f"SCENES (chronological):\n{json.dumps(compact_scenes, ensure_ascii=False)}"
            ),
        },
    ]
    schema = _schema(character_ids, scene_numbers)
    last_problems: list[str] = []
    for _ in range(MAX_ATTEMPTS):
        if last_problems:
            messages.append({
                "role": "user",
                "content": "Fix these problems and return the corrected full JSON object:\n"
                           + "\n".join(f"- {p}" for p in last_problems),
            })
        raw_data = call_llm_json(messages, schema, max_completion_tokens=8192)
        problems = _validate(raw_data, character_ids, scenes_by_number)
        if not problems:
            by_id = {c["id"]: c for c in raw_data["characters"]}
            out = []
            for character in characters:
                variants = list((by_id.get(character["id"]) or {}).get("variants") or [])
                for variant in variants:
                    variant["outfit_prompt"] = compile_wardrobe_profile(variant["clothing_profile"])
                out.append({
                    **character,
                    "variants": variants,
                    "wardrobe_contract_version": WARDROBE_CONTRACT_VERSION,
                })
            return out
        messages.append({"role": "assistant", "content": json.dumps(raw_data, ensure_ascii=False)})
        last_problems = problems
    raise RuntimeError(f"character_wardrobe.decide() failed validation after {MAX_ATTEMPTS} attempts: {last_problems}")


if __name__ == "__main__":
    sample_characters = [
        {"id": "protagonist", "name": "Maria", "role": "the protagonist"},
        {"id": "pastor_daniel", "name": "Pastor Daniel", "role": "her pastor"},
    ]
    sample_scenes = [
        {"scene_number": 1, "character_ids": ["protagonist"], "script_snippet": "She prayed quietly in her kitchen.", "image_prompt": "Kitchen, morning light, woman praying at the table."},
        {"scene_number": 2, "character_ids": ["protagonist", "pastor_daniel"], "script_snippet": "At her niece's wedding, she wore her good green dress.", "image_prompt": "Church wedding, formal guests, stained glass light."},
        {"scene_number": 3, "character_ids": ["protagonist", "pastor_daniel"], "script_snippet": "Pastor Daniel gave the wedding toast in his best suit.", "image_prompt": "Wedding reception hall, pastor raising a toast."},
        {"scene_number": 4, "character_ids": ["protagonist"], "script_snippet": "Back home, she watered her garden.", "image_prompt": "Backyard garden, watering can, everyday clothes."},
    ]
    result = decide(sample_characters, sample_scenes)
    assert len(result) == 2, result
    by_id = {c["id"]: c for c in result}
    scenes_by_number = {s["scene_number"]: s for s in sample_scenes}
    for character in result:
        for variant in character["variants"]:
            assert variant["outfit_prompt"].startswith("wears "), variant
            for n in variant["scene_numbers"]:
                assert character["id"] in scenes_by_number[n]["character_ids"], (character["id"], n)
    print(
        "ok  character_wardrobe.decide() -> "
        + ", ".join(f"{c['id']}: {len(c['variants'])} variant(s)" for c in result)
    )
