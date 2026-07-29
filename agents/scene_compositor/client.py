"""Scene compositor agent: per-scene t2i generation (gpt-image-2) using the tracked
characters present in that scene, character description folded into the prompt
text. NO vision-QA anywhere in this app — matching is a human call made off the
gallery review (src/gallery.py). i2i (Krea image-to-image against each character's
reference sheet) is cut for now — bring it back if t2i-only consistency doesn't
hold up in testing, not before.
"""
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "utils"))

import gpt_image      # src/

COMPOSITOR_CONTRACT_VERSION = 2
SCENE_STYLE_PREFIX = (
    "A horizontal 16:9 3D animated film still, Pixar style with soft-matte "
    "detailed textures. "
)

def _present_characters(scene: dict, characters_by_id: dict) -> list[dict]:
    return [characters_by_id[cid] for cid in (scene.get("character_ids") or []) if cid in characters_by_id]


def _role_label(character: dict) -> str:
    """Use film-neutral labels; source relationships belong to the narration lane."""
    character_id = character.get("id")
    if character_id == "protagonist":
        return "the protagonist"
    if character_id == "jesus":
        return "Jesus"
    return "the recurring supporting character"


def _name_tokens(character: dict) -> list[str]:
    """Return full and given-name forms, including names with role suffixes such as
    ``Sharon (sister-in-law)``. Common names in any ledger field can trigger the
    image endpoint's public-figure matcher."""
    name = (character.get("name") or "").strip()
    if not name:
        return []
    bare = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
    first = bare.split()[0] if bare else ""
    return sorted({part for part in (name, bare, first) if len(part) >= 2}, key=len, reverse=True)


def _anonymize_names(text: str, characters_by_id: dict) -> str:
    """gpt-image-2 blocks prompts containing a real given name as a 'public-figure'
    safety match (confirmed: 'Ellen' alone flips an otherwise-fine prompt from OK to
    moderation_blocked) — even a common first name can false-positive-match a real
    person. Strip every cast name, not only names of characters present in the scene:
    roles and appearances can refer to another member of the cast."""
    for c in characters_by_id.values():
        for name in _name_tokens(c):
            text = re.sub(rf"\b{re.escape(name)}\b", _role_label(c), text, flags=re.IGNORECASE)
    return text


def _safe_appearance(character: dict, characters_by_id: dict) -> str:
    appearance = _anonymize_names(character.get("appearance") or "", characters_by_id)
    return re.sub(r"\s+", " ", appearance).strip(" .")


def build_scene_prompt(
    scene: dict,
    characters_by_id: dict,
    movie_style: str = "",
) -> str:
    # The director's long movie_style was useful while exploring art direction but
    # over-specified the image model. Scene action plus locked character profiles is
    # now the complete production prompt.
    del movie_style
    present = _present_characters(scene, characters_by_id)
    prompt = (
        SCENE_STYLE_PREFIX
        + _anonymize_names(scene["image_prompt"].strip(), characters_by_id)
    )
    if present:
        prompt += " " + " ".join(
            f"{_role_label(c).capitalize()} is {_safe_appearance(c, characters_by_id)}."
            for c in present
        )
    return _anonymize_names(prompt, characters_by_id)


def _build_constraints(scene: dict) -> str:
    """Positive composition constraints only.

    The Images API has no negative-prompt channel. Sending the old comma-separated
    SFW_NEGATIVE list as normal prompt text exposed the request itself to explicit
    safety vocabulary and caused avoidable moderation matches.
    """
    ids = scene.get("character_ids") or []
    people = ""
    if ids:
        people = (
            "Preserve every stated character detail exactly."
        )
    return (
        people
        + " Fill the entire horizontal 16:9 frame with the requested scene. "
        "Include no writing, logos, or watermarks."
    )


