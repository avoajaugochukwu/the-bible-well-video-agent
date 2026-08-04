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
CHARACTER_CONTRACT_VERSION = 18

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
    "A character's base outfit is the fallback worn in EVERY scene that has no special "
    "outfit, so make it versatile and put-together enough to read naturally across many "
    "everyday settings at once — a workday, a dinner, a celebration, a church service — a "
    "smart-casual to semi-formal register in a real saturated color, never loungewear, "
    "sweats, athletic wear, or a drab uniform. Women lean toward a colorful dress or a "
    "tailored blouse with a skirt or trousers; men toward a crisp collared shirt or an "
    "unstructured blazer without a tie, in a confident non-neutral color. "
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
                "default every character to gray, beige, tan, or olive regardless of age. A base "
                "outfit is the fallback worn in every scene without a special outfit, so make it a "
                "versatile, put-together, smart-casual to semi-formal look in a real saturated "
                "color that reads naturally across a workday, a dinner, a celebration, or a church "
                "service — never loungewear, sweats, athletic wear, or a drab uniform. Describe each field "
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


# ponytail: the female protagonist's base outfit is HARD-PINNED, not LLM-chosen —
# the model kept picking drab/odd everyday clothes (and boots) that read wrong the
# moment a scene has no wardrobe variant. This is the deterministic universal
# fallback: a put-together skirt-suit that fits office / dinner / celebration /
# service alike. Upgrade path: make it per-channel config if a channel ever wants a
# different signature look, or extend to the male protagonist with his own template.
_FEMALE_PROTAGONIST_BASE_OUTFIT = {
    "inner_top": "fitted white ribbed sleeveless top with a straight square neckline",
    "outer_layer": "dusty rose-pink tailored peplum blazer with notched lapels and long sleeves",
    "outer_layer_closure": "fully open",
    "bottom": "matching dusty rose-pink knee-length pencil skirt",
    "footwear": "pointed-toe blush-grey low heels",
    "jewelry": "no jewelry",
}

_FEMALE_TOKENS = ("female", "woman", "women", "girl")


def _is_female(profile: dict) -> bool:
    return any(t in (profile.get("gender") or "").lower() for t in _FEMALE_TOKENS)


def _pin_protagonist_base_outfit(characters: list[dict]) -> None:
    """Hard-lock the female protagonist's base outfit to the universal fallback
    (_FEMALE_PROTAGONIST_BASE_OUTFIT) instead of trusting the ledger LLM's per-run
    clothing pick, and recompile her appearance so her base reference image renders
    that outfit. Only the clothing fields change — face/hair/build stay as authored.
    A male protagonist is left to the prompt-guided base. Mutates in place."""
    for c in characters:
        if c.get("id") != "protagonist":
            continue
        profile = c.get("visual_profile") or {}
        if not _is_female(profile):
            continue
        profile.update(_FEMALE_PROTAGONIST_BASE_OUTFIT)
        c["visual_profile"] = profile
        c["appearance"] = compile_visual_profile(profile)


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
            _pin_protagonist_base_outfit(data["characters"])
            return data
        messages.append({
            "role": "assistant",
            "content": json.dumps(raw_data, ensure_ascii=False),
        })
        last_problems = problems
    raise RuntimeError(f"character_ledger.build() failed validation after {MAX_ATTEMPTS} attempts: {last_problems}")


_ADDITIVE_SYSTEM = (
    "You are reviewing an ALREADY-BUILT character ledger for one Christian story "
    "video, for completeness only. You are given the whole script and the "
    "characters that are ALREADY tracked. Your ONLY job is to name characters "
    "that are MISSING from that cast and genuinely worth tracking as a recurring "
    "visual identity, and to return ONLY those additions.\n"
    "Add a character ONLY if BOTH hold: (a) they are a specific named or clearly "
    "role-defined person (a bride, a groom, an officiant/pastor, a named friend) "
    "— never an anonymous crowd or a plural collective (guests, the congregation, "
    "coworkers, mourners), and (b) they recur across more than one beat OR anchor "
    "a significant occasion the script actually depicts (a wedding, a funeral, a "
    "graduation, a baptism) where a named figure clearly belongs. An occasion the "
    "existing cast leaves empty of the people it obviously needs — a wedding with "
    "no bride or groom, a service with no minister — is exactly what to catch.\n"
    "Do NOT repeat, rename, re-id, restate, or 'improve' any already-tracked "
    "character; additions must be genuinely new people. Do NOT add one-off "
    "mentions or background figures. If nothing is missing, return an EMPTY "
    "characters list — that is a valid and common answer; never invent someone "
    "just to fill it.\n"
    "Every added character is a full locked visual_profile with the SAME "
    "discipline as the rest of the ledger: fill every field with exactly one "
    "concrete choice, no ranges or 'or' or deferred decisions; one uniform hair "
    "color; hair_length and outer_layer_closure from the schema's fixed "
    "categories; 'no hair accessory', 'no accessories', and 'no jewelry' unless "
    "the script explicitly makes one worn item identity-critical. The base outfit "
    "is a versatile, put-together, smart-casual-to-semi-formal look in a real "
    "saturated color (never drab gray/beige/olive, never loungewear or a uniform) "
    "that reads across a workday, a dinner, a celebration, or a service. Make each "
    "addition visually distinct from every already-tracked character and from the "
    "other additions. Keep profiles free of names, story events, and scene props.\n"
    "Return ONLY the JSON object described by the schema."
)


