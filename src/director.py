"""Text-overlay "director" planning engine — decides WHEN and WHAT card
(photo-title, photo-caption, big-stat, opening-title, pull-quote, year-card)
appears on top of the rendered scenes.

Ported from helpers/ui/remotion/remotion-test-2 (read there, don't edit):
  lib/director/understanding.ts    -> understand_script(), compute_target_beats()
  lib/director/spine.ts            -> build_spine() + its opening-hook sub-call
  lib/director/plan.ts             -> plan_director_timeline()
  lib/director/parsers/photo-title.ts    -> parse_photo_title_entry()
  lib/director/parsers/photo-caption.ts  -> parse_photo_caption_entry()
  lib/director/parsers/big-stat.ts       -> parse_big_stat_entry()
  lib/director/parsers/heavy-cards.ts    -> parse_opening_title_entry(),
                                             parse_pull_quote_entry(),
                                             parse_year_card_entry()
  lib/director/topup.ts            -> build_topup_moments() + its scene-picking /
                                       refine sub-functions
  lib/director/transcript.ts       -> normalize_token(), first_word_normalized(),
                                       find_word_timestamp(), find_digit_timestamp(),
                                       find_snippet_timestamp(), extract_leading_digits(),
                                       group_words_into_segments()
  lib/director/validators.ts       -> compute_kind_duration_sec(), is_valid_start_sec(),
                                       violates_gap()
  lib/director/script-types.ts     -> VALID_SCRIPT_TYPES, is_documentary_type()
  lib/director/prompts/english.ts  -> resolve_director_system_prompt()
  lib/config/director-rules.ts     -> module constants below
  lib/cardDurations.ts             -> *_DURATION_SEC constants (given verbatim, ported as-is)
  lib/cards/registry.ts            -> CARD_FAMILY, CARD_WHEN_TO_USE, card_glossary()
  lib/alignment/index.ts (alignWithDiagnostics) -> plan_cards()'s call order

Single public entrypoint: plan_cards(script, video_title, scenes, whisper_words,
total_duration) -> list[dict], one flat list of PlacedCard-shaped dicts
(camelCase keys — startSec, coveredCount, etc. — consumed directly by the
Remotion/React renderer, never snake_cased).

Heritage has no subscribe-button overlay (no channel-membership CTA in this
pipeline), so unlike the reference's `occupiedSlots` argument (which starts
pre-loaded with deterministic subscribe placements) ours starts empty and is
populated only by the spine's own cards — same shape, just nothing to seed it
with here.
"""
import json
import math
import re
import unicodedata

import scene_engine  # src/: _chat() — reused, not duplicated (see CLAUDE.md)

# ============================================================================
# lib/config/director-rules.ts
# ============================================================================
DIRECTOR_MIN_GAP_SEC = 20
MOMENTS_MIN_GAP_SEC = 8
DIRECTOR_HEAD_GUARD_SEC = 10
DIRECTOR_TAIL_GUARD_SEC = 10
OPENING_TITLE_HARDCODED_START_SEC = 4
OPENING_TITLE_HARD_TEXT_CHARS = 17
PULL_QUOTE_SNAP_WINDOW_SEC = 8
TOPUP_PHOTO_TITLE_MIN_SPACING_SEC = 45
BIG_STAT_MIN_GAP_SEC = 90

# ============================================================================
# lib/cardDurations.ts — given verbatim by the task, ported line-for-line.
# ============================================================================
PHOTO_TITLE_DURATION_SEC = 0.4 + 4.2 + 0.4  # 5.0
PHOTO_CAPTION_DURATION_SEC = 0.4 + 4.2 + 0.4  # 5.0
BIG_STAT_DURATION_SEC = 0.5 + 4.0 + 0.5  # 5.0
OPENING_TITLE_DURATION_SEC = 5
PULL_QUOTE_DURATION_SEC = 5
YEAR_CARD_DURATION_SEC = 5

# ============================================================================
# lib/cards/registry.ts — family (decides which occupancy track a kind uses)
# + the whenToUse glossary the Director prompt is generated from. Dict
# insertion order mirrors CARDS' key order in registry.ts so card_glossary()
# groups/orders identically.
# ============================================================================
CARD_FAMILY = {
    "photo-title": "moment",
    "photo-caption": "moment",
    "big-stat": "moment",
    "opening-title": "summary",
    "pull-quote": "summary",
    "year-card": "summary",
}

CARD_WHEN_TO_USE = {
    "photo-title": (
        "Punctuate ONE strong word/name/phrase spoken VERBATIM at that moment "
        "— renders big and CENTERED."
    ),
    "photo-caption": (
        "A short contextual line in YOUR OWN words (NOT a verbatim quote), "
        "rendered bottom-left, coexists with the scene. Keep it ≤ ~8 words."
    ),
    "big-stat": "Spotlight a QUANTITY the narrator says out loud (percentage, money, count, metric).",
    "opening-title": "The video's ONE cinematic opening title, at the very top. Use exactly once.",
    "pull-quote": "A standout VERBATIM quotation the narrator reads aloud, placed WHERE it is spoken.",
    "year-card": "Spotlight a pivotal YEAR/date as a giant centered figure with eyebrow + caption.",
}


def _kind_duration_sec(kind: str, item_count: int = 0) -> float:
    if kind == "photo-title":
        return PHOTO_TITLE_DURATION_SEC
    if kind == "photo-caption":
        return PHOTO_CAPTION_DURATION_SEC
    if kind == "big-stat":
        return BIG_STAT_DURATION_SEC
    if kind == "opening-title":
        return OPENING_TITLE_DURATION_SEC
    if kind == "pull-quote":
        return PULL_QUOTE_DURATION_SEC
    if kind == "year-card":
        return YEAR_CARD_DURATION_SEC
    raise ValueError(f"unknown card kind: {kind}")


def card_glossary() -> str:
    def line(kind: str) -> str:
        return f'- "{kind}" — {CARD_WHEN_TO_USE[kind]}'

    def by_family(family: str) -> str:
        return "\n".join(line(k) for k, fam in CARD_FAMILY.items() if fam == family)

    preamble = (
        "Match a card to a moment by INTENT, not keywords — if a beat fits a "
        "card's spirit, use it even when the exact case isn't spelled out here, "
        "and aim for every kind to earn its place across a video. Where two "
        "kinds could fit, the distinction noted in each line breaks the tie."
    )
    return (
        f"{preamble}\n\nHEAVY (anchor the frame — pick deliberately):\n{by_family('summary')}"
        f"\n\nLIGHT (overlays — place generously):\n{by_family('moment')}"
    )


# ============================================================================
# lib/director/script-types.ts
# ============================================================================
VALID_SCRIPT_TYPES = {
    "documentary", "listicle", "tutorial", "explainer",
    "essay", "narrative", "commentary", "other",
}


def is_documentary_type(script_type: str) -> bool:
    return script_type == "documentary"


# ============================================================================
# lib/director/validators.ts
# ============================================================================
def compute_kind_duration_sec(kind: str, item_count: int) -> float:
    return _kind_duration_sec(kind, item_count)


def is_valid_start_sec(start_sec, video_duration_sec: float, kind_duration_sec: float) -> bool:
    if start_sec is None or not isinstance(start_sec, (int, float)) or not math.isfinite(start_sec):
        return False
    if start_sec < DIRECTOR_HEAD_GUARD_SEC:
        return False
    if start_sec + kind_duration_sec > video_duration_sec - DIRECTOR_TAIL_GUARD_SEC:
        return False
    return True


def violates_gap(start_sec: float, occupied: list, min_gap_sec: float = DIRECTOR_MIN_GAP_SEC) -> bool:
    return any(abs(t - start_sec) < min_gap_sec for t in occupied)


# ============================================================================
# lib/director/transcript.ts
# ============================================================================
def _js_round(x: float) -> int:
    """Math.round semantics (half rounds toward +infinity), not Python's
    round-half-to-even — matters for the small cosmetic roundings below."""
    return math.floor(x + 0.5) if x >= 0 else -math.floor(-x + 0.5)


def normalize_token(s: str) -> str:
    """Lowercase + strip diacritics + drop everything that isn't a letter/digit.
    "Sunrise!" -> "sunrise"; "cafe" (from "café") -> "cafe"; "11%" -> "11"."""
    s = s.lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if ch.isalnum())


def first_word_normalized(s: str) -> str:
    parts = s.strip().split()
    return normalize_token(parts[0]) if parts else ""


