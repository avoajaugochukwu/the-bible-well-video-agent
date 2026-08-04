"""Casting director agent: for each beat, decides WHO is in frame — the single
"presence" judgment that used to live tangled inside src/scene_engine.py's shot
authors. One decision per beat, ahead of authoring:

- which tracked characters (character_ids) are actually foregrounded — default
  none or protagonist-alone, adding another tracked character ONLY when this
  beat's own narration singles that specific person out (by name, an
  unambiguous singular reference, or direct quoted speech). A plural collective
  noun (guests, friends, the congregation) NEVER adds a tracked character.
- whether the protagonist should be LEFT OUT entirely — a STANDING PREFERENCE,
  applied aggressively (user-directed, said repeatedly): she appears in many
  beats already, so whenever a beat can stand on its own without her (it names
  an event, an occasion, other people, a place, or an object the shot can be
  built around) she is left out — take every such opportunity. This holds even
  when the line is phrased as her watching/attending/standing at the occasion
  rather than acting in it: depict the occasion, not her apart from it. She
  stays in only when the beat cannot be itself without her (names her by name/
  singular action, or is an inherently private interior moment of hers). When in
  doubt, leave her out.
- how to stage the shot's population — a quoted line spoken AT the protagonist
  by an untracked person is staged as a two-person moment with that speaker in
  frame as an anonymous figure; a group occasion is staged as a populated group
  shot, not the protagonist standing solo in it yet again.

Confirmed 2026-08-03 (the reason this became its own agent): the shot author was
deciding all of the above inside one already-overloaded prompt, and it kept
defaulting the protagonist into every frame — 7 straight church-wedding beats
with her standing in the same outfit, a group event rendered as her alone at
home, someone else's quoted taunt rendered as her reacting to an unseen voice.
Presence is a casting call; it lives here now, and the author just renders the
cast this agent hands it.

Feeds forward into src/scene_engine.py's author_literal_beat, which stays the
single final author of the image_prompt — this agent only decides the cast and
its staging, never writes the shot itself. Post-hoc reviewers this is NOT (see
agents/CLAUDE.md rule 2's carve-out) — it is a pre-pass that feeds forward, the
allowed shape.
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "utils"))

from llm import call_llm_json

CASTING_DIRECTOR_CONTRACT_VERSION = 3
CHUNK_SIZE = 8
MAX_ATTEMPTS = 3


def _schema(cast_ids: list[str]) -> dict:
    id_item = {"type": "string", "enum": cast_ids} if cast_ids else {"type": "string"}
    return {
        "name": "beat_castings",
        "schema": {
            "type": "object",
            "properties": {
                "castings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "character_ids": {"type": "array", "items": id_item},
                            "staging_note": {"type": "string"},
                        },
                        "required": ["character_ids", "staging_note"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["castings"],
            "additionalProperties": False,
        },
    }


def _sanitize(text: str) -> str:
    """Strip stray control bytes the decoder can inject when a similar string
    repeats many times in one array (an em dash / curly apostrophe corrupted to
    e.g. \\x19 — confirmed 2026-08-03). A decoder artifact, not a semantic issue,
    so fix it in place rather than reject a good staging note over one stray
    byte."""
    cleaned = "".join(c for c in (text or "") if ord(c) >= 32 or c in "\t\n")
    return " ".join(cleaned.split())


def _validate(castings: list[dict], beats: list[dict], cast_ids: set[str]) -> list[str]:
    if len(castings) != len(beats):
        return [f"castings must have exactly {len(beats)} entries, one per beat in "
                f"order — got {len(castings)}"]
    problems = []
    for i, c in enumerate(castings, start=1):
        ids = c.get("character_ids") or []
        if len(ids) != len(set(ids)):
            problems.append(f"beat {i}'s character_ids has duplicate ids: {ids}")
        for cid in ids:
            if cid not in cast_ids:
                problems.append(f"beat {i} names an unknown character_id {cid!r}")
    return problems


_SYSTEM = """
You are the casting director for one Christian animated short film. For each
beat below you decide ONLY who is in frame and how the shot is populated and
dressed for its occasion — you do NOT write the shot, describe the location, or
choose the action. A separate shot author renders exactly the cast and staging
you hand it.

TRACKED CAST (the only named characters that can carry a character_ids entry —
everyone else in any shot is an anonymous, uncredited background/foreground
figure):
{cast}

Each beat is one of two kinds, marked on it:
- A CONCRETE beat gives you its narration, its location, and — when it is one
  fragment of a longer continuous scene — the surrounding passage as context.
  Cast it from what that narration actually depicts.
- An ABSTRACT beat is interior reflection with no literal event to film; it is
  narration-blind by design, so you get only its location and its emotional
  stakes, never narration. Cast it from the shared world and those stakes — an
  abstract beat is almost always the protagonist alone in a private reflective
  moment, unless its stakes clearly center on a shared event involving others.
