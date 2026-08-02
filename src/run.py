#!/usr/bin/env python3
"""Christian Story pipeline driver — one Baserow row -> finished video, pushed
to ClickUp.

Nothing is kept on local disk: Railway has no volume, so a redeploy used to wipe
runs/<row_id>/ mid-job and strand it. The Supabase job row (bible_well_jobs) is
the only durable state — scenes and their images land there as they're produced,
render reads scenes straight back out of it, and renderUrl/clickupPushedAt on the
payload are what stop a rerun re-paying for a Lambda render or prepending the
video line to the same ClickUp task twice. Everything upstream of the scene list
(context, narration cut, dossier, cast, director) is in-memory only and simply
re-runs: a failed prepare re-does the whole prepare, images included. A failed
stage raises immediately and stops the process — nothing retries silently.

This pipeline NEVER writes scripts, NEVER generates its own narration audio,
and NEVER writes back to Baserow — row selection is the caller's job (n8n
picks the row_id and fires /ingest, already closing its own side of the job
immediately). script/voice_url both already exist on the row by the time
run_pipeline(row_id) reads it. The alignment stage runs real Whisper+DTW
against the row's OWN downloaded voice_url, never a freshly-TTS'd file (that
only happens in scene_engine.py's __main__ self-test, which has no real row
to test against).

  baserow(get_row) -> context(infer_context) -> characters(agents/character_ledger
  + agents/character_sheet — who's worth tracking, one full-body reference image
  each) -> scenes(break_into_scenes, characters-aware) -> wardrobe
  (agents/character_wardrobe — which significant recurring contexts need their
  own outfit variant, one i2i variant reference image each) -> [production UI:
  human approves the wardrobe review before any scene image is generated] ->
  images (agents/scene_compositor, gpt-image-2 i2i per scene against each
  present tracked character's base or wardrobe-variant reference image — no
  vision-QA anywhere in this pipeline, match/no-match is a human call off the
  production UI) -> download narration -> whisper_words
  -> align(align_scene_durations, real Whisper+DTW — duration_seconds lands on
  every scene here, in prepare_images_and_align, so the production UI can show
  it before render) -> [production UI review/edit] -> render_pipeline(): remotion/src/scenes.json
  (scenes + narrationUrl + whisper words, for <Captions>'s current-word
  highlight) -> Remotion Lambda render (deploy:site + render:remote — NEVER local
  `remotion render`, that freezes the machine) -> S3 -> ClickUp

Usage:
  python3 src/run.py <baserow_row_id>   (from the repo root)
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
RENDER_DIR = os.path.join(PROJECT_ROOT, "remotion")
if HERE not in sys.path:
    sys.path.insert(0, HERE)
UTILS_DIR = os.path.join(PROJECT_ROOT, "utils")
if UTILS_DIR not in sys.path:
    sys.path.insert(0, UTILS_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import baserow                          # src/
import clickup as heritage_clickup      # src/: push_video()
import s3 as heritage_s3                # src/: put_file()
import scene_engine                     # src/
import supabase_jobs                    # src/: production-UI job row
from agents.character_ledger import client as character_ledger
from agents.character_sheet import client as character_sheet
from agents.character_wardrobe import client as character_wardrobe
from agents.scene_compositor import client as scene_compositor
from agents.story_dossier import client as story_dossier_agent
from agents.visual_director import client as visual_director

# Cooperative cancellation. ingest_server.py replaces this with a lookup into its
# own _cancelled_ids set; a plain CLI run has nothing to cancel it, so the
# default always says no.
is_cancelled = lambda row_id: False


class Cancelled(Exception):
    """The job was cancelled, so prepare_pipeline stopped — at the next stage
    boundary, or at the next finished image inside compose_all. Everything
    finished before that point is kept: scenes and images already written to the
    job row."""


def _stage(row_id, stage: str) -> None:
    """One stage boundary: bail out if the job was cancelled while the previous
    stage was running, otherwise publish what we're about to do. Cancelling
    during a stage doesn't interrupt it — except image generation, which checks
    between finished images (see scene_compositor.compose_all)."""
    if is_cancelled(row_id):
        raise Cancelled(f"job {row_id} cancelled before {stage!r}")
    supabase_jobs.set_stage(row_id, stage)


def run_node(cmd: list[str], extra_env: dict | None = None, timeout: int = 3600) -> str:
    """subprocess.run an npm/node script, cwd=render/. Raises with the tail of
    stderr/stdout on a non-zero exit — never swallows a render/deploy failure."""
    print("$ " + " ".join(cmd), flush=True)
    env = {**os.environ, **(extra_env or {})}
    r = subprocess.run(cmd, cwd=RENDER_DIR, env=env, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} {' '.join(cmd[1:3])} exit {r.returncode}: "
                            f"{(r.stderr or r.stdout)[-2000:]}")
    return r.stdout


def _backfill_missing_images(scenes: list[dict]) -> None:
    """Hands-off run, no human review — a blank scene is worse than a repeated one.
    Fill any scene['image_url'] left None with the nearest neighbor's image_url
    (previous scene preferred, else next), in place. No-op if every scene failed
    (nothing to borrow from)."""
    for i, s in enumerate(scenes):
        if s["image_url"]:
            continue
        for j in list(range(i - 1, -1, -1)) + list(range(i + 1, len(scenes))):
            if scenes[j]["image_url"]:
                s["image_url"] = scenes[j]["image_url"]
                s["generation_method"] = f"neighbor:{scenes[j]['scene_number']}"
                break


def _transcribe(voice_url: str) -> tuple[list[dict], float]:
    """Whisper word timestamps for the row's OWN narration (never a fresh TTS
    call). The mp3 is scratch — downloaded to a tempfile and always unlinked,
    same as src/gpt_image.py — so both prepare and render just re-fetch the
    already-public voice_url instead of relying on a file surviving between
    them."""
    fd, path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    try:
        print("  narration: downloading voice_url...", flush=True)
        baserow.download(voice_url, path)
        print("  whisper: whisper_words()...", flush=True)
        return scene_engine.whisper_words(path)
    finally:
        os.path.exists(path) and os.unlink(path)


def prepare_cast_and_scenes(row_id) -> dict:
    """Stages 1-7: script -> context -> narration cut -> dossier -> cast ->
    director -> scenes -> wardrobe variants. Ends by upserting an
    'awaiting_wardrobe_approval' job row to Supabase (bible_well_jobs) instead of
    generating any scene images — a human reviews the character wardrobe (base
    image + each significant-context variant) in the production UI and fires
    POST /jobs/{row_id}/approve-wardrobe once satisfied, which is what runs
    prepare_images_and_align() below. row_id is handed to us explicitly (n8n
    picks it via /ingest, or a human passes it on the CLI) — this pipeline never
    scans or writes Baserow itself, only reads the one row it's told to process.

    Nothing here is cached on disk, so a retry re-runs every stage through
    scene-cutting. Wardrobe itself IS idempotent though: if the job already has
    characters carrying non-empty variants (this stage already completed once),
    that decision is reused rather than re-paid for — same posture as
    render_pipeline's renderUrl check."""
    row = baserow.get_row(row_id)
    print(f"== row {row_id}: {row.get('title')!r}")
    _stage(row_id, "Reading script")

    script = row.get("script") or ""
    if not script.strip():
        raise RuntimeError(f"row {row_id} has an empty script — nothing to break into scenes")
    voice_url = row.get("voice_url")
    if not voice_url:
        raise RuntimeError(f"row {row_id} has no voice_url — voice_status=done but nothing to align")
    clickup_url = row.get("clickup_url")
    if not clickup_url:
        raise RuntimeError(f"row {row_id} has no clickup_url — nowhere to push the finished video")

    # 1 CONTEXT
    _stage(row_id, "Analyzing story context")
    context = scene_engine.infer_context(script)

    # 2 NARRATION CUT — the ONE place narration gets cut into chronological
    # snippets (scene_engine.cut_narration_scenes: lossless, verbatim-anchored).
    # Every later stage (the director's emotional scoring, scene authoring)
    # consumes this exact list by position instead of re-segmenting the same
    # script a second time — that double segmentation is what used to let a
    # scene's caption and its own emotional beat quietly drift apart.
    _stage(row_id, "Cutting narration into scenes")
    print("  narration cut: cut_narration_scenes()...", flush=True)
    narration_snippets = scene_engine.cut_narration_scenes(script)
    print(f"  narration cut: {len(narration_snippets)} verbatim snippets", flush=True)

    # 3 DOSSIER — read the whole script before casting or directing. Source facts
    # remain evidence-backed; unspecified production details are inferred from the
    # full story's professional, social, and wardrobe vibe.
    _stage(row_id, "Building casting dossier")
    print("  dossier: story_dossier.build()...", flush=True)
    story_dossier = story_dossier_agent.build(script)
    print(f"  dossier: {story_dossier['whole_script_vibe']['primary_visual_vibe']}", flush=True)

    # 4 SOURCE CAST — characters that exist in the narration. Reference sheets wait
    # until after the director declares any recurring people invented for its film.
    _stage(row_id, "Identifying tracked characters")
    print("  source cast: character_ledger.build()...", flush=True)
    source_characters = character_ledger.build(
        script,
        context,
        story_dossier=story_dossier,
    )["characters"]
    print(
        f"  source cast: {len(source_characters)} tracked -> "
        f"{[c['id'] for c in source_characters]}",
        flush=True,
    )

    # 5 DIRECTOR — narration and visuals are separate lanes. The director sees
    # the categorical emotional score (one entry per narration snippet, scored by
    # position — never its own invented boundaries), evidence-backed bridge cues,
    # production dossier, and source cast. It declares recurring foreground
    # film-only roles and returns exactly one story beat per narration snippet.
    _stage(row_id, "Directing visual story")
    print("  director: visual_director.build()...", flush=True)
    visual_story = visual_director.build(
        source_characters,
        narration_snippets,
        story_dossier=story_dossier,
    )
    print(
        f"  director: {visual_story['film_title']!r}, "
        f"{len(visual_story['story_beats'])} story beats",
        flush=True,
    )

    # 6 COMPLETE CAST — lock identities for director-invented recurring foreground
    # roles, then generate one reference sheet for every source and film character.
    _stage(row_id, "Casting supporting characters")
    director_characters = character_ledger.build_director_cast(
        visual_story,
        source_characters,
        story_dossier=story_dossier,
    )
    characters = source_characters + director_characters
    print(
        f"  characters: {len(characters)} locked -> {[c['id'] for c in characters]}",
        flush=True,
    )
    _stage(row_id, "Generating character reference images")
    print("  characters: character_sheet.generate_all()...", flush=True)
    characters = character_sheet.generate_all(characters)
    print("  characters: done")

    # 7 SCENES — the pre-cut verbatim narration snippets zipped 1:1 by position
    # with the director's story beats (guaranteed equal counts). Every beat gets
    # both a parallel-world shot (never sees narration) and a literal shot (sees
    # only its own snippet); each beat's own visual_mode tag from the emotional
    # spine picks which one reaches the compositor.
    _stage(row_id, "Cutting scenes and writing image prompts")
    print("  scenes: break_into_scenes()...", flush=True)
    scenes = scene_engine.break_into_scenes(
        narration_snippets,
        characters,
        visual_story=visual_story,
    )
    print(f"  scenes: done ({len(scenes)} scenes)")

    # 7.5 WARDROBE — one whole-film decision per character: which SIGNIFICANT
    # recurring contexts (a wedding, a work uniform) need their own outfit
    # variant, everyday scenes keep the base reference. Idempotent: a resumed
    # job that already ran this once reuses its decision rather than re-paying
    # for it (character_wardrobe.decide() + generate_variants_all() both spend
    # real OpenAI money).
    existing = supabase_jobs.get_job(row_id)
    already_decided = bool(existing) and any(
        (c.get("variants") or []) for c in (existing.get("characters") or [])
    )
    if already_decided:
        print("  wardrobe: variants already decided on a prior run — reusing", flush=True)
        characters = existing["characters"]
    else:
        _stage(row_id, "Deciding wardrobe variants")
        print("  wardrobe: character_wardrobe.decide()...", flush=True)
        characters = character_wardrobe.decide(characters, scenes, story_dossier=story_dossier)
        _stage(row_id, "Generating wardrobe variant images")
        print("  wardrobe: character_sheet.generate_variants_all()...", flush=True)
        characters = character_sheet.generate_variants_all(characters)
        print(
            "  wardrobe: "
            + ", ".join(f"{c['id']}: {len(c.get('variants') or [])} variant(s)" for c in characters),
            flush=True,
        )

    # Publish scenes + characters (with wardrobe variants) and STOP — no scene
    # image has been generated yet. A human reviews/edits/approves the wardrobe
    # in the production UI; POST /jobs/{row_id}/approve-wardrobe is what enqueues
    # prepare_images_and_align() to actually spend on scene image generation.
    _stage(row_id, "Awaiting wardrobe approval")
    payload = supabase_jobs.upsert_scenes(
        row_id, row, scenes, status="awaiting_wardrobe_approval", characters=characters,
    )
    print(f"  job: {payload['id']} status={payload['status']} — waiting for wardrobe approval", flush=True)
    return payload


