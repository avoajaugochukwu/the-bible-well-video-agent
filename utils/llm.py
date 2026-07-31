"""One OpenAI structured-JSON chat-completions caller, shared by src/scene_engine.py
and agents/. Extracted from scene_engine.py's _post_openai/_chat/_extract_json —
same raw-urllib house style, no SDK dependency.
"""
import json
import re
import urllib.error
import urllib.request

import env  # utils: one .env lookup (checks root .env)

OPENAI_API = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-5-mini"


def _post_openai(body: dict) -> dict:
    token = env.require("OPENAI_API_KEY")
    req = urllib.request.Request(
        OPENAI_API,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    # ponytail: a fixed 300s timeout was fine for short scripts but a long
    # script's schema (one item per narration snippet, no fixed cap) can need
    # a max_completion_tokens budget in the hundreds of thousands — scale the
    # read timeout with it instead of guessing one constant for every script length.
    timeout = min(1800, max(300, body.get("max_completion_tokens", 4096) // 100))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"OpenAI API {e.code}: {e.read().decode()[:800]}")


def _extract_json(text: str) -> dict:
    """Strip ```json fences if the model added them, then parse — with an outer-brace
    salvage fallback for the rare truncated/chatty response that slips past the
    strict json_schema constraint."""
    t = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.DOTALL)
    if m:
        t = m.group(1)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        i, j = t.find("{"), t.rfind("}")
        if i >= 0 and i < j:
            return json.loads(t[i:j + 1])
        raise


def call_llm_json(
    messages: list[dict],
    schema: dict,
    model: str = DEFAULT_MODEL,
    max_completion_tokens: int = 4096,
    reasoning_effort: str = "low",
) -> dict:
    """One structured-output OpenAI chat-completions call, strict json_schema
    (grammar-constrained — far more reliable than response_format=json_object for
    getting the exact shape asked for). Raises on refusal/empty/malformed.

    model defaults to gpt-5-mini; reasoning_effort is dropped for non-gpt-5 models
    since it's a gpt-5-only param.
    """
    body = {
        "model": model,
        "max_completion_tokens": max_completion_tokens,
        "response_format": {"type": "json_schema", "json_schema": {**schema, "strict": True}},
        "messages": messages,
    }
    if model.startswith("gpt-5"):
        body["reasoning_effort"] = reasoning_effort
    resp = _post_openai(body)
    if resp.get("error"):
        raise RuntimeError(f"OpenAI API error: {resp['error']}")
    choice = (resp.get("choices") or [{}])[0]
    if choice.get("finish_reason") == "content_filter":
        raise RuntimeError(f"OpenAI refused the request (content_filter): {resp}")
    text = (choice.get("message") or {}).get("content") or ""
    if not text.strip() and choice.get("finish_reason") == "length":
        # gpt-5's reasoning tokens are billed out of the same max_completion_tokens
        # budget as the visible answer — a hard call can spend the ENTIRE budget
        # reasoning and leave nothing to actually write the JSON (finish_reason
        # 'length', content ''), not because the answer itself is long. Retry once
        # with a much bigger budget before giving up; a genuinely oversized
        # schema/prompt still fails clearly on the second attempt.
        body["max_completion_tokens"] = min(max_completion_tokens * 4, 128000)
        resp = _post_openai(body)
        if resp.get("error"):
            raise RuntimeError(f"OpenAI API error: {resp['error']}")
        choice = (resp.get("choices") or [{}])[0]
        if choice.get("finish_reason") == "content_filter":
            raise RuntimeError(f"OpenAI refused the request (content_filter): {resp}")
        text = (choice.get("message") or {}).get("content") or ""
    if not text.strip():
        raise RuntimeError(f"OpenAI returned no text content: {resp}")
    return _extract_json(text)


if __name__ == "__main__":
    schema = {
        "name": "sanity_check",
        "schema": {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        },
    }
    out = call_llm_json(
        [
            {"role": "system", "content": "Reply with the exact word 'ok' in the answer field."},
            {"role": "user", "content": "ping"},
        ],
        schema,
        max_completion_tokens=256,
    )
    assert out.get("answer"), f"expected non-empty answer, got {out}"
    print(f"ok  call_llm_json round-trip: {out}")
