"""Krea image-generation client — submit + poll a photoreal-still job.

Extracted from the old `shared/assets.py` (which also had sheet/pexels asset-
planning code for the cold-case/true-crime-news pipelines' 3-lane asset model).
heritage has no sheet/stock lane — scene_engine.py routes every scene straight
to Krea — so only the Krea-calling machinery is kept here: `krea_photo()` and
its direct helpers/constants. `plan_assets()`/`materialize()`/
`materialize_scenes()`/the pexels-backed `resolve()` lane were cold-case/
true-crime-news-specific and are NOT ported here.
"""
import json
import time

_IMAGE_API = "https://avoajaugochukwu--open-source-image-gen-web.modal.run"


def _load_env():
    """IMAGE_API_TOKEN lives in a sibling project's env, not this repo's — same
    external lookup the old shared/assets.py always did, just relocated with it."""
    import os
    if os.environ.get("IMAGE_API_TOKEN"):
        return
    path = "/Users/avoaja/Documents/mine/youtube/helpers/ui/stories/sleep-stories/.env.local"
    if os.path.exists(path):
        for line in open(path):
            if line.startswith("IMAGE_API_TOKEN="):
                os.environ["IMAGE_API_TOKEN"] = line.split("=", 1)[1].strip().strip('"').strip("'")


def _post(url, body, headers):
    import urllib.request
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _get(url, headers):
    import urllib.request
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
        return json.load(r)


def _krea_job(prompt: str, h: dict, timeout_s: int, negative_prompt: str = "",
              style: str = "photo", lora: str | None = None) -> str:
    body = {"prompt": prompt[:2000], "style": style, "aspect_ratio": "16:9",
            "quality": "fast", "scale": 1, "n": 1}
    if negative_prompt:
        body["negative_prompt"] = negative_prompt[:1000]
    if lora:
        body["lora"] = lora
    job = _post(f"{_IMAGE_API}/generate", body, h)
    jid = job["job_id"]
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            st = _get(f"{_IMAGE_API}/status/{jid}", h)
        except Exception:                           # transient blip mid-poll -> keep polling
            time.sleep(3)
            continue
        if st.get("status") == "completed":
            return st["images"][0]["url"]
        if st.get("status") in ("failed", "error"):
            raise RuntimeError(f"krea failed: {st.get('error')}")
        time.sleep(3)
    raise TimeoutError(f"krea job {jid} unfinished in {timeout_s}s")


def krea_photo(prompt: str, token: str | None = None, timeout_s: int = 300, tries: int = 3,
               negative_prompt: str = "", style: str = "photo", lora: str | None = None) -> str:
    """Generate one 16:9 still; return its public URL. Retries the whole job (submit
    + poll), not just the submit -- a job-level failure/timeout is usually
    transient, not the API being down, so a fresh job often succeeds. Backoff (3s,
    6s, 12s, ...) so a rough patch gets more breathing room each retry.
    `style`/`lora` default to the existing photoreal pipeline (lora is ignored when
    style="photo") -- pass style="cartoon" + a named lora key (e.g. "gouache",
    "watercolor", "poster") to use Krea's illustrated-style LoRA router instead of
    prompt-only styling."""
    import os
    token = token or os.environ["IMAGE_API_TOKEN"]
    h = {"Authorization": f"Bearer {token}"}
    for attempt in range(tries):
        try:
            return _krea_job(prompt, h, timeout_s, negative_prompt, style, lora)
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(3 * 2 ** attempt)


def _poll_job(jid: str, h: dict, timeout_s: int) -> str:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            st = _get(f"{_IMAGE_API}/status/{jid}", h)
        except Exception:                           # transient blip mid-poll -> keep polling
            time.sleep(3)
            continue
        if st.get("status") == "completed":
            return st["images"][0]["url"]
        if st.get("status") in ("failed", "error"):
            raise RuntimeError(f"krea failed: {st.get('error')}")
        time.sleep(3)
    raise TimeoutError(f"krea job {jid} unfinished in {timeout_s}s")


def _krea_edit_job(prompt: str, reference_images: list[str], h: dict, timeout_s: int,
                    negative_prompt: str = "", style: str = "cartoon") -> str:
    body = {"prompt": prompt[:2000], "aspect_ratio": "16:9", "style": style,
            "quality": "fast", "scale": 1, "n": 1, "reference_images": reference_images}
    if negative_prompt:
        body["negative_prompt"] = negative_prompt[:1000]
    job = _post(f"{_IMAGE_API}/edit", body, h)
    return _poll_job(job["job_id"], h, timeout_s)


def krea_edit_photo(prompt: str, reference_images: list[str], token: str | None = None,
                     timeout_s: int = 300, tries: int = 3, negative_prompt: str = "",
                     style: str = "cartoon") -> str:
    """Image-to-image style transfer: apply the look of `reference_images` (public
    URLs or base64 data) to a new scene described by `prompt`. Same submit+poll
    retry shape as krea_photo()."""
    import os
    token = token or os.environ["IMAGE_API_TOKEN"]
    h = {"Authorization": f"Bearer {token}"}
    for attempt in range(tries):
        try:
            return _krea_edit_job(prompt, reference_images, h, timeout_s, negative_prompt, style)
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(3 * 2 ** attempt)


if __name__ == "__main__":
    _load_env()
    import os
    assert os.environ.get("IMAGE_API_TOKEN"), "no IMAGE_API_TOKEN found via _load_env()"
    print("ok  IMAGE_API_TOKEN resolved (not making a real Krea call — this is a smoke test only)")