def prepare_images_and_align(row_id) -> dict:
    """Stages 8-9: images -> narration download + Whisper align
    (duration_seconds per scene). Fired once a human has approved the wardrobe
    review (production UI's approve-wardrobe action) or the CLI auto-approved
    it. Reads scenes/characters straight back out of the Supabase job row
    rather than from in-memory state — nothing survives on local disk between
    prepare_cast_and_scenes() and this call, and a restart can land here on its
    own via ingest_server.py's resume sweep. Ends by upserting a 'ready' job
    row for production-UI review — the human render trigger is unchanged.

    Deliberately never re-passes `characters=` to upsert_scenes: any human edit
    made during wardrobe review (a regenerated base image or variant) must
    survive this write untouched."""
    row = baserow.get_row(row_id)
    voice_url = row.get("voice_url")
    if not voice_url:
        raise RuntimeError(f"row {row_id} has no voice_url — voice_status=done but nothing to align")

    job = supabase_jobs.get_job(row_id)
    if job is None:
        raise RuntimeError(f"no Supabase job row for {row_id} — run prepare_cast_and_scenes({row_id!r}) first")
    scenes = supabase_jobs.full_scenes_from_job(job)
    characters = job.get("characters") or []

    # 8 IMAGES — agents/scene_compositor, i2i per scene against whichever tracked
    # characters (and, where the wardrobe stage assigned one, wardrobe variant)
    # that scene calls for, in parallel (t2i fallback only). No vision-QA
    # anywhere — a human reviews the images in the production UI and judges
    # consistency. The count lives in the job's total/completed counters now,
    # so the label stays a plain verb the UI can show as-is.
    _stage(row_id, "Generating images")
    print("  images: scene_compositor.compose_all()...", flush=True)
    scenes = scene_compositor.compose_all(
        scenes, characters, row_id=row_id, is_cancelled=lambda: is_cancelled(row_id),
    )
    miss = [s["scene_number"] for s in scenes if not s["image_url"]]
    if miss:
        print(f"  images: {len(scenes) - len(miss)}/{len(scenes)} generated, "
              f"{len(miss)} MISSING, backfilling from neighbor: {miss}", flush=True)
        _backfill_missing_images(scenes)
    print("  images: done")

    # 9 NARRATION DURATION — real Whisper+DTW alignment now, not at render time,
    # so every scene carries a real duration_seconds before a human ever sees it
    # in the production UI — that's how they know how many seconds of video a
    # scene actually needs before generating or uploading a clip for it.
    _stage(row_id, "Transcribing narration (Whisper)")
    words, total_duration = _transcribe(voice_url)
    print(f"  whisper: done ({len(words)} words, {total_duration:.1f}s)")

    _stage(row_id, "Aligning scene durations to narration")
    print("  align: align_scene_durations() (real Whisper+DTW)...", flush=True)
    scenes = scene_engine.align_scene_durations(scenes, words, total_duration)
    print("  align: done")

    # Essentially a status flip to 'ready' now — scenes and images are already in
    # the row (published above, then filled in one by one by compose_all). This
    # rewrite is what carries duration_seconds and any neighbor-backfilled image
    # over; it MERGES rather than overwrites, so an image a human regenerated in
    # the UI while this run was still going isn't thrown away here.
    _stage(row_id, "Finishing up")
    print("  job: flipping the Supabase row to 'ready' for production-UI review...", flush=True)
    payload = supabase_jobs.upsert_scenes(row_id, row, scenes)
    print(f"  job: {payload['id']} status={payload['status']}", flush=True)

    return payload


