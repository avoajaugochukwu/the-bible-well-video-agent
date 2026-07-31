#!/usr/bin/env python3
"""HTTP API for the Bible Well pipeline, deployed as its own Railway service.
Two jobs:

1. Ingest trigger — POST /ingest (x-ingest-secret header, JSON {"row_id": ...})
   enqueues prepare_pipeline(row_id) and returns immediately. row_id is
   required: the caller (n8n) owns row selection and closes its own side of
   the job the moment it fires this request, so this pipeline never scans or
   writes Baserow itself, only reads the one row it's told to process.
   Ingest only PREPARES now (stages 1-9: script -> images -> gallery) — it no
   longer renders automatically. A human reviews/edits scenes in the
   production UI (web/) and fires render separately.

2. Production-UI API — everything the production UI (web/) needs to review
   and edit a prepared job before rendering: list/read jobs, regenerate a
   scene's image, generate/commit a video for a scene, search/pick Pexels
   assets, activate or delete a history item, and trigger render manually.
   Every route below is behind the same x-ingest-secret header as /ingest
   (except GET /health) — this service does real spend (OpenAI, video-gen,
   Remotion Lambda) on these calls, it is not a read-only API.

Stdlib only (http.server + threading + queue + re), no new dependency to
deploy — matches every other src/*.py file in this repo.

remotion/src/scenes.json is a single shared file (not per-row), so two
render_pipeline() calls can't render concurrently — a single background
worker drains a FIFO render queue, one row at a time, same pattern as the
existing ingest queue (kept as a second, separate queue+worker so a slow
render never blocks new /ingest calls from being accepted).
"""
import json
import os
import queue
import re
import sys
import threading
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "utils"))
sys.path.insert(0, PROJECT_ROOT)  # for agents/ below

import env             # utils/
import pexels          # utils/
import run as pipeline  # src/: prepare_pipeline(), render_pipeline()
import s3              # src/
import supabase_jobs   # src/
import video_gen       # src/
from agents.scene_compositor import client as scene_compositor  # agents/

RUNS_DIR = os.path.join(os.path.dirname(HERE), "runs")

_ingest_queue = queue.Queue()
_render_queue = queue.Queue()
_current_ingest_row_id = None
_current_render_row_id = None
# Mirrored alongside each Queue so _ensure_resumed() can tell "already waiting
# to run" apart from "stranded" without Queue.queue's own internals.
_ingest_queue_ids = set()
_render_queue_ids = set()
_resumed_once = False


def _enqueue_ingest(row_id) -> None:
    _ingest_queue_ids.add(row_id)
    _ingest_queue.put(row_id)


def _enqueue_render(row_id) -> None:
    _render_queue_ids.add(row_id)
    _render_queue.put(row_id)


def _ensure_resumed() -> None:
    """Same problem military's ensureResumed()/requeueRunning() solves: the
    ingest/render queues are in-memory only, so a job stranded mid-flight by a
    process restart (crash, Railway redeploy) would otherwise sit at its last
    status forever with nothing to resume it. Runs once per process boot, on
    the first GET /jobs (no client-side polling anywhere — a human has to load
    the queue page for this to fire, same as military's page-load trigger)."""
    global _resumed_once
    if _resumed_once:
        return
    _resumed_once = True
    for summary in supabase_jobs.list_jobs():
        row_id, status = summary["id"], summary["status"]
        if status == "queued" and row_id != _current_ingest_row_id and row_id not in _ingest_queue_ids:
            print(f"resume: re-enqueuing stranded prepare job {row_id!r}", flush=True)
            _enqueue_ingest(row_id)
        elif status == "rendering" and row_id != _current_render_row_id and row_id not in _render_queue_ids:
            print(f"resume: re-enqueuing stranded render job {row_id!r}", flush=True)
            _enqueue_render(row_id)


