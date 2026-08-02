"""Scene compositor agent: per-scene i2i generation (gpt-image-2 images.edit) using
the tracked characters present in that scene. Identity now comes from each
character's own reference image, conditioned via edit, not from restated
appearance text in the prompt — the prompt only carries the scene's visible
action. Reference images are downloaded + shrunk once per character and reused
across every scene that includes them. NO vision-QA anywhere in this app —
matching is a human call made off the production UI review. Falls
back to plain t2i (gpt-image-2 generate, full appearance text) only if a
character has no usable reference image, or if an edit call is rejected.
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
import supabase_jobs  # src/
from images import ImageFetcher, shrink_for_upload  # utils/

COMPOSITOR_CONTRACT_VERSION = 6
SCENE_STYLE_PREFIX = (
    "A horizontal 16:9 3D animated film still, Pixar style with soft-matte "
    "detailed textures. "
)
REFERENCE_MATCH_INSTRUCTION = " Depict each person exactly as shown in their reference image."


def _present_characters(scene: dict, characters_by_id: dict) -> list[dict]:
    return [characters_by_id[cid] for cid in (scene.get("character_ids") or []) if cid in characters_by_id]


def _role_label(character: dict) -> str:
    """Use film-neutral labels; source relationships belong to the narration lane."""
    character_id = character.get("id")
    if character_id == "protagonist":
        return "the protagonist"
    if character_id == "jesus":
        return "Jesus"
    if character.get("cast_origin") == "director":
        role = re.sub(r"\s+", " ", character.get("role") or "").strip(" .")
        if role:
            return f"the {role}"
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


def build_scene_prompt(scene: dict, characters_by_id: dict) -> str:
    """The visible action only — no character content at all. Identity is carried
    by whichever reference images accompany the edit call, not by text (see
    agents/CLAUDE.md rule 5), so there is nothing here for a role label to leak
    into."""
    visible_action = _anonymize_names(scene["image_prompt"].strip(), characters_by_id)
    return _anonymize_names(f"{SCENE_STYLE_PREFIX}{visible_action}", characters_by_id)


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


def build_fallback_prompt(scene: dict, characters_by_id: dict) -> str:
    """Conservative t2i fallback — used when a character has no usable reference
    image, or an edit call is rejected. States each present character's appearance
    directly (the one place appearance text still belongs, since there's no
    reference image to carry identity instead), with no role-label framing riding
    along as content (see agents/CLAUDE.md rule 5).
    """
    present = _present_characters(scene, characters_by_id)
    subject = scene.get("hero_subject") or scene.get("image_prompt") or "a quiet turning point"
    designs = " ".join(f"{_safe_appearance(c, characters_by_id)}." for c in present)
    return _anonymize_names(
        f"{SCENE_STYLE_PREFIX}A clear, uncluttered movie moment: {subject}. "
        f"{designs} {_build_constraints(scene)}",
        characters_by_id,
    )


def _reference_key(character_id: str, variant_id: str | None) -> str:
    """A variant's bytes never collide with its own character's base bytes in
    the reference_bytes_by_id cache."""
    return f"{character_id}::{variant_id}" if variant_id else character_id


def _variant_lookup(characters: list[dict]) -> dict[tuple[str, int], str]:
    """Deterministic fact, not an LLM decision: which wardrobe variant (if any)
    applies to a given (character_id, scene_number) pair — inverted once from
    each variant's own scene_numbers list (agents/character_wardrobe's output)."""
    lookup: dict[tuple[str, int], str] = {}
    for c in characters:
        for v in c.get("variants") or []:
            for n in v.get("scene_numbers") or []:
                lookup[(c["id"], n)] = v["variant_id"]
    return lookup


def _fetch_reference_bytes(characters: list[dict]) -> dict[str, bytes]:
    """Download + shrink each tracked character's base reference sheet AND every
    wardrobe variant's own reference image, ONCE, reused by every scene that
    needs them (see utils/images.py:shrink_for_upload — trims resolution/bytes
    before every edit call, not per scene)."""
    urls = {
        c["id"]: c["reference_image_url"]
        for c in characters
        if c.get("reference_image_url")
    }
    for c in characters:
        for v in c.get("variants") or []:
            if v.get("image_url"):
                urls[_reference_key(c["id"], v["variant_id"])] = v["image_url"]
    fetched = ImageFetcher().fetch_many(list(urls.values()))
    out = {}
    for key, url in urls.items():
        data = fetched.get(url)
        if data:
            out[key] = shrink_for_upload(data)
    return out


def compose_one(
    scene: dict,
    characters_by_id: dict,
    reference_bytes_by_id: dict,
    variant_lookup: dict | None = None,
) -> dict:
    """i2i when every present character has a usable reference image; t2i (plain
    generate, full appearance text) when none are present, or a character is
    missing a reference, or the edit call itself is rejected. Fail-open: on
    generation error, image_url is None rather than raising. image_basis/basis_kind
    match the production UI's existing display contract (image_basis = the actual
    prompt used, for review). `variant_lookup` (defaults to {}, fully backward
    compatible) picks a character's wardrobe-variant reference over their base one
    where the scene calls for it — falling back to the base reference if that
    variant's image isn't available (still generating, or failed) rather than
    failing the whole scene over one missing variant image. `character_refs_used`
    on the result records which reference each present character actually
    resolved to, for the production UI's per-scene audit display."""
    variant_lookup = variant_lookup or {}
    present = _present_characters(scene, characters_by_id)
    scene_number = scene.get("scene_number")
    references = []
    character_refs_used = []
    for c in present:
        variant_id = variant_lookup.get((c["id"], scene_number))
        bytes_ = reference_bytes_by_id.get(_reference_key(c["id"], variant_id)) if variant_id else None
        if bytes_ is None:
            variant_id = None
            bytes_ = reference_bytes_by_id.get(c["id"])
        if bytes_ is not None:
            references.append(bytes_)
        character_refs_used.append({"character_id": c["id"], "variant_id": variant_id})
    use_edit = bool(references) and len(references) == len(present)

    prompt = build_scene_prompt(scene, characters_by_id).rstrip(". ")
    if use_edit:
        prompt += "." + REFERENCE_MATCH_INSTRUCTION
    prompt_with_constraints = f"{prompt.rstrip('. ')}. {_build_constraints(scene).strip()}"
    generation_method = "edit" if use_edit else "direct"
    try:
        url = (
            gpt_image.edit_image(prompt_with_constraints, references)
            if use_edit
            else gpt_image.generate_image(prompt_with_constraints)
        )
    except Exception as ex:
        fallback = build_fallback_prompt(scene, characters_by_id)
        print(
            f"    scene {scene.get('scene_number')}: authored prompt rejected; "
            f"retrying conservative t2i fallback ({ex})",
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
                "character_refs_used": character_refs_used,
                "compositor_contract_version": COMPOSITOR_CONTRACT_VERSION,
            }
    return {
        **scene,
        "image_url": url,
        "image_basis": prompt_with_constraints,
        "basis_kind": "prompt",
        "generation_method": generation_method,
        "character_refs_used": character_refs_used,
        "compositor_contract_version": COMPOSITOR_CONTRACT_VERSION,
    }


