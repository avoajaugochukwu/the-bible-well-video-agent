#!/usr/bin/env python3
"""HTTP API for the Bible Well pipeline, deployed as its own Railway service.
Two jobs:

1. Ingest trigger — POST /ingest (x-ingest-secret header, JSON {"row_id": ...})
   enqueues prepare_pipeline(row_id) and returns immediately. row_id is
   required: the caller (n8n) owns row selection and closes its own side of
   the job the moment it fires this request, so this pipeline never scans or
   writes Baserow itself, only reads the one row it's told to process.
   Ingest only PREPARES now (stages 1-9: script -> images -> align) — it no
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
import signal
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

import baserow          # src/
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
# Job ids the user hit Delete/Cancel on. Checked when a worker dequeues a job
# (skips it entirely, zero cost, if it hadn't started yet), at every stage
# boundary inside prepare_pipeline (run.py's _stage -> is_cancelled below, so an
# in-flight prepare stops at the NEXT stage instead of running to the end), and
# again after a pipeline call returns. A render, and whichever prepare stage is
# already running, still finishes and still spends what it was going to spend.
_cancelled_ids = set()
pipeline.is_cancelled = lambda row_id: row_id in _cancelled_ids


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
    status forever with nothing to resume it. Called once at process boot
    (main below) and again defensively on the first GET /jobs — guarded by
    _resumed_once so it's a no-op the second time either way."""
    global _resumed_once
    if _resumed_once:
        return
    _resumed_once = True
    for summary in supabase_jobs.list_jobs():
        row_id, status = summary["id"], summary["status"]
        if status in ("queued", "preparing") and row_id != _current_ingest_row_id and row_id not in _ingest_queue_ids:
            print(f"resume: re-enqueuing stranded prepare job {row_id!r}", flush=True)
            _enqueue_ingest(row_id)
        elif status == "rendering" and row_id != _current_render_row_id and row_id not in _render_queue_ids:
            print(f"resume: re-enqueuing stranded render job {row_id!r}", flush=True)
            _enqueue_render(row_id)


def _ingest_worker():
    global _current_ingest_row_id
    while True:
        row_id = _ingest_queue.get()
        _ingest_queue_ids.discard(row_id)
        if row_id in _cancelled_ids:
            _cancelled_ids.discard(row_id)
            print(f"ingest: {row_id!r} was deleted before it started — skipping", flush=True)
            _ingest_queue.task_done()
            continue
        _current_ingest_row_id = row_id
        # Distinct from 'queued' (waiting its turn) — otherwise a job actively
        # being prepared looks identical to one that hasn't started, which is
        # exactly the "is this actually running or stuck?" confusion the
        # queue/job pages can't resolve without cross-checking /health.
        try:
            supabase_jobs.set_status(row_id, "preparing")
            pipeline.prepare_pipeline(row_id)
            if row_id in _cancelled_ids:
                _cancelled_ids.discard(row_id)
                supabase_jobs.delete_job(row_id)
        except pipeline.Cancelled as e:
            # Expected, not a failure — h_delete_job already removed the row, so
            # there's nothing to mark and no traceback worth printing.
            _cancelled_ids.discard(row_id)
            print(f"ingest: {e}", flush=True)
        except Exception as e:
            print(f"ingest: prepare_pipeline({row_id!r}) raised:", flush=True)
            traceback.print_exc()
            if row_id in _cancelled_ids:
                _cancelled_ids.discard(row_id)
            else:
                # ponytail: this worker thread is the ONLY one that ever runs a
                # prepare — if a Supabase blip escapes here the `while True` loop
                # exits, the thread is gone for the life of the process, and every
                # later /ingest silently queues forever. Losing one status write is
                # survivable; losing the worker is not.
                try:
                    supabase_jobs.set_status(row_id, "failed", error=str(e), failedStage="prepare")
                except Exception:
                    traceback.print_exc()
        finally:
            _current_ingest_row_id = None
            _ingest_queue.task_done()