def _ingest_worker():
    global _current_ingest_row_id
    while True:
        row_id = _ingest_queue.get()
        _current_ingest_row_id = row_id
        _ingest_queue_ids.discard(row_id)
        try:
            pipeline.prepare_pipeline(row_id)
        except Exception as e:
            print(f"ingest: prepare_pipeline({row_id!r}) raised:", flush=True)
            traceback.print_exc()
            supabase_jobs.set_status(row_id, "failed", error=str(e))
        finally:
            _current_ingest_row_id = None
            _ingest_queue.task_done()


def _render_worker():
    global _current_render_row_id
    while True:
        row_id = _render_queue.get()
        _current_render_row_id = row_id
        _render_queue_ids.discard(row_id)
        try:
            pipeline.render_pipeline(row_id)
        except Exception:
            print(f"render: render_pipeline({row_id!r}) raised:", flush=True)
            traceback.print_exc()
        finally:
            _current_render_row_id = None
            _render_queue.task_done()


def _characters_for(row_id) -> list[dict]:
    path = os.path.join(RUNS_DIR, str(row_id), "characters.json")
    if not os.path.exists(path):
        raise RuntimeError(f"no runs/{row_id}/characters.json — prepare_pipeline hasn't run yet")
    return json.load(open(path))


def _job_scene(job: dict, scene_number: int) -> dict:
    for s in job.get("scenes") or []:
        if s["sceneNumber"] == scene_number:
            return s
    raise RuntimeError(f"scene {scene_number} not found")


def _active_image_url(scene: dict) -> str:
    asset = scene["asset"]
    for item in asset.get("imageHistory") or []:
        if item["id"] == asset.get("activeImageId"):
            return item["url"]
    raise RuntimeError(f"scene {scene['sceneNumber']} has no active image")


# --- route handlers ---------------------------------------------------------
# Each takes (match: re.Match, body: dict, query: dict) and returns
# (status_code, response_body_dict).

def h_health(m, body, query):
    return 200, {
        "ok": True,
        "ingest_busy": _current_ingest_row_id is not None,
        "current_ingest_row_id": _current_ingest_row_id,
        "ingest_queue_depth": _ingest_queue.qsize(),
        "render_busy": _current_render_row_id is not None,
        "current_render_row_id": _current_render_row_id,
        "render_queue_depth": _render_queue.qsize(),
    }


def h_ingest(m, body, query):
    row_id = body.get("row_id")
    if not row_id:
        return 400, {"error": "row_id is required"}
    if supabase_jobs.get_job(row_id) is None:
        # Placeholder row so this job shows up in the queue list immediately —
        # otherwise it's invisible until prepare_pipeline() finishes. A row_id
        # that already has a job (a re-ingest / resume-from-cache case) is left
        # untouched rather than stomped with a blank placeholder.
        supabase_jobs.create_queued_job(row_id)
    _enqueue_ingest(row_id)
    return 202, {"ok": True, "status": "queued", "row_id": row_id,
                 "queue_depth": _ingest_queue.qsize()}


def h_list_jobs(m, body, query):
    _ensure_resumed()
    return 200, {"jobs": supabase_jobs.list_jobs()}


def h_get_job(m, body, query):
    job = supabase_jobs.get_job(m.group("row_id"))
    if job is None:
        return 404, {"error": "job not found"}
    return 200, job


def h_render(m, body, query):
    row_id = m.group("row_id")
    if supabase_jobs.get_job(row_id) is None:
        return 404, {"error": "job not found"}
    # Set immediately (not just once render_pipeline() actually starts) so a
    # job waiting its turn in _render_queue is already visible as "rendering"
    # rather than still showing "ready" — closes the same invisibility gap
    # h_ingest's placeholder closes on the prepare side.
    supabase_jobs.set_status(row_id, "rendering")
    _enqueue_render(row_id)
    return 202, {"ok": True, "status": "rendering", "row_id": row_id,
                 "queue_depth": _render_queue.qsize()}