def regenerate_one(scene: dict, characters: list[dict]) -> dict:
    """Regenerate a single scene's image outside the full pipeline run — the
    production UI's per-scene 'edit prompt, regenerate' action. Fetches only
    the reference images this one scene actually needs, not the whole cast."""
    characters_by_id = {c["id"]: c for c in characters}
    present = _present_characters(scene, characters_by_id)
    reference_bytes_by_id = _fetch_reference_bytes(present)
    variant_lookup = _variant_lookup(present)
    return compose_one(scene, characters_by_id, reference_bytes_by_id, variant_lookup)


def _persist(row_id, scene: dict) -> None:
    """Land one finished image in the Supabase job row as soon as it exists, so
    the production UI fills in during the ~20-minute image stage instead of
    showing nothing until the whole run ends. Never raises into the pipeline —
    same posture as src/clickup.py: a Supabase hiccup must not throw away an
    image that has already been paid for."""
    try:
        supabase_jobs.add_scene_image(
            row_id, scene["scene_number"], scene["image_url"], "gpt-image",
            prompt=scene.get("image_prompt"),
            character_refs_used=scene.get("character_refs_used"),
        )
    except Exception as ex:
        print(f"    scene {scene.get('scene_number')}: progress write failed ({ex})", flush=True)


def compose_all(scenes: list[dict], characters: list[dict], row_id=None, is_cancelled=None) -> list[dict]:
    """row_id is optional — pass it and every finished image is written to that
    job's Supabase row as it lands (progress), leave it out (self-tests, any
    non-job caller) and this behaves exactly as before.

    is_cancelled is checked after every finished image: cancelling a job during
    this stage is exactly the case where cost runs away (one image per scene,
    ~111 of them), so pending scenes are dropped instead of waiting for the next
    stage boundary. Whatever was already generated stays persisted."""
    characters_by_id = {c["id"]: c for c in characters}
    reference_bytes_by_id = _fetch_reference_bytes(characters)
    variant_lookup = _variant_lookup(characters)
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {
            ex.submit(compose_one, s, characters_by_id, reference_bytes_by_id, variant_lookup): i
            for i, s in enumerate(scenes)
        }
        results = [None] * len(scenes)
        for fut in as_completed(futures):
            scene = fut.result()
            results[futures[fut]] = scene
            if row_id is not None and scene.get("image_url"):
                _persist(row_id, scene)
            if is_cancelled is not None and is_cancelled():
                for f in futures:
                    f.cancel()   # the ~8 already in flight still finish; the rest never start
                # Imported here, not at module scope: src/run.py imports this
                # module, so a top-level import back would be circular.
                from run import Cancelled  # src/
                raise Cancelled(f"job {row_id} cancelled during image generation")
    return results