Return one casting per beat, same order.

character_ids — default to EMPTY or ["protagonist"] alone. Add any OTHER tracked
character ONLY when this beat singles that specific person out: by their name,
by an unambiguous singular reference ("her ex", "the man who approached her"),
or by direct quoted speech attributed to them. Never add a tracked character
because they recur elsewhere, because the mood or setting makes their presence
plausible, or because a scene "should" have them. A plural collective noun on
its own — friends, people, everyone, guests, the congregation, coworkers, the
crowd — NEVER justifies adding a named tracked character; it always means
anonymous background figures. If you catch yourself adding a second or third
tracked character to a crowd/group beat, stop: that is the exact bug this
instruction prevents.

LEAVING THE PROTAGONIST OUT — this is a STANDING PREFERENCE; apply it
aggressively. She is the film's throughline across the WHOLE film and already
appears in many beats, so she is NEVER required in any single shot. Whenever a
beat can stand on its own WITHOUT her — it names or describes an event, an
occasion, other people, a place, or an object the shot can be built around —
LEAVE HER OUT (character_ids empty). Take every such opportunity; never default
her in just because she is the protagonist or because a beat "could" plausibly
include her. This applies when the beat is really ABOUT the occasion or the
other people in it — depict the occasion or those people themselves (the
gathered guests, the celebration, the object named), NOT the protagonist
standing apart from it.
BUT do NOT cut her out of an occasion she is personally attending when the beat
centers HER OWN experience of being there — her watching, her reaction, her
hands together, her tears during the service, a beat that is clearly her felt
moment inside the event. Being one guest among many at an event she is part of
is not the same as the shot being about the event instead of her; keep her IN
those beats, staged within the crowd, so a run of scenes at an occasion she
attends is not entirely emptied of her. Keep her in when the beat genuinely
cannot be itself without her: its narration names her by name or a singular
action she performs, it centers her felt reaction to being somewhere, OR it is
an inherently private interior moment of hers (her own prayer, her own grief
alone, a direct line about her own story). Leave her out only when the beat can
be built entirely around the event or other people with no real loss.

STAGING — write one short, plain sentence telling the shot author who is in the
frame and how it is populated and dressed:
- Quoted line spoken TO or AT the protagonist by someone who is NOT tracked
  cast: stage it as a two-person moment — that speaker in frame as an anonymous
  foreground figure addressing her — never her alone reacting to an unseen
  voice. (character_ids still holds only tracked cast, so the speaker adds no id.)
- Shared group occasion: stage it as a populated group shot of that occasion,
  and say how the crowd is DRESSED for what it actually is — a wedding is guests
  in bright or pastel formalwear with a couple at the altar and an officiant; a
  funeral is mourners in black or muted formalwear; an ordinary gathering is
  plain everyday dress, not ceremonial costuming. Place the tracked cast — if
  any — within that crowd; never a significant occasion as an empty unpopulated
  room.
- Ordinary solo beat: say so plainly (e.g. "protagonist alone, mid-action").
Prefer a populated, group, or two-person staging over a solo static protagonist
whenever the beat plausibly allows it. Keep the staging note under 35 words and
never name a tracked character by their given name — refer to the protagonist as
"the protagonist" and any other tracked character by their role.

