"""Client for the in-house image-to-video API (open-source-video-gen, hosted on
Modal — see README.md for the Swagger docs url). Async submit->poll, same
pattern as src/scene_engine.py:whisper_words() for a hosted Modal service and
src/clickup.py for the urllib+env.require() shape.

  submit(image_url, prompt=None) -> job_id   POST /generate
  poll(job_id) -> status dict                GET  /status/{job_id}
    {"job_id", "status", "video": {"url", "width", "height", "duration_s", "fps"} | None, "error"}

Auth: Authorization: Bearer VIDEO_GEN_TOKEN on every call except /health.
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "utils"))
import env  # utils/


def _req(path: str, method: str = "GET", body: dict | None = None) -> dict:
    url = env.require("VIDEO_GEN_URL").rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": f"Bearer {env.require('VIDEO_GEN_TOKEN')}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"video-gen {path} {e.code}: {e.read().decode()[:500]}")


def submit(image_url: str, prompt: str | None = None) -> str:
    body = {"input_image_url": image_url}
    if prompt:
        body["prompt"] = prompt
    data = _req("/generate", method="POST", body=body)
    return data["job_id"]


def poll(job_id: str) -> dict:
    return _req(f"/status/{job_id}")


if __name__ == "__main__":
    assert env.get("VIDEO_GEN_URL") and env.get("VIDEO_GEN_TOKEN"), \
        "VIDEO_GEN_URL/VIDEO_GEN_TOKEN not set — can't even check auth is wired"
    print("ok  VIDEO_GEN_URL/VIDEO_GEN_TOKEN are set (no live job submitted — smoke test only)")
