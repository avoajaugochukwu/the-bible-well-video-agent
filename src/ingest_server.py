#!/usr/bin/env python3
"""Minimal HTTP ingestion trigger for the Bible Well pipeline, deployed as its own
Railway service. POST /ingest (x-ingest-secret header, JSON body {"row_id": ...})
kicks off run_pipeline(row_id) in a background thread and returns immediately —
same as calling `python3 src/run.py <row_id>` by hand, just reachable over HTTP
so an outside system can trigger it. row_id is required: the caller (n8n) owns
row selection and closes its own side of the job the moment it fires this
request, so this pipeline never scans or writes Baserow itself, only reads the
one row it's told to process. Stdlib only (http.server + threading), no new
dependency to deploy.

remotion/src/scenes.json is a single shared file (not per-row), so run_pipeline()
is NOT safe to run concurrently with itself — a global lock serializes triggers;
a call that arrives mid-run gets {"ok": true, "status": "busy"} instead of
starting a second overlapping render.
"""
import json
import os
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "utils"))

import env             # utils/
import run as pipeline  # src/: run_pipeline()

_lock = threading.Lock()
_busy = False


def _run_in_background(row_id):
    global _busy
    try:
        pipeline.run_pipeline(row_id)
    except Exception:
        # Full traceback, not just str(e) — this runs unattended, Railway logs
        # are the only record of why a job died, a one-line message isn't
        # enough to find which stage/line actually raised.
        print("ingest: run_pipeline() raised:", flush=True)
        traceback.print_exc()
    finally:
        with _lock:
            _busy = False


class Handler(BaseHTTPRequestHandler):
    def _json(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        global _busy
        if self.path.rstrip("/") != "/ingest":
            return self._json(404, {"error": "not found"})
        if self.headers.get("x-ingest-secret") != env.require("INGEST_SECRET"):
            return self._json(401, {"error": "bad secret"})
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "body must be JSON"})
        row_id = body.get("row_id")
        if not row_id:
            return self._json(400, {"error": "row_id is required"})
        with _lock:
            if _busy:
                return self._json(200, {"ok": True, "status": "busy"})
            _busy = True
        threading.Thread(target=_run_in_background, args=(row_id,), daemon=True).start()
        self._json(202, {"ok": True, "status": "queued", "row_id": row_id})

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            return self._json(200, {"ok": True, "busy": _busy})
        self._json(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)


if __name__ == "__main__":
    port = int(env.get("PORT", "8080"))
    print(f"ingest server listening on :{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
