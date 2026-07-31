# CLAUDE.md — remotion/ (render)

Directory-scoped instructions for the standalone Remotion project. Root `CLAUDE.md` owns
the overall SOP; this file owns render mechanics only. Remotion has no character/style
awareness at all — it just renders whatever `image_url`/`video_url` each scene carries.

## Hard rule: never render locally

`remotion render` freezes the machine — banned. Always `npm run deploy:site` (uploads the
current bundle, prints `REMOTION_SERVE_URL=...`) then `npm run render:remote` with that url
in the environment (Remotion Lambda). `src/run.py:run_node()` is the only caller; it raises
with the tail of stderr/stdout on a non-zero exit rather than swallowing a failed
deploy/render.

## scenes.json

Written fresh by `src/scene_engine.py:build_remotion_payload()` right before render, shape
`{scenes, narrationUrl, words}`:
- `narrationUrl` — the row's OWN `voice_url` (already a public S3 url, no rehost needed),
  muxed in via a plain `<Audio src={narrationUrl}>` in `HeritageScenes.tsx`.
- `words` — the same cached whisper words `scene_engine.py:whisper_words()` computed for
  scene alignment, reused here for `<Captions>`'s current-word highlight. Never
  re-transcribed for render.
- Each scene: a still `image_url` by default, or — when the production UI's asset `mode` is
  `'video'` — a `video_url` that renders via `OffthreadVideo` (looped, muted) instead of the
  still image.

## HeritageScenes.tsx

Owns the one shared black backdrop so no per-scene component needs its own opaque
background. `Root.tsx` registers it under composition id `"HeritageScenes"`.
