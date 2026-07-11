"""Script<->audio DTW aligner (pure stdlib port of the TypeScript sync stack).

Ported from helpers/ui/remotion/remotion-test-2:
  lib/utils/normalize.ts      -> normalize_text / normalize_token
  lib/utils/dtw-global.ts     -> _align_script_to_whisper (global edit-distance DTW)
  lib/sync/matcher.ts         -> _match_scenes_to_whisper
  lib/sync/estimator.ts       -> _estimate_unmatched_timings
  lib/sync/timeline.ts        -> _build_and_snap_timeline
  lib/sync/sanity.ts          -> _sanitize_durations
  lib/sync/index.ts           -> align (public entry, seconds in/out)
  lib/sync/types.ts           -> MIN_DURATION_MS, MATCH_RATIO_FLOOR

(The sleep-stories tree has NO aligner of its own — only node_modules — so
remotion-test-2 is the sole/canonical source.)

Maps Whisper word-timestamps onto verbatim scene snippets to produce a
contiguous set of hard-cut points for the video compiler.

Public API:
  normalize_token(w: str) -> str
  align(whisper_words, snippets, total_duration) -> list[dict]

No third-party deps, no network.
"""

from __future__ import annotations

import re

# ---- constants (lib/sync/types.ts) ------------------------------------------
MIN_DURATION_MS = 500
MATCH_RATIO_FLOOR = 0.6

# ---- DTW costs (lib/utils/dtw-global.ts) ------------------------------------
_DIAG, _UP, _LEFT = 0, 1, 2
_FILLER_WORDS = frozenset(("uh", "um", "hmm", "ah", "mhm"))
_MISMATCH_COST = 10
_DELETION_COST = 5
_INSERTION_COST = 5
_FILLER_INSERTION_COST = 1


# =============================================================================
# normalize.ts
# =============================================================================
_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 1_000_000, "billion": 1_000_000_000}
_ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
    "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11,
    "twelfth": 12, "thirteenth": 13, "fourteenth": 14, "fifteenth": 15,
    "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19,
    "twentieth": 20, "thirtieth": 30, "fortieth": 40, "fiftieth": 50,
    "sixtieth": 60, "seventieth": 70, "eightieth": 80, "ninetieth": 90,
}

# JS \w is ASCII-only ([A-Za-z0-9_]); use re.ASCII so the port matches exactly.
_A = re.ASCII
_CORE_LEAD = re.compile(r"^[^\w]+", _A)
_CORE_TRAIL = re.compile(r"[^\w]+$", _A)
_ENDS_RUN = re.compile(r"[,.;:!?)]$")
_ORDINAL_DIGIT = re.compile(r"^(\d+)(st|nd|rd|th)$", re.IGNORECASE)
_THOUSANDS_SEP = re.compile(r"(\d),(\d)")
_WS = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^\w\s']", _A)
_EDGE_APOS = re.compile(r"(?<!\w)'|'(?!\w)", _A)


def _core(token: str) -> str:
    return _CORE_TRAIL.sub("", _CORE_LEAD.sub("", token))


# Atom is a tuple: ("n", value) | ("s", value) | ("and", None)
def _classify(word: str):
    if word in _UNITS:
        return ("n", _UNITS[word])
    if word in _TENS:
        return ("n", _TENS[word])
    if word in _SCALES:
        return ("s", _SCALES[word])
    if word in _ORDINALS:
        return ("n", _ORDINALS[word])
    if word == "and":
        return ("and", None)
    if "-" in word:
        parts = word.split("-")
        hi, lo = parts[0], (parts[1] if len(parts) > 1 else "")
        if hi and lo and hi in _TENS:
            if lo in _UNITS:
                return ("n", _TENS[hi] + _UNITS[lo])
            if lo in _ORDINALS and _ORDINALS[lo] < 10:
                return ("n", _TENS[hi] + _ORDINALS[lo])
    return None


