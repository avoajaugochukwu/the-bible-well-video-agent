#!/usr/bin/env python3
"""Generate a style showcase gallery — protagonist in 10 different stick-figure styles."""
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "utils"))
sys.path.insert(0, os.path.join(HERE, "src"))

import env
import krea as scene_assets

SHOWCASE_STYLES = {
    "01-simple": {
        "label": "Simple clean lines",
        "desc": "Minimal stick figures, basic shapes, no embellishment.",
        "prefix": "simple minimalist stick figure drawing, thin black lines on white background, ",
    },
    "02-expressive": {
        "label": "Expressive gesture",
        "desc": "Stick figures with exaggerated movement and emotional poses.",
        "prefix": "expressive cartoon stick figure, exaggerated gestures and poses, black ink on white, ",
    },
    "03-geometric": {
        "label": "Geometric shapes",
        "desc": "Stick figures constructed from clean geometric forms.",
        "prefix": "geometric stick figure drawing, made of simple circles and lines, clean minimalist, ",
    },
    "04-flowing": {
        "label": "Flowing lines",
        "desc": "Stick figures with smooth, flowing curved lines.",
        "prefix": "flowing curved stick figure drawing, smooth elegant lines, black ink, ",
    },
    "05-storybook": {
        "label": "Storybook style",
        "desc": "Warm children's book illustration of stick figures.",
        "prefix": "children's storybook stick figure illustration, warm pen and ink, gentle and approachable, ",
    },
    "06-bold": {
        "label": "Bold outlines",
        "desc": "Thick bold outlined stick figures, high contrast.",
        "prefix": "bold thick-outline stick figure, chunky black lines on white, high contrast, ",
    },
    "07-watercolor": {
        "label": "Watercolor",
        "desc": "Soft watercolor wash with stick figure linework.",
        "prefix": "watercolor stick figure, clean ink outlines with soft color washes, ",
    },
    "08-comic": {
        "label": "Comic style",
        "desc": "Comic book style stick figures with Ben-Day dots.",
        "prefix": "comic book stick figure, bold outlines, flat bright color with halftone texture, ",
    },
    "09-retro": {
        "label": "Retro 70s",
        "desc": "Groovy retro 1970s cartoon stick figures.",
        "prefix": "retro 1970s cartoon stick figure, groovy bold shapes, bright earthy palette, ",
    },
    "10-elegant": {
        "label": "Elegant minimal",
        "desc": "Sophisticated minimal line drawing, artist quality.",
        "prefix": "elegant minimal stick figure, artist-quality line drawing, refined and sophisticated, ",
    },
}

HERO_SUBJECTS = [
    "A man in his 30s with simple casual modern clothes, kneeling with hands open in surrender, face peaceful, surrounded by divine light.",
    "A woman in her 40s wearing comfortable modern clothing, arms raised in praise, face radiant with joy, bathed in warm light.",
    "A young adult in their 20s in casual modern attire, sitting quietly in reflection, face thoughtful and calm, glowing with inner peace.",
    "A middle-aged person in simple modern clothes, reaching forward with hope and expectation, face peaceful, surrounded by gentle light.",
]

def generate_style_variant(hero_idx: int, style_key: str, style_info: dict) -> tuple[str, str, str]:
    """Generate one style variant. Returns (image_url, prompt_used, style_key)."""
    hero = HERO_SUBJECTS[hero_idx % len(HERO_SUBJECTS)]
    prefix = style_info["prefix"]
    prompt = prefix + hero

    scene_assets._load_env()
    try:
        url = scene_assets.krea_photo(prompt, negative_prompt="text, labels, words")
        print(f"  {style_key}: generated", flush=True)
        return url, prompt, style_key
    except Exception as ex:
        print(f"  {style_key}: failed — {ex}", flush=True)
        return None, prompt, style_key


def build_html(results: list[dict]) -> str:
    """Build gallery HTML from style variants."""
    cards = []
    for r in results:
        if not r["url"]:
            continue
        style_key = r["style_key"]
        style_info = SHOWCASE_STYLES[style_key]
        cards.append(f"""<div class="card">
<img src="{r['url']}" alt="{style_info['label']}">
<h3>{style_info['label']}</h3>
<p class="s">{style_info['desc']}</p>
<details><summary>full prompt</summary><pre>{r['prompt']}</pre></details>
</div>""")

    html = f"""<!doctype html><meta charset=utf-8>
<title>Bible Well — protagonist style showcase</title>
<style>
 body{{background:#f4f4f4;color:#222;font-family:system-ui,Arial;margin:24px}}
 h1{{font-size:20px}} .grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:20px}}
 .card{{background:#fff;border:1px solid #ddd;border-radius:10px;padding:10px}}
 .card img{{width:100%;border-radius:6px;display:block}}
 .card h3{{margin:8px 0 2px;font-size:14px;color:#06c}}
 .card .s{{margin:0 0 6px;font-size:12px;color:#666}}
 details summary{{cursor:pointer;font-size:12px;color:#06c}}
 pre{{white-space:pre-wrap;font-size:11px;color:#333;background:#f0f0f0;padding:8px;border-radius:6px;margin:6px 0 0}}
</style>
<h1>Bible Well — Protagonist Style Showcase</h1>
<p style="color:#888">Same character, {len(cards)} different stick-figure rendering styles</p>
<div class="grid">
{chr(10).join(cards)}
</div>"""
    return html


if __name__ == "__main__":
    print("Generating protagonist style showcase...")
    results = []
    for style_key, style_info in SHOWCASE_STYLES.items():
        url, prompt, key = generate_style_variant(0, style_key, style_info)
        results.append({"url": url, "prompt": prompt, "style_key": key})

    html = build_html(results)
    out_path = os.path.join(HERE, "style_showcase.html")
    with open(out_path, "w") as f:
        f.write(html)

    print(f"Style showcase written to {out_path}")
