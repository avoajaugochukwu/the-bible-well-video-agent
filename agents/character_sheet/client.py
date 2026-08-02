"""Character-sheet agent: one full-body reference image per tracked character,
generated once via gpt-image-2 t2i (src/gpt_image.py, quality=low — kept cheap on
purpose). No automated vision-QA — whether a reference is good enough is a human call
made off the production UI review, same as the rest of this pipeline's image QA today.
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "utils"))
sys.path.insert(0, ROOT)  # for agents.character_ledger below

import gpt_image  # src/
from images import ImageFetcher, shrink_for_upload  # utils/
from agents.character_ledger import client as character_ledger  # agents/: compile_identity_profile

CHARACTER_SHEET_CONTRACT_VERSION = 2
REFERENCE_SCAFFOLD = (
    "A full-body 3D animated character reference, Pixar style with soft-matte detailed "
    "textures. One adult, complete head-to-shoes front view, neutral standing pose, "
    "plain light-gray studio background, no writing or logos"
)
VARIANT_MATCH_INSTRUCTION = (
    " Same face, hairstyle, and build as shown in the reference image — only the "
    "outfit changes to match this description."
)


def build_reference_prompt(character: dict) -> str:
    return f"{REFERENCE_SCAFFOLD}, {character['appearance']}"


def build_variant_reference_prompt(character: dict, variant: dict) -> str:
    """Identity anchored with CONCRETE age/build/face/hair text (compiled from
    the character's own locked visual_profile), not just a bare 'same build'
    instruction leaning on reference-image conditioning alone — a generic
    instruction with no text backing it is exactly what let body build drift
    between variants."""
    identity = character_ledger.compile_identity_profile(character.get("visual_profile") or {})
    return f"{REFERENCE_SCAFFOLD}, {identity} {variant['outfit_prompt']}.{VARIANT_MATCH_INSTRUCTION}"


def generate_one(character: dict, prompt: str | None = None) -> dict:
    """Returns character extended with reference_image_url + reference_prompt
    (the exact prompt used — always stored, so the production UI can show/edit
    the REAL prompt on a regenerate rather than a fragment that silently drops
    the style/identity framing). Fail-open: on generation error,
    reference_image_url is None rather than raising — matches
    asset_selector.route()'s existing per-scene fail-open catch, so one bad character
    never blocks the rest of the ledger. `prompt` defaults to the character's own
    build_reference_prompt() but can be overridden — the production UI's "regenerate
    base image with an edited prompt" route passes its own (used verbatim, no
    further wrapping — what the human sees and edits IS what gets sent)."""
    reference_prompt = prompt or build_reference_prompt(character)
    try:
        url = gpt_image.generate_image(reference_prompt)
        print(f"    character '{character['id']}': ✓", flush=True)
        return {
            **character,
            "reference_image_url": url,
            "reference_prompt": reference_prompt,
            "character_sheet_contract_version": CHARACTER_SHEET_CONTRACT_VERSION,
        }
    except Exception as ex:
        print(f"    character '{character['id']}': ✗ {ex}", flush=True)
        return {
            **character,
            "reference_image_url": None,
            "reference_prompt": reference_prompt,
            "character_sheet_contract_version": CHARACTER_SHEET_CONTRACT_VERSION,
        }


def generate_all(characters: list[dict]) -> list[dict]:
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(generate_one, c): i for i, c in enumerate(characters)}
        results = [None] * len(characters)
        for fut in as_completed(futures):
            results[futures[fut]] = fut.result()
    return results


def generate_variant_one(character: dict, variant: dict, prompt: str | None = None) -> dict:
    """One wardrobe variant's reference image: i2i off the character's OWN base
    reference image (identity carried by the image AND by concrete identity
    text — see build_variant_reference_prompt), only the outfit prompt changes,
    same mechanism agents/scene_compositor already uses for scene images.
    Always returns `reference_prompt` (the exact prompt used), same reasoning
    as generate_one. `prompt` can be overridden — used verbatim, no further
    wrapping — the production UI's per-variant regenerate route passes its own
    edited full prompt. Fail-open: image_url is None (not raised) if the
    character has no usable base reference yet, or generation itself fails —
    one bad variant never blocks the rest."""
    reference_prompt = prompt or build_variant_reference_prompt(character, variant)
    base_url = character.get("reference_image_url")
    if not base_url:
        print(f"    character '{character['id']}' variant '{variant['variant_id']}': "
              "✗ no base reference image to condition on", flush=True)
        return {**variant, "reference_prompt": reference_prompt, "image_url": None}
    base_bytes = ImageFetcher().fetch(base_url)
    if not base_bytes:
        print(f"    character '{character['id']}' variant '{variant['variant_id']}': "
              "✗ could not fetch base reference image", flush=True)
        return {**variant, "reference_prompt": reference_prompt, "image_url": None}
    try:
        url = gpt_image.edit_image(reference_prompt, [shrink_for_upload(base_bytes)])
        print(f"    character '{character['id']}' variant '{variant['variant_id']}': ✓", flush=True)
        return {**variant, "reference_prompt": reference_prompt, "image_url": url}
    except Exception as ex:
        print(f"    character '{character['id']}' variant '{variant['variant_id']}': ✗ {ex}", flush=True)
        return {**variant, "reference_prompt": reference_prompt, "image_url": None}


def generate_variants_all(characters: list[dict]) -> list[dict]:
    """Returns `characters` with every character's `variants` list extended with
    an `image_url` per variant. Fans out across every (character, variant) pair
    at once — a character with 3 variants doesn't wait on itself."""
    jobs = [
        (i, j, character, variant)
        for i, character in enumerate(characters)
        for j, variant in enumerate(character.get("variants") or [])
    ]
    if not jobs:
        return characters
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {
            ex.submit(generate_variant_one, character, variant): (i, j)
            for i, j, character, variant in jobs
        }
        results = {}
        for fut in as_completed(futures):
            results[futures[fut]] = fut.result()
    out = []
    for i, character in enumerate(characters):
        variants = character.get("variants") or []
        new_variants = [results.get((i, j), v) for j, v in enumerate(variants)]
        out.append({**character, "variants": new_variants})
    return out