def _parse_one_number(atoms, start):
    i = start
    current = atoms[i][1]
    i += 1

    # Year-style concatenation: "nineteen forty-five" -> 1945.
    if i < len(atoms) and atoms[i][0] == "n":
        g2 = atoms[i][1]
        return current * 100 + g2, i + 1

    # Standard cardinal accumulation.
    total = 0
    while i < len(atoms):
        a = atoms[i]
        if a[0] == "and":
            if i + 1 < len(atoms) and atoms[i + 1][0] == "n":
                i += 1
                continue
            break
        if a[0] == "s":
            if a[1] == 100:
                current = (1 if current == 0 else current) * 100
            else:
                total += (1 if current == 0 else current) * a[1]
                current = 0
            i += 1
            continue
        # a[0] == "n"
        current += a[1]
        i += 1
    return total + current, i


def _parse_run(atoms):
    nums = []
    i = 0
    while i < len(atoms):
        if atoms[i][0] == "and":
            i += 1
            continue
        if atoms[i][0] == "s":
            nums.append(str(atoms[i][1]))
            i += 1
            continue
        v, nxt = _parse_one_number(atoms, i)
        nums.append(str(v))
        i = nxt
    return nums


def _ends_run(raw_token: str) -> bool:
    return bool(_ENDS_RUN.search(raw_token))


def _preprocess(text: str) -> str:
    lower = _THOUSANDS_SEP.sub(r"\1\2", text.lower())
    tokens = [t for t in _WS.split(lower) if t]
    out = []

    i = 0
    n = len(tokens)
    while i < n:
        atom = _classify(_core(tokens[i]))
        if atom and atom[0] != "and":
            run = []
            j = i
            while j < n:
                a = _classify(_core(tokens[j]))
                if a and a[0] != "and":
                    run.append(a)
                    j += 1
                    if _ends_run(tokens[j - 1]):
                        break
                    continue
                if a and a[0] == "and":
                    nxt = _classify(_core(tokens[j + 1])) if j + 1 < n else None
                    if nxt and nxt[0] != "and":
                        run.append(a)
                        j += 1
                        continue
                break
            for num in _parse_run(run):
                out.append(num)
            i = j
        else:
            c = _core(tokens[i])
            m = _ORDINAL_DIGIT.match(c)
            out.append(m.group(1) if m else tokens[i])
            i += 1

    return " ".join(out)


def normalize_text(text: str) -> str:
    """Full normalize pipeline (matches normalize.ts `normalizeText`)."""
    s = _preprocess(text)
    s = _NON_WORD.sub(" ", s)
    s = _EDGE_APOS.sub("", s)
    s = _WS.sub(" ", s)
    return s.strip()


def normalize_token(w: str) -> str:
    """Normalize a single word (per-word use of normalizeText, as dtw-global does)."""
    return normalize_text(w)


def _tokenize(text: str):
    return [t for t in _WS.split(normalize_text(text)) if t]


def _word_count(text: str) -> int:
    return len([w for w in _WS.split(normalize_text(text)) if len(w) > 0])