def _render_worker():
    global _current_render_row_id
    while True:
        row_id = _render_queue.get()
        _render_queue_ids.discard(row_id)
        if row_id in _cancelled_ids:
            _cancelled_ids.discard(row_id)
            print(f"render: {row_id!r} was deleted before it started — skipping", flush=True)
            _render_queue.task_done()
            continue
        _current_render_row_id = row_id
        try:
            pipeline.render_pipeline(row_id)
            if row_id in _cancelled_ids:
                _cancelled_ids.discard(row_id)
                supabase_jobs.delete_job(row_id)
        except Exception:
            print(f"render: render_pipeline({row_id!r}) raised:", flush=True)
            traceback.print_exc()
            _cancelled_ids.discard(row_id)
        finally:
            _current_render_row_id = None
            _render_queue.task_done()


def _handle_shutdown_signal(signum, frame):
    """Railway sends SIGTERM on every redeploy/restart, forwarded here by
    docker-entrypoint.sh's trap. prepare_pipeline()'s cancellation checks only
    fire between stages, and render_pipeline() has none — an in-flight call
    can't be finished gracefully in a signal handler, so this doesn't try. It
    just makes the shutdown visible in logs instead of the process vanishing
    mid-write with no trace, and exits
    promptly so Railway doesn't have to wait out the SIGKILL grace period.
    Whatever was in flight resumes from its cached runs/ artifacts (or from
    scratch if the run dir didn't survive) via _ensure_resumed() on next boot."""
    in_flight = [r for r in (_current_ingest_row_id, _current_render_row_id) if r]
    if in_flight:
        print(f"{signal.Signals(signum).name} received — job(s) {in_flight} still in "
              "flight, can't finish mid-signal, will resume on next boot", flush=True)
    else:
        print(f"{signal.Signals(signum).name} received — no job in flight, exiting", flush=True)
    sys.exit(0)


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
    existing = supabase_jobs.get_job(row_id)
    if existing is None:
        # Placeholder row so this job shows up in the queue list immediately —
        # otherwise it's invisible until prepare_pipeline() finishes. Best-effort
        # title/clickup_url lookup so the placeholder shows a real name instead
        # of the bare row_id — if this read fails, prepare_pipeline() will raise
        # properly on its own re-fetch, so it's safe to swallow here.
        title, clickup_url = None, None
        try:
            row = baserow.get_row(row_id)
            title, clickup_url = row.get("title"), row.get("clickup_url")
        except Exception:
            pass
        supabase_jobs.create_queued_job(row_id, title=title, clickup_url=clickup_url)
    elif existing.get("status") == "failed":
        # Manual retry of a failed prepare — flip back to 'queued' and clear the
        # stale error immediately, so the UI shows it's retrying right away
        # instead of leaving the old "failed" state up until the worker
        # actually gets to it.
        supabase_jobs.set_status(row_id, "queued", error=None, failedStage=None)
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


def h_delete_job(m, body, query):
    row_id = m.group("row_id")
    in_flight = row_id in (_current_ingest_row_id, _current_render_row_id)
    _cancelled_ids.add(row_id)
    _ingest_queue_ids.discard(row_id)
    _render_queue_ids.discard(row_id)
    supabase_jobs.delete_job(row_id)
    return 200, {
        "ok": True, "deleted": row_id,
        "was_in_flight": in_flight,
        "note": ("an in-flight prepare stops at the next stage boundary (the stage already "
                 "running still finishes and still spends what it was going to spend); a "
                 "render runs to completion") if in_flight else None,
    }


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
    ("DELETE", re.compile(rf"^/jobs/{_ROW}/?$"), h_delete_job, True),
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
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)
    signal.signal(signal.SIGINT, _handle_shutdown_signal)
    port = int(env.get("PORT", "8080"))
    threading.Thread(target=_ingest_worker, daemon=True).start()
    threading.Thread(target=_render_worker, daemon=True).start()
    _ensure_resumed()
    print(f"ingest server listening on :{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
