"""Drama reviewer agent: a post-hoc pass over already-authored scenes
(src/scene_engine.py's shot author, already fed agents/emotion_scout's
emotional_stakes/expression_directive) that rewrites a scene's image_prompt
only when its rendered expression still reads as too calm, subdued, or
neutral for what that beat's own stakes call for.

Deliberate, flagged exception to agents/CLAUDE.md rule 2 ("no second LLM
judges the first LLM's taste") — see that file's carve-out note, same
narrow-scope reasoning as agents/recognition_reviewer: this call may only
ever intensify the existing expression/body-language description, never
re-author the shot's location, subject, characters, or camera framing, and it
must return the original image_prompt verbatim whenever the expression
already matches the stakes (the common case).
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "utils"))

from llm import call_llm_json

DRAMA_REVIEWER_CONTRACT_VERSION = 2
CHUNK_SIZE = 8
MAX_ATTEMPTS = 3

_SCHEMA = {
    "name": "drama_review",
    "schema": {
        "type": "object",
        "properties": {
            "image_prompts": {
                "type": "array",
                "items": {"type": "string"},
            }
        },
        "required": ["image_prompts"],
        "additionalProperties": False,
    },
}

_SYSTEM = """
You are reviewing already-authored shot prompts for a Christian animated short
film, checking only ONE thing: does the rendered expression/body language
match how large this beat's own emotional stakes actually are?

For each shot below, given its emotional_stakes and expression_directive, read
image_prompt. If image_prompt already renders an overt, legible expression
matching that intensity — visible tears, open laughter, a hand pressed to the
head, whatever the expression_directive calls for — return image_prompt
UNCHANGED, verbatim. This will be the common case; do not edit prompts that
already work.

Only rewrite image_prompt when it currently defaults to a calm, pleasant, or
neutral resting expression despite stakes/expression_directive calling for
something bold. When you rewrite, intensify the existing expression/body-
language phrase to match expression_directive and change nothing else: keep
the same location, subject, other people, time of day, and camera framing
verbatim. You are amplifying legibility of feeling only, never re-authoring
the shot.

Never invent drama where the beat's own expression_directive genuinely calls
for calm — leave those prompts unchanged.

Return exactly {count} strings in "image_prompts", one per shot, same order,
each still 25-45 words.
""".strip()


def _sanitize(text: str) -> str:
    """Strip stray control bytes the decoder can inject when a similar string
    repeats many times in one array (an em dash / curly apostrophe corrupted to
    e.g. \\x19 — confirmed 2026-08-03). A decoder artifact, not a semantic issue,
    so fix it in place rather than reject the prompt and fall back to the
    un-reviewed original over one stray byte."""
    cleaned = "".join(c for c in (text or "") if ord(c) >= 32 or c in "\t\n")
    return " ".join(cleaned.split())


def _validate(prompts: list[str], scenes: list[dict]) -> list[str]:
    if len(prompts) != len(scenes):
        return [f"image_prompts must have exactly {len(scenes)} entries, one per "
                f"shot in order — got {len(prompts)}"]
    problems = []
    for i, p in enumerate(prompts, start=1):
        if not (p or "").strip():
            problems.append(f"shot {i} has an empty image_prompt")
    return problems


def _review_chunk(scenes: list[dict]) -> list[str]:
    numbered = "\n".join(
        f"{i + 1}. emotional_stakes: {s.get('emotional_stakes') or '(none)'} | "
        f"expression_directive: {s.get('expression_directive') or '(none)'} | "
        f"image_prompt: {s['image_prompt']}"
        for i, s in enumerate(scenes)
    )
    system = _SYSTEM.format(count=len(scenes))
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"SHOTS:\n{numbered}"},
    ]
    # Scaled with chunk size, not a flat constant — same reasoning as
    # agents/location_scout: echoing back up to 8 full 25-45 word prompts,
    # some rewritten longer, can outgrow a flat budget mid-array.
    token_budget = min(max(4096, 400 * len(scenes)), 32000)
    last_problems: list[str] = []
    for attempt in range(MAX_ATTEMPTS):
        if last_problems:
            messages.append({
                "role": "user",
                "content": "Fix these problems and return the corrected full JSON object:\n"
                           + "\n".join(f"- {p}" for p in last_problems),
            })
        data = call_llm_json(messages, _SCHEMA, max_completion_tokens=token_budget)
        prompts = [_sanitize(p) for p in (data.get("image_prompts") or [])]
        problems = _validate(prompts, scenes)
        if not problems:
            return prompts
        if attempt == MAX_ATTEMPTS - 1:
            # Fact-check, not taste: a count mismatch means the call malformed
            # its own output, not that a rewrite decision was wrong — fall
            # back to the original prompts rather than risk dropping one.
            print(f"    drama_reviewer: {problems[0]} after {MAX_ATTEMPTS} attempts, "
                  f"keeping originals", flush=True)
            return [s["image_prompt"] for s in scenes]
        messages.append({"role": "assistant", "content": json.dumps(data, ensure_ascii=False)})
        last_problems = problems


def review(scenes: list[dict], emotional_beats: list[dict], workers: int = 8) -> list[dict]:
    """Returns `scenes` with `image_prompt` possibly rewritten in place for
    beats whose rendered expression didn't already match their own stakes.
    `emotional_beats` is zipped 1:1 by position with `scenes`, same order
    break_into_scenes() produced them in."""
    annotated = [
        {
            **scene,
            "emotional_stakes": beat.get("emotional_stakes", ""),
            "expression_directive": beat.get("expression_directive", ""),
        }
        for scene, beat in zip(scenes, emotional_beats)
    ]
    chunks = [annotated[i:i + CHUNK_SIZE] for i in range(0, len(annotated), CHUNK_SIZE)]
    with ThreadPoolExecutor(max_workers=min(workers, len(chunks) or 1)) as ex:
        results = list(ex.map(_review_chunk, chunks))
    revised_prompts = [prompt for chunk_result in results for prompt in chunk_result]
    return [
        {**scene, "image_prompt": prompt, "drama_reviewer_contract_version": DRAMA_REVIEWER_CONTRACT_VERSION}
        for scene, prompt in zip(scenes, revised_prompts)
    ]


if __name__ == "__main__":
    sample = [
        {"scene_number": 1, "image_prompt": "The protagonist sits calmly at a table, pleasant expression, medium shot."},
    ]
    beats = [
        {"emotional_stakes": "she has just learned her sister is pregnant, the child she herself has prayed years for", "expression_directive": "tears on her cheeks, one hand pressed to her mouth"},
    ]
    out = review(sample, beats, workers=1)
    assert len(out) == 1, out
    print(f"ok  drama_reviewer.review() -> {out[0]['image_prompt'][:60]}")