def render_pipeline(row_id) -> str:
    """Stages 11-13: Remotion Lambda render -> S3 -> ClickUp (narration
    download + Whisper+DTW align already happened in prepare_pipeline(), stage
    9). Fired manually (production UI's Render button)
    once prepare_pipeline()'s job has been reviewed/edited. Scenes come straight
    out of the Supabase job row — the only place they live — so every per-scene
    asset choice made in the UI (regenerated images, Pexels picks, image/video
    overrides) reaches the final video, and a render fired hours or days after
    prepare, on a container that has since been redeployed, still works."""
    row = baserow.get_row(row_id)
    voice_url = row.get("voice_url")
    if not voice_url:
        raise RuntimeError(f"row {row_id} has no voice_url — voice_status=done but nothing to align")
    clickup_url = row.get("clickup_url")
    if not clickup_url:
        raise RuntimeError(f"row {row_id} has no clickup_url — nowhere to push the finished video")

    job = supabase_jobs.get_job(row_id)
    if job is None:
        raise RuntimeError(f"no Supabase job row for {row_id} — run prepare_pipeline({row_id!r}) first")

    scenes = supabase_jobs.scenes_from_job(job)
    print(f"  job: {len(scenes)} scenes from the Supabase row, including every "
          "production-UI edit (regenerated images, Pexels picks, video overrides)", flush=True)

    supabase_jobs.set_status(row_id, "rendering")
    try:
        video_url = _render(row_id, job, scenes, voice_url, clickup_url)
    except Exception as e:
        supabase_jobs.set_status(row_id, "failed", error=str(e), failedStage="render")
        raise
    supabase_jobs.set_status(row_id, "rendered", renderUrl=video_url)
    return video_url


