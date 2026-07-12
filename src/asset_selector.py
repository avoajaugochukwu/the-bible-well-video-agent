"""Generate spiritual images via Krea for Christian story scenes."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "utils"))

import krea as scene_assets
import scene_engine

# Style prefixes for Krea image generation — high-quality digital painting.
STYLE_PREFIXES = {
    "spiritual_moment": "high quality digital painting, spiritual and emotional, divine light, ",
    "transformation": "high quality digital painting, spiritual transformation, divine light, ",
    "revelation": "high quality digital painting, spiritual awakening, divine light, ",
    "decision": "high quality digital painting, spiritual conviction, divine light, ",
    "reflection": "high quality digital painting, spiritual contemplation, divine light, ",
}
DEFAULT_STYLE_PREFIX = "high quality digital painting, spiritual and emotional, divine light, "

# Krea's latent space defaults faith-themed prompts toward a robed/barefoot/biblical
# look — suppress that on the protagonist specifically. Skipped when the scene is
# actually about Jesus (he's meant to look robed/biblical, distinct from the
# protagonist — see infer_characters()).
ANTI_BIBLICAL_NEGATIVE = (
    "biblical robes, tunic, ancient drapery, sandals, staff, halo, "
    "first-century clothing, biblical beard"
)


def route(scene: dict, context: dict) -> dict:
    """Generate image via Krea. Returns scene with image_url, lane, image_basis, basis_kind."""
    scene_assets._load_env()
    stype = scene.get("scene_type", "spiritual_moment")
    prefix = STYLE_PREFIXES.get(stype, DEFAULT_STYLE_PREFIX)
    prompt = prefix + scene["image_prompt"]

    negative = f"{scene_engine.BASE_NEGATIVE}, text, labels, words"
    if scene.get("negative_prompt"):
        negative += ", " + scene["negative_prompt"]
    mentions_jesus = "jesus" in (scene.get("image_prompt", "") + scene.get("hero_subject", "")).lower()
    if not mentions_jesus:
        negative += ", " + ANTI_BIBLICAL_NEGATIVE

    try:
        url = scene_assets.krea_photo(prompt, negative_prompt=negative)
        print(f"    {stype}: ✓", flush=True)
        return {**scene, "image_url": url, "lane": "krea", "image_basis": prompt, "basis_kind": "prompt"}
    except Exception as ex:
        print(f"    {stype}: ✗ {ex}", flush=True)
        return {**scene, "image_url": None, "lane": None, "image_basis": prompt, "basis_kind": "prompt"}