def _validate_additive(data: dict, existing_ids: set[str]) -> list[str]:
    """Additive-pass facts only (agents/CLAUDE.md rule 3): an addition may not
    collide with an already-tracked id, additions may not collide with each
    other, and every profile field is filled. An EMPTY list is valid — "nothing
    was missed" is the common, correct answer, so (unlike _validate) emptiness is
    never itself a problem."""
    problems = []
    chars = data.get("characters") or []
    ids = [c.get("id") for c in chars]
    for cid in ids:
        if cid in existing_ids:
            problems.append(
                f"character '{cid}' duplicates an already-tracked character — "
                "additions must be genuinely NEW people, not restatements"
            )
    if len(ids) != len(set(ids)):
        problems.append("duplicate character ids among additions — every id must be unique")
    for c in chars:
        problems.extend(_profile_contract_problems(c))
    return problems


def build_additive(
    script: str,
    context: dict,
    existing_characters: list[dict],
    story_dossier: dict | None = None,
) -> list[dict]:
    """Second, ADDITIVE ledger pass: given the whole script and the cast already
    tracked, return ONLY the characters that were missed and are worth tracking
    (e.g. a named bride/groom/officiant a depicted occasion needs) — never
    duplicating or restating an existing character. Returns [] when nothing is
    missing, which is the common case. cast_origin='source-additive'. This is a
    generative add-only call, not a reviewer grading the first pass's taste (it
    never rewrites or rejects existing characters), so it sits inside
    agents/CLAUDE.md rule 2, same as build_director_cast()."""
    existing_ids = {c.get("id") for c in existing_characters}
    existing_brief = [
        {"id": c.get("id"), "role": c.get("role"), "name": c.get("name")}
        for c in existing_characters
    ]
    messages = [
        {"role": "system", "content": _ADDITIVE_SYSTEM},
        {
            "role": "user",
            "content": (
                f"WHOLE-SCRIPT PRODUCTION DOSSIER:\n{story_dossier or {}}\n\n"
                "ALREADY-TRACKED CAST (do NOT return any of these again):\n"
                f"{json.dumps(existing_brief, ensure_ascii=False, indent=2)}\n\n"
                f"SCRIPT:\n{script}"
            ),
        },
    ]
    last_problems: list[str] = []
    for _ in range(MAX_ATTEMPTS):
        if last_problems:
            messages.append({
                "role": "user",
                "content": "Fix these problems and return the corrected full JSON object:\n"
                           + "\n".join(f"- {p}" for p in last_problems),
            })
        raw_data = call_llm_json(messages, _SCHEMA, max_completion_tokens=6144)
        data = _materialize_appearances(raw_data)
        problems = _validate_additive(data, existing_ids)
        if not problems:
            for character in data["characters"]:
                character["character_contract_version"] = CHARACTER_CONTRACT_VERSION
                character["cast_origin"] = "source-additive"
            return data["characters"]
        messages.append({"role": "assistant", "content": json.dumps(raw_data, ensure_ascii=False)})
        last_problems = problems
    raise RuntimeError(
        f"character_ledger.build_additive() failed validation after {MAX_ATTEMPTS} attempts: {last_problems}"
    )


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

    # _validate_additive is pure logic — check it deterministically, no LLM call.
    _full = {f: "x" for f in _VISUAL_PROFILE_PROPERTIES}
    assert _validate_additive({"characters": []}, {"protagonist"}) == [], "empty additions must be valid"
    _collide = {"characters": [{"id": "protagonist", "visual_profile": _full}]}
    assert any("duplicates" in p for p in _validate_additive(_collide, {"protagonist"})), "id collision must be caught"
    _new = {"characters": [{"id": "bride", "visual_profile": _full}]}
    assert _validate_additive(_new, {"protagonist"}) == [], "a genuinely new, fully-specified addition must pass"
    print("ok  character_ledger._validate_additive: empty ok, collision caught, new addition passes")

    # _pin_protagonist_base_outfit is pure logic — check deterministically, no LLM.
    _she = {"id": "protagonist", "visual_profile": {**_full, "gender": "female"}, "appearance": "old"}
    _he = {"id": "protagonist", "visual_profile": {**_full, "gender": "male", "outer_layer": "navy blazer"}, "appearance": "old"}
    _other = {"id": "friend", "visual_profile": {**_full, "gender": "female", "outer_layer": "teal coat"}, "appearance": "old"}
    _pin_protagonist_base_outfit([_she, _he, _other])
    assert _she["visual_profile"]["outer_layer"] == _FEMALE_PROTAGONIST_BASE_OUTFIT["outer_layer"], _she
    assert "rose-pink" in _she["appearance"], _she["appearance"]
    assert _he["visual_profile"]["outer_layer"] == "navy blazer", "male protagonist must be untouched"
    assert _other["visual_profile"]["outer_layer"] == "teal coat", "non-protagonist woman must be untouched"
    print("ok  character_ledger._pin_protagonist_base_outfit: female protagonist pinned, male + others untouched")