if __name__ == "__main__":
    fake_character = {
        "id": "protagonist",
        "name": "Maria",
        "role": "the protagonist",
        "appearance": (
            "a woman in her early 30s with medium-brown skin, shoulder-length dark "
            "curly hair, wearing a simple modern cardigan over a plain t-shirt and jeans"
        ),
        "visual_profile": {
            "age": 32, "ethnicity": "Black", "gender": "female", "height": "5'6\"",
            "build": "average, soft-shouldered", "skin_tone": "medium-brown",
            "face_shape": "oval", "cheek_structure": "soft round cheeks",
            "eye_description": "dark brown almond eyes", "nose_description": "straight nose",
            "lip_description": "full lips", "age_markers": "none", "eyewear": "no eyewear",
            "hair_color": "black", "hair_texture": "curly", "hair_length": "medium (chin to shoulder)",
            "haircut": "loose curls", "hair_part": "center part", "hair_end_shape": "natural ends",
            "hair_position": "loose", "hair_accessory": "no hair accessory",
            "inner_top": "plain t-shirt", "outer_layer": "modern cardigan",
            "outer_layer_closure": "fully open", "bottom": "jeans", "footwear": "sneakers",
            "jewelry": "no jewelry", "accessories": "no accessories",
        },
    }
    prompt = build_reference_prompt(fake_character)
    assert REFERENCE_SCAFFOLD in prompt and fake_character["appearance"] in prompt, prompt
    print(f"ok  build_reference_prompt() -> {prompt!r}")

    fake_variant = {"variant_id": "wedding_guest", "context_label": "Wedding guest",
                     "outfit_prompt": "wears a soft green formal dress, fully closed, low heels, a wedding ring."}
    variant_prompt = build_variant_reference_prompt(fake_character, fake_variant)
    # Identity (age/build/face/hair) must be present so it's NOT left purely to
    # reference-image conditioning — confirms the weight/identity-drift fix.
    assert "32-year-old Black female" in variant_prompt, variant_prompt
    assert "average, soft-shouldered" in variant_prompt, variant_prompt
    assert fake_variant["outfit_prompt"] in variant_prompt, variant_prompt
    assert fake_character["appearance"] not in variant_prompt, variant_prompt  # old outfit must not leak in
    print(f"ok  build_variant_reference_prompt() anchors identity -> {variant_prompt!r}")