def find_word_timestamp(words: list, target: str, near_sec: float, window_sec: float):
    """First whisper word whose normalized form equals `target` and whose start
    is closest to `near_sec`, within +/- window_sec. None if no match."""
    t = normalize_token(target)
    if not t:
        return None
    best = None
    for w in words:
        if abs(w["start"] - near_sec) > window_sec:
            continue
        if normalize_token(w["word"]) != t:
            continue
        dist = abs(w["start"] - near_sec)
        if best is None or dist < best[1]:
            best = (w["start"], dist)
    return best[0] if best else None


def find_digit_timestamp(words: list, digit_target: str, near_sec: float, window_sec: float):
    """Like find_word_timestamp but SUBSTRING match on digits — a figure like
    "11%" may be transcribed as "11" by whisper."""
    t = normalize_token(digit_target)
    if not t or not any(c.isdigit() for c in t):
        return None
    best = None
    for w in words:
        if abs(w["start"] - near_sec) > window_sec:
            continue
        if t not in normalize_token(w["word"]):
            continue
        dist = abs(w["start"] - near_sec)
        if best is None or dist < best[1]:
            best = (w["start"], dist)
    return best[0] if best else None


def find_snippet_timestamp(words: list, snippet: str, anchor_len: int = 5, max_gap: int = 2, near_sec=None):
    """Locate where a multi-word snippet is actually spoken. Slides a leading
    anchor of the snippet's normalized words across the whisper stream,
    tolerating up to `max_gap` inserted/dropped filler words, and falls back to
    progressively shorter anchors if the full one matches nothing. When
    `near_sec` is given, picks the candidate closest to it (a topic previewed
    in the intro shouldn't snap a hero to that early mention)."""
    snip_tokens = [normalize_token(t) for t in snippet.split()]
    snip_tokens = [t for t in snip_tokens if t][:anchor_len]
    if not snip_tokens:
        return None
    word_tokens = [normalize_token(w["word"]) for w in words]

    length = len(snip_tokens)
    while length >= 1:
        anchor = snip_tokens[:length]
        candidates = []
        for start in range(len(word_tokens)):
            if word_tokens[start] != anchor[0]:
                continue
            ai, wi, gap = 1, start + 1, 0
            while ai < len(anchor) and wi < len(word_tokens):
                if word_tokens[wi] == anchor[ai]:
                    ai += 1
                    wi += 1
                    gap = 0
                else:
                    gap += 1
                    if gap > max_gap:
                        break
                    wi += 1
            if ai == len(anchor):
                candidates.append(words[start]["start"])
        if candidates:
            if near_sec is None:
                return candidates[0]
            return min(candidates, key=lambda c: abs(c - near_sec))
        if length == 1:
            break
        length -= 1
    return None


_LEADING_DIGITS_RE = re.compile(r"-?\d{1,3}(?:[, ]?\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?")


def extract_leading_digits(figure: str):
    m = _LEADING_DIGITS_RE.search(figure)
    if not m:
        return None
    return m.group(0).replace(",", "").replace(" ", "")


_PAUSE_THRESHOLD_SEC = 0.7
_SEGMENT_MAX_DURATION_SEC = 8


def group_words_into_segments(words: list) -> list:
    if not words:
        return []
    out = []
    buf = [words[0]]
    for i in range(1, len(words)):
        prev, cur = words[i - 1], words[i]
        gap = cur["start"] - prev["end"]
        seg_dur = cur["end"] - buf[0]["start"]
        if gap > _PAUSE_THRESHOLD_SEC or seg_dur > _SEGMENT_MAX_DURATION_SEC:
            out.append({"start": buf[0]["start"], "end": buf[-1]["end"],
                        "text": " ".join(w["word"] for w in buf).strip()})
            buf = []
        buf.append(cur)
    if buf:
        out.append({"start": buf[0]["start"], "end": buf[-1]["end"],
                    "text": " ".join(w["word"] for w in buf).strip()})
    return out


def _str(raw: dict, key: str) -> str:
    """Mirrors the reference's `str = (v) => typeof v === "string" ? v.trim() : ""`
    — our strict json_schema always returns a string (possibly empty) for every
    optional field, so this is just a trim."""
    v = raw.get(key)
    return v.strip() if isinstance(v, str) else ""


def _card_id(raw: dict, next_id) -> str:
    return raw.get("id") or next_id()


# ============================================================================
# lib/director/understanding.ts
# ============================================================================
MAX_UNDERSTANDING_RETRIES = 2

UNDERSTANDING_SCHEMA = {
    "name": "video_understanding",
    "schema": {
        "type": "object",
        "properties": {
            "subject": {"type": "string"},
            "scriptType": {"type": "string", "enum": sorted(VALID_SCRIPT_TYPES)},
            "toneNote": {"type": "string"},
            "suggestedTitles": {"type": "array", "items": {"type": "string"}},
            "themes": {"type": "array", "items": {"type": "string"}},
            "keyEntities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "role": {"type": "string"}},
                    "required": ["name", "role"],
                    "additionalProperties": False,
                },
            },
            "keyFacts": {"type": "array", "items": {"type": "string"}},
            "sectionBeats": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "headline": {"type": "string"},
                        "summary": {"type": "string"},
                        "sourceSnippet": {"type": "string"},
                        "roughStartFraction": {"type": "number"},
                    },
                    "required": ["headline", "summary", "sourceSnippet", "roughStartFraction"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["subject", "scriptType", "toneNote", "suggestedTitles", "themes",
                      "keyEntities", "keyFacts", "sectionBeats"],
        "additionalProperties": False,
    },
}


def compute_target_beats(video_duration_sec: float) -> int:
    """One beat per ~5 minutes, clamped to [2, 8] — computed in code (never
    left to the model, which gets lazy and returns 3 regardless of length)."""
    raw = _js_round(video_duration_sec / 60 / 5)
    return max(2, min(8, raw))


def _understanding_system_prompt(target_beats: int) -> str:
    return f"""You read a full video script and return a structured "video understanding" document. This document is the FOUNDATION every downstream visual decision works from — the Director planner, the per-scene caption refinement, the brief headers — so it must be accurate, opinionated, and hold up across the whole video.

Read the ENTIRE script before writing anything. Form a holistic understanding of:
- The subject and arc.
- Major sections / chapter beats.
- Recurring themes and motifs.
- Key people, places, organizations, dates, and numbers the narrator names.
- Tone (documentary, essay, narrative, investigative, etc.).

Return JSON shaped exactly like:

{{
  "subject": "<1 line — what this video is about>",
  "scriptType": "documentary" | "listicle" | "tutorial" | "explainer" | "essay" | "narrative" | "commentary" | "other",  // "documentary" = history, biography, nature, true-crime, or any factual long-form storytelling — prefer it for that content over "narrative"
  "toneNote": "<1 line tone — e.g. 'warm historical documentary'>",
  "suggestedTitles": ["<3-8 word title>", ...],                  // 3-5 entries
  "themes": ["<short theme>", ...],                              // 3-6 entries, recurring motifs
  "keyEntities": [ {{ "name": "...", "role": "..." }} ],           // up to ~10
  "keyFacts": ["<a number / date / claim the narrator actually says>", ...], // EXHAUSTIVE list, up to ~40 — every distinct number, percentage, date, dollar/quantity, or named figure the narrator says out loud. For data-dense scripts (history with battle stats, finance, sports), err high; for sparse scripts, return only what's actually there. Each entry is a big-stat candidate.
  "sectionBeats": [
    {{ "headline": "<2-5 words>", "summary": "<1-2 sentences>", "sourceSnippet": "<1-3 sentence verbatim excerpt copied from the script where this section begins>", "roughStartFraction": 0.0 }}
  ]                                                              // EXACTLY {target_beats} sections, in order; cover start to end; roughStartFraction is 0..1
}}

Constraints:
- sectionBeats must cover the WHOLE video, in order, from roughStartFraction 0 to ~1.
- Produce EXACTLY {target_beats} section beats, in order — not fewer, not more. This count is fixed for this video's length; do not collapse to a smaller number. Pick the {target_beats} MOST MAJOR sections — these become the video's spine, so each must be a real act the audience would recognize, not a minor aside.
- "sourceSnippet" MUST be copied VERBATIM (word-for-word) from the script — a 1-3 sentence run from the spot where that section actually begins. Do NOT paraphrase it; it is matched against the spoken audio to place a card precisely. Pick a distinctive line, not boilerplate the narrator might repeat.
- Do not invent facts. Stay faithful to the script."""


