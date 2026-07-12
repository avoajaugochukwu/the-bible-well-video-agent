"""Generate spiritual images via gpt-image-2 for Christian story scenes, in a
clean flat 2D cartoon/whiteboard style."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "utils"))

import gpt_image as scene_assets
import scene_engine

# Style prefixes for gpt-image-2 — flat 2D vector/whiteboard illustration, no
# photoreal or 3D rendering.
STYLE_PREFIXES = {
    "spiritual_moment": "simple 2D vector illustration, clean black ink outlines, flat colors, minimalist whiteboard style, plain light background, ",
    "transformation": "simple 2D vector illustration, clean black ink outlines, flat colors, minimalist whiteboard style, plain light background, ",
    "revelation": "simple 2D vector illustration, clean black ink outlines, flat colors, minimalist whiteboard style, plain light background, ",
    "decision": "simple 2D vector illustration, clean black ink outlines, flat colors, minimalist whiteboard style, plain light background, ",
    "reflection": "simple 2D vector illustration, clean black ink outlines, flat colors, minimalist whiteboard style, plain light background, ",
}
DEFAULT_STYLE_PREFIX = "simple 2D vector illustration, clean black ink outlines, flat colors, minimalist whiteboard style, plain light background, "

# Suppresses 3D/photoreal/shaded renders so gpt-image-2 stays in flat cartoon space.
CARTOON_NEGATIVE = (
    "photorealistic, 3D render, realistic shading, detailed textures, "
    "complex background, depth of field, photographic, realistic skin, "
    "gradients, shadows, volumetric lighting, airbrushed, digital painting"
)

# gpt-image-2 still defaults faith-themed prompts toward a robed/barefoot/biblical
# look — suppress that on the protagonist specifically. Skipped when the scene is
# actually about Jesus (he's meant to look robed/biblical, distinct from the
# protagonist — see infer_characters()).
ANTI_BIBLICAL_NEGATIVE = (
    "biblical robes, tunic, ancient drapery, sandals, staff, halo, "
    "first-century clothing, biblical beard"
)


def route(scene: dict, context: dict) -> dict:
    """Generate image via gpt-image-2. Returns scene with image_url, lane, image_basis, basis_kind."""
    stype = scene.get("scene_type", "spiritual_moment")
    prefix = STYLE_PREFIXES.get(stype, DEFAULT_STYLE_PREFIX)
    prompt = prefix + scene["image_prompt"]

    negative = f"{scene_engine.BASE_NEGATIVE}, {CARTOON_NEGATIVE}"
    if scene.get("negative_prompt"):
        negative += ", " + scene["negative_prompt"]
    mentions_jesus = "jesus" in (scene.get("image_prompt", "") + scene.get("hero_subject", "")).lower()
    if not mentions_jesus:
        negative += ", " + ANTI_BIBLICAL_NEGATIVE

    try:
        url = scene_assets.generate_image(prompt, negative_prompt=negative)
        print(f"    {stype}: ✓", flush=True)
        return {**scene, "image_url": url, "lane": "gpt-image-2", "image_basis": prompt, "basis_kind": "prompt"}
    except Exception as ex:
        print(f"    {stype}: ✗ {ex}", flush=True)
        return {**scene, "image_url": None, "lane": None, "image_basis": prompt, "basis_kind": "prompt"}
