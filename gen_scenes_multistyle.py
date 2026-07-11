#!/usr/bin/env python3
"""Generate 20 Bible scenes in 8 cartoon styles, all in one gallery HTML."""
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "utils"))
sys.path.insert(0, os.path.join(HERE, "src"))

import env
import krea as scene_assets

STYLES = {
    "satmorning": {
        "label": "Saturday-morning cartoon",
        "prefix": "Classic Saturday-morning cartoon style, bouncy clean linework, bright saturated fills. ",
    },
    "minimal-flat": {
        "label": "Minimal flat design",
        "prefix": "Minimal modern flat design, clean simple shapes, generous negative space, bright pastel palette. ",
    },
    "gamecel": {
        "label": "Game cel-shaded",
        "prefix": "Cel-shaded stylized video-game art, clean crisp shading, bright saturated color. ",
    },
    "comic-halftone": {
        "label": "Comic-book halftone",
        "prefix": "Classic comic-book style, bold outlines, flat primary colors, Ben-Day halftone dots. ",
    },
    "watercolor": {
        "label": "Loose watercolor",
        "prefix": "Loose watercolor cartoon, clean ink outlines with bright washed color, airy. ",
    },
    "screenprint": {
        "label": "Screenprint poster",
        "prefix": "Two-color screenprint poster style, flat bold ink, halftone texture, clean graphic. ",
    },
    "storybook": {
        "label": "Storybook illustration",
        "prefix": "Warm children's storybook illustration, soft clean shapes, gentle bright palette. ",
    },
    "graphic-novel": {
        "label": "Graphic novel",
        "prefix": "Bold graphic-novel ink style, strong black linework, flat cel color, dramatic clean shapes. ",
    },
}


def load_scenes() -> list[dict]:
    """Load scenes from runs/<row_id>/scenes.json."""
    runs_dir = os.path.join(HERE, "runs")
    if os.path.isdir(runs_dir):
        for row_id in os.listdir(runs_dir):
            scenes_file = os.path.join(runs_dir, row_id, "scenes.json")
            if os.path.isfile(scenes_file):
                with open(scenes_file) as f:
                    data = json.load(f)
                    # scenes.json is an array directly
                    if isinstance(data, list):
                        scenes = data[:20]
                        # Ensure scene_number is set
                        for i, s in enumerate(scenes, 1):
                            if "scene_number" not in s:
                                s["scene_number"] = i
                        return scenes

    # Fallback: create test scenes
    print("WARNING: No scenes.json found, using placeholder", flush=True)
    return [
        {"scene_number": i,
         "script_snippet": f"Scene {i}: A spiritual moment of transformation.",
         "image_prompt": f"A person experiencing spiritual transformation and divine light."}
        for i in range(1, 21)
    ]


def generate_image(scene_num: int, style_key: str, style_info: dict, image_prompt: str) -> dict:
    """Generate one image. Returns {scene_num, style_key, url}."""
    prompt = style_info["prefix"] + image_prompt
    scene_assets._load_env()
    try:
        url = scene_assets.krea_photo(prompt, negative_prompt="text, labels, words")
        print(f"  scene {scene_num:02d} / {style_key}: ✓", flush=True)
        return {"scene_num": scene_num, "style_key": style_key, "url": url, "prompt": prompt}
    except Exception as ex:
        print(f"  scene {scene_num:02d} / {style_key}: ✗ {ex}", flush=True)
        return {"scene_num": scene_num, "style_key": style_key, "url": None, "prompt": prompt}


def build_html(results: list[dict], scenes: list[dict]) -> str:
    """Build gallery HTML — scenes as rows, styles as columns."""
    # Group results by scene
    by_scene = {}
    for r in results:
        if r["scene_num"] not in by_scene:
            by_scene[r["scene_num"]] = {}
        by_scene[r["scene_num"]][r["style_key"]] = r

    style_order = list(STYLES.keys())
    rows = []
    for scene in scenes[:20]:
        scene_num = scene.get("scene_number", 1)
        snippet = scene.get("script_snippet", "")[:100]
        row_html = f'<tr><td style="border:1px solid #ddd;padding:8px;font-size:12px;max-width:150px;word-wrap:break-word"><strong>Scene {scene_num}</strong><br>{snippet}...</td>'
        for style_key in style_order:
            result = by_scene.get(scene_num, {}).get(style_key, {})
            url = result.get("url")
            img_html = f'<img src="{url}" style="width:100%;border-radius:4px;">' if url else '<div style="background:#eee;width:100%;padding:20px;text-align:center;">Failed</div>'
            row_html += f'<td style="border:1px solid #ddd;padding:4px;"><details style="font-size:10px"><summary>prompt</summary><pre style="font-size:9px;white-space:pre-wrap;margin:4px 0">{result.get("prompt", "")}</pre></details>{img_html}</td>'
        row_html += '</tr>'
        rows.append(row_html)

    style_headers = ''.join([f'<th style="border:1px solid #ddd;padding:8px;font-weight:bold;font-size:12px">{STYLES[k]["label"]}</th>' for k in style_order])

    html = f"""<!doctype html><meta charset=utf-8>
<title>Bible Well — 20 scenes × 8 styles</title>
<style>
 body{{background:#f4f4f4;color:#222;font-family:system-ui,Arial;margin:12px}}
 h1{{font-size:18px}} table{{border-collapse:collapse;width:100%;background:#fff}}
 td,th{{border:1px solid #ddd;padding:4px}}
 img{{max-width:150px;height:auto}}
 details{{cursor:pointer}}
 pre{{font-size:9px;white-space:pre-wrap;margin:4px 0;background:#f9f9f9;padding:4px;border-radius:2px}}
</style>
<h1>Bible Well — 20 scenes × 8 styles showcase</h1>
<p style="color:#888">Each row: one scene across all 8 cartoon styles. Click "prompt" for full generation prompt.</p>
<table>
<tr><th style="border:1px solid #ddd;padding:8px">Scene</th>{style_headers}</tr>
{chr(10).join(rows)}
</table>"""
    return html


if __name__ == "__main__":
    print("Loading scenes...")
    scenes = load_scenes()
    print(f"Loaded {len(scenes)} scenes")

    print(f"Generating {len(scenes)} scenes × {len(STYLES)} styles = {len(scenes) * len(STYLES)} images...")
    results = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = []
        for scene in scenes:
            scene_num = scene.get("scene_number", 1)
            image_prompt = scene.get("image_prompt", "A spiritual transformation.")
            for style_key, style_info in STYLES.items():
                future = ex.submit(generate_image, scene_num, style_key, style_info, image_prompt)
                futures.append(future)

        for future in as_completed(futures):
            results.append(future.result())

    print("Building gallery HTML...")
    gallery_html = build_html(results, scenes)
    out_path = os.path.join(HERE, "scenes_multistyle_gallery.html")
    with open(out_path, "w") as f:
        f.write(gallery_html)

    print(f"Gallery written to {out_path}")
