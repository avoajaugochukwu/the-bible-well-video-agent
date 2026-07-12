"""One-time experiment: fire a Christian Story run's scenes at the shared
remotion-test-2 render service (/api/handoff) instead of our own remotion/
Lambda deploy, just to see how their composition (Ken Burns + cards, own
Whisper alignment) renders our material. Not wired into run.py.

Usage: python3 src/try_remotion_handoff.py [row_id]   (default 1947)
"""
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "utils"))
import env  # utils/

BASE_URL = env.get("REMOTION_HANDOFF_URL", "https://remotion-gen-production.up.railway.app").rstrip("/")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLL_SECONDS = 4


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def _get(path: str) -> dict:
    with urllib.request.urlopen(BASE_URL + path, timeout=30) as r:
        return json.loads(r.read().decode())


def build_payload(row: dict, scenes: list[dict]) -> dict:
    segments = []
    for s in scenes:
        text = s["script_snippet"]
        seg = {
            "id": f"s{s['scene_number']}",
            "segmentText": text,
            "visualContext": s["image_prompt"],
            "duration": max(1.0, len(text.split()) / 2.5),  # hint only — their Whisper aligns the real audio
            "mode": "images",
        }
        if s.get("image_url"):
            seg["images"] = [{"url": s["image_url"]}]
        segments.append(seg)

    return {
        "projectId": str(row["id"]),
        "fps": 30,
        "width": 1920,
        "height": 1080,
        "audioUrl": row["voice_url"],
        "__rawScript": row["script"],
        "scenes": [],
        "rawSegments": segments,
    }


def main():
    row_id = sys.argv[1] if len(sys.argv) > 1 else "1947"
    run_dir = os.path.join(PROJECT_ROOT, "runs", row_id)
    row = json.load(open(os.path.join(run_dir, "row.json")))
    scenes = json.load(open(os.path.join(run_dir, "scenes.json")))

    payload = build_payload(row, scenes)
    print(f"POST {BASE_URL}/api/handoff  ({len(scenes)} segments)")
    job = _post("/api/handoff", payload)
    job_id = job["jobId"]
    print(f"jobId={job_id} — polling...")

    while True:
        status = _get(f"/api/handoff/{job_id}")
        print(f"  {status.get('status')}: {status.get('progress')}")
        if status.get("status") == "done":
            print(f"\nmp4: {status['url']}")
            return
        if status.get("status") == "error":
            raise RuntimeError(f"handoff failed: {status.get('error')}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