Return exactly {count} castings in "castings", one per beat, same order.
""".strip()


def _cast_block(characters: list[dict]) -> str:
    lines = []
    for c in characters:
        role = "protagonist" if c["id"] == "protagonist" else (c.get("role") or "recurring supporting character")
        brief = c.get("story_function") or c.get("appearance") or ""
        lines.append(f'- id "{c["id"]}", role "{role}"' + (f": {brief}" if brief else ""))
    return "\n".join(lines)


def _beat_block(i: int, b: dict) -> str:
    """Concrete beats show narration (+ surrounding passage); abstract beats
    show only stakes, never narration — they are narration-blind by design (see
    agents/CLAUDE.md rule 1), so casting them off narration would pierce that
    lane exactly the way the shot author is forbidden to."""
    head = f"BEAT {i + 1} ({b['visual_mode'] or 'concrete'}):\n  location: {b['location'] or '(unspecified)'}"
    if (b.get('visual_mode') or 'concrete') == 'concrete':
        head += f"\n  narration: {b['snippet']}"
        if b['local_context']:
            head += ("\n  surrounding scene (context only, do not treat as this beat's own "
                     f"content): {b['local_context']}")
    else:
        head += ("\n  (abstract beat — no narration by design; cast from the world, this "
                 f"location, and these stakes)\n  emotional stakes: {b['emotional_stakes'] or '(none)'}")
    return head


def _assign_chunk(beats: list[dict], cast_block: str, cast_ids: list[str]) -> list[dict]:
    numbered = "\n\n".join(_beat_block(i, b) for i, b in enumerate(beats))
    system = _SYSTEM.format(cast=cast_block, count=len(beats))
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"BEATS:\n{numbered}"},
    ]
    schema = _schema(cast_ids)
    token_budget = min(max(2048, 300 * len(beats)), 32000)
    cast_id_set = set(cast_ids)
    last_problems: list[str] = []
    for attempt in range(MAX_ATTEMPTS):
        if last_problems:
            messages.append({
                "role": "user",
                "content": "Fix these problems and return the corrected full JSON object:\n"
                           + "\n".join(f"- {p}" for p in last_problems),
            })
        data = call_llm_json(messages, schema, max_completion_tokens=token_budget)
        castings = data.get("castings") or []
        for c in castings:
            c["staging_note"] = _sanitize(c.get("staging_note") or "")
        problems = _validate(castings, beats, cast_id_set)
        if not problems:
            return castings
        if attempt == MAX_ATTEMPTS - 1:
            # Fail-open to protagonist-solo, the safe legacy default: a missing
            # casting must never crash a run, and "protagonist alone" is exactly
            # what the author used to default to before this agent existed.
            print(f"    casting_director: {problems[0]} after {MAX_ATTEMPTS} attempts, "
                  f"defaulting the rest to protagonist-solo", flush=True)
            fallback = {"character_ids": ["protagonist"], "staging_note": ""}
            castings = (castings + [fallback] * len(beats))[:len(beats)]
            return [
                c if not _validate([c], [b], cast_id_set) else fallback
                for c, b in zip(castings, beats)
            ]
        messages.append({"role": "assistant", "content": json.dumps(data, ensure_ascii=False)})
        last_problems = problems


def assign(
    snippets: list[str],
    characters: list[dict],
    locations: list[str],
    local_contexts: list[str],
    emotional_beats: list[dict],
    workers: int = 8,
) -> list[dict]:
    """One casting ({character_ids, staging_note}) per beat, by position — for
    EVERY beat, concrete or abstract, so presence lives in exactly one place and
    both shot authors are pure renderers. Chunked in parallel like agents/
    recognition_director — each beat's casting depends only on its own narration
    (concrete) or stakes (abstract) + location + surrounding-passage context
    (already computed by scene_engine._local_contexts), never its neighbors', so
    there is nothing for parallel chunks to disagree about at the seams."""
    beats = [
        {"snippet": s, "location": loc, "local_context": lc,
         "visual_mode": b.get("visual_mode"), "emotional_stakes": b.get("emotional_stakes", "")}
        for s, loc, lc, b in zip(snippets, locations, local_contexts, emotional_beats)
    ]
    cast_ids = [c["id"] for c in characters]
    cast_block = _cast_block(characters)
    chunks = [beats[i:i + CHUNK_SIZE] for i in range(0, len(beats), CHUNK_SIZE)]
    with ThreadPoolExecutor(max_workers=min(workers, len(chunks) or 1)) as ex:
        results = list(ex.map(lambda ch: _assign_chunk(ch, cast_block, cast_ids), chunks))
    return [c for chunk_result in results for c in chunk_result]


if __name__ == "__main__":
    chars = [
        {"id": "protagonist", "appearance": "a woman in her 40s"},
        {"id": "james", "role": "her ex", "story_function": "the man who left her"},
    ]
    snippets = [
        '"You know you aren\'t getting younger, right?" a coworker said.',
        "baby showers she was invited to but dreaded,",
        "James finally called her after three years.",
    ]
    locations = ["Her office", "A friend's decorated living room", "Her apartment"]
    local_contexts = ["", "", ""]
    emotional_beats = [
        {"visual_mode": "concrete", "emotional_stakes": "a coworker's careless jab"},
        {"visual_mode": "concrete", "emotional_stakes": "someone else's celebration she is only a guest at"},
        {"visual_mode": "concrete", "emotional_stakes": "the man who left her, back after years"},
    ]
    out = assign(snippets, chars, locations, local_contexts, emotional_beats, workers=1)
    assert len(out) == 3, out
    # Quoted taunt by an untracked coworker -> no tracked id forced, staged two-person.
    assert "protagonist" not in out[0]["character_ids"] or len(out[0]["character_ids"]) <= 1, out[0]
    # A baby shower centered on someone else -> protagonist defaulted OUT.
    assert "protagonist" not in out[1]["character_ids"], out[1]
    # A beat that names James by name -> james is allowed in.
    assert "james" in out[2]["character_ids"], out[2]
    print(f"ok  casting_director.assign() -> {json.dumps(out, indent=2)}")
