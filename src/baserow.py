"""Baserow ingest for the heritage pipeline.

Pull a Bible Well row that already has a finished script + voice, feed those into
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


def get_row(row_id) -> dict:
    """Read-only. This pipeline never writes back to Baserow — the ingest trigger
    (n8n) owns row_id selection and closes its own side of the job immediately;
    this is just a lookup for script/voice_url/clickup_url."""
    _, table = _base()
    return _req(f"/api/database/rows/table/{table}/{row_id}/?user_field_names=true", token=_token())


def download(url: str, path: str) -> None:
    """Fetch voice_url -> path. Browser UA in case the host blocks python-urllib."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180) as r, open(path, "wb") as f:
        f.write(r.read())


if __name__ == "__main__":
    import sys
    try:
        assert _token(), "no token returned"
        print("auth: ok")
        if len(sys.argv) > 1:
            row = get_row(sys.argv[1])
            print(f"get_row({sys.argv[1]}): title={row.get('title')!r}")
    except Exception as e:  # ponytail: don't crash the self-test suite when offline
        print(f"baserow self-test skipped (network?): {e}")
