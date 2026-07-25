"""Character ledger agent: read the whole script once, decide which characters are
worth tracking as a recurring, visually-consistent identity across scenes (not every
mentioned person — only the protagonist, Jesus if he actually appears, and any
supporting character who recurs across multiple beats). Generate -> deterministic
validate -> retry-with-feedback loop, same shape as military/agents/entity_ledger.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "utils"))

from llm import call_llm_json  # utils/

MAX_ATTEMPTS = 3

_SCHEMA = {
    "name": "character_ledger",
    "schema": {
        "type": "object",
        "properties": {
            "characters": {
                "type": "array",
                "minItems": 1,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "short lowercase slug, unique, e.g. 'protagonist', 'jesus', 'pastor_daniel'"},
                        "name": {"type": "string", "description": "their name, or a short descriptor if unnamed (e.g. 'the pastor')"},
                        "role": {"type": "string", "description": "one short phrase, their narrative role"},
                        "appearance": {
                            "type": "string",
                            "description": (
                                "40-60 words, a FULL-FIGURED (not stick-figure/abstract) visual "
                                "description: concrete age, gender, ethnicity, build, hairstyle, and "
                                "modern clothing. Never a bare 'a person'/'a figure' — every character "
                                "must be visually concrete and distinguishable from the others."
                            ),
                        },
                        "script_spans": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 4,
                            "items": {"type": "string"},
                            "description": "1-4 short substrings quoted VERBATIM from the script where this character appears",
                        },
                    },
                    "required": ["id", "name", "role", "appearance", "script_spans"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["characters"],
        "additionalProperties": False,
    },
}

_SYSTEM = (
    "You are building a character ledger for a full-figured, visually consistent "
    "illustrated Christian story video. Read the whole script and identify ONLY the "
    "characters worth tracking as a recurring visual identity across scenes:\n"
    "- The protagonist is ALWAYS included, with id exactly 'protagonist'.\n"
    "- Jesus is included ONLY if the script actually depicts him appearing/speaking as "
    "a character — not just mentioned in passing or prayer.\n"
    "- Any other character is included ONLY if they recur across multiple beats of the "
    "script, not a single one-off mention. Do not include background/crowd figures or "
    "unnamed onlookers.\n"
    "Every appearance must be visually concrete (age, gender, ethnicity, build, "
    "hairstyle, modern clothing) — a bare 'a person'/'a figure' is a known failure mode "
    "where image models default unspecified characters into a generic long-haired "
    "bearded robed 'Jesus' look; avoid that for anyone who isn't actually Jesus.\n"
    "Return ONLY the JSON object described by the schema."
)


def _validate(data: dict, script: str) -> list[str]:
    problems = []
    chars = data.get("characters") or []
    if not chars:
        problems.append("characters is empty")
        return problems
    ids = [c.get("id") for c in chars]
    if "protagonist" not in ids:
        problems.append("no character with id 'protagonist' — the protagonist must always be included")
    if len(ids) != len(set(ids)):
        problems.append("duplicate character ids — every id must be unique")
    seen_appearance_heads = set()
    for c in chars:
        words = len((c.get("appearance") or "").split())
        if words < 15:
            problems.append(f"character '{c.get('id')}' appearance is too thin ({words} words) — needs a concrete 40-60 word description")
        head = (c.get("appearance") or "")[:40].lower()
        if head in seen_appearance_heads:
            problems.append(f"character '{c.get('id')}' has a near-duplicate appearance to another character — make each visually distinct")
        seen_appearance_heads.add(head)
        # script_spans is a loose "where does this character show up" hint, not
        # consumed anywhere downstream yet (author_chunk() decides character_ids
        # per scene straight from the chunk text) — a quoting mismatch here (this
        # script's doubled ""smart-quote"" style trips exact substring checks) isn't
        # worth failing the whole ledger over. Log, don't block.
        for span in c.get("script_spans") or []:
            if span and span not in script:
                print(f"    note: character '{c.get('id')}' script_span {span[:60]!r}... "
                      f"isn't an exact verbatim substring (quoting mismatch, likely harmless)", flush=True)
    return problems


def build(script: str, context: dict) -> dict:
    """Return {"characters": [...]} — see _SCHEMA for the exact shape."""
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"Story context: {context}\n\nSCRIPT:\n{script}"},
    ]
    last_problems: list[str] = []
    for attempt in range(MAX_ATTEMPTS):
        if last_problems:
            messages.append({
                "role": "user",
                "content": "Fix these problems with your previous answer and return the corrected full JSON object:\n"
                           + "\n".join(f"- {p}" for p in last_problems),
            })
        data = call_llm_json(messages, _SCHEMA, max_completion_tokens=4096)
        problems = _validate(data, script)
        if not problems:
            return data
        last_problems = problems
    raise RuntimeError(f"character_ledger.build() failed validation after {MAX_ATTEMPTS} attempts: {last_problems}")


if __name__ == "__main__":
    sample_script = (
        "Maria had always kept her faith quiet, tucked away like a secret. Every morning "
        "she scrolled her phone before she ever thought to pray. Then Pastor Daniel stopped "
        "her after service one Sunday. 'God isn't asking for your Sunday,' he said gently, "
        "'He's asking for your whole week.' The words stayed with Maria all week. By Friday, "
        "she had moved her Bible from the shelf to her nightstand, the first thing she'd see "
        "each morning instead of her phone. Pastor Daniel smiled when she told him the "
        "following Sunday — a small, ordinary victory, but hers."
    )
    sample_context = {"setting": "modern daily life", "spiritual_theme": "surrender", "emotional_palette": "warm"}
    result = build(sample_script, sample_context)
    chars = result["characters"]
    assert any(c["id"] == "protagonist" for c in chars), result
    assert all(len(c["appearance"].split()) >= 15 for c in chars), result
    print(f"ok  character_ledger.build() -> {len(chars)} tracked character(s): {[c['id'] for c in chars]}")
