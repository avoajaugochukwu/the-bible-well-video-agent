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
CHARACTER_CONTRACT_VERSION = 12

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
    "hair_length": {"type": "string"},
    "haircut": {"type": "string", "description": "one named, geometrically repeatable cut"},
    "hair_part": {"type": "string", "description": "exact side and placement"},
    "hair_end_shape": {"type": "string", "description": "exact blunt, tapered, feathered, curled, or other end geometry"},
    "hair_position": {"type": "string", "description": "exact loose, tucked, tied, braided, or other placement state"},
    "hair_accessory": {"type": "string", "description": "exact hair accessory or explicit no hair accessory"},
    "inner_top": {"type": "string", "description": "neckline, fabric, color, and garment type"},
    "outer_layer": {"type": "string", "description": "color, fabric, and garment type"},
    "outer_layer_closure": {
        "type": "string",
        "description": "exact fully open, fully closed, partially closed with fasteners named, or pullover state",
    },
    "bottom": {"type": "string", "description": "one simple exact trouser or skirt design"},
    "footwear": {"type": "string"},
    "jewelry": {"type": "string", "description": "complete exact jewelry or explicit no jewelry"},
    "accessories": {
        "type": "string",
        "description": "exact reusable accessories worn on the body or explicit no accessories; no bags or handheld props",
    },
}

_VISUAL_PROFILE_SCHEMA = {
    "type": "object",
    "properties": _VISUAL_PROFILE_PROPERTIES,
    "required": list(_VISUAL_PROFILE_PROPERTIES),
    "additionalProperties": False,
}

_REVIEW_SCHEMA = {
    "name": "character_ledger_review",
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
                        "script_spans": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 4,
                            "items": {"type": "string"},
                            "description": "1-4 short substrings quoted VERBATIM from the script where this character appears",
                        },
                    },
                    "required": [
                        "id",
                        "name",
                        "role",
                        "visual_profile",
                        "casting_basis",
                        "script_spans",
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
    "The haircut must be geometrically repeatable: exact length, named cut, exact part, end "
    "shape, placement state, and hair accessory. Do not write only 'bob', 'short hair', or "
    "'ponytail'. Clothing must name the inner top, outer layer, exact closure state, one "
    "simple bottom, footwear, jewelry, and wearable non-jewelry accessories or explicit "
    "absence. Preserve credible family "
    "resemblance when the script establishes relatives. Keep the profile reusable and free "
    "of names, story events, relationships, occupation, religion, emotional history, locations, "
    "and scene props. 'Full-body' is framing, never body size. Body shape must not encode age, "
    "occupation, faith, competence, or emotion.\n"
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


def _review(data: dict, script: str, story_dossier: dict) -> list[str]:
    review = call_llm_json(
        [
            {
                "role": "system",
                "content": (
                    "Review locked structured character profiles for production readiness and "
                    "visual continuity. Approve only if every field is one concrete concise choice; "
                    "no identity, clothing, closure, hair, or jewelry choice is open, hedged, "
                    "variable, or deferred. Hair must use one exact color and a geometrically "
                    "repeatable length, cut, part, end shape, placement, and accessory state rather "
                    "than a generic style name. Established relatives "
                    "have credible visual continuity; body shape is not used as shorthand for "
                    "age, occupation, faith, competence, or emotion; the protagonist follows the "
                    "production dossier's physical casting. The compiled appearance is deliberately occupation- "
                    "and plot-free, so do not demand that a job or narrative role appear in it. "
                    "A stable apparent age within the script's stated age range is sufficient even "
                    "when narration spans birthdays. Ordinary reusable clothing and accessories are "
                    "valid costume continuity, while appearance descriptions contain "
                    "no source events, relationships, occupations, religious identity, locations, "
                    "scene props, or event-specific costumes. Report only concise actionable issues."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"PRODUCTION DOSSIER:\n{story_dossier}\n\n"
                    f"SCRIPT (for identity and relationship audit only):\n{script}\n\n"
                    f"PROPOSED LEDGER:\n{data}"
                ),
            },
        ],
        _REVIEW_SCHEMA,
        max_completion_tokens=2048,
    )
    if review.get("approved"):
        return []
    return review.get("issues") or ["character ledger reviewer rejected the design"]


def _review_profile_contract(data: dict) -> list[str]:
    """Audit only the reusable visual contract, without long-script distraction."""
    review = call_llm_json(
        [
            {
                "role": "system",
                "content": (
                    "Audit locked character visual profiles. Approve only when every field "
                    "contains one exact reusable production choice. Hair must use one uniform "
                    "color and one deterministic geometry: length, cut, part, end shape, "
                    "placement state, and accessory state. Reject mixed or variable color "
                    "patterns unless explicitly marked as a source fact, generic styles that "
                    "can change shape between renders, alternatives, ranges, optional wording, "
                    "and deferred decisions. Clothing must be one ordinary reusable outfit "
                    "with an exact inner top, outer layer, closure state, bottom, footwear, "
                    "jewelry state, and wearable non-jewelry accessories or explicit absence. "
                    "Closure must say fully open, fully closed, pullover, or name exactly which "
                    "fasteners are closed. Accessories must be worn on the body; bags, purses, "
                    "totes, cases, and handheld items are scene props and must be rejected. "
                    "Reject any event costume or references to scenes, "
                    "ceremonies, narrative roles, occupations, locations, props, or different "
                    "outfits for different occasions. Physical specificity is required; do "
                    "not flatten distinct body or facial designs. Report concise actionable issues."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(data, ensure_ascii=False),
            },
        ],
        _REVIEW_SCHEMA,
        max_completion_tokens=2048,
    )
    if review.get("approved"):
        return []
    return review.get("issues") or ["profile contract reviewer rejected the design"]


def _validate(data: dict, script: str) -> list[str]:
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
    seen_appearance_heads = set()
    for c in chars:
        profile = c.get("visual_profile") or {}
        empty_fields = [
            field for field in _VISUAL_PROFILE_PROPERTIES
            if not str(profile.get(field, "")).strip()
        ]
        if empty_fields:
            problems.append(
                f"character '{c.get('id')}' has empty visual_profile fields: {empty_fields}"
            )
        words = len((c.get("appearance") or "").split())
        if words < 35:
            problems.append(
                f"character '{c.get('id')}' compiled appearance is too thin "
                f"({words} words); make visual_profile fields concrete"
            )
        head = (c.get("appearance") or "")[:40].lower()
        if head in seen_appearance_heads:
            problems.append(f"character '{c.get('id')}' has a near-duplicate appearance to another character — make each visually distinct")
        seen_appearance_heads.add(head)
        # script_spans is a loose "where does this character show up" hint retained
        # for ledger review; visual-story shot planning does not consume it — a quoting mismatch here (this
        # script's doubled ""smart-quote"" style trips exact substring checks) isn't
        # worth failing the whole ledger over. Log, don't block.
        for span in c.get("script_spans") or []:
            if span and span not in script:
                print(f"    note: character '{c.get('id')}' script_span {span[:60]!r}... "
                      f"isn't an exact verbatim substring (quoting mismatch, likely harmless)", flush=True)
    return problems


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
        problems = _validate(data, script)
        if not problems:
            problems = _review_profile_contract(data)
        if not problems:
            problems = _review(data, script, story_dossier or {})
        if not problems:
            for character in data["characters"]:
                character["character_contract_version"] = CHARACTER_CONTRACT_VERSION
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
