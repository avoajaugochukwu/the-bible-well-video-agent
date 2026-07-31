#!/usr/bin/env python3
"""Christian Story pipeline driver — one Baserow row -> finished video, pushed
to ClickUp.

Resumable: each stage writes an artifact into runs/<row_id>/ and SKIPS if that
artifact already exists, same pattern as true-crime-news/run.py and
cold-case/run.py (this file is a direct port of that design onto heritage's
stage list). A failed stage raises immediately and stops the process — nothing
retries silently, no paid API (OpenAI scene breakdown, Krea images, Remotion
Lambda render) gets hit again without you seeing why it failed. Fix the cause,
rerun with the same row_id; completed stages are skipped, so you resume
exactly where it broke.

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
  each) -> scenes(break_into_scenes, characters-aware) -> images
  (agents/scene_compositor, gpt-image-2 i2i per scene against each present tracked
  character's reference image — no vision-QA anywhere in this pipeline, match/no-match is a human call
  off the gallery) -> gallery(build_gallery, non-blocking review) -> download
  narration -> whisper_words (cached, computed ONCE) ->
  align(align_scene_durations, real Whisper+DTW) -> remotion/src/scenes.json
  (scenes + narrationUrl + the same whisper words, for <Captions>'s current-word
  highlight) -> Remotion Lambda render (deploy:site + render:remote — NEVER local
  `remotion render`, that freezes the machine) -> S3 -> ClickUp -> prune_runs

Usage:
  python3 src/run.py <baserow_row_id>   (from the repo root)
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
RENDER_DIR = os.path.join(PROJECT_ROOT, "remotion")
RUNS_DIR = os.path.join(PROJECT_ROOT, "runs")
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
import gallery as heritage_gallery      # src/
import scene_engine                     # src/
import supabase_jobs                    # src/: production-UI job row
import cleanup                          # utils/
from agents.character_ledger import client as character_ledger
from agents.character_sheet import client as character_sheet
from agents.scene_compositor import client as scene_compositor
from agents.story_dossier import client as story_dossier_agent
from agents.visual_director import client as visual_director

DONE_MARKER = "done.marker"


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


def prepare_pipeline(row_id) -> dict:
    """Stages 1-9: script -> characters -> director -> scenes -> images ->
    gallery. Ends by upserting a 'ready' job row to Supabase (bible_well_jobs)
    for the production UI instead of continuing straight into render — a human
    now reviews/edits scenes there and fires render_pipeline() manually when
    satisfied, rather than this pipeline rendering unattended every time.
    row_id is handed to us explicitly (n8n picks it via /ingest, or a human
    passes it on the CLI) — this pipeline never scans or writes Baserow itself,
    only reads the one row it's told to process."""
    row = baserow.get_row(row_id)
    rd = os.path.join(RUNS_DIR, str(row_id))
    os.makedirs(rd, exist_ok=True)
    print(f"== row {row_id}: {row.get('title')!r}\n== run dir: {rd}")

    row_path = os.path.join(rd, "row.json")
    if not os.path.exists(row_path):
        json.dump(row, open(row_path, "w"), indent=2)
    script = row.get("script") or ""
    if not script.strip():
        raise RuntimeError(f"row {row_id} has an empty script — nothing to break into scenes")
    voice_url = row.get("voice_url")
    if not voice_url:
        raise RuntimeError(f"row {row_id} has no voice_url — voice_status=done but nothing to align")
    clickup_url = row.get("clickup_url")
    if not clickup_url:
        raise RuntimeError(f"row {row_id} has no clickup_url — nowhere to push the finished video")

    # 1 CONTEXT — cheap to recompute, but cached anyway so a rerun never re-pays for
    # it and stays identical across a resumed run.
    context_path = os.path.join(rd, "context.json")
    context_current = False
    if os.path.exists(context_path):
        context = json.load(open(context_path))
        context_current = (
            context.get("context_contract_version")
            == scene_engine.CONTEXT_CONTRACT_VERSION
        )
    if not context_current:
        if os.path.exists(context_path):
            print("  context: cached contract is outdated; re-analyzing story meaning", flush=True)
        context = scene_engine.infer_context(script)
        json.dump(context, open(context_path, "w"), indent=2)

    # 2 NARRATION CUT — the ONE place narration gets cut into chronological
    # snippets (scene_engine.cut_narration_scenes: lossless, verbatim-anchored).
    # Every later stage (the director's emotional scoring, scene authoring)
    # consumes this exact list by position instead of re-segmenting the same
    # script a second time — that double segmentation is what used to let a
    # scene's caption and its own emotional beat quietly drift apart.
    narration_snippets_path = os.path.join(rd, "narration-snippets.json")
    if os.path.exists(narration_snippets_path):
        narration_snippets = json.load(open(narration_snippets_path))
    else:
        print("  narration cut: cut_narration_scenes()...", flush=True)
        narration_snippets = scene_engine.cut_narration_scenes(script)
        json.dump(narration_snippets, open(narration_snippets_path, "w"), indent=2)
        print(f"  narration cut: {len(narration_snippets)} verbatim snippets", flush=True)

    # 3 DOSSIER — read the whole script before casting or directing. Source facts
    # remain evidence-backed; unspecified production details are inferred from the
    # full story's professional, social, and wardrobe vibe.
    dossier_path = os.path.join(rd, "story-dossier.json")
    dossier_current = False
    if os.path.exists(dossier_path):
        story_dossier = json.load(open(dossier_path))
        dossier_current = (
            story_dossier.get("story_dossier_contract_version")
            == story_dossier_agent.STORY_DOSSIER_CONTRACT_VERSION
        )
    if not dossier_current:
        print("  dossier: story_dossier.build()...", flush=True)
        story_dossier = story_dossier_agent.build(script)
        json.dump(story_dossier, open(dossier_path, "w"), indent=2)
        print(
            "  dossier: "
            f"{story_dossier['whole_script_vibe']['primary_visual_vibe']}",
            flush=True,
        )

    # 4 SOURCE CAST — characters that exist in the narration. Reference sheets wait
    # until after the director declares any recurring people invented for its film.
    source_characters_path = os.path.join(rd, "source-characters.json")
    source_characters_current = False
    if os.path.exists(source_characters_path):
        source_characters = json.load(open(source_characters_path))
        source_characters_current = bool(source_characters) and all(
            c.get("character_contract_version")
            == character_ledger.CHARACTER_CONTRACT_VERSION
            for c in source_characters
        )
    if not source_characters_current:
        print("  source cast: character_ledger.build()...", flush=True)
        source_characters = character_ledger.build(
            script,
            context,
            story_dossier=story_dossier,
        )["characters"]
        json.dump(source_characters, open(source_characters_path, "w"), indent=2)
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
    visual_story_path = os.path.join(rd, "visual-story.json")
    visual_story_current = False
    if os.path.exists(visual_story_path):
        visual_story = json.load(open(visual_story_path))
        visual_story_current = (
            visual_story.get("visual_story_contract_version")
            == visual_director.VISUAL_STORY_CONTRACT_VERSION
            and len(visual_story.get("story_beats") or []) == len(narration_snippets)
        )
    if not visual_story_current:
        print("  director: visual_director.build()...", flush=True)
        visual_story = visual_director.build(
            source_characters,
            narration_snippets,
            story_dossier=story_dossier,
        )
        json.dump(visual_story, open(visual_story_path, "w"), indent=2)
        print(
            f"  director: {visual_story['film_title']!r}, "
            f"{len(visual_story['story_beats'])} story beats",
            flush=True,
        )

    # 6 COMPLETE CAST — lock identities for director-invented recurring foreground
    # roles, then generate one reference sheet for every source and film character.
    characters_path = os.path.join(rd, "characters.json")
    declared_supporting_ids = {
        character["id"]
        for character in visual_story.get("supporting_characters") or []
    }
    expected_character_ids = {
        character["id"] for character in source_characters
    } | declared_supporting_ids
    characters_current = False
    if os.path.exists(characters_path):
        characters = json.load(open(characters_path))
        characters_current = (
            bool(characters)
            and {character.get("id") for character in characters}
            == expected_character_ids
            and all(
                character.get("character_contract_version")
                == character_ledger.CHARACTER_CONTRACT_VERSION
                and character.get("character_sheet_contract_version")
                == character_sheet.CHARACTER_SHEET_CONTRACT_VERSION
                for character in characters
            )
        )
    if not characters_current:
        if os.path.exists(characters_path):
            print(
                "  characters: cast declaration or cached contract changed; regenerating",
                flush=True,
            )
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
        print("  characters: character_sheet.generate_all()...", flush=True)
        characters = character_sheet.generate_all(characters)
        json.dump(characters, open(characters_path, "w"), indent=2)
        print("  characters: done")

    # 7 SCENES — the pre-cut verbatim narration snippets zipped 1:1 by position
    # with the director's story beats (guaranteed equal counts). Every beat gets
    # both a parallel-world shot (never sees narration) and a literal shot (sees
    # only its own snippet); each beat's own visual_mode tag from the emotional
    # spine picks which one reaches the compositor. scenes.json is a single
    # evolving artifact — later stages add keys to it
    # (image_url, then start/end/duration_seconds) rather than writing separate
    # files, so resume-checks below inspect the keys already on each scene rather
    # than a stage-specific filename.
    scenes_path = os.path.join(rd, "scenes.json")
    scenes_current = False
    if os.path.exists(scenes_path):
        scenes = json.load(open(scenes_path))
        scenes_current = bool(scenes) and all(
            s.get("prompt_contract_version") == scene_engine.PROMPT_CONTRACT_VERSION
            and s.get("visual_story_contract_version")
            == visual_director.VISUAL_STORY_CONTRACT_VERSION
            for s in scenes
        )
    scenes_regenerated = not scenes_current
    if scenes_regenerated:
        if os.path.exists(scenes_path):
            print("  scenes: cached prompt contract is outdated; redesigning visual metaphors", flush=True)
        print("  scenes: break_into_scenes()...", flush=True)
        scenes = scene_engine.break_into_scenes(
            narration_snippets,
            characters,
            visual_story=visual_story,
        )
        json.dump(scenes, open(scenes_path, "w"), indent=2)
        print(f"  scenes: done ({len(scenes)} scenes)")
    # 8 IMAGES — agents/scene_compositor, i2i per scene against whichever tracked
    # characters that scene calls for, in parallel (t2i fallback only). No vision-QA anywhere — a human
    # reviews the gallery and judges consistency. The compositor has its own cache
    # contract because final prompt construction can change without changing shot plans.
    images_current = bool(scenes) and all(
        s.get("image_url")
        and s.get("compositor_contract_version")
        == scene_compositor.COMPOSITOR_CONTRACT_VERSION
        for s in scenes
    )
    images_regenerated = not images_current
    if images_regenerated:
        if scenes and any(s.get("image_url") for s in scenes):
            print("  images: cached compositor contract is outdated; regenerating", flush=True)
        print("  images: scene_compositor.compose_all()...", flush=True)
        scenes = scene_compositor.compose_all(scenes, characters)
        miss = [s["scene_number"] for s in scenes if not s["image_url"]]
        if miss:
            print(f"  images: {len(scenes) - len(miss)}/{len(scenes)} generated, "
                  f"{len(miss)} MISSING, backfilling from neighbor: {miss}", flush=True)
            _backfill_missing_images(scenes)
        json.dump(scenes, open(scenes_path, "w"), indent=2)
        print("  images: done")

    # 9 GALLERY — manual-review HTML, non-blocking (never waits on human approval).
    gallery_path = os.path.join(rd, "gallery.html")
    if scenes_regenerated or images_regenerated or not os.path.exists(gallery_path):
        heritage_gallery.build_gallery(scenes, gallery_path)
        print(f"  gallery: {gallery_path}")

    print("  job: upserting 'ready' row to Supabase for production-UI review...", flush=True)
    job_row = supabase_jobs.build_job_payload(row_id, row, scenes)
    supabase_jobs.upsert_job(job_row)
    print(f"  job: {job_row['id']} status={job_row['status']}", flush=True)

    return job_row["payload"]


