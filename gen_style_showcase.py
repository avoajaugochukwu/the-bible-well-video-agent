#!/usr/bin/env python3
"""Fetch Verdun prompts from S3, run through Krea, build local gallery."""
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "utils"))
sys.path.insert(0, os.path.join(HERE, "src"))

import env
import krea as scene_assets

VERDUN_URL = "https://art-of-war-attachments.s3.us-west-2.amazonaws.com/thumbnails/sleepretreat/1000-verdun-cartoon/gallery.html"


def fetch_verdun_html() -> str:
    """Fetch Verdun gallery HTML from S3."""
    try:
        with urllib.request.urlopen(VERDUN_URL, timeout=30) as r:
            return r.read().decode()
    except Exception as ex:
        raise RuntimeError(f"Failed to fetch Verdun gallery: {ex}")


def extract_styles(html: str) -> list[dict]:
    """Parse HTML, extract each style's key, desc, and full prompt."""
    styles = []
    # Match each .card block
    cards = re.findall(r'<div class="card">.*?</div>', html, re.DOTALL)
    for card in cards:
        # Extract style key from h3
        key_match = re.search(r'<h3>(v\d+-[^<]+)</h3>', card)
        if not key_match:
            continue
        key = key_match.group(1)

        # Extract description from .s paragraph
        desc_match = re.search(r'<p class="s">([^<]+)</p>', card)
        desc = desc_match.group(1) if desc_match else ""

        # Extract full prompt from <pre>
        prompt_match = re.search(r'<pre>([^<]+)</pre>', card)
        if not prompt_match:
            continue
        prompt = prompt_match.group(1).strip()
        # Unescape HTML entities
        prompt = prompt.replace("&#x27;", "'").replace("&quot;", '"')

        styles.append({"key": key, "desc": desc, "prompt": prompt})

    return styles


def generate_krea(prompt: str, style_key: str) -> str | None:
    """Run prompt through Krea. Returns image URL or None."""
    scene_assets._load_env()
    try:
        url = scene_assets.krea_photo(prompt, negative_prompt="")
        print(f"  {style_key}: generated", flush=True)
        return url
    except Exception as ex:
        print(f"  {style_key}: failed — {ex}", flush=True)
        return None


def build_html(styles_with_urls: list[dict]) -> str:
    """Build gallery HTML from styles + generated URLs."""
    cards = []
    for s in styles_with_urls:
        if not s["url"]:
            continue
        cards.append(f"""<div class="card"><img src="{s['url']}"><h3>{s['key']}</h3><p class="s">{s['desc']}</p><details><summary>full prompt</summary><pre>{s['prompt']}</pre></details></div>""")

    html = f"""<!doctype html><meta charset=utf-8>
<title>Verdun — 20 cartoon styles (Krea-generated)</title>
<style>
 body{{background:#f4f4f4;color:#222;font-family:system-ui,Arial;margin:24px}}
 h1{{font-size:20px}} .grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:20px}}
 .card{{background:#fff;border:1px solid #ddd;border-radius:10px;padding:10px}}
 .card img{{width:100%;border-radius:6px;display:block}}
 .card h3{{margin:8px 0 2px;font-size:14px;color:#b00}}
 .card .s{{margin:0 0 6px;font-size:12px;color:#666}}
 details summary{{cursor:pointer;font-size:12px;color:#06c}}
 pre{{white-space:pre-wrap;font-size:11px;color:#333;background:#f0f0f0;padding:8px;border-radius:6px;margin:6px 0 0}}
</style>
<h1>Verdun (Krea-generated) — 20 cartoon styles</h1>
<p style="color:#888">Prompts from original Verdun gallery, rendered locally via Krea</p>
<div class="grid">
{chr(10).join(cards)}
</div>"""
    return html


if __name__ == "__main__":
    print("Fetching Verdun prompts...")
    html = fetch_verdun_html()

    print("Extracting styles...")
    styles = extract_styles(html)
    print(f"Found {len(styles)} styles")

    print("Generating via Krea...")
    for s in styles:
        url = generate_krea(s["prompt"], s["key"])
        s["url"] = url

    print("Building gallery...")
    gallery_html = build_html(styles)
    out_path = os.path.join(HERE, "verdun_krea_gallery.html")
    with open(out_path, "w") as f:
        f.write(gallery_html)

    print(f"Gallery written to {out_path}")
