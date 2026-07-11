#!/usr/bin/env python3
"""Quick script: cleaned script -> first 20 scenes -> gallery HTML."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "src"))
sys.path.insert(0, os.path.join(HERE, "utils"))

import scene_engine
import gallery

# Read cleaned script
script_path = os.path.join(HERE, "script_cleaned.txt")
with open(script_path) as f:
    script = f.read()

print("Breaking script into scenes...", flush=True)
context = scene_engine.infer_context(script)
scenes = scene_engine.break_into_scenes(script, context=context)

# Take first 20
scenes_20 = scenes[:20]
print(f"Generating images for first {len(scenes_20)} scenes...", flush=True)
scenes_with_images = scene_engine.generate_images(scenes_20, context)

# Build gallery
out_path = os.path.join(HERE, "gallery_preview.html")
gallery.build_gallery(scenes_with_images, out_path)
print(f"Gallery written to {out_path}", flush=True)