def render_pipeline(row_id) -> str:
    """Stages 10-13: narration download -> Whisper+DTW align -> Remotion Lambda
    render -> S3 -> ClickUp. Fired manually (production UI's Render button)
    once prepare_pipeline()'s job has been reviewed/edited. Pulls the current
    Supabase job row first and syncs its per-scene asset choices (regenerated
    images, Pexels picks, image/video overrides) onto the local scenes.json
    before rendering, so UI edits actually reach the final video."""
    row = baserow.get_row(row_id)
    rd = os.path.join(RUNS_DIR, str(row_id))
    if not os.path.exists(rd):
        raise RuntimeError(f"no runs/{row_id}/ — run prepare_pipeline({row_id!r}) first")
    voice_url = row.get("voice_url")
    if not voice_url:
        raise RuntimeError(f"row {row_id} has no voice_url — voice_status=done but nothing to align")
    clickup_url = row.get("clickup_url")
    if not clickup_url:
        raise RuntimeError(f"row {row_id} has no clickup_url — nowhere to push the finished video")

    scenes_path = os.path.join(rd, "scenes.json")
    scenes = json.load(open(scenes_path))

    job = supabase_jobs.get_job(row_id)
    if job is None:
        raise RuntimeError(f"no Supabase job row for {row_id} — run prepare_pipeline({row_id!r}) first")
    scenes = supabase_jobs.sync_scenes_from_job(scenes, job)
    json.dump(scenes, open(scenes_path, "w"), indent=2)
    print("  job: synced production-UI edits (regenerated images, Pexels picks, "
          "video overrides) into scenes.json before render", flush=True)

    supabase_jobs.set_status(row_id, "rendering")
    try:
        video_url = _render(row_id, rd, scenes, scenes_path, voice_url, clickup_url)
    except Exception as e:
        supabase_jobs.set_status(row_id, "failed", error=str(e))
        raise
    supabase_jobs.set_status(row_id, "rendered", renderUrl=video_url)
    return video_url


