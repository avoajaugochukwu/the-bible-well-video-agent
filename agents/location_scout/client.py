"""Location scout agent: one location string per narration snippet, assigned
ahead of shot authoring so every author call (literal or story) receives a
place it must honor instead of picking freely per-beat with no memory of its
neighbors. Extracted out of src/scene_engine.py so location assignment is its
own diagnosable unit (previously `assign_locations()`/`_assign_locations_chunk()`
lived inline there).

Also owns the grandeur-matching rule: a significant occasion (a wedding, a
funeral, a baptism, any ceremony) must get a location whose real-world scale
and formality actually matches that occasion — not just a topically-correct
room. Confirmed bug this fixes: the pre-pass previously could hold a wedding
continuous across six beats (correct) while assigning it something like "St.
Luke's Community Room" (folding chairs) — technically continuous, but reads
as a plain meeting room, not a wedding.

Chunks run SEQUENTIALLY (see `assign()`), each one's last snippet+location
carried into the next chunk's call. Confirmed bug this fixes (2026-08-03): a
single continuous event whose narration happened to land across two chunks
(nothing about the event itself changed) silently got renamed mid-event — one
real church scene held "St. Luke's" for the snippets in one chunk, then
became "St. Agnes" for the rest, because the next chunk had no memory it was
still the same event.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "utils"))

from llm import call_llm_json  # utils/

LOCATION_SCOUT_CONTRACT_VERSION = 5
CHUNK_SIZE = 8
MAX_ATTEMPTS = 3

_SCHEMA = {
    "name": "beat_locations",
    "schema": {
        "type": "object",
        "properties": {
            "locations": {
                "type": "array",
                "items": {"type": "string"},
            }
        },
        "required": ["locations"],
        "additionalProperties": False,
    },
}


def _sanitize(text: str) -> str:
    """Strip stray control bytes the decoder can inject when the same long
    string repeats many times in one array — an em dash or curly apostrophe
    corrupted into e.g. \\x19 (confirmed 2026-08-03). It is a decoder artifact,
    not a semantic problem, so we FIX it in place (drop the byte, collapse the
    whitespace it leaves) rather than reject the location: a persistent
    corruption used to survive all retries and hard-crash the whole job, when
    the string minus one stray byte is a perfectly usable venue name."""
    cleaned = "".join(c for c in (text or "") if ord(c) >= 32 or c in "\t\n")
    return " ".join(cleaned.split())


def _validate(locations: list[str], snippets: list[str]) -> list[str]:
    problems = []
    if len(locations) != len(snippets):
        problems.append(
            f"locations must have exactly {len(snippets)} entries, one per "
            f"snippet in order — got {len(locations)}"
        )
        return problems
    for i, loc in enumerate(locations, start=1):
        if not (loc or "").strip():
            problems.append(f"snippet {i} has no location assigned — every snippet needs one")
    return problems


def _assign_chunk(snippets: list[str], recurring_locations: list, previous_tail: dict | None) -> list[str]:
    """Snippets in the same chunk are seen together so the model can hold one
    location steady across a run of beats describing the same continuous event.
    `previous_tail` (the immediately preceding chunk's own last snippet + the
    location it was assigned, or None for the first chunk) carries continuity
    ACROSS the chunk boundary — confirmed 2026-08-03: a continuous event whose
    narration happened to get chunked across two calls (nothing about the
    event actually changed) silently got renamed mid-event (one real script's
    single wedding sentence, cut into per-clause snippets, held "St. Luke's"
    for the snippets in chunk N then silently became "St. Agnes" for the
    remaining snippets in chunk N+1) because chunk N+1 had no memory this was
    the same event at all."""
    numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(snippets))
    previous_context = (
        f"""
PREVIOUS SNIPPET (already assigned, immediately precedes snippet 1 below —
read-only, do not re-assign it): {previous_tail["snippet"]!r}
PREVIOUS SNIPPET'S LOCATION: {previous_tail["location"]!r}
If snippet 1 (and any snippets after it) are clearly still part of that same
continuous event, repeat PREVIOUS SNIPPET'S LOCATION exactly, verbatim — do
not invent a new venue just because this is a new call.
"""
        if previous_tail else
        "This is the first chunk of the narration — no previous snippet to continue from."
    )
    system = f"""
Assign exactly one location string to each narration snippet below, in the
order given. Snippets that are clearly part of the same continuous real event
or scene (e.g. several consecutive lines all describing one wedding, one
conversation, one drive) MUST get the exact same location string, verbatim,
repeated — never rephrase it slightly between them. Only choose a new location
when a snippet's own words clearly move the story to a different place or a
new scene begins.

{previous_context}