def _trim_str(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def _string_array(v, max_n: int) -> list:
    if not isinstance(v, list):
        return []
    out = [_trim_str(s) for s in v if _trim_str(s)]
    return out[:max_n]


def _compute_stat_density(key_facts_count: int, video_duration_sec: float) -> str:
    minutes = max(video_duration_sec / 60, 0.5)
    per_minute = key_facts_count / minutes
    if per_minute >= 1.5:
        return "high"
    if per_minute < 0.5:
        return "low"
    return "normal"


def _sanitize_understanding(raw: dict, video_duration_sec: float, target_beats: int) -> dict:
    script_type = raw.get("scriptType") if raw.get("scriptType") in VALID_SCRIPT_TYPES else "other"

    key_entities = []
    for e in raw.get("keyEntities") or []:
        if not isinstance(e, dict):
            continue
        name = _trim_str(e.get("name"))
        role = _trim_str(e.get("role"))
        if name:
            key_entities.append({"name": name, "role": role})
    key_entities = key_entities[:12]

    section_beats = []
    for b in raw.get("sectionBeats") or []:
        if not isinstance(b, dict):
            continue
        headline = _trim_str(b.get("headline"))
        summary = _trim_str(b.get("summary"))
        source_snippet = _trim_str(b.get("sourceSnippet"))
        f = b.get("roughStartFraction")
        f = max(0.0, min(1.0, f)) if isinstance(f, (int, float)) else 0.0
        if not headline:
            continue
        section_beats.append({"headline": headline, "summary": summary,
                              "sourceSnippet": source_snippet, "roughStartFraction": f})
    section_beats = section_beats[:target_beats]

    key_facts = _string_array(raw.get("keyFacts"), 40)

    return {
        "subject": _trim_str(raw.get("subject")),
        "scriptType": script_type,
        "toneNote": _trim_str(raw.get("toneNote")),
        "suggestedTitles": _string_array(raw.get("suggestedTitles"), 6),
        "themes": _string_array(raw.get("themes"), 8),
        "keyEntities": key_entities,
        "keyFacts": key_facts,
        "statDensity": _compute_stat_density(len(key_facts), video_duration_sec),
        "sectionBeats": section_beats,
    }


def understand_script(script: str, video_duration_sec: float) -> dict:
    """One upfront GPT pass: the canonical "what is this video about" answer
    every later pass (spine, Director, topup) works from instead of re-reading
    the raw script. Retries (code-owned beat count, never left to the model)
    up to MAX_UNDERSTANDING_RETRIES times if it undershoots targetBeats."""
    target_beats = compute_target_beats(video_duration_sec)
    system_prompt = _understanding_system_prompt(target_beats)
    user_message = "\n".join([
        f"Video duration: {_js_round(video_duration_sec)} seconds (~{video_duration_sec / 60:.1f} min).",
        f"Produce EXACTLY {target_beats} section beats.",
        "",
        "Script:",
        script,
    ])

    understanding = None
    for _ in range(MAX_UNDERSTANDING_RETRIES + 1):
        data = scene_engine._chat(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}],
            UNDERSTANDING_SCHEMA,
            max_completion_tokens=8192,
        )
        understanding = _sanitize_understanding(data, video_duration_sec, target_beats)
        if len(understanding["sectionBeats"]) >= target_beats:
            break

    if len(understanding["sectionBeats"]) < target_beats:
        print(f"  director: understanding requested {target_beats} beats, got "
              f"{len(understanding['sectionBeats'])} after retries", flush=True)
    return understanding


# ============================================================================
# lib/director/spine-titles.ts + lib/director/spine.ts
# ============================================================================
OPENING_TITLE_MAX_WORD_CHARS = 13
OPENING_TITLE_MAX_WORDS = 2
OPENING_BYLINE_MAX_CHARS = 48

OPENING_HOOK_SCHEMA = {
    "name": "opening_hook",
    "schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "eyebrow": {"type": "string"},
            "subtitle": {"type": "string"},
        },
        "required": ["title", "eyebrow", "subtitle"],
        "additionalProperties": False,
    },
}

_OPENING_HOOK_SYSTEM_PROMPT = """You write the COLD-OPEN title card for a YouTube documentary — the hook a viewer sees in the first second. Hooks decide whether they keep watching, so make it land.

Return JSON: { "title": "...", "eyebrow": "...", "subtitle": "..." }

- "title": the giant on-screen hook. EXACTLY 1 or 2 words — never 3+. It's rendered enormous (one word per line), so each word must be short (<=13 characters). Two punchy words can characterize anything ("Wooden Warplane", "Reliable Car", "War Whip"). Title Case, no punctuation. This is the hook — make it intriguing and concrete, not generic.
- "eyebrow": a short uppercase kicker that frames the title, 1-3 words, <=17 characters (e.g. "WWII AVIATION"). Leave empty if you have nothing strong.
- "subtitle": a one-line byline that carries the specific detail the 1-2 word title can't (<=48 characters). This is where the specifics go.

Do not invent facts beyond the subject. No misleading clickbait."""


def _keep_safe_words(text: str) -> str:
    return " ".join(w for w in text.strip().split() if 0 < len(w) <= OPENING_TITLE_MAX_WORD_CHARS)


def _clamp_title(text: str) -> str:
    words = [w for w in _keep_safe_words(text).split() if w]
    return " ".join(words[:OPENING_TITLE_MAX_WORDS])


def _derive_fallback_title(understanding: dict, video_title: str) -> str:
    sources = [video_title or "", *understanding.get("suggestedTitles", []), understanding.get("subject", "")]
    for s in sources:
        t = _clamp_title(s)
        if t:
            return t
    return ""


def _resolve_opening_hook(understanding: dict, video_title: str) -> dict:
    fallback = {"title": _derive_fallback_title(understanding, video_title), "eyebrow": None, "subtitle": None}
    try:
        user_payload = {"subject": understanding["subject"], "suggestedTitles": understanding["suggestedTitles"]}
        if video_title:
            user_payload["videoTitle"] = video_title
        data = scene_engine._chat(
            [{"role": "system", "content": _OPENING_HOOK_SYSTEM_PROMPT},
             {"role": "user", "content": json.dumps(user_payload, indent=2)}],
            OPENING_HOOK_SCHEMA,
            max_completion_tokens=512,
        )
    except Exception as e:  # noqa: BLE001 — deterministic fallback covers this
        print(f"  director: opening-hook pass failed: {e}", flush=True)
        return fallback

    title = _clamp_title(data.get("title") or "")
    if not title:
        return fallback

    eyebrow_raw = (data.get("eyebrow") or "").strip()
    eyebrow = eyebrow_raw if eyebrow_raw and len(eyebrow_raw) <= OPENING_TITLE_HARD_TEXT_CHARS else None

    subtitle_raw = (data.get("subtitle") or "").strip()
    subtitle = subtitle_raw if subtitle_raw and len(subtitle_raw) <= OPENING_BYLINE_MAX_CHARS else None

    return {"title": title, "eyebrow": eyebrow, "subtitle": subtitle}


def build_spine(understanding: dict, scenes: list, whisper_words: list,
                video_duration_sec: float, video_title: str = "") -> list:
    """The spine builder — ports lib/director/spine.ts. Owns opening-title
    (documentary only, pinned at 4s). This kind is then off-limits to the
    Director (see plan_director_timeline)."""
    beats = understanding.get("sectionBeats") or []
    if not beats:
        return []

    cards = []

    # ── opening-title (documentary only, spine-owned) ──────────────────────
    if is_documentary_type(understanding["scriptType"]):
        hook = _resolve_opening_hook(understanding, video_title)
        ot_start = OPENING_TITLE_HARDCODED_START_SEC
        ot_dur = compute_kind_duration_sec("opening-title", 0)
        ot_fits = ot_start + ot_dur <= video_duration_sec - DIRECTOR_TAIL_GUARD_SEC
        if hook["title"] and ot_fits:
            opening_title_card = {
                "kind": "opening-title", "id": "spine-opening-title", "startSec": ot_start,
                "title": hook["title"],
            }
            if hook.get("eyebrow"):
                opening_title_card["eyebrow"] = hook["eyebrow"]
            if hook.get("subtitle"):
                opening_title_card["subtitle"] = hook["subtitle"]
            cards.append(opening_title_card)

    return cards


# ============================================================================
# lib/director/parsers/photo-title.ts
# ============================================================================
_MAX_WORD_LEN_CHARS = 40
_MAX_DESCRIPTOR_LEN_CHARS = 60
_PHOTO_TITLE_SNAP_WINDOW_SEC = 5


