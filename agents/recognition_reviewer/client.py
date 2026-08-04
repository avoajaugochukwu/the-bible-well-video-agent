"""Recognition reviewer agent: a post-hoc pass over already-authored scenes
(src/scene_engine.py's shot author, already fed agents/recognition_director's
staging cue) that rewrites a scene's image_prompt only when it still doesn't
read as instantly recognizable for its specific place/occasion.

Deliberate, flagged exception to agents/CLAUDE.md rule 2 ("no second LLM
judges the first LLM's taste") — see that file's carve-out note. Kept narrow
to limit the taste-arbitration risk that rule warns about: this call may only
ever ADD one concrete iconic visual anchor to an existing prompt, never
re-author the shot's subject, action, characters, or camera framing, and it
must return the original image_prompt verbatim whenever no change is needed
(the common case) rather than paraphrase for its own sake.
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "utils"))

from llm import call_llm_json

RECOGNITION_REVIEWER_CONTRACT_VERSION = 2
CHUNK_SIZE = 8
MAX_ATTEMPTS = 3

_SCHEMA = {
    "name": "recognition_review",
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
film, checking only ONE thing: would a viewer instantly recognize this shot's
specific place and occasion from a single still frame?

For each shot below, given its location, read image_prompt. If it already
reads as unmistakably that specific place/occasion — real-world scale and
formality match the occasion, a recognizable landmark or signature detail is
present where the occasion calls for one — return image_prompt UNCHANGED,
verbatim. This will be the common case; do not edit prompts that already work.

Only rewrite image_prompt when a SIGNIFICANT occasion (a wedding, a funeral, a
baptism, a major ceremony or public event) currently reads as a plain,
generic, or low-key version of that occasion — a wedding that could pass for
any meeting room, a ceremony with no unmistakable visual anchor. When you
rewrite, ADD exactly one concrete, real-world-scaled iconic visual detail to
the existing sentence and change nothing else: keep the same subject, visible
action, people, body language, time of day, and camera framing verbatim. You
are elevating specificity of place only, never re-authoring the shot.

Never invent grandeur for an ordinary or domestic location — leave those
prompts unchanged.

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
        f"{i + 1}. location: {s.get('location') or '(unspecified)'} | "
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
            print(f"    recognition_reviewer: {problems[0]} after {MAX_ATTEMPTS} attempts, "
                  f"keeping originals", flush=True)
            return [s["image_prompt"] for s in scenes]
        messages.append({"role": "assistant", "content": json.dumps(data, ensure_ascii=False)})
        last_problems = problems


def review(scenes: list[dict], workers: int = 8) -> list[dict]:
    """Returns `scenes` with `image_prompt` possibly rewritten in place for
    significant occasions that didn't already read as iconic."""
    chunks = [scenes[i:i + CHUNK_SIZE] for i in range(0, len(scenes), CHUNK_SIZE)]
    with ThreadPoolExecutor(max_workers=min(workers, len(chunks) or 1)) as ex:
        results = list(ex.map(_review_chunk, chunks))
    revised_prompts = [prompt for chunk_result in results for prompt in chunk_result]
    return [
        {**scene, "image_prompt": prompt, "recognition_reviewer_contract_version": RECOGNITION_REVIEWER_CONTRACT_VERSION}
        for scene, prompt in zip(scenes, revised_prompts)
    ]


if __name__ == "__main__":
    sample = [
        {"scene_number": 1, "location": "St. Luke's Community Room", "image_prompt": "The protagonist stands at the front of a plain room with folding chairs during her sister's wedding, morning light, medium shot."},
        {"scene_number": 2, "location": "Her own kitchen", "image_prompt": "The protagonist stirs a pot at her kitchen stove, morning light, medium shot."},
    ]
    out = review(sample, workers=1)
    assert len(out) == 2, out
    assert all("image_prompt" in s for s in out)
    print(f"ok  recognition_reviewer.review() -> {[s['image_prompt'][:50] for s in out]}")