def _render(row_id, job, scenes, voice_url, clickup_url) -> str:
    # 11 RENDER — write remotion/src/scenes.json ({scenes, narrationUrl, words}),
    # narrationUrl = the row's OWN voice_url (already public, no rehost), words =
    # whisper words for remotion's <Captions> (highlights whichever word is
    # currently being spoken) — re-transcribed here rather than cached anywhere,
    # since nothing survives on disk between prepare and render. Then Remotion
    # Lambda (deploy:site + render:remote). NEVER local `remotion render` —
    # freezes the machine, banned per root CLAUDE.md.
    #
    # GATE: payload.renderUrl. A rerun after a successful render (a restart
    # mid-ClickUp-push, a re-queued job) must never re-deploy/re-render — that's
    # a full Lambda render's worth of real money, spent silently.
    video_url = job.get("renderUrl")
    if not video_url:
        # duration_seconds already came from prepare_pipeline's align stage via the
        # job row (that's what the production UI shows per scene); only the caption
        # words need computing here.
        words, _ = _transcribe(voice_url)

        remotion_scenes_path = os.path.join(RENDER_DIR, "src", "scenes.json")
        payload = scene_engine.build_remotion_payload(scenes, narration_url=voice_url, words=words)
        json.dump(payload, open(remotion_scenes_path, "w"), indent=2)
        total_frames = sum(s["duration_frames"] for s in payload["scenes"])
        print(f"  render: wrote {remotion_scenes_path} ({total_frames} frames @ 30fps)")

        print("  render: deploy:site...", flush=True)
        deploy_out = run_node(["npm", "run", "deploy:site"], timeout=900)
        print(deploy_out[-1500:])
        m = re.search(r"REMOTION_SERVE_URL=(\S+)", deploy_out)
        if not m:
            raise RuntimeError("deploy:site produced no REMOTION_SERVE_URL in its output")
        serve_url = m.group(1)

        print("  render: render:remote (Lambda)...", flush=True)
        render_out = run_node(["npm", "run", "render:remote"],
                               extra_env={"REMOTION_SERVE_URL": serve_url}, timeout=3600)
        print(render_out[-1500:])

        rendered_mp4 = os.path.join(RENDER_DIR, "out", "preview-lambda.mp4")
        if not os.path.exists(rendered_mp4):
            raise RuntimeError(f"render:remote reported success but {rendered_mp4} is missing")

        # 12 S3 — raw public url, NEVER presigned (that's what gets shared for review).
        print("  s3: uploading rendered mp4...", flush=True)
        video_url = heritage_s3.put_file(rendered_mp4, f"bible-well/renders/{row_id}.mp4")
        if not video_url:
            raise RuntimeError("s3 put_file failed — rendered mp4 not uploaded")
        # Close the render gate the moment the mp4 is somewhere durable, not at
        # the end of render_pipeline() — a ClickUp failure below must not cost
        # another Lambda render on the retry.
        supabase_jobs.set_status(row_id, "rendering", renderUrl=video_url)
        print(f"  s3: {video_url}")

    # 13 CLICKUP — update-existing-task only, never create. push_video() itself never
    # raises (falls back to a comment on a description-PUT failure) — but if BOTH
    # routes fail it returns False, and we raise here so this run isn't silently
    # marked done with nowhere the video actually landed. This is the pipeline's
    # last stage — Baserow is never written back to; the ingest trigger (n8n)
    # already closed its own side of the job when it fired /ingest.
    #
    # GATE: payload.clickupPushedAt. push_video() prepends "🎬 VIDEO: <url>"
    # unconditionally and nothing on the ClickUp side detects a duplicate, so
    # without this a second render pass silently prepends the same line twice to
    # the same task description.
    if not job.get("clickupPushedAt"):
        print("  clickup: push_video()...", flush=True)
        ok = heritage_clickup.push_video(clickup_url, video_url)
        if not ok:
            raise RuntimeError(f"clickup push_video failed for row {row_id} -> {clickup_url}")
        supabase_jobs.set_status(row_id, "rendering",
                                 clickupPushedAt=datetime.now(timezone.utc).isoformat())
        print("  clickup: done")

    print(f"== DONE row {row_id} -> {video_url}")
    return video_url


def run_pipeline(row_id, auto_approve_wardrobe: bool = True) -> str | None:
    """Back-compat: prepare then render in one unattended call — the CLI's
    `python3 src/run.py <row_id>` contract. auto_approve_wardrobe=True (the
    CLI default) skips the human wardrobe-review gate and runs straight
    through, same "unattended local/dev" posture this entrypoint always had.
    ingest_server.py never calls this function — it calls
    prepare_cast_and_scenes()/prepare_images_and_align() directly, so the
    production/UI path always hard-pauses for wardrobe approval regardless of
    this default."""
    prepare_cast_and_scenes(row_id)
    if not auto_approve_wardrobe:
        return None
    supabase_jobs.set_status(
        row_id, "preparing", wardrobeApprovedAt=datetime.now(timezone.utc).isoformat(),
    )
    prepare_images_and_align(row_id)
    return render_pipeline(row_id)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: run.py <baserow_row_id>")
    run_pipeline(sys.argv[1])