def parse_photo_title_entry(raw: dict, video_duration_sec: float, occupied_heavy: list,
                             occupied_moments: list, whisper_words: list, next_id):
    planner_start = raw.get("startSec")
    if not isinstance(planner_start, (int, float)) or not math.isfinite(planner_start):
        return None
    word = _str(raw, "word")
    if not word or len(word) > _MAX_WORD_LEN_CHARS:
        return None

    snapped = find_word_timestamp(whisper_words, first_word_normalized(word), planner_start, _PHOTO_TITLE_SNAP_WINDOW_SEC)
    if snapped is None:
        return None

    dur = compute_kind_duration_sec("photo-title", 0)
    if not is_valid_start_sec(snapped, video_duration_sec, dur):
        return None
    if violates_gap(snapped, occupied_heavy):
        return None
    if violates_gap(snapped, occupied_moments, MOMENTS_MIN_GAP_SEC):
        return None

    descriptor = None
    d = _str(raw, "descriptor")
    if d and len(d) <= _MAX_DESCRIPTOR_LEN_CHARS:
        descriptor = d

    id_ = _card_id(raw, next_id)
    card = {"kind": "photo-title", "id": id_, "startSec": snapped, "word": word}
    if descriptor:
        card["descriptor"] = descriptor
    entry = {"id": id_, "kind": "photo-title", "startSec": snapped,
             "label": f"{word} — {descriptor}" if descriptor else word}
    return card, entry


# ============================================================================
# lib/director/parsers/photo-caption.ts
# ============================================================================
_MAX_TEXT_LEN_CHARS = 80
_MAX_LABEL_LEN_CHARS = 40


def parse_photo_caption_entry(raw: dict, video_duration_sec: float, occupied_heavy: list,
                               occupied_moments: list, next_id):
    start_sec = raw.get("startSec")
    if not isinstance(start_sec, (int, float)) or not math.isfinite(start_sec):
        return None
    text = _str(raw, "text")
    if not text or len(text) > _MAX_TEXT_LEN_CHARS:
        return None

    dur = compute_kind_duration_sec("photo-caption", 0)
    if not is_valid_start_sec(start_sec, video_duration_sec, dur):
        return None
    if violates_gap(start_sec, occupied_heavy):
        return None
    if violates_gap(start_sec, occupied_moments, MOMENTS_MIN_GAP_SEC):
        return None

    id_ = _card_id(raw, next_id)
    label = text if len(text) <= _MAX_LABEL_LEN_CHARS else f"{text[:_MAX_LABEL_LEN_CHARS - 1]}…"
    card = {"kind": "photo-caption", "id": id_, "startSec": start_sec, "text": text}
    entry = {"id": id_, "kind": "photo-caption", "startSec": start_sec, "label": label}
    return card, entry


# ============================================================================
# lib/director/parsers/big-stat.ts
# ============================================================================
_BIG_STAT_SNAP_WINDOW_SEC = 5
_VALID_DIRECTIONS = {"up", "down", "neutral"}


def parse_big_stat_entry(raw: dict, video_duration_sec: float, occupied_heavy: list,
                          occupied_moments: list, placed: list, whisper_words: list, next_id):
    planner_start = raw.get("startSec")
    if not isinstance(planner_start, (int, float)) or not math.isfinite(planner_start):
        return None
    figure = _str(raw, "figure")
    label = _str(raw, "label")
    if not figure or not label:
        return None

    digit_target = extract_leading_digits(figure)
    snapped = (
        find_digit_timestamp(whisper_words, digit_target, planner_start, _BIG_STAT_SNAP_WINDOW_SEC)
        if digit_target is not None else None
    )
    final_start = snapped if snapped is not None else planner_start

    dur = compute_kind_duration_sec("big-stat", 0)
    if not is_valid_start_sec(final_start, video_duration_sec, dur):
        return None
    if violates_gap(final_start, occupied_heavy):
        return None
    if violates_gap(final_start, occupied_moments, MOMENTS_MIN_GAP_SEC):
        return None

    # Big stats are center-screen/intrusive; keep a wider gap between
    # consecutive ones even though they clear the generic gaps above.
    placed_big_stat_secs = [c["startSec"] for c in placed if c["kind"] == "big-stat"]
    if violates_gap(final_start, placed_big_stat_secs, BIG_STAT_MIN_GAP_SEC):
        return None

    direction = raw.get("direction") if raw.get("direction") in _VALID_DIRECTIONS else "neutral"

    id_ = _card_id(raw, next_id)
    card = {"kind": "big-stat", "id": id_, "startSec": final_start, "figure": figure,
            "label": label, "direction": direction}
    entry = {"id": id_, "kind": "big-stat", "startSec": final_start, "label": f"{figure} · {label}"}
    return card, entry


# ============================================================================
# lib/director/parsers/heavy-cards.ts
# ============================================================================
def _place_heavy(kind: str, raw: dict, video_duration_sec: float, occupied: list, next_id, build):
    start_sec = raw.get("startSec")
    built = build(raw)
    if built is None:
        return None
    fields, label = built
    dur = compute_kind_duration_sec(kind, 0)
    if not is_valid_start_sec(start_sec, video_duration_sec, dur):
        return None
    if violates_gap(start_sec, occupied):
        return None
    id_ = _card_id(raw, next_id)
    card = {"kind": kind, "id": id_, "startSec": start_sec, **fields}
    entry = {"id": id_, "kind": kind, "startSec": start_sec, "label": label}
    return card, entry


def parse_opening_title_entry(raw: dict, video_duration_sec: float, script_type: str, placed: list, next_id):
    """Bypasses the standard placement: documentary-only, used at most once,
    server-pinned to the 4s mark (ignores the planner's startSec, the
    head-guard, and the gap rule), and REJECTS outright when either text
    overruns the hard char cap."""
    if not script_type or not is_documentary_type(script_type):
        return None
    if any(c["kind"] == "opening-title" for c in placed):
        return None

    title = _str(raw, "title")
    eyebrow = _str(raw, "eyebrow")
    if not title or len(title) > OPENING_TITLE_HARD_TEXT_CHARS or len(eyebrow) > OPENING_TITLE_HARD_TEXT_CHARS:
        return None

    subtitle = _str(raw, "subtitle")
    start = OPENING_TITLE_HARDCODED_START_SEC
    dur = compute_kind_duration_sec("opening-title", 0)
    if start + dur > video_duration_sec - DIRECTOR_TAIL_GUARD_SEC:
        return None

    id_ = _card_id(raw, next_id)
    card = {"kind": "opening-title", "id": id_, "startSec": start, "title": title}
    if eyebrow:
        card["eyebrow"] = eyebrow
    if subtitle:
        card["subtitle"] = subtitle
    entry = {"id": id_, "kind": "opening-title", "startSec": start, "label": title}
    return card, entry


def parse_pull_quote_entry(raw: dict, video_duration_sec: float, occupied: list, whisper_words: list, next_id):
    quote = _str(raw, "quote") or _str(raw, "text")
    if not quote:
        return None
    planner_start = raw.get("startSec")
    if not isinstance(planner_start, (int, float)) or not math.isfinite(planner_start):
        return None

    snapped = find_word_timestamp(whisper_words, first_word_normalized(quote), planner_start, PULL_QUOTE_SNAP_WINDOW_SEC)
    if snapped is None:
        return None

    dur = compute_kind_duration_sec("pull-quote", 0)
    if not is_valid_start_sec(snapped, video_duration_sec, dur):
        return None
    if violates_gap(snapped, occupied):
        return None

    attribution = _str(raw, "attribution")
    date = _str(raw, "date")
    id_ = _card_id(raw, next_id)
    card = {"kind": "pull-quote", "id": id_, "startSec": snapped, "quote": quote}
    if attribution:
        card["attribution"] = attribution
    if date:
        card["date"] = date
    label = f'"{quote}" — {attribution}' if attribution else f'"{quote}"'
    entry = {"id": id_, "kind": "pull-quote", "startSec": snapped, "label": label}
    return card, entry


def parse_year_card_entry(raw: dict, video_duration_sec: float, occupied: list, next_id):
    def build(r):
        year = _str(r, "year") or _str(r, "figure")
        if not year:
            return None
        eyebrow = _str(r, "eyebrow")
        caption = _str(r, "caption")
        fields = {"year": year}
        if eyebrow:
            fields["eyebrow"] = eyebrow
        if caption:
            fields["caption"] = caption
        label = f"{year} · {caption}" if caption else year
        return fields, label
    return _place_heavy("year-card", raw, video_duration_sec, occupied, next_id, build)