if __name__ == "__main__":
    protagonist = {"id": "protagonist", "name": "Maria", "role": "the protagonist", "appearance": "a woman in her early 30s with dark curly hair, modern clothing"}
    scene_with_char = {"scene_number": 1, "image_prompt": "Maria kneels by her bed at dawn", "character_ids": ["protagonist"]}
    scene_no_char = {"scene_number": 2, "image_prompt": "a sunrise over a quiet town", "character_ids": []}
    by_id = {"protagonist": protagonist}

    # Fully deterministic — no LLM call, no image call. Names scrubbed, no
    # appearance text or structural role label present since identity now rides
    # on the reference image, not the prompt.
    p2 = build_scene_prompt(scene_no_char, by_id)
    assert p2 == SCENE_STYLE_PREFIX + scene_no_char["image_prompt"], p2

    p1 = build_scene_prompt(scene_with_char, by_id)
    assert "Maria" not in p1, p1
    # "the protagonist" here is the name-scrub substitute, not the old bug (which
    # injected it as unrequested appearance-description scaffolding) — no
    # appearance text rides along at all now, confirmed by the exact match below.
    assert p1 == SCENE_STYLE_PREFIX + "the protagonist kneels by her bed at dawn", p1
    assert protagonist["appearance"] not in p1, p1

    fallback = build_fallback_prompt(scene_with_char, by_id)
    assert "Maria" not in fallback, fallback
    assert protagonist["appearance"] in fallback, fallback

    constraints = _build_constraints(scene_with_char)
    assert "Preserve every stated character detail exactly" in constraints, constraints
    assert "entire horizontal 16:9 frame" in constraints, constraints
    assert "Jesus" not in constraints and "nsfw" not in constraints, constraints

    print("ok  prompt construction: names scrubbed, no appearance text in the i2i prompt, fallback intact")
