"""Multi-lane scene asset router: archival (real photo/painting/map/document via
Google Images/Serper + GPT-4o vision QA) -> stock (Pexels, modern/geographic
b-roll, no QA) -> graphic (GPT-image generated map/document, legible text is the
whole point) -> Krea (AI painting, fallback whenever no real/generated asset
applies). Ported from the sibling `military/` repo's
lib/collect/{serper,identify,graphics}.ts, reduced to what heritage needs: reads
(not writes) the same Turso `blocked_domains` table military/footage-collector
share, no perceptual-hash dedup (first accepted candidate wins — add dedup if
repeats show up in gallery review).

route(scene, context) is the entry point scene_engine.py:generate_images() calls
per scene. Routing by scene["scene_type"] (see scene_engine.py:SCENE_TYPES):

  map / document  -> named_entity set  -> archival_search() -> graphic_image() fallback
                     named_entity empty -> graphic_image() directly
  geographic      -> named_entity set  -> archival_search() -> pexels_search() -> krea fallback
                     named_entity empty -> pexels_search() -> krea fallback
  modern_scientific -> pexels_search() -> krea fallback
  historical_dramatic -> named_entity set -> archival_search() -> krea fallback
                         named_entity empty -> krea fallback (unchanged single-lane behavior)
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "utils"))

import env               # utils: one .env lookup
import s3 as heritage_s3  # src: upload_from_url() / upload_bytes()

SERPER_ENDPOINT = "https://google.serper.dev/images"
OPENAI_CHAT_ENDPOINT = "https://api.openai.com/v1/chat/completions"
OPENAI_IMAGES_ENDPOINT = "https://api.openai.com/v1/images/generations"
PEXELS_ENDPOINT = "https://api.pexels.com/v1/search"

VISION_MODEL = "gpt-4o"

# Same model/size/quality the sibling military/lib/collect/graphics.ts uses —
# legible in-image text is the entire point of this lane, gpt-image is
# best-in-class at it. 1536x864 native 16:9, quality 'low' (~4x cheaper than
# medium, no visible legibility loss per that file's own A/B note).
GRAPHIC_MODEL = "gpt-image-2"
GRAPHIC_SIZE = "1536x864"
GRAPHIC_QUALITY = "low"

# Renderings that auto-reject a candidate regardless of confidence — ported from
# military/lib/collect/identify.ts's AUTO_REJECT_RENDERINGS.
AUTO_REJECT_RENDERINGS = {"toy", "scale model", "3d render", "statue"}

# Watermarked/paywalled stock-agency hosts that show up in Google Images results
# but aren't usable (visible watermark, or a hotlinked preview that 404s).
BLOCKED_HOST_SUBSTRINGS = (
    "gettyimages", "istockphoto", "alamy", "shutterstock", "dreamstime",
    "123rf", "depositphotos", "stocksy", "adobe.com/stock", "pinterest.",
)

# Turso `blocked_domains` table — shared with military/footage-collector, read-only
# here (this pipeline never flags new domains, only skips known-dead ones before
# paying for a vision-QA call that's going to fail anyway). Fetched once per
# process and memoized — a run is one short-lived batch, not a long server, so
# there's no need for the TS side's 30s TTL.
_TURSO_BLOCKED_CACHE: set | None = None


def _turso_blocked_domains() -> set:
    global _TURSO_BLOCKED_CACHE
    if _TURSO_BLOCKED_CACHE is not None:
        return _TURSO_BLOCKED_CACHE
    try:
        db_url = env.require("TURSO_DATABASE_URL").replace("libsql://", "https://")
        token = env.require("TURSO_AUTH_TOKEN")
        body = {"requests": [{"type": "execute", "stmt": {"sql": "SELECT domain FROM blocked_domains"}},
                              {"type": "close"}]}
        resp = _post_json(f"{db_url}/v2/pipeline", body, {"Authorization": f"Bearer {token}"}, timeout=15)
        rows = resp["results"][0]["response"]["result"]["rows"]
        _TURSO_BLOCKED_CACHE = {row[0]["value"].lower() for row in rows}
        print(f"  asset_selector: loaded {len(_TURSO_BLOCKED_CACHE)} blocked domains from Turso", flush=True)
    except Exception as ex:  # noqa: BLE001 — a Turso hiccup blocks nothing this run, not a hard failure
        print(f"  asset_selector: Turso blocklist fetch failed ({ex}) — continuing with static list only",
              flush=True)
        _TURSO_BLOCKED_CACHE = set()
    return _TURSO_BLOCKED_CACHE

# All scenes for Bible app: high quality digital painting with spiritual/biblical
# aesthetic. Single style across all scene_types — the app tells transformation
# stories centered on a believer's faith journey, rendered as spiritual art.
STYLE_PREFIXES = {
    "historical_dramatic": (
        "high quality digital painting, spiritual and emotional, divine light, "
    ),
    "geographic": (
        "high quality digital painting, spiritual landscape, divine light, "
    ),
    "modern_scientific": (
        "high quality digital painting, spiritual transformation, divine light, "
    ),
}
DEFAULT_STYLE_PREFIX = "high quality digital painting, spiritual and emotional, divine light, "

# Graphic-lane prompt style, keyed by scene_type ('map'/'document'). gpt-image has
# no negative_prompt param — "no photographs" is baked into the prompt text itself,
# same as military/lib/collect/graphics.ts's infographic prompts. No mood/lighting
# language, same reasoning as STYLE_PREFIXES above — just the medium + legibility.
GRAPHIC_STYLE = {
    "map": ("close-up three-quarter angle of an antique parchment historical map on a "
            "table, sepia ink linework, hand-lettered legible place names, cartographic "
            "compass rose, no photographs, no modern elements. "),
    "document": ("close-up three-quarter angle of an aged parchment historical document on a "
                 "table, period-accurate legible handwriting or typography, aged paper "
                 "texture, no photographs, no modern elements. "),
}


def _is_blocked(url: str) -> bool:
    u = (url or "").lower()
    if any(host in u for host in BLOCKED_HOST_SUBSTRINGS):
        return True
    return any(domain in u for domain in _turso_blocked_domains())


def _post_json(url: str, body: dict, headers: dict, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                  headers={"Content-Type": "application/json", **headers},
                                  method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"POST {url} {e.code}: {e.read().decode()[:500]}")


_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def _get_json(url: str, headers: dict, timeout: int = 30) -> dict:
    # urllib's default User-Agent ("Python-urllib/3.x") gets Cloudflare'd (403,
    # error 1010) on Pexels even with a valid key — a real browser UA sails
    # through, curl (which sends its own UA) confirmed the key/endpoint were
    # never the problem.
    req = urllib.request.Request(url, headers={"User-Agent": _UA, **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GET {url} {e.code}: {e.read().decode()[:500]}")


# ---------------------------------------------------------------------------
# ARCHIVAL LANE — Google Images (Serper) + GPT-4o vision QA gate
# ---------------------------------------------------------------------------

def serper_search(query: str, num: int = 10) -> list[dict]:
    """Google Images search via Serper. Returns [] on any failure (soft miss —
    the caller falls through to the next lane, never crashes the pipeline)."""
    try:
        key = env.require("SERPER_API_KEY")
        data = _post_json(SERPER_ENDPOINT, {"q": query, "num": min(max(num, 1), 100)},
                           {"X-API-KEY": key})
        return data.get("images", []) or []
    except Exception as ex:  # noqa: BLE001 — soft miss, log and move on
        print(f"    serper_search({query!r}) failed: {ex}", flush=True)
        return []


# SFW gate — applied to EVERY archival candidate regardless of kind. The real-photo
# lane pulls from open Google Images results, which (unlike Krea's own
# negative_prompt/scene_engine.BASE_NEGATIVE, or gpt-image's built-in moderation)
# has NO content filter of its own — a historical script can legitimately name a
# massacre/battle/execution and Google Images will happily return a graphic period
# illustration or war photo for it. Reject those here rather than relying on luck.
_SFW_SYSTEM_SUFFIX = (
    " SFW GATE (applies above all else): set matches=false, regardless of anything else, "
    "if the image shows graphic violence, gore, blood, wounds, mutilation, dismemberment, "
    "corpses/dead bodies, execution, torture, or any other disturbing/graphic imagery. This "
    "channel is strictly family-friendly — when in doubt, reject."
)
_SFW_USER_SUFFIX = (
    " Regardless of anything above: if the image shows graphic violence, gore, blood, "
    "wounds, mutilation, corpses, or execution/torture, matches=false — no exceptions."
)


def _qa_prompts(kind: str, target: str, era: str, snippet: str, title_hint: str) -> tuple[str, str]:
    """Type-aware accept bar, adapted from military/lib/collect/identify.ts's
    buildPrompts() — heritage drops the nation discriminator (not relevant here)
    and never attempts real-person identity matching (era/attire plausibility
    only), matching this repo's stance that there are no case photos to verify.
    Every branch's system/user prompt gets the SFW gate appended before return —
    see _finish() below."""
    hint = f' The image\'s own title/caption reads: "{title_hint.strip()}".' if title_hint.strip() else ""
    story = f' This must depict the specific subject THIS script passage is about: "{snippet[:400]}".' if snippet else ""
    era_line = f" Target era: {era}." if era else ""

    def _finish(system: str, user: str) -> tuple[str, str]:
        return system + _SFW_SYSTEM_SUFFIX, user + _SFW_USER_SUFFIX

    if kind == "person":
        return _finish(
            "You assess whether an image is a genuine period photograph or historical "
            "painting/portrait plausibly depicting a named historical figure. Do NOT attempt "
            "to conclusively confirm identity by facial recognition — that is unreliable and "
            "out of scope. Judge instead: is this a real photograph/painting (not a modern "
            "toy, statue, 3D render, or costumed reenactor), and does the era/attire/setting "
            "plausibly fit the target?",
            f'Target person: "{target}".{era_line} Set matches=true if this is a real photograph '
            f"or painting (not a render/statue/reenactor) whose era/attire plausibly fits the "
            f"target.{hint}{story} Otherwise matches=false.",
        )
    if kind == "location":
        return _finish(
            "You assess whether an image depicts a specific named real-world landmark or "
            "place AND whether it visually fits the target era. Prefer a literal match to the "
            "named landmark; if unsure, judge whether the scene category (castle, valley, "
            "coastline, city street, harbor, etc.) plausibly fits. Treat era as a HARD "
            "discriminator when a historical era is given: modern skyscrapers, glass-and-steel "
            "towers, cars, paved highways, neon/electric lighting, or any other unmistakably "
            "contemporary skyline/streetscape is a MISMATCH for a pre-20th-century target, even "
            "if it's the same city/place by name — a present-day photo of a city is not a period "
            "photo of that same city centuries earlier. Reject clear toys, scale models, 3D "
            "renders, and statues.",
            f'Target landmark/place: "{target}".{era_line} Set matches=true ONLY if the image '
            f"plausibly shows this specific place AND its buildings/streetscape/lighting fit the "
            f"target era — a modern skyline/cityscape is matches=false even when it is literally "
            f"the same named place today.{hint}{story} Otherwise matches=false.",
        )
    if kind == "map":
        return _finish(
            "You assess whether an image is a genuine historical map relevant to a given "
            "subject/region. Text, labels, and hand-lettering are EXPECTED and should never "
            "be penalized. Reject only clear 3D renders or obviously fabricated/modern "
            "infographic mockups.",
            f'Target map subject: "{target}".{era_line} Set matches=true if this is a real '
            f"historical/period-style map relevant to that subject (labels/text are normal "
            f"and welcome).{hint}{story} Otherwise matches=false.",
        )
    # document
    return _finish(
        "You assess whether an image is a genuine historical document/record/manuscript "
        "relevant to a given subject. Text and handwriting are EXPECTED and should never be "
        "penalized. Reject only clear 3D renders or obviously fabricated/modern mockups.",
        f'Target document subject: "{target}".{era_line} Set matches=true if this is a real '
        f"historical document/record/manuscript relevant to that subject (text/handwriting "
        f"are normal and welcome).{hint}{story} Otherwise matches=false.",
    )


_QA_SCHEMA = {
    "name": "archival_qa",
    "schema": {
        "type": "object",
        "properties": {
            "matches": {"type": "boolean"},
            "rendering": {"type": "string",
                          "enum": ["real", "scale model", "toy", "3d render", "statue", "illustration"]},
            "confidence": {"type": "number"},
        },
        "required": ["matches", "rendering", "confidence"],
        "additionalProperties": False,
    },
    "strict": True,
}


def _vision_qa(image_url: str, kind: str, target: str, era: str, snippet: str,
               title_hint: str = "") -> dict | None:
    """One GPT-4o vision call: does this candidate image satisfy the accept bar for
    `kind`? Returns None (treat as reject) on any network/parse error — unlike
    military's fail-open-to-accept, this pipeline always has a Krea fallback
    downstream, so a QA hiccup should just skip the candidate, not blind-accept it."""
    try:
        key = env.require("OPENAI_API_KEY")
        system, user = _qa_prompts(kind, target, era, snippet, title_hint)
        body = {
            "model": VISION_MODEL,
            "temperature": 0,
            "max_tokens": 200,
            "response_format": {"type": "json_schema", "json_schema": _QA_SCHEMA},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type": "text", "text": user},
                    {"type": "image_url", "image_url": {"url": image_url, "detail": "low"}},
                ]},
            ],
        }
        resp = _post_json(OPENAI_CHAT_ENDPOINT, body, {"Authorization": f"Bearer {key}"}, timeout=60)
        content = (resp.get("choices") or [{}])[0].get("message", {}).get("content")
        if not content:
            return None
        return json.loads(content)
    except Exception as ex:  # noqa: BLE001 — treat as reject, try next candidate
        print(f"    vision_qa failed for {image_url[:80]}: {ex}", flush=True)
        return None


def _qa_accepts(qa: dict) -> bool:
    if qa.get("rendering") in AUTO_REJECT_RENDERINGS:
        return False
    return bool(qa.get("matches")) and float(qa.get("confidence", 0)) >= 0.6


def archival_search(search_terms: list[str], kind: str, era: str = "", snippet: str = "",
                     tries: int = 6) -> tuple[str | None, str]:
    """Google Images (Serper) -> vision-QA gate -> first accepted candidate's raw
    url (NOT yet re-hosted — caller uploads to S3, since Google Images hosts
    routinely hotlink-block) + the literal search term that actually hit, so the
    caller can show that basis in the review gallery. `search_terms` is a list of
    1-2 author-written literal image-search queries (scene["search_terms"]) —
    tried in order, first term that yields an accepted candidate wins; if the
    first term strikes out entirely, the second (if present) is tried before
    giving up. None if nothing passes any term, `search_terms` is empty, or
    SERPER_API_KEY is unset."""
    last_query = ""
    for query in (search_terms or [])[:2]:
        last_query = query
        candidates = serper_search(query, num=max(tries * 2, 10))
        checked = 0
        for c in candidates:
            if checked >= tries:
                break
            url = c.get("imageUrl") or c.get("link")
            if not url or _is_blocked(url):
                continue
            checked += 1
            qa = _vision_qa(url, kind, query, era, snippet, title_hint=c.get("title", ""))
            if qa and _qa_accepts(qa):
                return url, query
    return None, last_query


# ---------------------------------------------------------------------------
# STOCK LANE — Pexels (no vision QA; trusted catalog)
# ---------------------------------------------------------------------------

def pexels_search(search_terms: list[str], per_page: int = 5) -> tuple[str | None, str]:
    """Pexels photo search, landscape orientation, first result's large url + the
    query string that hit. None on any failure (soft miss). No QA gate — Pexels'
    own catalog is curated enough that a wrong-category miss is rare and
    low-stakes for b-roll. `search_terms` is a list of 1-2 author-written literal
    queries (scene["search_terms"]) — tried in order, first term with a result
    wins. Queried VERBATIM, no code-appended mood/style words — Pexels indexes
    real photo captions, and "misty moody cinematic" tacked onto a plain search
    term returns nothing; mood/atmosphere is the author's job (image_prompt), not
    a search-query decoration."""
    last_query = ""
    for query in (search_terms or [])[:2]:
        last_query = query
        try:
            key = env.require("PEXELS_API_KEY")
            import urllib.parse
            qs = urllib.parse.urlencode({"query": query, "per_page": per_page, "orientation": "landscape"})
            data = _get_json(f"{PEXELS_ENDPOINT}?{qs}", {"Authorization": key})
            photos = data.get("photos") or []
            for photo in photos:
                src = photo.get("src", {})
                url = src.get("large2x") or src.get("large") or src.get("original")
                if url:
                    return url, query
        except Exception as ex:  # noqa: BLE001 — soft miss, try next term
            print(f"    pexels_search({query!r}) failed: {ex}", flush=True)
    return None, last_query


# ---------------------------------------------------------------------------
# GRAPHIC LANE — GPT-image generated map/document (legible text)
# ---------------------------------------------------------------------------

def graphic_image(prompt: str, style_key: str, tries: int = 3) -> tuple[str | None, str]:
    """One GPT-image generation, style-keyed (map/document), uploaded to S3 —
    returns the url + the full generation prompt actually sent, so the caller can
    show that basis in the review gallery. Retries on transient safety-filter
    400s — same intermittent behavior military/lib/collect/graphics.ts's
    docstring notes for gpt-image prompts."""
    style = GRAPHIC_STYLE.get(style_key, "")
    # gpt-image has no negative_prompt param — SFW has to be baked into the prompt
    # text itself, same as the "no photographs" instruction already in GRAPHIC_STYLE.
    sfw = "Strictly family-friendly: no gore, no blood, no graphic violence, no disturbing imagery. "
    full_prompt = (style + sfw + prompt)[:4000]
    try:
        key = env.require("OPENAI_API_KEY")
    except Exception:
        return None, full_prompt
    body = {"model": GRAPHIC_MODEL, "prompt": full_prompt, "size": GRAPHIC_SIZE,
            "quality": GRAPHIC_QUALITY, "n": 1}
    for attempt in range(tries):
        try:
            resp = _post_json(OPENAI_IMAGES_ENDPOINT, body, {"Authorization": f"Bearer {key}"}, timeout=120)
            item = (resp.get("data") or [{}])[0]
            b64 = item.get("b64_json")
            if b64:
                data = base64.b64decode(b64)
                return heritage_s3.upload_bytes(data, key_seed=full_prompt, prefix="heritage-graphics"), full_prompt
            if item.get("url"):
                return heritage_s3.upload_from_url(item["url"], prefix="heritage-graphics"), full_prompt
        except Exception as ex:  # noqa: BLE001 — retry, transient safety-filter/5xx
            print(f"    graphic_image attempt {attempt + 1}/{tries} failed: {ex}", flush=True)
            time.sleep(2 * (attempt + 1))
    return None, full_prompt


# ---------------------------------------------------------------------------
# ROUTING
# ---------------------------------------------------------------------------

def _krea_fallback(scene: dict, context: dict) -> tuple[str | None, str]:
    """Krea AI painting — the always-works fallback. Returns url + the full
    generation prompt used. Imports scene_engine LAZILY (inside the function, not
    at module top) since scene_engine.py imports THIS module at top level for
    generate_images(); a top-level import here would be circular."""
    import scene_engine  # src/ — deferred import, see docstring above
    import krea as scene_assets  # src/

    stype = scene.get("scene_type", "historical_dramatic")
    prefix = STYLE_PREFIXES.get(stype, DEFAULT_STYLE_PREFIX)
    prompt = prefix + scene["image_prompt"]
    negative = ", ".join(x for x in (scene.get("negative_prompt"), scene_engine.BASE_NEGATIVE) if x)
    scene_assets._load_env()
    try:
        return scene_assets.krea_photo(prompt, negative_prompt=negative), prompt
    except Exception as ex:  # noqa: BLE001 — degrade to None, caller logs the miss
        print(f"    krea fallback failed: {ex}", flush=True)
        return None, prompt


def route(scene: dict, context: dict) -> dict:
    """Per-scene lane router. Returns scene merged with `image_url` (may be None
    if every lane failed), `lane` (which lane actually produced it, or
    'krea'/None), `image_basis` (the literal search query or generation prompt
    that produced it — attempted even when the lane failed, so a reviewer can see
    WHY nothing came back), and `basis_kind` ('search' or 'prompt').

    TODO: Bible app currently forces KREA digital painting only (skips archival/stock).
    Remove this workaround once hero_subject authoring consistently shows protagonist."""
    stype = scene.get("scene_type", "historical_dramatic")
    entity = (scene.get("named_entity") or "").strip()
    entity_kind = scene.get("named_entity_kind") or ""
    era = context.get("era", "")
    snippet = scene.get("script_snippet", "")

    # Defensive fallback (shouldn't normally happen): if a scene has no authored
    # search_terms, fall back to the named_entity alone as a single-term list
    # rather than crashing the archival lane.
    search_terms = scene.get("search_terms") or ([entity] if entity else [])

    def _archival(kind: str) -> dict | None:
        raw, query = archival_search(search_terms, kind, era, snippet)
        if not raw:
            return None
        hosted = heritage_s3.upload_from_url(raw, prefix="heritage-archival")
        if not hosted:
            return None
        return {**scene, "image_url": hosted, "lane": "archival",
                "image_basis": query, "basis_kind": "search"}

    def _stock() -> dict | None:
        url, query = pexels_search(scene.get("search_terms") or [])
        if not url:
            return None
        return {**scene, "image_url": url, "lane": "stock",
                "image_basis": query, "basis_kind": "search"}

    # Bible app: force KREA digital painting for all scenes. Skip archival/stock search.
    if stype in ("map", "document"):
        url, prompt = graphic_image(scene["image_prompt"], stype)
        return {**scene, "image_url": url, "lane": f"graphic-{stype}" if url else None,
                "image_basis": prompt, "basis_kind": "prompt"}

    # All other scene types: Krea digital painting only
    url, prompt = _krea_fallback(scene, context)
    return {**scene, "image_url": url, "lane": "krea", "image_basis": prompt, "basis_kind": "prompt"}


if __name__ == "__main__":
    assert _is_blocked("https://media.gettyimages.com/photos/foo.jpg")
    assert not _is_blocked("https://upload.wikimedia.org/wikipedia/commons/foo.jpg")
    print("ok  blocklist check (not making real API calls — this is a smoke test only)")