# ============================================================================
# lib/director/prompts/english.ts + lib/director/prompts/index.ts
# ============================================================================
def _resolve_director_system_prompt(stat_density: str, script_type: str) -> str:
    glossary = card_glossary()
    kind_count = len(CARD_FAMILY)
    min_gap_sec = DIRECTOR_MIN_GAP_SEC
    moments_min_gap_sec = MOMENTS_MIN_GAP_SEC
    head_guard_sec = DIRECTOR_HEAD_GUARD_SEC
    tail_guard_sec = DIRECTOR_TAIL_GUARD_SEC
    is_listicle = script_type == "listicle"

    # Listicle scripts repurpose photo-title entirely: one per ranked item,
    # fired where the narrator names it, showing ONLY the item's name (never
    # the rank digit/ordinal) — never used for anything else in this mode, so
    # there's no ambiguity between a countdown callout and a generic beat.
    photo_title_genre_line = (
        "- listicle → photo-title is REPURPOSED as the list callout — see the LISTICLE MODE section below. "
        "Do not also use it for generic evocative words in this mode. Pair with big-stats where the script "
        "gives each item a number/stat, and photo-captions for quiet context between items."
        if is_listicle else
        "- listicle / tutorial / explainer → LOTS of big-stats where data is mentioned + photo-titles to pace it."
    )

    photo_title_content_rule = (
        "- photo-title → LISTICLE MODE is active (see below): \"word\" is ONLY the ranked item's name/subject "
        "(1-3 words, verbatim from the timestamped segments, within ±5 s of startSec — same HARD CONTRACT as "
        "section 4). NEVER the rank digit, NEVER \"Number\"/\"#N\"/the ordinal word itself. Optional \"descriptor\" "
        "(2-5 words) may add short framing, but never the rank. One per list item; nothing else becomes a "
        "photo-title in this mode."
        if is_listicle else
        "- photo-title → \"word\" (1-3 words; the FIRST word MUST be a verbatim token from the timestamped "
        "segments below, within ±5 s of your startSec — see the HARD CONTRACT in section 4) + optional "
        "\"descriptor\" (2-5 words, your own short framing — NOT another quote). Always renders big and "
        "CENTERED: the \"word\" is the loud thing on the frame, the descriptor a small caption underneath. "
        "For quieter, bottom-left context use photo-caption instead."
    )

    listicle_mode_section = (
        """
LISTICLE MODE — this script is a listicle/countdown. Photo-title is REPURPOSED:

The script names a series of ranked items ("Number 10, ...", "#3 ...", "First, ...", or any equivalent countdown/
enumeration phrasing, however much preamble comes before the list starts). For EVERY ranked item, place ONE
photo-title at the moment the narrator actually names that item — anchor it on the item's own name/subject
(the person, place, thing, or concept the rank is about), NOT on the rank word/digit itself. Example: the line
"Number one, Miller, changed everything" → photo-title "word" is "Miller", startSec near where "Miller" is
spoken — never "1" or "Number".

Do not place photo-title for anything else in this script — no generic evocative words, no charged verbs outside
the list. If a section of the script isn't part of the countdown (intro/outro/framing), skip photo-title there
entirely; use photo-caption or big-stat if that section still needs a beat.
"""
        if is_listicle else ""
    )

    return f"""You are the visual director for a documentary-style video. You plan WHEN and WHAT visual elements appear on screen so that the rendered video has variety, breathing room, and good pacing. You have {kind_count} element kinds to choose from. They split into two families.

HEAVY ELEMENTS (take over or anchor the frame — pick fewer, place deliberately):

1. "opening-title" — A ~6.5-second cinematic HEAVY title card shown ONCE at the very OPENING of the video. DOCUMENTARY SCRIPTS ONLY (dropped otherwise). It carries TWO text lines plus a byline: "eyebrow" on line 1, "title" on line 2, and a "subtitle" byline on one line below — a fuller dateline (place + period or a short framing tagline, ~3-7 words), NOT a bare year (e.g. eyebrow "A DOCUMENTARY", title "THE MOSQUITO", subtitle "Hatfield, England · 1943" or "Britain's wooden warplane"). BOTH "eyebrow" and "title" must be ≤ 15 characters each (HARD max 17 — if EITHER exceeds 17, the WHOLE card is dropped). Each line must be meaningful and together capture the whole video's feel. The card is server-pinned to the 4-second mark, so do NOT set "startSec" (it's ignored). Use AT MOST ONCE.

2. "pull-quote" — A ~6.5-second HEAVY full-frame card for a standout VERBATIM quotation the narrator reads aloud: a big italic "quote" with optional "attribution" (speaker) and optional "date". The server SNAPS this card to the moment the quote is actually spoken (it anchors on the FIRST word of your "quote" in the audio), so copy the quote VERBATIM and pick a "startSec" near where it's said — if the first word isn't found in the audio near your startSec, the card is DROPPED. Use sparingly (0-2 per video); when several lines qualify, pick the most profound. Covers the frame with its own dark branded background.

3. "year-card" — A ~6.5-second HEAVY spotlight on a pivotal YEAR or date: a giant "year" figure with an optional "eyebrow" and "caption", centered on a teal card. Use for a strong moment-in-time beat (a turning-point year the narrator emphasizes).

LIGHT ELEMENTS (transparent overlays — coexist with the underlying scene; place these GENEROUSLY):

4. "photo-title" — A ~5-second kinetic-type overlay: ONE strong word (or 2-3 short words) pulled VERBATIM from the line being spoken at that moment, with an optional 2-5 word descriptor underneath. Replaces the old "scene caption" approach. Use to punctuate evocative phrases, character names, place names, charged verbs. **HARD CONTRACT:** the FIRST word of "word" MUST appear as a real spoken token in the timestamped segments below within ±5 s of your "startSec". The server snaps your "startSec" to the actual audio time of that word. If the word is not found in the audio inside that ±5 s window, your photo-title is DROPPED — so don't paraphrase, don't translate, don't summarize. Copy the token directly from the timestamped segments and pick a "startSec" near its segment's time. A photo-title ALWAYS renders big and centered — it is the loud attention-grab. When you want quieter, script-aware context layered in without crowding the center of the frame, use a "photo-caption" (bottom-left) instead.

5. "photo-caption" — A ~5-second lightweight contextual caption overlay: ONE short on-screen line written in YOUR OWN words (a frame, location, or thematic note from your video understanding), rendered bottom-left as a small black box with white text. UNLIKE "photo-title", it is NOT snapped to a spoken word — there is no verbatim contract, so you are free to write your own framing. Use it to add quiet context that coexists with the scene (e.g. "A quiet turning point", "Somewhere near the front"). Keep it short — ideally ≤ ~8 words.

6. "big-stat" — A ~5.5-second big-figure callout for a number, percentage, date, dollar amount, or quantity that the narrator says out loud. Renders as a centered figure + optional direction arrow + a short ALL-CAPS label. Use whenever the script says a specific number that lands as a "fact." Examples: 11% increase, $4.2 billion, 1987, 3 in 5 households. **Snap behavior:** the server best-effort snaps "startSec" to the audio time of the matching digits in the whisper stream. When the figure is rendered as digits in the transcribed segments below ("11", "1987"), pick a "startSec" near that segment so the snap lands cleanly. When the narrator says the number as words ("eleven percent") and the transcript shows it that way, the snap will fall back to your "startSec" — pick it within ±2 s of the spoken figure.

STEP 0 — READ THE WHOLE SCRIPT FIRST

Before placing or writing ANY element, read the entire script end-to-end and form a holistic understanding of:
  - The full arc (opening hook → middle beats → close).
  - Every distinct topic, chapter, or section the video covers.
  - Specific numbers/dates/figures the narrator says out loud, anywhere in the script.
  - Strong evocative words/names worth photo-title treatment, anywhere in the script.
  - Moments where a short contextual caption (photo-caption) in your own words would add quiet framing.

Only after you have that whole-script mental model do you start emitting timeline entries.

STEP 1 — CLASSIFY THE SCRIPT

Pick exactly one "scriptType" from: "documentary", "listicle", "tutorial", "explainer", "essay", "narrative", "commentary", "other". Use "documentary" for history, biography, nature, true-crime, or any factual long-form storytelling (prefer it over "narrative" for that content). Also produce a short "suggestedTitle" (3-8 words).

STEP 2 — PICK COMPONENTS THAT FIT THE GENRE

WHEN TO USE EACH (quick reference — detailed contracts are in the numbered sections above):
{glossary}

Don't force every kind into every video. Match the toolkit to the script:

- documentary (history, biography, nature, true-crime, factual long-form) → opening-title once at the very start, photo-titles + photo-captions as the workhorse, big-stats for quantities and year-cards for pivotal years/dates the narrator emphasizes, pull-quotes sparingly.
{photo_title_genre_line}
- tutorial / explainer → LOTS of big-stats where data is mentioned + photo-titles to pace it.
- essay / commentary → photo-titles are the workhorse; photo-captions for quiet framing; big-stats only where real numbers appear.
- narrative (fiction / story-driven) → photo-titles are the workhorse; photo-captions to set scene/location context; big-stats for dates/figures the narrator says.

If a kind doesn't fit, omit it. Quality of fit > checking every box.
{listicle_mode_section}

STAT-DENSITY OVERRIDE (this script's stat density is: {stat_density}):

A pre-pass measured how many distinct numbers/dates/figures the narrator says per minute. This OVERRIDES the per-genre stat guidance above:

- "high" → the script is densely packed with stats (common for history including WW2/military, finance, sports, science). Treat it as a data-dense script REGARDLESS of scriptType. Do not throttle big-stats because the genre is "narrative" — go heavy. Place a big-stat for every distinct figure in keyFacts, soft cap of one every ~15s (instead of ~25s). Photo-captions are the relief valve so the center frame doesn't fight stat after stat — when stats are dense, lean harder on bottom-left photo-captions to carry context.
- "low" → keep big-stats rare; let photo-titles carry density.
- "normal" → follow the per-genre defaults above as written.

STEP 3 — DENSITY (HARD floor: ≥2 animations per minute)

**HARD FLOOR:** at least 2 animations per minute of video, heavy + light combined. So a 10-min video needs ≥20 elements, a 22-min video needs ≥44, a 50-min video needs ≥100. This is a floor, not a target — go above it. The point is to mask any AI-generated feel by keeping the frame visually engaged. Light elements (photo-title, big-stat) make this easy to hit; lean on them. Bottom-left photo-titles stack density without crowding center, so use them generously when the center variant would be too much.

LIGHT elements (place AT LEAST these many; go over freely):
- photo-title minimum: 2 every 60s (so ~20 in a 10-min video, ~100 in a 50-min video). Some photo-titles will get DROPPED by the snap check, so over-provision — propose more than the floor so the floor still holds after dropouts.
- big-stat: place one for EVERY specific number/percent/date the narrator says out loud, up to a soft cap of one every ~25s.

PLACEMENT RULES — ALL MUST HOLD:

- Minimum {min_gap_sec}-second gap between any two HEAVY elements.
- Minimum {min_gap_sec}-second gap from any LIGHT element to any HEAVY element.
- Minimum {moments_min_gap_sec}-second gap between two LIGHT elements (photo-title + big-stat) — they can sit closer together than heavy cards.
- Minimum {min_gap_sec}-second gap from any subscribe-button placement (provided to you below as occupied slots).
- No element in the first {head_guard_sec} seconds or the last {tail_guard_sec} seconds of the video.
- BIAS HEAVY ELEMENTS TOWARD THE BEGINNING. ~60-70% of heavy elements before the midpoint. Light elements can spread evenly across the whole video.
- LOCAL-AWARENESS RULE: every element must be tied to the part of the script it sits in. A photo-title is a verbatim word from the line being spoken right then. A big-stat's figure is a number the narrator is saying right then.

PER-KIND CONTENT RULES:

{photo_title_content_rule}

- photo-caption → "text" (a single short line, ≤ ~8 words, in YOUR OWN words — a frame/location/thematic note, NOT a verbatim quote). No snap contract; place it where the context fits the scene.

- big-stat → "figure" (the number EXACTLY as the narrator says it: "11%", "$4.2 billion", "1987", "3 in 5") + "label" (2-6 word ALL-CAPS-able phrase explaining what the figure represents) + optional "direction": "up" | "down" | "neutral" (omit / "neutral" for plain figures like dates; "up"/"down" only when the script frames the figure as a rise or fall).

- opening-title → "eyebrow" (line 1) + "title" (line 2) + "subtitle" (a fuller one-line byline: place + period or a short framing tagline, ~3-7 words — not a bare year; omit only if you truly have nothing). BOTH "eyebrow" and "title" must be ≤ 15 chars each (HARD max 17 — over 17 and the whole card is dropped). DOCUMENTARY scripts only, used once. Do NOT set "startSec" — the server pins it to the 4-second mark. Make each line meaningful and capture the whole video's feel.

- pull-quote → "quote" (the verbatim quotation, no surrounding quote marks — copied EXACTLY so the server can snap to where it's spoken) + optional "attribution" (the speaker, omit if unknown) + optional "date" (omit if none). Set "startSec" near where the quote is said. Use sparingly; pick the most profound line(s).

- year-card → "year" (the year/date as a string, e.g. "1945") + optional "eyebrow" + optional "caption". Use for a pivotal moment-in-time beat.

Return JSON shaped like:
{{
  "scriptType": "...",
  "suggestedTitle": "...",
  "timeline": [
    {{ "id": "v-03", "kind": "photo-title", "startSec": 52, "word": "Sunrise", "descriptor": "Before dawn" }},
    {{ "id": "v-04", "kind": "big-stat", "startSec": 68, "figure": "11%", "label": "Yield increase", "direction": "up" }},
    {{ "id": "v-09", "kind": "photo-caption", "startSec": 95, "text": "A quiet turning point" }}
  ]
}}

The timeline MUST be sorted by startSec ascending."""


