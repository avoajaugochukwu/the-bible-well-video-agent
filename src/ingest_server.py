#!/usr/bin/env python3
"""Minimal HTTP ingestion trigger for the Bible Well pipeline, deployed as its own
Railway service. POST /ingest (x-ingest-secret header) kicks off run_pipeline()
in a background thread and returns immediately — same as calling
`python3 src/run.py` by hand, just reachable over HTTP so an outside system can
trigger it. No body needed: run_pipeline() still pulls next_ready() off Baserow
itself. Stdlib only (http.server + threading), no new dependency to deploy.

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


def _run_in_background():
    global _busy
    try:
        pipeline.run_pipeline()
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
        with _lock:
            if _busy:
                return self._json(200, {"ok": True, "status": "busy"})
            _busy = True
        threading.Thread(target=_run_in_background, daemon=True).start()
        self._json(202, {"ok": True, "status": "queued"})

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