def _render(row_id, rd, scenes, scenes_path, voice_url, clickup_url) -> str:
    # 10 ALIGN — download the row's OWN narration (never a fresh TTS call — that's
    # only scene_engine.py's self-test), then real Whisper+DTW alignment against it.
    narration_path = os.path.join(rd, "narration.mp3")
    if not os.path.exists(narration_path):
        print("  narration: downloading voice_url...", flush=True)
        baserow.download(voice_url, narration_path)
        print("  narration: done")

    # Whisper words are cached once and reused by BOTH align_scene_durations()
    # below and the remotion payload's caption words further down —
    # transcribing the same narration.mp3 twice would double the (CPU-bound,
    # non-trivial) whisper cost for no reason. Same resumable-artifact pattern
    # as every other stage here.
    whisper_words_path = os.path.join(rd, "whisper-words.json")
    if not os.path.exists(whisper_words_path):
        print("  whisper: whisper_words()...", flush=True)
        words, total_duration = scene_engine.whisper_words(narration_path)
        json.dump({"words": words, "total_duration": total_duration},
                  open(whisper_words_path, "w"), indent=2)
        print(f"  whisper: done ({len(words)} words, {total_duration:.1f}s)")
    else:
        _ww = json.load(open(whisper_words_path))
        words, total_duration = _ww["words"], _ww["total_duration"]

    if not scenes or "duration_seconds" not in scenes[0]:
        print("  align: align_scene_durations() (real Whisper+DTW)...", flush=True)
        scenes = scene_engine.align_scene_durations(scenes, words, total_duration)
        json.dump(scenes, open(scenes_path, "w"), indent=2)
        print("  align: done")

    # 11 RENDER — write remotion/src/scenes.json ({scenes, narrationUrl, words}),
    # narrationUrl = the row's OWN voice_url (already public, no rehost), words =
    # the same whisper words computed above (remotion's <Captions> highlights
    # whichever word is currently being spoken). Then Remotion Lambda (deploy:site
    # + render:remote). NEVER local `remotion render` — freezes the machine,
    # banned per root CLAUDE.md. Gated on video-url.txt so a rerun after a
    # successful render never re-deploys/re-renders (real Lambda $).
    video_url_path = os.path.join(rd, "video-url.txt")
    if not os.path.exists(video_url_path):
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
        local_copy = os.path.join(rd, "output.mp4")
        with open(rendered_mp4, "rb") as src, open(local_copy, "wb") as dst:
            dst.write(src.read())

        # 12 S3 — raw public url, NEVER presigned (that's what gets shared for review).
        print("  s3: uploading rendered mp4...", flush=True)
        video_url = heritage_s3.put_file(local_copy, f"bible-well/renders/{row_id}.mp4")
        if not video_url:
            raise RuntimeError("s3 put_file failed — rendered mp4 not uploaded")
        open(video_url_path, "w").write(video_url)
        print(f"  s3: {video_url}")
    video_url = open(video_url_path).read().strip()

    # 13 CLICKUP — update-existing-task only, never create. push_video() itself never
    # raises (falls back to a comment on a description-PUT failure) — but if BOTH
    # routes fail it returns False, and we raise here so this run isn't silently
    # marked done with nowhere the video actually landed. Gated so a rerun never
    # double-prepends the video line. This is the pipeline's last stage — Baserow
    # is never written back to; the ingest trigger (n8n) already closed its own
    # side of the job when it fired /ingest.
    done_marker_path = os.path.join(rd, DONE_MARKER)
    if not os.path.exists(done_marker_path):
        print("  clickup: push_video()...", flush=True)
        ok = heritage_clickup.push_video(clickup_url, video_url)
        if not ok:
            raise RuntimeError(f"clickup push_video failed for row {row_id} -> {clickup_url}")
        open(done_marker_path, "w").write(video_url)
        print("  clickup: done")

    print(f"== DONE row {row_id} -> {video_url}")

    # video's in S3 + ClickUp now — local run artifacts (narration.mp3, output.mp4
    # backup, etc.) have nothing left to prove. Keeps the single most recent done
    # run for 24h (debugging), prunes the rest.
    removed = cleanup.prune_runs(RUNS_DIR, DONE_MARKER)
    if removed:
        print(f"  cleanup: pruned {len(removed)} finished run dir(s)")

    return video_url


def run_pipeline(row_id) -> str | None:
    """Back-compat: prepare then render in one unattended call, same behavior
    as before the production UI existed — still what the CLI and the plain
    `python3 src/run.py <row_id>` flow use. The /ingest HTTP path now calls
    prepare_pipeline() alone; render_pipeline() is fired separately, manually,
    from the production UI's Render button."""
    prepare_pipeline(row_id)
    return render_pipeline(row_id)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: run.py <baserow_row_id>")
    run_pipeline(sys.argv[1])
