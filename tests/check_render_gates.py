"""The two gates that used to live on local disk, now on the job payload:
video-url.txt -> payload.renderUrl, done.marker -> payload.clickupPushedAt.
Both are silent-money bugs if they leak (a re-render costs a full Remotion
Lambda pass; a second ClickUp push prepends "🎬 VIDEO:" twice to the same task
description with nothing on ClickUp's side detecting the duplicate), so this
runs render_pipeline() twice over an already-rendered job with every paid call
stubbed to explode.

  PYTHONPATH=. .venv/bin/python tests/check_render_gates.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import run  # src/
import supabase_jobs  # src/

payload = {
    "id": "row-gate-check", "createdAt": "2026-07-31T00:00:00+00:00", "status": "rendering",
    "renderUrl": "https://example.com/already-rendered.mp4",
    "scenes": [{"sceneNumber": 1, "durationSeconds": 4.0, "asset": {
        "imageHistory": [{"id": "seed-1", "url": "https://example.com/1.png"}],
        "videoHistory": [], "activeImageId": "seed-1", "activeVideoId": None, "mode": "image"}}],
}
pushes = []


def boom(*a, **k):
    raise AssertionError("gate leaked — a paid call was made for an already-finished render")


run.baserow.get_row = lambda row_id: {"voice_url": "https://example.com/v.mp3",
                                       "clickup_url": "https://app.clickup.com/t/abc123"}
run.supabase_jobs.get_job = lambda row_id: payload
run.supabase_jobs.set_status = lambda row_id, status, **patch: payload.update(patch, status=status)
run.heritage_clickup.push_video = lambda clickup_url, video_url: pushes.append(video_url) or True
run._transcribe = boom          # whisper service call
run.run_node = boom             # deploy:site / render:remote (Lambda $)
run.heritage_s3.put_file = boom

url = run.render_pipeline("row-gate-check")
assert url == "https://example.com/already-rendered.mp4", url
assert pushes == ["https://example.com/already-rendered.mp4"], pushes
assert payload["clickupPushedAt"], "clickup gate was never closed"
print("ok  renderUrl gate skips deploy/render/S3; ClickUp is pushed once")

run.render_pipeline("row-gate-check")
assert pushes == ["https://example.com/already-rendered.mp4"], \
    f"clickupPushedAt gate leaked — pushed {len(pushes)} times: {pushes}"
print("ok  clickupPushedAt gate stops the second push (no duplicate '🎬 VIDEO:' line)")

# scenes_from_job is now render's only source of scenes — no local scenes.json.
assert supabase_jobs.scenes_from_job(payload)[0]["image_url"] == "https://example.com/1.png"
print("ok  scenes come straight from the job payload")
