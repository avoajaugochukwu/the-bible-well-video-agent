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
import scene_engine    # src/ — reuses BASE_NEGATIVE / JESUS_NEGATIVE_BLOCK / COUNT_NEGATIVE_BLOCKS

# Matches agents/character_sheet's REFERENCE_SCAFFOLD tone so scene renders and
# character reference sheets stay in the same visual family — deliberately stylized
# so it reads as obviously animated/AI, never an attempt to mimic a real photo of a
# real person.
SCENE_STYLE_PREFIX = (
    "stylized 3D-rendered animated scene, Pixar/animated-film style, smooth "
    "toon-shaded materials, clearly a 3D animated render and not a real photograph, "
)


def _present_characters(scene: dict, characters_by_id: dict) -> list[dict]:
    return [characters_by_id[cid] for cid in (scene.get("character_ids") or []) if cid in characters_by_id]


def _anonymize_names(text: str, present: list[dict]) -> str:
    """gpt-image-2 blocks prompts containing a real given name as a 'public-figure'
    safety match (confirmed: 'Ellen' alone flips an otherwise-fine prompt from OK to
    moderation_blocked, deterministically, every time) — even a common first name can
    false-positive-match a real person. Code-enforced, not prompt-trust: strip every
    tracked character's literal name from the final prompt and swap in their role,
    regardless of whether scene_engine's authored image_prompt already avoided it."""
    for c in present:
        name = c.get("name")
        if name:
            text = re.sub(re.escape(name), c.get("role") or "this character", text, flags=re.IGNORECASE)
    return text


def build_scene_prompt(scene: dict, characters_by_id: dict) -> str:
    present = _present_characters(scene, characters_by_id)
    prompt = SCENE_STYLE_PREFIX + scene["image_prompt"]
    if present:
        prompt += ". Characters in this scene: " + " ".join(
            f"{c.get('role') or 'a character'}: {c['appearance']}." for c in present
        )
    return _anonymize_names(prompt, present)


def _build_negative(scene: dict) -> str:
    ids = scene.get("character_ids") or []
    negative = scene_engine.BASE_NEGATIVE
    if scene.get("negative_prompt"):
        negative += ", " + scene["negative_prompt"]
    count_block = scene_engine.COUNT_NEGATIVE_BLOCKS.get(len(ids))
    if count_block:
        negative += ", " + count_block
    if ids and "jesus" not in ids:
        negative += ", " + scene_engine.JESUS_NEGATIVE_BLOCK
    return negative


def compose_one(scene: dict, characters_by_id: dict) -> dict:
    """t2i only. Fail-open: on generation error, image_url is None rather than
    raising — matches asset_selector.route()'s (now-removed) per-scene fail-open
    catch. image_basis/basis_kind match src/gallery.py's existing display contract
    (image_basis = the actual prompt used, for review)."""
    prompt = build_scene_prompt(scene, characters_by_id)
    negative = _build_negative(scene)
    try:
        url = gpt_image.generate_image(prompt, negative_prompt=negative)
        return {**scene, "image_url": url, "image_basis": prompt, "basis_kind": "prompt"}
    except Exception as ex:
        print(f"    scene {scene.get('scene_number')}: ✗ {ex}", flush=True)
        return {**scene, "image_url": None, "image_basis": prompt, "basis_kind": "prompt"}


def compose_all(scenes: list[dict], characters: list[dict]) -> list[dict]:
    characters_by_id = {c["id"]: c for c in characters}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(compose_one, s, characters_by_id): i for i, s in enumerate(scenes)}
        results = [None] * len(scenes)
        for fut in as_completed(futures):
            results[futures[fut]] = fut.result()
    return results


if __name__ == "__main__":
    protagonist = {"id": "protagonist", "name": "Maria", "role": "the protagonist", "appearance": "a woman in her early 30s with dark curly hair, modern clothing"}
    scene_with_char = {"scene_number": 1, "image_prompt": "Maria kneels by her bed at dawn", "negative_prompt": "", "character_ids": ["protagonist"]}
    scene_no_char = {"scene_number": 2, "image_prompt": "a sunrise over a quiet town", "negative_prompt": "", "character_ids": []}
    by_id = {"protagonist": protagonist}

    p1 = build_scene_prompt(scene_with_char, by_id)
    assert "Maria" not in p1, p1  # names must be scrubbed — gpt-image-2 blocks real given names as a public-figure false positive
    assert "the protagonist" in p1 and protagonist["appearance"] in p1, p1
    p2 = build_scene_prompt(scene_no_char, by_id)
    assert p2 == SCENE_STYLE_PREFIX + scene_no_char["image_prompt"], p2

    neg1 = _build_negative(scene_with_char)
    assert scene_engine.JESUS_NEGATIVE_BLOCK in neg1, neg1
    neg2 = _build_negative(scene_no_char)
    assert scene_engine.JESUS_NEGATIVE_BLOCK not in neg2, neg2

    print(f"ok  build_scene_prompt()/_build_negative(): with-character and no-character paths both correct")