# =============================================================================
# dtw-global.ts  — global edit-distance DTW + per-scene slice
# =============================================================================
def _align_script_to_whisper(scene_texts, whisper_words):
    """Returns list of dicts:
    {whisper_start_idx, whisper_end_idx, match_ratio, matched}
    """
    scene_count = len(scene_texts)

    script_tokens = []
    scene_ranges = []
    for s in range(scene_count):
        start = len(script_tokens)
        script_tokens.extend(_tokenize(scene_texts[s]))
        scene_ranges.append((start, len(script_tokens)))

    whisper_tokens = [normalize_text(w["word"]) for w in whisper_words]
    M = len(script_tokens)
    N = len(whisper_tokens)

    def unmatched():
        return [
            {"whisper_start_idx": None, "whisper_end_idx": None,
             "match_ratio": 0.0, "matched": False}
            for _ in scene_texts
        ]

    if M == 0 or N == 0:
        return unmatched()

    # Two rolling cost rows + full Int8-equivalent traceback matrix.
    prev = [0.0] * (N + 1)          # free start: leading whisper words free
    cur = [0.0] * (N + 1)
    row_len = N + 1
    T = bytearray((M + 1) * row_len)  # 0=DIAG (also default),1=UP,2=LEFT

    for i in range(1, M + 1):
        base = i * row_len
        cur[0] = prev[0] + _DELETION_COST
        T[base] = _UP
        si = script_tokens[i - 1]
        for j in range(1, N + 1):
            wj = whisper_tokens[j - 1]
            match_cost = 0 if si == wj else _MISMATCH_COST
            insertion_cost = (
                _FILLER_INSERTION_COST if wj in _FILLER_WORDS else _INSERTION_COST
            )
            diag = prev[j - 1] + match_cost
            up = prev[j] + _DELETION_COST
            left = cur[j - 1] + insertion_cost

            if diag <= up and diag <= left:
                cur[j] = diag
                T[base + j] = _DIAG
            elif up <= left:
                cur[j] = up
                T[base + j] = _UP
            else:
                cur[j] = left
                T[base + j] = _LEFT
        prev, cur = cur, prev

    # `prev` now holds cost row M (free end): pick min-cost column.
    best_j = 1
    best_cost = float("inf")
    for j in range(1, N + 1):
        if prev[j] < best_cost:
            best_cost = prev[j]
            best_j = j

    # Traceback.
    script_to_whisper = [-1] * M
    i, j = M, best_j
    total_exact = 0
    while i > 0:
        d = T[i * row_len + j]
        if d == _DIAG:
            script_to_whisper[i - 1] = j - 1
            if script_tokens[i - 1] == whisper_tokens[j - 1]:
                total_exact += 1
            i -= 1
            j -= 1
        elif d == _UP:
            i -= 1
        else:
            j -= 1

    # Per-scene slicing.
    out = []
    for (a, b) in scene_ranges:
        if b <= a:
            out.append({"whisper_start_idx": None, "whisper_end_idx": None,
                        "match_ratio": 0.0, "matched": False})
            continue
        first_mapped = None
        last_mapped = None
        exact = 0
        for k in range(a, b):
            w = script_to_whisper[k]
            if w >= 0:
                if first_mapped is None:
                    first_mapped = w
                last_mapped = w
                if script_tokens[k] == whisper_tokens[w]:
                    exact += 1
        matched = first_mapped is not None and last_mapped is not None
        out.append({
            "whisper_start_idx": first_mapped,
            "whisper_end_idx": last_mapped,
            "match_ratio": exact / (b - a),
            "matched": matched,
        })
    return out


# =============================================================================
# matcher.ts
# =============================================================================
def _match_scenes_to_whisper(scenes, all_whisper_words, warnings):
    alignments = _align_script_to_whisper(
        [s["verbatim_text"] for s in scenes], all_whisper_words
    )
    results = []
    for idx, scene in enumerate(scenes):
        a = alignments[idx]
        if a["matched"] and a["whisper_start_idx"] is not None and a["whisper_end_idx"] is not None:
            results.append({
                "scene_number": scene["scene_number"],
                "verbatim_text": scene["verbatim_text"],
                "audio_start_ms": all_whisper_words[a["whisper_start_idx"]]["start"] * 1000,
                "audio_end_ms": all_whisper_words[a["whisper_end_idx"]]["end"] * 1000,
                "matched": True,
                "dtw_match_ratio": a["match_ratio"],
                "cursor_start": a["whisper_start_idx"],
                "cursor_end": a["whisper_end_idx"] + 1,
            })
        else:
            warnings.append(
                f"Scene {scene['scene_number']}: no whisper words mapped, using estimated timing"
            )
            results.append({
                "scene_number": scene["scene_number"],
                "verbatim_text": scene["verbatim_text"],
                "audio_start_ms": 0,
                "audio_end_ms": 0,
                "matched": False,
                "dtw_match_ratio": None,
                "cursor_start": 0,
                "cursor_end": 0,
            })
    return results