When a snippet describes a significant occasion (a wedding, a funeral, a
baptism, a graduation, any ceremony or major life event), the location you
choose or invent must match that occasion's real-world scale and formality —
a wedding is a proper wedding venue (a grand sanctuary, a real event hall),
never a plain meeting room or folding-chair space, even if a plainer room
would be topically defensible. Ordinary everyday snippets (a kitchen, a car, a
walk) still just get whatever plain real place fits — do not inflate scale
where the occasion itself is not significant.

A communal or social occasion hosted for or about OTHER people — a baby shower,
a wedding, a wedding reception, a graduation party, an engagement party, a
funeral or its reception, any group gathering — happens at the real public or
social venue that occasion is held in (a banquet or event hall, a church hall, a
restaurant, a decorated home clearly belonging to the hosts), NOT the
protagonist's own home or apartment. This applies even when the mention is
plural, passing, or a montage reference to such occasions in general, and even
when the line is framed as the protagonist merely watching, standing at,
attending, or thinking about the event: the shot will depict the occasion
itself, so give it the occasion's real venue — a baby shower is a room full of
guests around a mother-to-be, never the protagonist's living room. Only assign
the protagonist's own home when the snippet is genuinely a private domestic
moment of hers with no shared occasion in it at all.

Prefer reusing one of these established world locations when it fits:
{json.dumps(recurring_locations, indent=2)}

Invent a short, specific new location only when none of the above fit this
narration.

SNIPPETS:
{numbered}

Return exactly {len(snippets)} non-empty strings in "locations", one per
snippet, same order — never leave one blank.
""".strip()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": "Assign the locations."},
    ]
    # Scaled with chunk size, not a flat constant: the grandeur-matching rule
    # above can ask for a real, descriptive venue name per snippet rather than
    # a short room label, and a fixed 2048-token budget silently ran out mid-
    # chunk (confirmed 2026-08-03: truncated response left several snippets in
    # the chunk with an empty location once the reply hit the token ceiling).
    token_budget = min(max(2048, 400 * len(snippets)), 32000)
    last_problems: list[str] = []
    for _ in range(MAX_ATTEMPTS):
        if last_problems:
            messages.append({
                "role": "user",
                "content": "Fix these problems and return the corrected full JSON object:\n"
                           + "\n".join(f"- {p}" for p in last_problems),
            })
        data = call_llm_json(messages, _SCHEMA, max_completion_tokens=token_budget)
        locations = [_sanitize(loc) for loc in (data.get("locations") or [])]
        problems = _validate(locations, snippets)
        if not problems:
            return locations
        messages.append({"role": "assistant", "content": json.dumps(data, ensure_ascii=False)})
        last_problems = problems
    raise RuntimeError(f"location_scout failed validation after {MAX_ATTEMPTS} attempts: {last_problems}")


def assign(snippets: list[str], visual_story: dict) -> list[str]:
    """Chunk narration the same way cut_narration_scenes chunks it for cutting,
    and assign one location per snippet ahead of shot authoring. Chunks run
    SEQUENTIALLY, not in parallel: each one's own last snippet+location carries
    forward into the next chunk's call, the only way a continuous event that
    happens to straddle a chunk boundary still holds one location across it.
    Chunks are cheap, fast calls, so this costs little latency in exchange for
    a real correctness guarantee full parallelism can't provide."""
    recurring_locations = visual_story.get("recurring_locations") or []
    chunks = [snippets[i:i + CHUNK_SIZE] for i in range(0, len(snippets), CHUNK_SIZE)]
    locations: list[str] = []
    previous_tail = None
    for chunk in chunks:
        chunk_locations = _assign_chunk(chunk, recurring_locations, previous_tail)
        locations.extend(chunk_locations)
        previous_tail = {"snippet": chunk[-1], "location": chunk_locations[-1]}
    return locations


if __name__ == "__main__":
    sample_snippets = [
        "She stood at the back of the sanctuary in her sister's wedding.",
        "The vows were said beneath the stained glass windows.",
    ]
    out = assign(sample_snippets, {"recurring_locations": []})
    assert len(out) == 2, out
    assert out[0] == out[1], "consecutive snippets of one continuous event must share one location"

    # Cross-chunk continuity: force two tiny chunks (size 1) so the same
    # continuous event spans a chunk boundary, and confirm it still holds.
    # (Plain reassignment, not `global` — this block already runs at true
    # module scope, the same namespace assign()'s CHUNK_SIZE lookup sees.)
    real_chunk_size, CHUNK_SIZE = CHUNK_SIZE, 1
    try:
        out2 = assign(sample_snippets, {"recurring_locations": []})
    finally:
        CHUNK_SIZE = real_chunk_size
    assert out2[0] == out2[1], (
        "a continuous event split across a chunk boundary must still hold one "
        f"location: {out2}"
    )
    print(f"ok  location_scout.assign() -> {out} (cross-chunk continuity: {out2})")