def h_regenerate_image(m, body, query):
    row_id, scene_number = m.group("row_id"), int(m.group("scene_number"))
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return 400, {"error": "prompt is required"}
    job = supabase_jobs.get_job(row_id)
    if job is None:
        return 404, {"error": "job not found"}
    job_scene = _job_scene(job, scene_number)
    characters = _characters_for(row_id)
    result = scene_compositor.regenerate_one(
        {"scene_number": scene_number, "image_prompt": prompt,
         "character_ids": job_scene.get("characterIds") or []},
        characters,
    )
    if not result.get("image_url"):
        return 502, {"error": "image generation failed", "detail": result.get("generation_method")}
    scene = supabase_jobs.add_scene_image(row_id, scene_number, result["image_url"], "gpt-image", prompt=prompt)
    return 200, scene


def h_generate_video(m, body, query):
    row_id, scene_number = m.group("row_id"), int(m.group("scene_number"))
    job = supabase_jobs.get_job(row_id)
    if job is None:
        return 404, {"error": "job not found"}
    scene = _job_scene(job, scene_number)
    image_url = _active_image_url(scene)
    job_id = video_gen.submit(image_url, prompt=(body.get("prompt") or None))
    return 202, {"job_id": job_id, "status": "queued"}


def h_video_status(m, body, query):
    return 200, video_gen.poll(m.group("job_id"))


def h_commit_video(m, body, query):
    row_id, scene_number = m.group("row_id"), int(m.group("scene_number"))
    job_id = body.get("job_id")
    if not job_id:
        return 400, {"error": "job_id is required"}
    status = video_gen.poll(job_id)
    if status.get("error"):
        return 502, {"error": status["error"]}
    video = status.get("video")
    if not video:
        return 409, {"error": "job not completed yet", "status": status.get("status")}
    scene = supabase_jobs.add_scene_video(row_id, scene_number, video["url"], "video-gen")
    return 200, scene


def h_pexels_search(m, body, query):
    kind = (query.get("kind") or [""])[0]
    q = (query.get("query") or [""])[0].strip()
    if not q:
        return 400, {"error": "query is required"}
    if kind == "video":
        return 200, {"results": pexels.search_videos(q)}
    if kind == "image":
        return 200, {"results": pexels.search_images(q)}
    return 400, {"error": "kind must be 'image' or 'video'"}


def h_pick_asset(m, body, query):
    row_id, scene_number = m.group("row_id"), int(m.group("scene_number"))
    kind, url = body.get("kind"), body.get("url")
    if kind not in ("image", "video") or not url:
        return 400, {"error": "kind ('image'|'video') and url are required"}
    if kind == "image":
        scene = supabase_jobs.add_scene_image(row_id, scene_number, url, body.get("source") or "pexels")
    else:
        scene = supabase_jobs.add_scene_video(row_id, scene_number, url, body.get("source") or "pexels")
    return 200, scene


def h_upload_asset(m, body, query):
    row_id, scene_number = m.group("row_id"), int(m.group("scene_number"))
    kind = (query.get("kind") or [""])[0]
    if kind not in ("image", "video"):
        return 400, {"error": "kind must be 'image' or 'video'"}
    data = body.get("_raw")
    if not data:
        return 400, {"error": "file body is required"}
    filename = (query.get("filename") or ["upload"])[0]
    content_type = body.get("_content_type") or "application/octet-stream"
    url = s3.upload_media(data, filename, content_type)
    if not url:
        return 502, {"error": "upload failed"}
    if kind == "image":
        scene = supabase_jobs.add_scene_image(row_id, scene_number, url, "upload")
    else:
        scene = supabase_jobs.add_scene_video(row_id, scene_number, url, "upload")
    return 200, scene