# =============================================================================
# estimator.ts — fill unmatched blocks proportional to word count
# =============================================================================
def _estimate_unmatched_timings(results, total_duration_ms):
    i = 0
    n = len(results)
    while i < n:
        if results[i]["matched"]:
            i += 1
            continue
        block_start = i
        while i < n and not results[i]["matched"]:
            i += 1
        block_end = i

        prev_end = results[block_start - 1]["audio_end_ms"] if block_start > 0 else 0
        next_start = results[block_end]["audio_start_ms"] if block_end < n else total_duration_ms

        available_ms = next_start - prev_end
        word_counts = [_word_count(results[j]["verbatim_text"])
                       for j in range(block_start, block_end)]
        total_words = sum(word_counts)
        block_count = block_end - block_start

        cursor = prev_end
        for j in range(block_start, block_end):
            if total_words > 0:
                proportion = word_counts[j - block_start] / total_words
            else:
                proportion = 1 / block_count
            duration = round(available_ms * proportion)
            results[j]["audio_start_ms"] = cursor
            cursor += duration
            results[j]["audio_end_ms"] = cursor


# =============================================================================
# timeline.ts — snap to contiguous hard cuts
# =============================================================================
def _build_and_snap_timeline(results, total_duration_ms):
    entries = [{
        "scene_number": r["scene_number"],
        "verbatim_text": r["verbatim_text"],
        "audio_start_ms": round(r["audio_start_ms"]),
        "audio_end_ms": round(r["audio_end_ms"]),
        "matched": r["matched"],
        "dtw_match_ratio": r.get("dtw_match_ratio"),
    } for r in results]

    if entries:
        entries[0]["audio_start_ms"] = 0
        entries[-1]["audio_end_ms"] = total_duration_ms
        for j in range(len(entries) - 1):
            entries[j]["audio_end_ms"] = entries[j + 1]["audio_start_ms"]

    return entries


# =============================================================================
# sanity.ts — flag scenes >4x their word-share AND >10s; redistribute by words
# =============================================================================
def _sanitize_durations(entries, total_duration_ms, warnings):
    if not entries:
        return

    word_counts = [_word_count(e["verbatim_text"]) for e in entries]
    total_words = sum(word_counts)
    if total_words == 0:
        return

    offending = []
    for i, e in enumerate(entries):
        expected_ms = total_duration_ms * (word_counts[i] / total_words)
        duration_ms = e["audio_end_ms"] - e["audio_start_ms"]
        if duration_ms > expected_ms * 4 and duration_ms > 10_000:
            offending.append(i)

    if not offending:
        return

    warnings.append(
        "Sanity check triggered (offending scenes: "
        + ", ".join(str(entries[i]["scene_number"]) for i in offending)
        + "), redistributing by word count"
    )

    zero_word_count = sum(1 for c in word_counts if c == 0)
    reserved_ms = zero_word_count * MIN_DURATION_MS
    distributable_ms = total_duration_ms - reserved_ms

    cursor = 0
    for i, e in enumerate(entries):
        if word_counts[i] == 0:
            duration = MIN_DURATION_MS
        else:
            duration = round(distributable_ms * (word_counts[i] / total_words))
        e["audio_start_ms"] = cursor
        cursor += duration
        e["audio_end_ms"] = cursor
    entries[-1]["audio_end_ms"] = total_duration_ms


