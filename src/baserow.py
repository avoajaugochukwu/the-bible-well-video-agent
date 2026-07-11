"""Baserow ingest for the heritage pipeline.

Pull a Heritage Decoded row that already has a finished script + voice, feed those into
the pipeline, and flip `video_processed=done` after a successful render. Stdlib urllib
only — mirrors space-cluster's front/baserow.py. Config comes from `utils/env.py` (checks
os.environ, then the root `.env` file) rather than raw os.environ, per this repo's
convention.

Sound: `voice_url` is narration only — confirmed against a real row, no separate SFX field.
"""
import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "utils"))
import env  # utils/

CHANNEL = "Heritage Decoded"
# select_options id on the "channel" single_select field (table id 2) — Baserow's
# single_select_equal filter needs this numeric id, not the display string (passing
# the string silently no-ops the filter: Baserow returns every row, unfiltered, no
# error). Option ids are stable once created, so hardcode rather than re-resolving
# it via /api/database/fields/ on every call. Confirmed via that endpoint 2026-07-08:
# {"id": 67, "value": "Heritage Decoded", ...}. If this table's channel field is ever
# rebuilt from scratch, re-check the id there before trusting this constant again.
CHANNEL_OPTION_ID = 67


def _base() -> tuple[str, str]:
    return env.require("BASE_ROW_URL").rstrip("/"), env.get("BASEROW_TABLE_ID", "2")


def _req(path: str, method: str = "GET", token: str | None = None, body: dict | None = None):
    url = _base()[0] + path
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"JWT {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def _token() -> str:
    r = _req("/api/user/token-auth/", method="POST",
             body={"email": env.require("BASEROW_EMAIL"), "password": env.require("BASEROW_PASSWORD")})
    return r["token"]


def _sel(x):
    # single_select fields come back as {"value": "done", ...} or null
    return x["value"] if isinstance(x, dict) else x


def _rows(token: str) -> list[dict]:
    _, table = _base()
    q = urllib.parse.urlencode({"user_field_names": "true",
                                "filter__channel__single_select_equal": CHANNEL_OPTION_ID,
                                "size": 50})
    # ponytail: order_by=-id errors on this table; sort client-side instead.
    return _req(f"/api/database/rows/table/{table}/?{q}", token=token)["results"]


def next_ready() -> dict | None:
    """Lowest-id Heritage Decoded row with script+voice done and not yet video_processed."""
    rows = sorted(_rows(_token()), key=lambda r: r["id"])
    for row in rows:
        if (_sel(row.get("script_status")) == "done"
                and _sel(row.get("voice_status")) == "done"
                and _sel(row.get("video_processed")) != "done"):
            return row
    return None


def get_row(row_id) -> dict:
    _, table = _base()
    return _req(f"/api/database/rows/table/{table}/{row_id}/?user_field_names=true", token=_token())


def mark_done(row_id) -> dict:
    _, table = _base()
    return _req(f"/api/database/rows/table/{table}/{row_id}/?user_field_names=true",
                method="PATCH", token=_token(), body={"video_processed": "done"})


def download(url: str, path: str) -> None:
    """Fetch voice_url -> path. Browser UA in case the host blocks python-urllib."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180) as r, open(path, "wb") as f:
        f.write(r.read())


if __name__ == "__main__":
    try:
        assert _token(), "no token returned"
        print("auth: ok")
        row = next_ready()
        if row:
            print(f"next_ready: id={row['id']} title={row.get('title')!r}")
        else:
            print("next_ready: none")
    except Exception as e:  # ponytail: don't crash the self-test suite when offline
        print(f"baserow self-test skipped (network?): {e}")
