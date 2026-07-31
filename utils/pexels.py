"""Pexels photo/video search, ported from homestead's TS Pexels proxy routes
(app/api/pexels/image-search/route.ts, app/api/pexels/search/route.ts) and its
lib/pexels-normalize.ts, to plain urllib for this repo's production-review UI
(attach a Pexels still or clip to a scene instead of the AI-generated image).

PEXELS_API_KEY comes from the root .env via utils/env.py.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

import env as _e

PEXELS_IMAGE_SEARCH_URL = "https://api.pexels.com/v1/search"
PEXELS_VIDEO_SEARCH_URL = "https://api.pexels.com/videos/search"

_TARGET_WIDTH = 1920
_TARGET_HEIGHT = 1080


def _get(url: str, params: dict) -> dict:
    api_key = _e.require("PEXELS_API_KEY")
    full_url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(full_url, headers={
        "Authorization": api_key,
        "User-Agent": "Mozilla/5.0 (compatible; bible-well-pipeline/1.0)",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"pexels {url} {e.code}: {e.read().decode()[:500]}")


def _normalize_photo(photo: dict) -> dict:
    src = photo.get("src", {})
    return {
        "id": photo["id"],
        "url": src.get("large2x") or src.get("original") or src.get("large"),
        "preview_url": src.get("large") or src.get("medium"),
        "thumbnail_url": src.get("medium") or src.get("small"),
        "width": photo.get("width"),
        "height": photo.get("height"),
        "source_url": photo.get("url"),
        "photographer": photo.get("photographer") or "",
        "photographer_url": photo.get("photographer_url") or "",
        "alt": photo.get("alt") or "",
    }


def _usable_mp4s(files: list[dict]) -> list[dict]:
    return [f for f in files if f.get("file_type") == "video/mp4" and f.get("link")
            and f.get("width") and f.get("height")]


def _pick_best_file(files: list[dict]) -> dict | None:
    mp4s = _usable_mp4s(files)
    if not mp4s:
        return None
    target_area = _TARGET_WIDTH * _TARGET_HEIGHT
    best = mp4s[0]
    best_score = float("inf")
    for f in mp4s:
        area = f["width"] * f["height"]
        score = abs(area - target_area)
        is_hd = f["width"] >= _TARGET_WIDTH
        best_is_hd = best["width"] >= _TARGET_WIDTH
        if is_hd and not best_is_hd:
            best, best_score = f, score
        elif is_hd == best_is_hd and score < best_score:
            best, best_score = f, score
    return best


def _normalize_video(video: dict) -> dict | None:
    file = _pick_best_file(video.get("video_files", []))
    if not file:
        return None
    return {
        "id": video["id"],
        "url": file["link"],
        "duration": video.get("duration"),
        "width": file.get("width") or video.get("width"),
        "height": file.get("height") or video.get("height"),
        "thumbnail_url": video.get("image"),
        "source_url": video.get("url"),
        "photographer": (video.get("user") or {}).get("name") or "",
        "photographer_url": (video.get("user") or {}).get("url") or "",
    }


def search_images(query: str, per_page: int = 15) -> list[dict]:
    data = _get(PEXELS_IMAGE_SEARCH_URL, {
        "query": query,
        "per_page": min(per_page, 80),
        "orientation": "landscape",
        "size": "medium",
    })
    return [_normalize_photo(p) for p in data.get("photos", [])]


def search_videos(query: str, per_page: int = 15) -> list[dict]:
    data = _get(PEXELS_VIDEO_SEARCH_URL, {
        "query": query,
        "per_page": min(per_page, 80),
        "orientation": "landscape",
        "size": "medium",
    })
    videos = (_normalize_video(v) for v in data.get("videos", []))
    return [v for v in videos if v is not None and v["duration"] and v["duration"] <= 30]


if __name__ == "__main__":
    images = search_images("mountains")
    assert images, "expected at least one Pexels photo result for 'mountains'"
    assert images[0]["url"] and images[0]["width"] and images[0]["height"]
    print(f"ok  search_images: {len(images)} results, first id={images[0]['id']}")

    videos = search_videos("mountains")
    assert videos, "expected at least one Pexels video result for 'mountains'"
    assert videos[0]["url"] and videos[0]["duration"]
    print(f"ok  search_videos: {len(videos)} results, first id={videos[0]['id']}")