# =============================================================================
# Guarantee pass (NOT in TS): enforce MIN_DURATION + monotonicity.
# The TS timeline only guarantees contiguity/endpoints; a matched scene can
# still land <500ms or non-monotonic if Whisper timings overlap. Since our
# public contract requires every cut >= MIN_DURATION and monotonic, we clamp
# the shared boundary points as a final, idempotent safety net (a no-op when
# the faithful timeline already satisfies the constraints).
# =============================================================================
def _enforce_min_and_monotonic(entries, total_duration_ms):
    if not entries:
        return
    n = len(entries)
    # Contiguous -> n+1 boundaries. b[0]=0, b[i]=start[i], b[n]=total.
    b = [0] + [entries[i]["audio_start_ms"] for i in range(1, n)] + [total_duration_ms]
    b[0] = 0
    b[n] = total_duration_ms

    # Forward: push each boundary right enough to clear MIN from the previous.
    for i in range(1, n):
        if b[i] < b[i - 1] + MIN_DURATION_MS:
            b[i] = b[i - 1] + MIN_DURATION_MS
    # Backward: pull boundaries left so the final scene keeps its MIN gap
    # (only reachable when total >= n*MIN; realistic durations satisfy this).
    for i in range(n - 1, 0, -1):
        if b[i] > b[i + 1] - MIN_DURATION_MS:
            b[i] = b[i + 1] - MIN_DURATION_MS

    for i in range(n):
        entries[i]["audio_start_ms"] = b[i]
        entries[i]["audio_end_ms"] = b[i + 1]


# =============================================================================
# Public entry (index.ts `synchronize`), seconds in / seconds out.
# =============================================================================
def align(whisper_words, snippets, total_duration):
    """Map Whisper word-timestamps onto verbatim scene snippets.

    whisper_words: [{"word": str, "start": float_sec, "end": float_sec}, ...]
    snippets:      verbatim scene texts, in order
    total_duration: total audio length in seconds

    Returns per-snippet dicts:
      {"scene_number", "start" (sec), "end" (sec), "matched", "match_ratio"}

    Guarantees: contiguous (out[i].end == out[i+1].start), out[0].start == 0.0,
    out[-1].end == total_duration, monotonic non-decreasing, every duration
    >= MIN_DURATION_MS/1000.
    """
    total_duration_ms = total_duration * 1000
    scenes = [{"scene_number": i + 1, "verbatim_text": t} for i, t in enumerate(snippets)]
    warnings = []

    results = _match_scenes_to_whisper(scenes, whisper_words, warnings)
    _estimate_unmatched_timings(results, total_duration_ms)
    entries = _build_and_snap_timeline(results, total_duration_ms)
    _sanitize_durations(entries, total_duration_ms, warnings)
    _enforce_min_and_monotonic(entries, total_duration_ms)

    out = []
    for e in entries:
        out.append({
            "scene_number": e["scene_number"],
            "start": e["audio_start_ms"] / 1000.0,
            "end": e["audio_end_ms"] / 1000.0,
            "matched": e["matched"],
            "match_ratio": e["dtw_match_ratio"] if e["dtw_match_ratio"] is not None else 0.0,
        })
    return out


