"""Generate spiritual images via gpt-image-2 for Christian story scenes, in a
muted, hand-drawn monochrome stick-figure whiteboard-doodle style."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "utils"))

import gpt_image as scene_assets
import scene_engine

# Style prefixes for gpt-image-2 — monochrome hand-drawn stick figure on a muted flat
# background, colored icon accents for the metaphor payload only. Same prefix for
# every scene_type; the churchy-doodle look doesn't vary by narrative beat.
_STICK_FIGURE_STYLE = (
    "muted hand-drawn whiteboard-doodle illustration, the person drawn as a simple "
    "black-ink stick figure (plain round head, dot eyes, thin single-stroke sketchy "
    "limbs, no color fill on the figure), a muted flat-color background wash, small "
    "colored flat icons for symbolic objects only, soft glowing particle sparkles, "
)
STYLE_PREFIXES = {t: _STICK_FIGURE_STYLE for t in scene_engine.SCENE_TYPES}
DEFAULT_STYLE_PREFIX = _STICK_FIGURE_STYLE

# Suppresses color-filled/photoreal/3D rendering ON THE FIGURE so gpt-image-2 stays in
# monochrome stick-figure space (icons/background may still carry muted color).
STYLE_NEGATIVE = (
    "photorealistic, 3D render, realistic shading on the figure, color-filled "
    "character, detailed clothing patterns, textured skin, full-color person, "
    "gradients on the character, glossy render, painterly brushwork, digital painting"
)

# gpt-image-2 still defaults faith-themed prompts toward a robed/barefoot/biblical
# look — suppress that on the protagonist specifically. Skipped when the scene is
# actually about Jesus (he's meant to look robed/biblical, distinct from the
# protagonist — see scene_engine.py's fixed JESUS_APPEARANCE/PROTAGONIST_APPEARANCE).
ANTI_BIBLICAL_NEGATIVE = (
    "biblical robes, tunic, ancient drapery, sandals, staff, halo, "
    "first-century clothing, biblical beard"
)


def route(scene: dict, context: dict) -> dict:
    """Generate image via gpt-image-2. Returns scene with image_url, lane, image_basis, basis_kind."""
    stype = scene.get("scene_type", "spiritual_moment")
    prefix = STYLE_PREFIXES.get(stype, DEFAULT_STYLE_PREFIX)
    prompt = prefix + scene["image_prompt"]

    negative = f"{scene_engine.BASE_NEGATIVE}, {STYLE_NEGATIVE}"
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
