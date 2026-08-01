"""Write/read the production-UI job row for one Baserow row_id, via Supabase's
PostgREST REST API — same Supabase project the sibling `military` app uses,
this pipeline's own table (`bible_well_jobs`). Stdlib urllib only, same
pattern as src/clickup.py: env.require() for creds, no swallowed errors here
(a failed write should stop the pipeline the same way any other stage does).

Table: id TEXT PK (the row_id), created_at TEXT, status TEXT, payload JSONB.
payload matches web/lib/types.ts's `Job` shape exactly (camelCase) — this is
the one place Python constructs that shape, so keep it in sync with types.ts
by hand; there's no shared schema between the two languages.
"""
import functools
import json
import os
import sys
import threading
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "utils"))
import env  # utils/

TABLE = "bible_well_jobs"

_LOCK = threading.Lock()


def _locked(fn):
    """Every function below marked with this re-reads the WHOLE payload, mutates
    it and writes it back — everything this app stores is one jsonb blob, so two
    of them running at once silently lose one another's edits (the pipeline's
    ingest worker writing scene images while an HTTP handler regenerates one is
    the real case). One process, so one plain lock is enough."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _LOCK:
            return fn(*args, **kwargs)
    return wrapper


def _headers() -> dict:
    key = env.require("SUPABASE_SECRET_KEY")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def upsert_job(row: dict) -> dict:
    """row = {id, created_at, status, payload}. Upserts on the id primary key."""
    url = f"{env.require('SUPABASE_URL')}/rest/v1/{TABLE}?on_conflict=id"
    req = urllib.request.Request(
        url, data=json.dumps([row]).encode(), method="POST",
        headers={**_headers(), "Prefer": "resolution=merge-duplicates,return=representation"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())[0]


def delete_job(row_id) -> None:
    """Hard-delete a job row — the queue page's kill switch. Note this only
    ever removes the tracking row; it cannot stop an already in-flight
    prepare_pipeline()/render_pipeline() call (see ingest_server.py's
    h_delete_job for how cancellation of a still-queued job is handled)."""
    url = f"{env.require('SUPABASE_URL')}/rest/v1/{TABLE}?id=eq.{row_id}"
    req = urllib.request.Request(url, method="DELETE", headers=_headers())
    with urllib.request.urlopen(req, timeout=30):
        pass


def list_jobs() -> list[dict]:
    """Job summaries for the queue view, newest first."""
    params = urllib.parse.urlencode({
        "select": "id,created_at,status,payload->>title,payload->scenes,payload->>currentStage,"
                  "payload->>clickupUrl,payload->total,payload->completed",
        "order": "created_at.desc",
    })
    url = f"{env.require('SUPABASE_URL')}/rest/v1/{TABLE}?{params}"
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=30) as r:
        rows = json.loads(r.read().decode())
    return [
        {
            "id": row["id"],
            "createdAt": row["created_at"],
            "status": row["status"],
            "title": row.get("title"),
            "sceneCount": len(row.get("scenes") or []),
            "currentStage": row.get("currentStage"),
            "clickupUrl": row.get("clickupUrl"),
            "total": row.get("total"),
            "completed": row.get("completed"),
        }
        for row in rows
    ]


def get_job(row_id) -> dict | None:
    """Returns the payload (the Job dict), or None if no row exists yet."""
    params = urllib.parse.urlencode({"id": f"eq.{row_id}", "select": "payload"})
    url = f"{env.require('SUPABASE_URL')}/rest/v1/{TABLE}?{params}"
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=30) as r:
        rows = json.loads(r.read().decode())
    return rows[0]["payload"] if rows else None


def _scene_asset(scene: dict) -> dict:
    """Seed a scene's asset history from whatever compose_all() already
    produced — one image entry, active, mode image. Every later regenerate/
    Pexels-pick/video-gen action (UI-driven, not this pipeline) APPENDS to
    this history rather than overwriting it."""
    if not scene.get("image_url"):
        return {"imageHistory": [], "videoHistory": [], "activeImageId": None,
                "activeVideoId": None, "mode": "image"}
    asset_id = f"seed-{scene['scene_number']}"
    return {
        "imageHistory": [{
            "id": asset_id,
            "url": scene["image_url"],
            "source": "gpt-image",
            "prompt": scene.get("image_prompt"),
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }],
        "videoHistory": [],
        "activeImageId": asset_id,
        "activeVideoId": None,
        "mode": "image",
    }


@_locked
def set_status(row_id, status: str, **payload_patch) -> dict | None:
    """Fetch the existing job, patch status (+ any other payload fields, e.g.
    renderUrl/error), re-upsert. Returns None if the row doesn't exist yet —
    render_pipeline() should always find one here, prepare_pipeline() writes
    it first."""
    payload = get_job(row_id)
    if payload is None:
        return None
    payload = {**payload, **payload_patch, "status": status}
    return upsert_job({
        "id": str(row_id),
        "created_at": payload.get("createdAt") or datetime.now(timezone.utc).isoformat(),
        "status": status,
        "payload": payload,
    })


@_locked
def set_stage(row_id, stage: str) -> None:
    """Lightweight per-stage progress marker (e.g. "Reading script", "Cutting
    scenes", "Generating scene images...") patched into the job payload without
    touching status/scenes/anything else — lets the production UI show what
    prepare_pipeline() is actually doing right now instead of a blanket
    'preparing'. No-op if the job row doesn't exist (shouldn't happen; the
    placeholder is always written before the worker starts)."""
    job = get_job(row_id)
    if job is None:
        return
    payload = {**job, "currentStage": stage}
    upsert_job({
        "id": str(row_id),
        "created_at": payload.get("createdAt") or datetime.now(timezone.utc).isoformat(),
        "status": payload.get("status", "preparing"),
        "payload": payload,
    })


def create_queued_job(row_id, title: str | None = None, clickup_url: str | None = None) -> dict:
    """Write a minimal 'queued' placeholder row immediately on /ingest, before
    prepare_pipeline() has done any work — so the job shows up in the queue
    list right away instead of being invisible until prepare finishes.
    prepare_pipeline()'s own upsert_scenes() call fills in the real payload
    (scenes, characters, title) once it has one. Caller
    must check get_job(row_id) is None first — never call this on a row that
    already has a job, or it would wipe out real progress with a placeholder."""
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "id": str(row_id), "createdAt": now, "status": "queued",
        "title": title, "clickupUrl": clickup_url, "scenes": [], "renderUrl": None, "error": None,
    }
    return upsert_job({"id": str(row_id), "created_at": now, "status": "queued", "payload": payload})


def build_job_payload(row_id, row: dict, scenes: list[dict], status: str = "ready") -> dict:
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "id": str(row_id),
        "createdAt": now,
        "status": status,
        "title": row.get("title"),
        "clickupUrl": row.get("clickup_url"),
        "scenes": [
            {
                "sceneNumber": s["scene_number"],
                "scriptSnippet": s["script_snippet"],
                "sceneType": s.get("scene_type"),
                "visualMode": s.get("visual_mode"),
                "characterIds": s.get("character_ids") or [],
                "heroSubject": s.get("hero_subject"),
                "imagePrompt": s.get("image_prompt"),
                "durationSeconds": s.get("duration_seconds"),
                "asset": _scene_asset(s),
            }
            for s in scenes
        ],
        # Progress counters for the UI. Written once here with the scene list
        # (prepare_pipeline calls this BEFORE image generation, so scenes are
        # visible while they fill in) and kept current by add_scene_image().
        "total": len(scenes),
        "completed": sum(1 for s in scenes if s.get("image_url")),
        "renderUrl": None,
        "error": None,
    }
    return {"id": str(row_id), "created_at": now, "status": status, "payload": payload}


@_locked
def upsert_scenes(row_id, row: dict, scenes: list[dict], status: str = "ready", **payload_patch) -> dict:
    """prepare_pipeline's two whole-scene-list writes (once before image
    generation, once at the end). Rebuilds the payload from `scenes`, but keeps
    what the row already holds and a rebuild can't know about:

    - every scene's asset history and active pointer — scenes are visible and
      editable in the UI while status is 'preparing', so a human regenerating an
      image mid-prepare must not lose it to the write at the end of the run;
    - renderUrl / clickupPushedAt — the gates that stop a rerun re-paying for a
      Lambda render or prepending the video line to the same ClickUp task twice.

    A scene with no history yet is seeded from its own image_url as usual, so
    duration_seconds and any neighbor-backfilled image still land."""
    existing = get_job(row_id) or {}
    fresh = build_job_payload(row_id, row, scenes, status=status)["payload"]
    by_number = {s["sceneNumber"]: s for s in existing.get("scenes") or []}
    for scene in fresh["scenes"]:
        old_asset = (by_number.get(scene["sceneNumber"]) or {}).get("asset") or {}
        if old_asset.get("imageHistory") or old_asset.get("videoHistory"):
            scene["asset"] = old_asset
    payload = {
        **existing, **fresh, **payload_patch,
        "createdAt": existing.get("createdAt") or fresh["createdAt"],
        "renderUrl": existing.get("renderUrl") or fresh["renderUrl"],
    }
    payload["completed"] = sum(1 for s in payload["scenes"] if s["asset"]["imageHistory"])
    upsert_job({"id": str(row_id), "created_at": payload["createdAt"],
                "status": payload["status"], "payload": payload})
    return payload


def _save(job: dict) -> None:
    upsert_job({
        "id": job["id"],
        "created_at": job["createdAt"],
        "status": job["status"],
        "payload": job,
    })


def _find_scene(job: dict, scene_number: int) -> dict:
    for s in job.get("scenes") or []:
        if s["sceneNumber"] == scene_number:
            return s
    raise RuntimeError(f"scene {scene_number} not found in job {job.get('id')!r}")


def _new_asset_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@_locked
def add_scene_image(row_id, scene_number: int, url: str, source: str, prompt: str | None = None) -> dict:
    """Append a new image to a scene's history and make it active — never
    overwrites a prior entry, so the UI can always pick an older one back.
    Also refreshes the job's `completed` counter (scenes that have an image),
    which is what the production UI's progress bar counts while the compositor
    is still working through the scene list."""
    job = get_job(row_id)
    if job is None:
        raise RuntimeError(f"no job for {row_id}")
    scene = _find_scene(job, scene_number)
    asset_id = _new_asset_id("img")
    scene["asset"]["imageHistory"].append({
        "id": asset_id, "url": url, "source": source, "prompt": prompt,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    })
    scene["asset"]["activeImageId"] = asset_id
    scene["asset"]["mode"] = "image"
    if prompt:
        scene["imagePrompt"] = prompt
    # Derived, not incremented: a regenerate on an already-done scene must not
    # push the counter past `total`.
    job["completed"] = sum(1 for s in job.get("scenes") or [] if s["asset"]["imageHistory"])
    _save(job)
    return scene


@_locked
def add_scene_video(row_id, scene_number: int, url: str, source: str) -> dict:
    """Append a new video to a scene's history and make it active (mode:
    'video' — video wins render precedence while active). The scene's image
    history is untouched, so deleting/switching away from this video falls
    straight back to whichever image was already active."""
    job = get_job(row_id)
    if job is None:
        raise RuntimeError(f"no job for {row_id}")
    scene = _find_scene(job, scene_number)
    asset_id = _new_asset_id("vid")
    scene["asset"]["videoHistory"].append({
        "id": asset_id, "url": url, "source": source,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    })
    scene["asset"]["activeVideoId"] = asset_id
    scene["asset"]["mode"] = "video"
    _save(job)
    return scene


@_locked
def activate_scene_asset(row_id, scene_number: int, kind: str, asset_id: str) -> dict:
    """Pick any past image or video back into the active slot — the 'user
    picks from history' behavior. Doesn't touch history, just the pointer."""
    job = get_job(row_id)
    if job is None:
        raise RuntimeError(f"no job for {row_id}")
    scene = _find_scene(job, scene_number)
    if kind == "image":
        scene["asset"]["activeImageId"] = asset_id
        scene["asset"]["mode"] = "image"
    else:
        scene["asset"]["activeVideoId"] = asset_id
        scene["asset"]["mode"] = "video"
    _save(job)
    return scene


@_locked
def delete_scene_asset(row_id, scene_number: int, kind: str, asset_id: str) -> dict:
    """Hard-delete one history item. If it was active, falls back to the most
    recent remaining item of the same kind (or None) — deleting the active
    video always falls back to mode:'image', per the 'delete video anytime'
    requirement."""
    job = get_job(row_id)
    if job is None:
        raise RuntimeError(f"no job for {row_id}")
    scene = _find_scene(job, scene_number)
    history_key = "imageHistory" if kind == "image" else "videoHistory"
    active_key = "activeImageId" if kind == "image" else "activeVideoId"
    scene["asset"][history_key] = [a for a in scene["asset"][history_key] if a["id"] != asset_id]
    if scene["asset"].get(active_key) == asset_id:
        remaining = scene["asset"][history_key]
        scene["asset"][active_key] = remaining[-1]["id"] if remaining else None
        if kind == "video":
            scene["asset"]["mode"] = "video" if remaining else "image"
    _save(job)
    return scene


def _resolve_asset(asset: dict) -> dict:
    """One scene's asset -> the fields render_pipeline actually needs: which
    url renders (image or video, per `mode`), never both."""
    image_history = {a["id"]: a for a in asset.get("imageHistory") or []}
    video_history = {a["id"]: a for a in asset.get("videoHistory") or []}
    active_image = image_history.get(asset.get("activeImageId"))
    active_video = video_history.get(asset.get("activeVideoId"))
    resolved: dict = {}
    if active_image:
        resolved["image_url"] = active_image["url"]
        if active_image.get("prompt"):
            resolved["image_prompt"] = active_image["prompt"]
    if asset.get("mode") == "video" and active_video:
        resolved["video_url"] = active_video["url"]
        resolved["mode"] = "video"
    else:
        resolved["mode"] = "image"
    return resolved


def scenes_from_job(job: dict) -> list[dict]:
    """The job payload -> the pipeline's own scene shape (snake_case). This is
    render_pipeline()'s ONLY source of scenes: nothing is kept on local disk, and
    render can fire hours or days after prepare (manual review in between), so
    Supabase is the durable source of truth for scene_number/image_url/
    duration_seconds (+ video_url/mode) — everything to_remotion_scenes() needs,
    including every production-UI edit (regenerated images, Pexels picks, video
    overrides)."""
    out = []
    for s in job.get("scenes") or []:
        scene = {"scene_number": s["sceneNumber"], "image_url": None,
                  "duration_seconds": s.get("durationSeconds")}
        scene.update(_resolve_asset(s["asset"]))
        out.append(scene)
    return out


if __name__ == "__main__":
    sample_row = {"title": "Sample Title", "clickup_url": "https://app.clickup.com/t/abc123"}
    sample_scenes = [
        {"scene_number": 1, "script_snippet": "A test snippet.", "scene_type": "reflection",
         "visual_mode": "abstract", "character_ids": ["protagonist"], "hero_subject": "protagonist",
         "image_prompt": "a test prompt", "image_url": "https://example.com/a.png"},
        {"scene_number": 2, "script_snippet": "No image yet.", "scene_type": "decision",
         "visual_mode": "concrete", "character_ids": [], "hero_subject": None,
         "image_prompt": "another prompt", "image_url": None},
    ]
    row = build_job_payload("row-selftest", sample_row, sample_scenes)
    assert row["payload"]["scenes"][0]["asset"]["activeImageId"] == "seed-1"
    assert row["payload"]["scenes"][0]["asset"]["mode"] == "image"
    assert row["payload"]["scenes"][1]["asset"]["imageHistory"] == []
    assert row["payload"]["scenes"][1]["asset"]["activeImageId"] is None
    print("ok  build_job_payload seeds asset history correctly (no live Supabase call)")
    assert env.get("SUPABASE_URL") and env.get("SUPABASE_SECRET_KEY"), \
        "SUPABASE_URL/SUPABASE_SECRET_KEY not set — can't even check auth is wired"
    print("ok  SUPABASE_URL/SUPABASE_SECRET_KEY are set (no live API call — smoke test only)")

    edited_job = {
        "id": "row-selftest",
        "scenes": [
            {"sceneNumber": 1, "asset": {
                "imageHistory": [{"id": "seed-1", "url": "https://example.com/a.png", "prompt": "p"},
                                  {"id": "regen-1", "url": "https://example.com/a2.png", "prompt": "p2"}],
                "videoHistory": [{"id": "vid-1", "url": "https://example.com/a.mp4"}],
                "activeImageId": "regen-1", "activeVideoId": "vid-1", "mode": "video",
            }},
            {"sceneNumber": 2, "asset": {
                "imageHistory": [{"id": "seed-2", "url": "https://example.com/b.png"}],
                "videoHistory": [], "activeImageId": "seed-2", "activeVideoId": None, "mode": "image",
            }},
        ],
    }
    synced = scenes_from_job(edited_job)
    assert synced[0]["mode"] == "video"
    assert synced[0]["video_url"] == "https://example.com/a.mp4"
    assert synced[0]["image_url"] == "https://example.com/a2.png"  # regenerated image, not the seed
    assert synced[1]["mode"] == "image"
    assert "video_url" not in synced[1]
    print("ok  scenes_from_job resolves active image/video per scene correctly")