# =============================================================================
# Self-test (no network)
# =============================================================================
if __name__ == "__main__":
    CADENCE = 0.4  # seconds per word

    def build_whisper(words, cadence=CADENCE):
        ww = []
        t = 0.0
        for w in words:
            ww.append({"word": w, "start": round(t, 4), "end": round(t + cadence, 4)})
            t += cadence
        return ww

    paragraph = (
        "the detective walked into the cold dark room and switched on the light "
        "she found the old case file buried under a pile of dusty forgotten papers "
        "every page told a story that no one had ever bothered to read again "
        "the truth had been waiting quietly in that room for nearly twenty years"
    )
    words = paragraph.split()
    n_words = len(words)
    whisper = build_whisper(words)
    total = round(n_words * CADENCE, 4)

    # Tile verbatim into 5 snippets.
    def tile(words_list, parts):
        size = len(words_list) // parts
        snips = []
        idx = 0
        for p in range(parts):
            end = len(words_list) if p == parts - 1 else idx + size
            snips.append(" ".join(words_list[idx:end]))
            idx = end
        return snips

    snippets = tile(words, 5)
    assert " ".join(" ".join(s.split()) for s in snippets) == " ".join(words)

    out = align(whisper, snippets, total)

    def check(out, total, label):
        assert len(out) == 5, f"{label}: expected 5, got {len(out)}"
        assert abs(out[0]["start"] - 0.0) < 1e-9, f"{label}: first start != 0"
        assert abs(out[-1]["end"] - total) < 1e-6, f"{label}: last end != total"
        for i in range(len(out) - 1):
            assert abs(out[i]["end"] - out[i + 1]["start"]) < 1e-6, f"{label}: gap at {i}"
        prev = -1.0
        for o in out:
            assert o["start"] >= prev - 1e-9, f"{label}: start not monotonic"
            assert o["end"] >= o["start"] - 1e-9, f"{label}: end<start"
            prev = o["start"]
            dur = o["end"] - o["start"]
            assert dur >= (MIN_DURATION_MS / 1000.0) - 1e-6, f"{label}: dur {dur} < min"

    # --- Test 1: all-verbatim tiling ---
    check(out, total, "verbatim")

    # Middle scene (index 2) true start = first word index of snippet 3.
    words_before_mid = len(snippets[0].split()) + len(snippets[1].split())
    true_mid_start = words_before_mid * CADENCE
    got_mid_start = out[2]["start"]
    assert abs(got_mid_start - true_mid_start) <= 1.0, (
        f"middle start {got_mid_start} not within 1s of {true_mid_start}"
    )
    assert all(o["matched"] for o in out), "expected all scenes matched in verbatim test"

    print("ok  verbatim: len=5, endpoints, contiguous, monotonic, >=0.5s all hold")
    print(f"ok  middle scene start {got_mid_start:.2f}s within 1s of true {true_mid_start:.2f}s")
    print(f"ok  all 5 scenes matched; total={total:.1f}s")

    # --- Test 2: audio actually OMITS the middle scene -> it can't match, so
    # the estimator must fill it. (A same-length paraphrase would still map
    # diagonally under the free-start/free-end DTW — matched == any token
    # mapped, and equal-cost ties resolve to DIAG — which is faithful TS
    # behavior; the only way a scene goes unmatched is when the audio lacks it.)
    kept_words = (snippets[0] + " " + snippets[1] + " "
                  + snippets[3] + " " + snippets[4]).split()
    whisper2 = build_whisper(kept_words)
    total2 = round(len(kept_words) * CADENCE, 4)
    snippets2 = list(snippets)  # still all 5 verbatim scenes; scene 3 absent from audio
    snippets2[2] = "meanwhile a completely unrelated sentence about arctic penguins sledding downhill"
    out2 = align(whisper2, snippets2, total2)
    check(out2, total2, "estimator")
    assert not out2[2]["matched"], "scene missing from audio should NOT match"
    assert out2[0]["matched"] and out2[1]["matched"], "neighbours should match"
    filled_dur = out2[2]["end"] - out2[2]["start"]
    assert filled_dur >= MIN_DURATION_MS / 1000.0 - 1e-6
    print(f"ok  estimator: scene 3 unmatched, filled {filled_dur:.2f}s contiguously between matched neighbours")
    print("ok  estimator: len=5, endpoints, contiguous, monotonic, >=0.5s all hold")

    # --- Test 3: normalize spot-checks (number collapsing) ---
    assert normalize_token("Nineteen") == "19"
    assert normalize_text("nineteen forty-five") == "1945"
    assert normalize_text("one hundred and twenty-two") == "122"
    assert normalize_text("three thousand eight hundred") == "3800"
    assert normalize_text("4th") == "4"
    assert normalize_text("Hello, WORLD!") == "hello world"
    assert normalize_text("don't") == "don't"
    print("ok  normalize: number collapsing + punctuation strip verified")

    print("ALL OK")
