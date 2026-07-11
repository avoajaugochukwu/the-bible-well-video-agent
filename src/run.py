#!/usr/bin/env python3
"""Heritage Decoded pipeline driver — one Baserow row -> finished video, pushed
to ClickUp, row flipped to done.

Resumable: each stage writes an artifact into runs/<row_id>/ and SKIPS if that
artifact already exists, same pattern as true-crime-news/run.py and
cold-case/run.py (this file is a direct port of that design onto heritage's
stage list). A failed stage raises immediately and stops the process — nothing
retries silently, no paid API (OpenAI scene breakdown, Krea images, Remotion
Lambda render) gets hit again without you seeing why it failed. Fix the cause,
rerun `python3 run.py`; completed stages are skipped, so you resume exactly
where it broke.

This pipeline NEVER writes scripts and NEVER generates its own narration audio
— both already exist on the Baserow row (`script`, `voice_url`) by the time
`next_ready()` picks it up. The alignment stage runs real Whisper+DTW against
the row's OWN downloaded voice_url, never a freshly-TTS'd file (that only
happens in scene_engine.py's __main__ self-test, which has no real row to test
against).

  baserow(next_ready) -> scenes(break_into_scenes) -> images(generate_images)
  -> gallery(build_gallery, non-blocking review) -> download narration
  -> whisper_words (cached, computed ONCE) -> align(align_scene_durations,
  real Whisper+DTW) -> cards(director.plan_cards, text-overlay timeline)
  -> remotion/src/scenes.json -> Remotion Lambda render (deploy:site +
  render:remote — NEVER local `remotion render`, that freezes the machine)
  -> S3 -> ClickUp -> Baserow mark_done -> prune_runs

Usage:
  python3 src/run.py   (from the repo root)
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

import baserow                          # src/
import clickup as heritage_clickup      # src/: push_video()
import s3 as heritage_s3                # src/: put_file()
import gallery as heritage_gallery      # src/
import scene_engine                     # src/
import director as heritage_director    # src/: plan_cards()
import cleanup                          # utils/

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


def run_pipeline() -> str | None:
    row = baserow.next_ready()
    if not row:
        print("== no ready Heritage Decoded row (script_status=done, voice_status=done, "
              "video_processed!=done)")
        return None

    row_id = row["id"]
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

    # 1/2 SCENES — LLM breakdown (context -> snippets -> per-batch authoring), same
    # chain scene_engine.py's own __main__ self-test uses. scenes.json is a single
    # evolving artifact (same shape the manual runs in runs/1027, runs/1947 already
    # produced) — later stages add keys to it (image_url, then start/end/
    # duration_seconds) rather than writing separate files, so resume-checks below
    # inspect the keys already on each scene rather than a stage-specific filename.
    # context.json is small and cheap to recompute, but cached anyway so a rerun
    # never re-pays for it and the archival lane's vision-QA prompts (era/place)
    # stay identical across a resumed run.
    context_path = os.path.join(rd, "context.json")
    if not os.path.exists(context_path):
        context = scene_engine.infer_context(script)
        json.dump(context, open(context_path, "w"), indent=2)
    else:
        context = json.load(open(context_path))

    scenes_path = os.path.join(rd, "scenes.json")
    if not os.path.exists(scenes_path):
        print("  scenes: break_into_scenes()...", flush=True)
        scenes = scene_engine.break_into_scenes(script, context=context)
        json.dump(scenes, open(scenes_path, "w"), indent=2)
        print(f"  scenes: done ({len(scenes)} scenes)")
    else:
        scenes = json.load(open(scenes_path))

    # 3 IMAGES — multi-lane per scene (archival/stock/graphic/Krea), in parallel.
    # Skip if every scene already carries an image_url (i.e. this scenes.json
    # already went through generate_images()).
    if not scenes or "image_url" not in scenes[0]:
        print("  images: generate_images()...", flush=True)
        scenes = scene_engine.generate_images(scenes, context)
        json.dump(scenes, open(scenes_path, "w"), indent=2)
        print("  images: done")

    # 4 GALLERY — manual-review HTML, non-blocking (never waits on human approval).
    gallery_path = os.path.join(rd, "gallery.html")
    if not os.path.exists(gallery_path):
        heritage_gallery.build_gallery(scenes, gallery_path)
        print(f"  gallery: {gallery_path}")

    # 5 ALIGN — download the row's OWN narration (never a fresh TTS call — that's
    # only scene_engine.py's self-test), then real Whisper+DTW alignment against it.
    narration_path = os.path.join(rd, "narration.mp3")
    if not os.path.exists(narration_path):
        print("  narration: downloading voice_url...", flush=True)
        baserow.download(voice_url, narration_path)
        print("  narration: done")

    # Whisper words are cached once and reused by BOTH align_scene_durations()
    # below and director.plan_cards() further down — transcribing the same
    # narration.mp3 twice would double the (CPU-bound, non-trivial) whisper cost
    # for no reason. Same resumable-artifact pattern as every other stage here.
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

    # 6 CARDS — LLM "director" planning pass: text-overlay cards (checklist,
    # photo-title, big-stat, etc.) laid over the rendered scenes. Reuses the
    # same whisper words + total_duration computed above rather than re-deriving
    # timing from scratch.
    cards_path = os.path.join(rd, "cards.json")
    if not os.path.exists(cards_path):
        print("  cards: director.plan_cards()...", flush=True)
        cards = heritage_director.plan_cards(script, row.get("title") or "", scenes, words, total_duration)
        json.dump(cards, open(cards_path, "w"), indent=2)
        print(f"  cards: done ({len(cards)} cards)")
    else:
        cards = json.load(open(cards_path))

    # 7/8 RENDER — write remotion/src/scenes.json ({scenes, narrationUrl, cards}),
    # narrationUrl = the row's OWN voice_url (already public, no rehost), then
    # Remotion Lambda (deploy:site + render:remote). NEVER local `remotion render`
    # — freezes the machine, banned per root CLAUDE.md. Gated on video-url.txt so
    # a rerun after a successful render never re-deploys/re-renders (real Lambda $).
    video_url_path = os.path.join(rd, "video-url.txt")
    if not os.path.exists(video_url_path):
        remotion_scenes_path = os.path.join(RENDER_DIR, "src", "scenes.json")
        payload = scene_engine.build_remotion_payload(scenes, narration_url=voice_url, cards=cards)
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

        # 9 S3 — raw public url, NEVER presigned (that's what gets shared for review).
        print("  s3: uploading rendered mp4...", flush=True)
        video_url = heritage_s3.put_file(local_copy, f"heritage/renders/{row_id}.mp4")
        if not video_url:
            raise RuntimeError("s3 put_file failed — rendered mp4 not uploaded")
        open(video_url_path, "w").write(video_url)
        print(f"  s3: {video_url}")
    video_url = open(video_url_path).read().strip()

    # 10 CLICKUP — update-existing-task only, never create. push_video() itself never
    # raises (falls back to a comment on a description-PUT failure) — but if BOTH
    # routes fail it returns False, and we raise here so mark_done never fires on a
    # video nobody can find. Gated so a rerun never double-prepends the video line.
    clickup_marker = os.path.join(rd, "clickup-pushed.txt")
    if not os.path.exists(clickup_marker):
        print("  clickup: push_video()...", flush=True)
        ok = heritage_clickup.push_video(clickup_url, video_url)
        if not ok:
            raise RuntimeError(f"clickup push_video failed for row {row_id} -> {clickup_url}")
        open(clickup_marker, "w").write(video_url)
        print("  clickup: done")

    # 11 BASEROW — only after S3 + ClickUp both succeeded (checked above).
    done_marker_path = os.path.join(rd, DONE_MARKER)
    if not os.path.exists(done_marker_path):
        print("  baserow: mark_done()...", flush=True)
        baserow.mark_done(row_id)
        open(done_marker_path, "w").write(video_url)
        print("  baserow: done")

    print(f"== DONE row {row_id} -> {video_url}")

    # video's in S3 + ClickUp + Baserow now — local run artifacts (narration.mp3,
    # output.mp4 backup, etc.) have nothing left to prove. Keeps the single most
    # recent done run for 24h (debugging), prunes the rest.
    removed = cleanup.prune_runs(RUNS_DIR, DONE_MARKER)
    if removed:
        print(f"  cleanup: pruned {len(removed)} finished run dir(s)")

    return video_url


if __name__ == "__main__":
    run_pipeline()
