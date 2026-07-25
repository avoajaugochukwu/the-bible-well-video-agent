"""Character-sheet agent: one full-figured reference image per tracked character,
generated once via gpt-image-2 t2i (src/gpt_image.py, quality=low — kept cheap on
purpose). No automated vision-QA — whether a reference is good enough is a human call
made off the gallery review, same as the rest of this pipeline's image QA today.
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src"))

import gpt_image  # src/

REFERENCE_SCAFFOLD = (
    "stylized 3D-rendered character reference sheet, Pixar/animated-film style, smooth "
    "toon-shaded materials, clearly a 3D animated character and not a real photographed "
    "person, single character, front-facing, neutral standing pose, plain light-grey "
    "studio background, no text"
)


def build_reference_prompt(character: dict) -> str:
    return f"{REFERENCE_SCAFFOLD}, {character['appearance']}"


def generate_one(character: dict) -> dict:
    """Returns character extended with reference_image_url. Fail-open: on generation
    error, reference_image_url is None rather than raising — matches
    asset_selector.route()'s existing per-scene fail-open catch, so one bad character
    never blocks the rest of the ledger."""
    prompt = build_reference_prompt(character)
    try:
        url = gpt_image.generate_image(prompt)
        print(f"    character '{character['id']}': ✓", flush=True)
        return {**character, "reference_image_url": url}
    except Exception as ex:
        print(f"    character '{character['id']}': ✗ {ex}", flush=True)
        return {**character, "reference_image_url": None}


def generate_all(characters: list[dict]) -> list[dict]:
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(generate_one, c): i for i, c in enumerate(characters)}
        results = [None] * len(characters)
        for fut in as_completed(futures):
            results[futures[fut]] = fut.result()
    return results


if __name__ == "__main__":
    fake_character = {
        "id": "protagonist",
        "name": "Maria",
        "role": "the protagonist",
        "appearance": (
            "a woman in her early 30s with medium-brown skin, shoulder-length dark "
            "curly hair, wearing a simple modern cardigan over a plain t-shirt and jeans"
        ),
    }
    prompt = build_reference_prompt(fake_character)
    assert REFERENCE_SCAFFOLD in prompt and fake_character["appearance"] in prompt, prompt
    print(f"ok  build_reference_prompt() -> {prompt!r}")