def h_activate_asset(m, body, query):
    row_id, scene_number = m.group("row_id"), int(m.group("scene_number"))
    kind, asset_id = body.get("kind"), body.get("assetId")
    if kind not in ("image", "video") or not asset_id:
        return 400, {"error": "kind ('image'|'video') and assetId are required"}
    scene = supabase_jobs.activate_scene_asset(row_id, scene_number, kind, asset_id)
    return 200, scene


def h_delete_asset(m, body, query):
    row_id, scene_number = m.group("row_id"), int(m.group("scene_number"))
    kind, asset_id = m.group("kind"), m.group("asset_id")
    scene = supabase_jobs.delete_scene_asset(row_id, scene_number, kind, asset_id)
    return 200, scene


_ROW = r"(?P<row_id>[^/]+)"
_SCENE = r"(?P<scene_number>\d+)"

ROUTES = [
    ("GET", re.compile(r"^/health/?$"), h_health, False),
    ("POST", re.compile(r"^/ingest/?$"), h_ingest, True),
    ("GET", re.compile(r"^/jobs/?$"), h_list_jobs, True),
    ("GET", re.compile(rf"^/jobs/{_ROW}/?$"), h_get_job, True),
    ("POST", re.compile(rf"^/jobs/{_ROW}/render/?$"), h_render, True),
    ("POST", re.compile(rf"^/jobs/{_ROW}/scenes/{_SCENE}/regenerate-image/?$"), h_regenerate_image, True),
    ("POST", re.compile(rf"^/jobs/{_ROW}/scenes/{_SCENE}/generate-video/?$"), h_generate_video, True),
    ("GET", re.compile(r"^/video-status/(?P<job_id>[^/]+)/?$"), h_video_status, True),
    ("POST", re.compile(rf"^/jobs/{_ROW}/scenes/{_SCENE}/commit-video/?$"), h_commit_video, True),
    ("GET", re.compile(r"^/pexels/search/?$"), h_pexels_search, True),
    ("POST", re.compile(rf"^/jobs/{_ROW}/scenes/{_SCENE}/pick-asset/?$"), h_pick_asset, True),
    ("POST", re.compile(rf"^/jobs/{_ROW}/scenes/{_SCENE}/upload-asset/?$"), h_upload_asset, True),
    ("POST", re.compile(rf"^/jobs/{_ROW}/scenes/{_SCENE}/activate-asset/?$"), h_activate_asset, True),
    ("DELETE", re.compile(rf"^/jobs/{_ROW}/scenes/{_SCENE}/asset/(?P<kind>image|video)/(?P<asset_id>[^/]+)/?$"),
     h_delete_asset, True),
]


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, x-ingest-secret")

    def _json(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _dispatch(self, method: str):
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        matched_path = False
        for route_method, pattern, handler, needs_auth in ROUTES:
            m = pattern.match(parsed.path)
            if not m:
                continue
            matched_path = True
            if route_method != method:
                continue
            if needs_auth and self.headers.get("x-ingest-secret") != env.require("INGEST_SECRET"):
                return self._json(401, {"error": "bad secret"})
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            content_type = self.headers.get("Content-Type", "")
            body = {}
            if raw and content_type.startswith("application/json"):
                try:
                    body = json.loads(raw)
                except json.JSONDecodeError:
                    return self._json(400, {"error": "body must be JSON"})
            elif raw:
                body = {"_raw": raw, "_content_type": content_type}
            try:
                status, response = handler(m, body, query)
            except Exception as e:
                print(f"{method} {parsed.path} raised:", flush=True)
                traceback.print_exc()
                return self._json(500, {"error": str(e)})
            return self._json(status, response)
        self._json(404 if not matched_path else 405, {"error": "not found" if not matched_path else "method not allowed"})

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)


if __name__ == "__main__":
    port = int(env.get("PORT", "8080"))
    threading.Thread(target=_ingest_worker, daemon=True).start()
    threading.Thread(target=_render_worker, daemon=True).start()
    print(f"ingest server listening on :{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