def build_fallback_prompt(
    scene: dict,
    characters_by_id: dict,
    movie_style: str = "",
) -> str:
    """Conservative fallback used only after the authored prompt is rejected.

    It preserves the cast and broad spiritual beat while dropping the story-specific
    construction that tripped moderation. This is preferable to silently reusing a
    neighboring scene image, which is what the previous pipeline did.
    """
    present = _present_characters(scene, characters_by_id)
    subject = scene.get("hero_subject") or scene.get("image_prompt") or "a quiet turning point"
    del movie_style
    designs = " ".join(
        f"{_role_label(c).capitalize()} is {_safe_appearance(c, characters_by_id)}."
        for c in present
    )
    return _anonymize_names(
        f"{SCENE_STYLE_PREFIX}A clear, uncluttered movie moment: {subject}. "
        f"{designs} {_build_constraints(scene)}",
        characters_by_id,
    )


def compose_one(scene: dict, characters_by_id: dict, movie_style: str = "") -> dict:
    """t2i only. Fail-open: on generation error, image_url is None rather than
    raising — matches asset_selector.route()'s (now-removed) per-scene fail-open
    catch. image_basis/basis_kind match src/gallery.py's existing display contract
    (image_basis = the actual prompt used, for review)."""
    prompt = build_scene_prompt(scene, characters_by_id, movie_style)
    prompt_with_constraints = f"{prompt}. {_build_constraints(scene)}"
    generation_method = "direct"
    try:
        url = gpt_image.generate_image(prompt_with_constraints)
    except Exception as ex:
        fallback = build_fallback_prompt(scene, characters_by_id, movie_style)
        print(
            f"    scene {scene.get('scene_number')}: authored prompt rejected; "
            f"retrying conservative fallback ({ex})",
            flush=True,
        )
        generation_method = "safety-fallback"
        prompt_with_constraints = fallback
        try:
            url = gpt_image.generate_image(fallback)
        except Exception as fallback_ex:
            print(f"    scene {scene.get('scene_number')}: ✗ {fallback_ex}", flush=True)
            return {
                **scene,
                "image_url": None,
                "image_basis": fallback,
                "basis_kind": "prompt",
                "generation_method": "failed",
                "compositor_contract_version": COMPOSITOR_CONTRACT_VERSION,
            }
    return {
        **scene,
        "image_url": url,
        "image_basis": prompt_with_constraints,
        "basis_kind": "prompt",
        "generation_method": generation_method,
        "compositor_contract_version": COMPOSITOR_CONTRACT_VERSION,
    }


def compose_all(
    scenes: list[dict],
    characters: list[dict],
    visual_story: dict | None = None,
) -> list[dict]:
    characters_by_id = {c["id"]: c for c in characters}
    del visual_story
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {
            ex.submit(compose_one, s, characters_by_id): i
            for i, s in enumerate(scenes)
        }
        results = [None] * len(scenes)
        for fut in as_completed(futures):
            results[futures[fut]] = fut.result()
    return results


if __name__ == "__main__":
    protagonist = {"id": "protagonist", "name": "Maria", "role": "the protagonist", "appearance": "a woman in her early 30s with dark curly hair, modern clothing"}
    scene_with_char = {"scene_number": 1, "image_prompt": "Maria kneels by her bed at dawn", "character_ids": ["protagonist"]}
    scene_no_char = {"scene_number": 2, "image_prompt": "a sunrise over a quiet town", "character_ids": []}
    by_id = {"protagonist": protagonist}

    p1 = build_scene_prompt(scene_with_char, by_id)
    assert "Maria" not in p1, p1  # names must be scrubbed — gpt-image-2 blocks real given names as a public-figure false positive
    assert "the protagonist" in p1 and protagonist["appearance"] in p1, p1
    p2 = build_scene_prompt(scene_no_char, by_id)
    assert p2 == SCENE_STYLE_PREFIX + scene_no_char["image_prompt"], p2

    constraints = _build_constraints(scene_with_char)
    assert "Preserve every stated character detail exactly" in constraints, constraints
    assert "entire horizontal 16:9 frame" in constraints, constraints
    assert "Jesus" not in constraints and "nsfw" not in constraints, constraints

    print("ok  prompt construction: names scrubbed, locked profiles applied, prompt kept compact")
