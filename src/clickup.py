"""Push the finished video's S3 url onto a ClickUp task so it's easy to find near the top.

Stdlib urllib only — mirrors space-cluster's front/clickup.py. Auth is a ClickUp
personal token (`pk_...`) via `env.require("CLICKUP_API")` (already in this repo's
root .env); the header is the RAW token, NO "Bearer" prefix (ClickUp v2 convention
for personal tokens).

  push_video(clickup_url, video_url):
    GET  /api/v2/task/{id}                       -> current description
    PUT  /api/v2/task/{id}  {"description": ...}  -> prepend "🎬 VIDEO: <url>"
  Falls back to POST /api/v2/task/{id}/comment if the description PUT fails.
  Then PUTs {"status": "fc done"} so the task visibly moves out of "in progress"
  in the list view — a hands-off run has no human doing that click.
Never raises into the caller — returns True/False.

List: "The Bible Well", id 901114103835, Team Space, Karl's Workspace. Statuses on
that list (confirmed via GET /api/v2/list/901114103835): to do / in progress /
fc done / complete.
"""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "utils"))
import env  # utils/

API = "https://api.clickup.com/api/v2"
LIST_ID = "901114103835"
DONE_STATUS = "fc done"


def _task_id(clickup_url: str) -> str:
    """Parse the task id out of a ClickUp url: the segment after '/t/'.
    Handles trailing slashes and query strings (e.g. .../t/abc123/?foo=1)."""
    tail = clickup_url.split("/t/", 1)[1] if "/t/" in clickup_url else clickup_url
    return tail.split("?", 1)[0].strip("/").split("/", 1)[0].strip()


def _req(path: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + path, data=data, method=method,
        headers={"Authorization": env.require("CLICKUP_API"), "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def push_video(clickup_url: str, video_url: str) -> bool:
    """Prepend '🎬 VIDEO: <video_url>' to the task description so it sits at the top,
    then move the task to DONE_STATUS ("fc done") so it's visibly finished with no
    human clicking anything. On any description failure, fall back to posting a
    comment. Returns True on success (status-move failure doesn't count against
    that — the video's findable either way, which is the part that must not fail)."""
    line = f"🎬 VIDEO: {video_url}"
    try:
        tid = _task_id(clickup_url)
        try:
            desc = _req(f"/task/{tid}").get("description") or ""
            new = line if not desc else f"{line}\n\n{desc}"
            _req(f"/task/{tid}", method="PUT", body={"description": new})
        except Exception as e:                 # description route failed -> comment fallback
            print(f"clickup: description PUT failed ({e}); falling back to comment")
            _req(f"/task/{tid}/comment", method="POST", body={"comment_text": line})
        try:
            _req(f"/task/{tid}", method="PUT", body={"status": DONE_STATUS})
        except Exception as e:                 # status move is a nice-to-have, not load-bearing
            print(f"clickup: status PUT to {DONE_STATUS!r} failed ({e})")
        return True
    except Exception as e:                      # never block the pipeline on ClickUp
        print(f"clickup: push_video failed ({e})")
        return False


if __name__ == "__main__":
    # parser self-test only — no live task mutation
    assert _task_id("https://app.clickup.com/t/abc123") == "abc123"
    assert _task_id("https://app.clickup.com/t/abc123/") == "abc123"
    assert _task_id("https://app.clickup.com/t/abc123?foo=1") == "abc123"
    assert _task_id("https://app.clickup.com/9876/v/li/t/abc123") == "abc123"
    assert _task_id("abc123") == "abc123"
    print("ok  _task_id parses all sample forms")
    assert env.get("CLICKUP_API"), "no CLICKUP_API — can't even check auth is wired"
    print("ok  CLICKUP_API is set (not making a real API call — this is a smoke test only)")