_DIRECTOR_ENTRY_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "kind": {"type": "string", "enum": list(CARD_FAMILY.keys())},
        "startSec": {"type": "number"},
        "items": {"type": "array", "items": {"type": "string"}},
        "header": {"type": "string"},
        "word": {"type": "string"},
        "descriptor": {"type": "string"},
        "text": {"type": "string"},
        "figure": {"type": "string"},
        "label": {"type": "string"},
        "direction": {"type": "string"},
        "eyebrow": {"type": "string"},
        "title": {"type": "string"},
        "subtitle": {"type": "string"},
        "quote": {"type": "string"},
        "attribution": {"type": "string"},
        "date": {"type": "string"},
        "year": {"type": "string"},
        "caption": {"type": "string"},
    },
    "required": ["id", "kind", "startSec", "items", "header", "word", "descriptor", "text",
                  "figure", "label", "direction", "eyebrow", "title", "subtitle", "quote",
                  "attribution", "date", "year", "caption"],
    "additionalProperties": False,
}

DIRECTOR_SCHEMA = {
    "name": "director_plan",
    "schema": {
        "type": "object",
        "properties": {
            "scriptType": {"type": "string", "enum": sorted(VALID_SCRIPT_TYPES)},
            "suggestedTitle": {"type": "string"},
            "timeline": {"type": "array", "items": _DIRECTOR_ENTRY_SCHEMA},
        },
        "required": ["scriptType", "suggestedTitle", "timeline"],
        "additionalProperties": False,
    },
}

# Kinds the spine already owns — the Director is told not to emit them; this
# defensively drops any it still returns so they can't double-place.
_SPINE_OWNED = {"opening-title"}


def _dispatch_parser(kind: str, raw: dict, video_duration_sec: float, occupied_heavy: list,
                      occupied_moments: list, whisper_words: list, script_type: str,
                      placed: list, next_id):
    """Mirrors lib/director/parsers/index.ts's PARSERS registry — one call
    signature, each kind's genuinely-different needs cherry-picked inline."""
    if kind == "photo-title":
        return parse_photo_title_entry(raw, video_duration_sec, occupied_heavy, occupied_moments,
                                        whisper_words, next_id)
    if kind == "photo-caption":
        return parse_photo_caption_entry(raw, video_duration_sec, occupied_heavy, occupied_moments, next_id)
    if kind == "big-stat":
        return parse_big_stat_entry(raw, video_duration_sec, occupied_heavy, occupied_moments,
                                     placed, whisper_words, next_id)
    if kind == "opening-title":
        return parse_opening_title_entry(raw, video_duration_sec, script_type, placed, next_id)
    if kind == "pull-quote":
        return parse_pull_quote_entry(raw, video_duration_sec, occupied_heavy, whisper_words, next_id)
    if kind == "year-card":
        return parse_year_card_entry(raw, video_duration_sec, occupied_heavy, next_id)
    return None


