"""Recognition director agent: for each beat, given its already-assigned
location (agents/location_scout) and emotional stakes (agents/emotion_scout),
proposes the ONE unmistakable visual anchor that makes this shot recognizable
as this specific place/occasion from a single still frame — a soaring stone
nave and stained glass for a cathedral wedding, not a generic room with rows
of chairs. Feeds forward into src/scene_engine.py's shot author
(author_story_beat/author_literal_beat), which stays the single final author
of the shot's image_prompt — this agent only proposes the anchor detail, it
does not write the shot itself.

Only significant/ceremonial occasions get a cue — an ordinary domestic or
workaday beat (a kitchen, a commute, a desk) returns an empty string rather
than being forced toward artificial grandeur it doesn't call for.

Scope (narrowed 2026-08-04): anchors are ARCHITECTURE or LANDMARK OBJECTS only
— the soaring nave, the tiered cake, the flag-draped casket. People — who is
present, how the crowd is staged, how they are dressed for the occasion — are
NOT this agent's job; agents/casting_director owns all of that now. (An earlier
2026-08-03 version let this agent propose people/attire anchors too; once
casting_director existed that overlapped its presence/staging call, so it was
pulled back here to keep one concept in one place — see agents/CLAUDE.md's
no-overlap principle.)
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "utils"))

from llm import call_llm_json

RECOGNITION_DIRECTOR_CONTRACT_VERSION = 3
CHUNK_SIZE = 8
MAX_ATTEMPTS = 3

_SCHEMA = {
    "name": "recognition_cues",
    "schema": {
        "type": "object",
        "properties": {
            "recognition_cues": {
                "type": "array",
                "items": {"type": "string"},
            }
        },
        "required": ["recognition_cues"],
        "additionalProperties": False,
    },
}

_SYSTEM = """
You are proposing the one unmistakable visual anchor for each beat below, so a
single still frame reads instantly as its specific place and occasion — the
way one glance at a soaring stone nave and stained glass reads as "cathedral
wedding," or one glance at a towering tiered cake reads as "wedding
reception." You are given each beat's already-assigned location and its
emotional stakes, in order.

For a beat whose location represents a significant, ceremonial, or
once-in-a-while occasion (a wedding, a funeral, a baptism, a graduation, a
major public event), name ONE concrete, real-world-scaled ARCHITECTURAL or
LANDMARK-OBJECT detail that makes that specific place/occasion instantly
recognizable — a soaring stained-glass window and stone nave for a cathedral
wedding, a towering tiered cake for a reception, a flag-draped casket and rows
of white headstones for a graveside funeral. Anchor ONLY on the place and its
signature objects, never on the people: who is present, how a crowd is staged,
and how they are dressed for the occasion are decided by a separate casting
pass and are NOT your call — do not describe guests, an officiant, a couple, or
mourners. Infer which kind of occasion this is from the emotional stakes
(celebratory stakes read as a wedding-type occasion; grief/loss stakes read as
a funeral-type occasion) and pick the single place/object detail that lets a
viewer recognize both the place AND the occasion from one glance. Scale it to
how grand that kind of occasion actually is in real life; do not undersell it
with a plain or generic version of the space.

For a beat whose location is ordinary, domestic, or workaday (a kitchen, a
commute, an office desk, a quiet walk), return an empty string — do not invent
artificial grandeur where the occasion itself does not call for it.

Return exactly {count} strings in "recognition_cues", one per beat, same
order, each at most 20 words.
""".strip()


def _sanitize(text: str) -> str:
    """Strip stray control bytes the decoder can inject when a similar string
    repeats many times in one array (an em dash / curly apostrophe corrupted to
    e.g. \\x19 — confirmed 2026-08-03). A decoder artifact, not a semantic issue,
    so fix it in place rather than drop a good anchor to empty over one stray
    byte."""
    cleaned = "".join(c for c in (text or "") if ord(c) >= 32 or c in "\t\n")
    return " ".join(cleaned.split())


def _validate(cues: list[str], beats: list[dict]) -> list[str]:
    if len(cues) != len(beats):
        return [f"recognition_cues must have exactly {len(beats)} entries, one per "
                f"beat in order — got {len(cues)}"]
    return []


def _assign_chunk(beats: list[dict]) -> list[str]:
    numbered = "\n".join(
        f"{i + 1}. location: {b['location'] or '(unspecified)'} | "
        f"stakes: {b['emotional_stakes'] or '(none)'}"
        for i, b in enumerate(beats)
    )
    system = _SYSTEM.format(count=len(beats))
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"BEATS:\n{numbered}"},
    ]
    # Scaled with chunk size, not a flat constant — same reasoning as
    # agents/location_scout: a real architectural/landmark description per
    # significant beat can run long, and a flat budget can truncate mid-array.
    token_budget = min(max(2048, 300 * len(beats)), 32000)
    last_problems: list[str] = []
    for attempt in range(MAX_ATTEMPTS):
        if last_problems:
            messages.append({
                "role": "user",
                "content": "Fix these problems and return the corrected full JSON object:\n"
                           + "\n".join(f"- {p}" for p in last_problems),
            })
        data = call_llm_json(messages, _SCHEMA, max_completion_tokens=token_budget)
        cues = [_sanitize(c) for c in (data.get("recognition_cues") or [])]
        problems = _validate(cues, beats)
        if not problems:
            return cues
        if attempt == MAX_ATTEMPTS - 1:
            # Fail-open: an empty cue is itself a valid answer (most beats get
            # one), so a still-malformed result (only a count mismatch can reach
            # here now) pads/truncates rather than raises — this is an optional
            # accent, not a hard shot requirement like location_scout's location.
            print(f"    recognition_director: {problems[0]} after {MAX_ATTEMPTS} attempts, "
                  f"padding/truncating", flush=True)
            return (cues + [""] * len(beats))[:len(beats)]
        messages.append({"role": "assistant", "content": json.dumps(data, ensure_ascii=False)})
        last_problems = problems


def assign(locations: list[str], emotional_beats: list[dict], workers: int = 8) -> list[str]:
    """One recognition cue per beat, by position — chunked the same way
    agents/location_scout chunks, since each beat's cue depends only on its
    own location/stakes, never its neighbors'."""
    beats = [
        {"location": loc, "emotional_stakes": beat.get("emotional_stakes", "")}
        for loc, beat in zip(locations, emotional_beats)
    ]
    chunks = [beats[i:i + CHUNK_SIZE] for i in range(0, len(beats), CHUNK_SIZE)]
    with ThreadPoolExecutor(max_workers=min(workers, len(chunks) or 1)) as ex:
        results = list(ex.map(_assign_chunk, chunks))
    return [cue for chunk_result in results for cue in chunk_result]


if __name__ == "__main__":
    locations = ["Grand downtown cathedral", "Her own kitchen"]
    beats = [
        {"emotional_stakes": "her sister's wedding, the marriage she has waited years for"},
        {"emotional_stakes": "an ordinary quiet morning"},
    ]
    out = assign(locations, beats, workers=1)
    assert len(out) == 2, out
    print(f"ok  recognition_director.assign() -> {out}")