def plan_director_timeline(script: str, whisper_words: list, video_duration_sec: float,
                            occupied_slots: list, understanding: dict) -> dict:
    """One GPT call (the Director) proposing a raw timeline, then deterministic
    per-kind parsing/placement (gap rules, snapping, drop-if-invalid) — ports
    lib/director/plan.ts's planDirectorTimeline()."""
    segments = group_words_into_segments(whisper_words)

    occupied_description = (
        "none" if not occupied_slots
        else ", ".join(f"{_js_round(s['startSec'])}s ({s['kind']})" for s in occupied_slots)
    )

    user_message = "\n".join([
        f"Video duration: {_js_round(video_duration_sec)} seconds (~{video_duration_sec / 60:.1f} min).",
        f"Occupied slots (keep ≥{DIRECTOR_MIN_GAP_SEC}s gap from each — these are pre-reserved "
        f"placements you must not clash with): {occupied_description}.",
        "",
        "Video understanding (THE BASIS for all your decisions — use this for arc, themes, "
        "header candidates, scriptType, and section structure; do NOT re-derive these from the raw script):",
        json.dumps(understanding, indent=2),
        "",
        f"Raw script (use ONLY for verbatim word lookups when picking photo-title \"word\" or "
        f"big-stat \"figure\" — the understanding above is canonical for arc/themes):\n{script}",
        (f"\n\nTimestamped segments from the audio transcription:\n{json.dumps(segments, indent=2)}"
         if segments else ""),
    ])

    system_prompt = _resolve_director_system_prompt(understanding["statDensity"], understanding["scriptType"])

    data = scene_engine._chat(
        [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}],
        DIRECTOR_SCHEMA,
        max_completion_tokens=16384,
    )

    script_type = data.get("scriptType") if data.get("scriptType") in VALID_SCRIPT_TYPES else "other"
    raw_entries = data.get("timeline") or []
    raw_entries = sorted(
        raw_entries,
        key=lambda e: e.get("startSec") if isinstance(e.get("startSec"), (int, float)) else float("inf"),
    )

    timeline = []
    cards = []
    occupied_heavy = [s["startSec"] for s in occupied_slots]
    occupied_moments = []
    counter = [0]

    def next_id() -> str:
        counter[0] += 1
        return f"v-{counter[0]:02d}"

    for raw in raw_entries:
        kind = raw.get("kind")
        if kind not in CARD_FAMILY or kind in _SPINE_OWNED:
            continue
        result = _dispatch_parser(kind, raw, video_duration_sec, occupied_heavy, occupied_moments,
                                   whisper_words, script_type, cards, next_id)
        if result is None:
            continue
        card, entry = result
        cards.append(card)
        timeline.append(entry)
        if CARD_FAMILY[kind] == "summary":
            occupied_heavy.append(entry["startSec"])
        else:
            occupied_moments.append(entry["startSec"])

    return {
        "cards": cards,
        "timeline": timeline,
        "scriptType": script_type,
        "suggestedTitle": data.get("suggestedTitle") or None,
    }


# ============================================================================
# lib/director/topup.ts
# ============================================================================
_MIN_ELEMENTS_PER_MIN = 2
_TOPUP_WORD_MAX_CHARS = 22
_TOPUP_TITLE_MAX_CHARS = 40
_TOPUP_SNAP_WINDOW_SEC = 5

TOPUP_REFINE_SCHEMA = {
    "name": "topup_refine",
    "schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}, "word": {"type": "string"}},
                    "required": ["id", "word"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    },
}


def _display_source(sc: dict) -> str:
    return (sc.get("visualContext") or "").strip()


def _trim_to_budget(s: str, max_chars: int) -> str:
    t = s.strip()
    if len(t) <= max_chars:
        return t
    cut = t[:max_chars]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > 0 else cut).strip()


def _pick_scenes_for_fill(scenes: list, video_duration_sec: float, existing_timeline: list,
                           occupied_heavy: list, occupied_moments: list) -> list:
    """Walk minute-by-minute; for each under-filled minute, pick scenes whose
    startSec lands in that window AND respect the gap rules."""
    tail_limit = video_duration_sec - DIRECTOR_TAIL_GUARD_SEC - PHOTO_CAPTION_DURATION_SEC
    total_minutes = math.ceil(video_duration_sec / 60)
    occupied_moments = list(occupied_moments)
    picked = []

    def violates_heavy(t):
        return any(abs(o - t) < DIRECTOR_MIN_GAP_SEC for o in occupied_heavy)

    def violates_moment(t):
        return any(abs(o - t) < MOMENTS_MIN_GAP_SEC for o in occupied_moments)

    sorted_scenes = sorted(scenes, key=lambda s: s["startSec"])

    for m in range(total_minutes):
        win_start = m * 60
        win_end = min((m + 1) * 60, video_duration_sec)
        in_window = (
            sum(1 for e in existing_timeline if win_start <= e["startSec"] < win_end)
            + sum(1 for p in picked if win_start <= p["startSec"] < win_end)
        )
        if in_window >= _MIN_ELEMENTS_PER_MIN:
            continue
        needed = _MIN_ELEMENTS_PER_MIN - in_window
        min_start = max(win_start, DIRECTOR_HEAD_GUARD_SEC)

        for sc in sorted_scenes:
            if needed <= 0:
                break
            if sc["startSec"] < min_start:
                continue
            if sc["startSec"] >= win_end:
                break
            if sc["startSec"] > tail_limit:
                break
            if not _display_source(sc):
                continue
            if any(p["sceneIndex"] == sc["sceneIndex"] for p in picked):
                continue
            if violates_heavy(sc["startSec"]):
                continue
            if violates_moment(sc["startSec"]):
                continue
            picked.append(sc)
            occupied_moments.append(sc["startSec"])
            needed -= 1

    return picked


def _pick_photo_title_slots(scenes: list, video_duration_sec: float, existing_timeline: list,
                             occupied_heavy: list, whisper_words: list) -> list:
    """photo-title is INTRUSIVE, so it needs >=45s clear on BOTH sides of
    anything already on the timeline — each accepted slot snaps the scene's
    first spoken word onto the real audio."""
    if not whisper_words:
        return []
    dur = compute_kind_duration_sec("photo-title", 0)
    occupied = [e["startSec"] for e in existing_timeline] + list(occupied_heavy)
    spacing = TOPUP_PHOTO_TITLE_MIN_SPACING_SEC

    def has_clearance(t):
        return not any(abs(o - t) < spacing for o in occupied)

    slots = []
    for sc in sorted(scenes, key=lambda s: s["startSec"]):
        anchor = (sc.get("anchorWord") or "").strip()
        if not anchor:
            continue
        snapped = find_word_timestamp(whisper_words, first_word_normalized(anchor), sc["startSec"], _TOPUP_SNAP_WINDOW_SEC)
        if snapped is None:
            continue
        if not is_valid_start_sec(snapped, video_duration_sec, dur):
            continue
        if not has_clearance(snapped):
            continue
        slots.append({"scene": sc, "startSec": snapped, "anchorWord": anchor})
        occupied.append(snapped)
    return slots


_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "in", "on", "at", "by",
    "to", "for", "with", "from", "into", "as", "is", "are", "was", "were",
    "be", "been", "being", "this", "that", "these", "those", "it", "its",
}


def _deterministic_refine(item: dict) -> dict:
    tokens = item["visualContext"].strip().split()
    content = [t for t in tokens if t.lower() not in _STOPWORDS]
    pick = content[:2] if content else tokens[:2]
    word = " ".join(pick)[:_TOPUP_WORD_MAX_CHARS]
    return {"id": item["id"], "word": word}


_REFINE_SYSTEM_PROMPT = f"""You take per-scene "visualContext" strings and rewrite each into a SHORT caption that renders bottom-left over the underlying scene. Each input is one short descriptive phrase (e.g. "1950s farm life with family involvement"). For each, return ONE short phrase (the "word" field).

HARD CONSTRAINTS:
- "word" MUST be ≤ {_TOPUP_WORD_MAX_CHARS} characters. The badge keeps it on a single line — anything longer would be silently truncated, which looks bad.
- 1-3 words ideally. Picky-noun + optional adjective. Strip every filler ("the", "with", "and", "a", "of", helper verbs).
- Stay faithful to the visualContext — don't invent details that aren't in it.
- Each scene's phrase must be DISTINCT from its neighbors. Read the FULL video understanding (provided) so you understand the arc and never repeat the same noun on consecutive scenes.
- Sentence case is fine; the renderer uppercases.

Return JSON: {{ "items": [{{ "id": "<input id>", "word": "..." }}, ...] }}
Each input id MUST appear exactly once."""


def _refine_visual_contexts(understanding: dict, inputs: list) -> list:
    if not inputs:
        return []
    understanding_for_prompt = {
        "subject": understanding.get("subject"),
        "toneNote": understanding.get("toneNote"),
        "themes": understanding.get("themes"),
        "keyEntities": understanding.get("keyEntities"),
        "sectionBeats": [{"headline": s["headline"], "summary": s["summary"]}
                         for s in understanding.get("sectionBeats", [])],
    }
    user_message = "\n".join([
        "Video understanding (use this for arc + tone + theme context, and to avoid repeating "
        "the same noun across adjacent scenes):",
        json.dumps(understanding_for_prompt, indent=2),
        "",
        f"Scenes to refine:\n{json.dumps(inputs, indent=2)}",
    ])
    try:
        data = scene_engine._chat(
            [{"role": "system", "content": _REFINE_SYSTEM_PROMPT}, {"role": "user", "content": user_message}],
            TOPUP_REFINE_SCHEMA,
            max_completion_tokens=4096,
        )
    except Exception as e:  # noqa: BLE001 — deterministic fallback covers this
        print(f"  director: topup refine pass failed ({e}); using deterministic fallback", flush=True)
        return [_deterministic_refine(i) for i in inputs]

    by_id = {}
    for r in data.get("items", []):
        id_ = r.get("id")
        word = (r.get("word") or "").strip()
        if id_ and word:
            by_id[id_] = {"id": id_, "word": word[:_TOPUP_WORD_MAX_CHARS]}

    return [by_id.get(i["id"]) or _deterministic_refine(i) for i in inputs]


def build_topup_moments(understanding: dict, scenes: list, video_duration_sec: float,
                         existing_timeline: list, occupied_heavy: list, occupied_moments: list,
                         next_id, whisper_words: list) -> dict:
    """Server-side density top-up: the Director routinely undershoots the
    per-minute floor, so this deterministically fills the gaps from each
    scene's visual_context — intrusive photo-titles first (need the most
    room), then a caption floor for whatever's left underfilled."""
    empty = {"moments": [], "entries": [], "refinedCount": 0, "filledCount": 0, "titledCount": 0}

    title_slots = _pick_photo_title_slots(scenes, video_duration_sec, existing_timeline,
                                           occupied_heavy, whisper_words or [])
    titled_scene_idx = {s["scene"]["sceneIndex"] for s in title_slots}
    title_times = [s["startSec"] for s in title_slots]
    spacing = TOPUP_PHOTO_TITLE_MIN_SPACING_SEC

    def in_breathing_zone(t):
        return any(abs(tt - t) < spacing for tt in title_times)

    synthetic_entries = list(existing_timeline) + [
        {"id": f"topup-title-{s['scene']['sceneIndex']}", "kind": "photo-title", "startSec": s["startSec"], "label": ""}
        for s in title_slots
    ]
    raw_captions = _pick_scenes_for_fill(scenes, video_duration_sec, synthetic_entries,
                                          occupied_heavy, occupied_moments + title_times)
    captions = [c for c in raw_captions
                if c["sceneIndex"] not in titled_scene_idx and not in_breathing_zone(c["startSec"])]

    if not title_slots and not captions:
        return empty

    caption_by_id = {}
    refine_inputs = []

    def queue_text(id_, sc):
        vc = (sc.get("visualContext") or "").strip()
        if vc:
            refine_inputs.append({"id": id_, "visualContext": vc})

    for c in captions:
        queue_text(f"s-{c['sceneIndex']}", c)
    for s in title_slots:
        queue_text(f"t-{s['scene']['sceneIndex']}", s["scene"])

    items = _refine_visual_contexts(understanding, refine_inputs)
    for it in items:
        caption_by_id[it["id"]] = it["word"]

    moments = []
    entries = []
    titled_count = 0

    for s in title_slots:
        descriptor = caption_by_id.get(f"t-{s['scene']['sceneIndex']}")
        id_ = next_id()
        desc = _trim_to_budget(descriptor, _TOPUP_TITLE_MAX_CHARS) if descriptor else None
        card = {"kind": "photo-title", "id": id_, "startSec": s["startSec"], "word": s["anchorWord"]}
        if desc:
            card["descriptor"] = desc
        moments.append(card)
        entries.append({"id": id_, "kind": "photo-title", "startSec": s["startSec"],
                        "label": f"{s['anchorWord']} — {desc}" if desc else s["anchorWord"]})
        titled_count += 1

    for c in captions:
        text = caption_by_id.get(f"s-{c['sceneIndex']}")
        if not text:
            continue
        id_ = next_id()
        moments.append({"kind": "photo-caption", "id": id_, "startSec": c["startSec"], "text": text})
        entries.append({"id": id_, "kind": "photo-caption", "startSec": c["startSec"], "label": text})

    return {"moments": moments, "entries": entries, "refinedCount": len(items),
            "filledCount": len(moments), "titledCount": titled_count}


# ============================================================================
# lib/alignment/index.ts (alignWithDiagnostics) — public entrypoint
# ============================================================================
def plan_cards(script: str, video_title: str, scenes: list[dict], whisper_words: list[dict],
                total_duration: float) -> list[dict]:
    """Four-pass card-planning pipeline, in the exact call order
    alignWithDiagnostics() uses: understand_script() -> build_spine() ->
    plan_director_timeline() (+ its per-kind parsers) -> build_topup_moments().
    Returns every card flattened into one list, each dict shaped like a
    PlacedCard variant (camelCase keys) ready for the Remotion/React renderer.

    `scenes` is this pipeline's own scene shape (scene_number, script_snippet,
    image_prompt, start, end, duration_seconds, ...) from
    scene_engine.align_scene_durations() — not the reference's Scene type.
    """
    print("  director: understand_script()...", flush=True)
    understanding = understand_script(script, total_duration)
    print(f"  director: {understanding['scriptType']} — {len(understanding['sectionBeats'])} beats, "
          f"statDensity={understanding['statDensity']}", flush=True)

    print("  director: build_spine()...", flush=True)
    spine_cards = build_spine(understanding, scenes, whisper_words, total_duration, video_title)
    print(f"  director: spine -> {len(spine_cards)} card(s)", flush=True)

    # The spine's own cards are the Director's occupied slots — same role the
    # reference's pre-reserved subscribe placements + spine cards play together
    # (this pipeline has no subscribe overlay, so spine cards are the whole set).
    occupied_slots = [
        {"id": c["id"], "kind": c["kind"], "startSec": c["startSec"], "label": f"spine {c['kind']}"}
        for c in spine_cards
    ]

    print("  director: plan_director_timeline()...", flush=True)
    plan_result = plan_director_timeline(script, whisper_words, total_duration, occupied_slots, understanding)
    print(f"  director: plan -> {len(plan_result['cards'])} card(s) "
          f"(scriptType={plan_result['scriptType']})", flush=True)

    scene_contexts = []
    for i, s in enumerate(scenes):
        vc = (s.get("image_prompt") or "").strip()
        if not vc:
            continue
        snippet = (s.get("script_snippet") or "").strip()
        scene_contexts.append({
            "sceneIndex": i,
            "startSec": s["start"],
            "visualContext": vc,
            "anchorWord": snippet.split()[0] if snippet else None,
        })

    occupied_heavy = [s["startSec"] for s in occupied_slots] + [
        e["startSec"] for e in plan_result["timeline"] if CARD_FAMILY.get(e["kind"]) == "summary"
    ]
    occupied_moments = [
        e["startSec"] for e in plan_result["timeline"] if CARD_FAMILY.get(e["kind"]) == "moment"
    ]

    topup_counter = [1000]

    def topup_next_id() -> str:
        topup_counter[0] += 1
        return f"t-{topup_counter[0]}"

    print("  director: build_topup_moments()...", flush=True)
    topup = build_topup_moments(understanding, scene_contexts, total_duration, plan_result["timeline"],
                                occupied_heavy, occupied_moments, topup_next_id, whisper_words)
    print(f"  director: topup -> {topup['filledCount']} moment(s) "
          f"({topup['titledCount']} photo-title, {topup['filledCount'] - topup['titledCount']} caption)",
          flush=True)

    all_cards = spine_cards + plan_result["cards"] + topup["moments"]
    kinds = {}
    for c in all_cards:
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
    print(f"  director: {len(all_cards)} total card(s) — "
          + " ".join(f"{k}x{n}" for k, n in kinds.items()), flush=True)
    return all_cards
