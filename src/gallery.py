"""Scenes + image urls -> one self-contained HTML preview file: a responsive
grid (thumbnail + script_snippet under each), click any image to open a
vanilla-JS lightbox modal with the full-size image and its snippet. No
external libs/CDNs, no build step — a single <html> file you can open
directly in a browser or attach to a ClickUp task for review.
"""
import html
import json


def build_gallery(scenes: list[dict], out_path: str) -> None:
    """Write `out_path` as a single self-contained HTML file. Each scene dict
    needs at least `scene_number`, `script_snippet`, and `image_url` (may be
    None — rendered as a placeholder card rather than skipped, so a partial
    batch is still visible for review)."""
    cards = []
    modal_data = []
    for s in scenes:
        n = s.get("scene_number")
        snippet = html.escape(s.get("script_snippet", ""))
        url = s.get("image_url")
        lane = s.get("lane")
        scene_type = s.get("scene_type")
        image_basis = s.get("image_basis") or ""
        basis_kind = s.get("basis_kind") or ""
        mood_designated = bool(s.get("mood_designated"))
        idx = len(modal_data)
        modal_data.append({
            "url": url,
            "snippet": s.get("script_snippet", ""),
            "n": n,
            "lane": lane,
            "scene_type": scene_type,
            "image_basis": image_basis,
            "basis_kind": basis_kind,
            "mood_designated": mood_designated,
        })
        if url:
            img_html = f'<img src="{html.escape(url)}" alt="Scene {n}" loading="lazy">'
        else:
            img_html = '<div class="missing">image failed</div>'
        lane_class = f"lane-{lane}" if lane else "lane-none"
        lane_label = html.escape(lane) if lane else "—"
        meta_html = ""
        if scene_type:
            meta_html += f'<div class="scene-type">{html.escape(scene_type)}</div>'
        if image_basis:
            basis_label = "Search" if basis_kind == "search" else "Prompt"
            meta_html += (f'<div class="basis basis-{basis_kind}">'
                           f'<span class="basis-label">{basis_label}:</span> {html.escape(image_basis)}</div>')
        mood_badge = '<span class="mood-badge">CULTURAL ANCHOR</span>' if mood_designated else ""
        card_class = "card mood-designated" if mood_designated else "card"
        cards.append(f"""
        <figure class="{card_class}" data-idx="{idx}">
          <div class="thumb">{img_html}<span class="badge">{n}</span><span class="lane-badge {lane_class}">{lane_label}</span>{mood_badge}</div>
          <figcaption>{snippet}{meta_html}</figcaption>
        </figure>""")

    scenes_json = json.dumps(modal_data)

    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Christian Story — Scene Gallery</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {{
    --bg: #14110f;
    --card-bg: #1e1a17;
    --border: #33291f;
    --text: #f0e6d8;
    --muted: #b8a88f;
    --accent: #c9973f;
    --lane-archival: #c9973f;
    --lane-stock: #4fa8a0;
    --lane-graphic: #8b7cc9;
    --lane-krea: #c0654a;
    --mood: #5fb26a;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: Georgia, 'Times New Roman', serif;
    padding: 32px 24px 64px;
  }}
  h1 {{
    font-size: 1.6rem;
    font-weight: 600;
    margin: 0 0 4px;
    color: var(--accent);
  }}
  p.sub {{
    margin: 0 0 28px;
    color: var(--muted);
    font-size: 0.95rem;
  }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 20px;
  }}
  .card {{
    margin: 0;
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
    cursor: pointer;
    transition: transform 0.15s ease, border-color 0.15s ease;
  }}
  .card:hover {{
    transform: translateY(-3px);
    border-color: var(--accent);
  }}
  .card.mood-designated {{
    border-color: var(--mood);
    box-shadow: 0 0 0 1px var(--mood);
  }}
  .mood-badge {{
    position: absolute;
    bottom: 8px;
    left: 8px;
    background: var(--mood);
    color: #0d1a0f;
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 0.03em;
    padding: 2px 8px;
    border-radius: 999px;
  }}
  .thumb {{
    position: relative;
    aspect-ratio: 16 / 9;
    background: #0c0a08;
    display: flex;
    align-items: center;
    justify-content: center;
  }}
  .thumb img {{
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }}
  .thumb .missing {{
    color: #8a5a4a;
    font-size: 0.85rem;
    font-style: italic;
  }}
  .badge {{
    position: absolute;
    top: 8px;
    left: 8px;
    background: rgba(0,0,0,0.65);
    color: var(--accent);
    font-size: 0.75rem;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 999px;
    border: 1px solid var(--border);
  }}
  figcaption {{
    padding: 12px 14px 16px;
    font-size: 0.85rem;
    line-height: 1.45;
    color: var(--text);
  }}
  figcaption .scene-type {{
    margin-top: 6px;
    color: var(--muted);
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }}
  figcaption .basis {{
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px dashed var(--border);
    color: var(--muted);
    font-size: 0.75rem;
    font-style: italic;
    line-height: 1.4;
  }}
  figcaption .basis-label {{
    color: var(--accent);
    font-style: normal;
    font-weight: 700;
    text-transform: uppercase;
    font-size: 0.68rem;
    letter-spacing: 0.03em;
  }}
  .lane-badge {{
    display: inline-block;
    font-size: 0.7rem;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 999px;
    border: 1px solid var(--border);
    text-transform: uppercase;
    letter-spacing: 0.03em;
    color: #14110f;
    background: var(--muted);
  }}
  .thumb .lane-badge {{
    position: absolute;
    top: 8px;
    right: 8px;
  }}
  .lane-badge.lane-archival {{ background: var(--lane-archival); }}
  .lane-badge.lane-stock {{ background: var(--lane-stock); }}
  .lane-badge.lane-graphic-map {{ background: var(--lane-graphic); }}
  .lane-badge.lane-graphic-document {{ background: var(--lane-graphic); }}
  .lane-badge.lane-krea {{ background: var(--lane-krea); }}
  .lane-badge.lane-none {{ background: var(--muted); color: var(--bg); }}

  /* Modal / lightbox */
  #modal {{
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.88);
    z-index: 100;
    align-items: center;
    justify-content: center;
    padding: 5vh 4vw;
  }}
  #modal.open {{ display: flex; }}
  #modal .modal-inner {{
    max-width: 1100px;
    width: 100%;
    max-height: 90vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 16px;
  }}
  #modal img {{
    max-width: 100%;
    max-height: 68vh;
    object-fit: contain;
    border-radius: 8px;
    border: 1px solid var(--border);
  }}
  #modal .caption {{
    color: var(--text);
    font-size: 1rem;
    line-height: 1.6;
    max-width: 800px;
    text-align: center;
  }}
  #modal .scene-num {{
    color: var(--accent);
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    font-size: 0.8rem;
    margin-bottom: 4px;
  }}
  #modal .modal-meta {{
    color: var(--muted);
    font-size: 0.85rem;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }}
  #modal .modal-basis {{
    color: var(--muted);
    font-size: 0.85rem;
    font-style: italic;
    line-height: 1.5;
    max-width: 800px;
    text-align: center;
    border-top: 1px solid var(--border);
    padding-top: 12px;
  }}
  #modal .modal-basis .basis-label {{
    color: var(--accent);
    font-style: normal;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    font-size: 0.75rem;
  }}
  #modal .close {{
    position: absolute;
    top: 20px;
    right: 28px;
    color: var(--text);
    font-size: 2rem;
    line-height: 1;
    cursor: pointer;
    background: none;
    border: none;
    font-family: inherit;
  }}
  #modal .close:hover {{ color: var(--accent); }}
</style>
</head>
<body>
  <h1>Christian Story — Scene Gallery</h1>
  <p class="sub">{len(scenes)} scenes, {sum(1 for s in scenes if s.get("mood_designated"))} marked
    <span style="color: var(--mood); font-weight: 700;">CULTURAL ANCHOR</span>
    (code-picked mood/establishing scenes). Click any image to view full size.</p>
  <div class="grid">{"".join(cards)}
  </div>

  <div id="modal">
    <button class="close" aria-label="Close">&times;</button>
    <div class="modal-inner">
      <div class="scene-num" id="modal-scene-num"></div>
      <span class="lane-badge" id="modal-lane"></span>
      <span class="mood-badge" id="modal-mood" style="position:static; display:none;">CULTURAL ANCHOR</span>
      <img id="modal-img" src="" alt="">
      <div class="caption" id="modal-caption"></div>
      <div class="modal-meta" id="modal-meta"></div>
      <div class="modal-basis" id="modal-basis"></div>
    </div>
  </div>

<script>
  var SCENES = {scenes_json};
  var modal = document.getElementById('modal');
  var modalImg = document.getElementById('modal-img');
  var modalCaption = document.getElementById('modal-caption');
  var modalSceneNum = document.getElementById('modal-scene-num');
  var modalLane = document.getElementById('modal-lane');
  var modalMeta = document.getElementById('modal-meta');
  var modalBasis = document.getElementById('modal-basis');
  var modalMood = document.getElementById('modal-mood');

  function openModal(idx) {{
    var s = SCENES[idx];
    if (!s || !s.url) return;
    modalImg.src = s.url;
    modalImg.alt = 'Scene ' + s.n;
    modalCaption.textContent = s.snippet;
    modalSceneNum.textContent = 'Scene ' + s.n;
    modalLane.className = 'lane-badge ' + (s.lane ? 'lane-' + s.lane : 'lane-none');
    modalLane.textContent = s.lane || '—';
    modalMood.style.display = s.mood_designated ? '' : 'none';
    var metaParts = [];
    if (s.scene_type) metaParts.push(s.scene_type);
    modalMeta.textContent = metaParts.join(' · ');
    if (s.image_basis) {{
      var label = s.basis_kind === 'search' ? 'Search' : 'Prompt';
      modalBasis.textContent = '';
      var labelSpan = document.createElement('span');
      labelSpan.className = 'basis-label';
      labelSpan.textContent = label + ': ';
      modalBasis.appendChild(labelSpan);
      modalBasis.appendChild(document.createTextNode(s.image_basis));
      modalBasis.style.display = '';
    }} else {{
      modalBasis.textContent = '';
      modalBasis.style.display = 'none';
    }}
    modal.classList.add('open');
  }}

  function closeModal() {{
    modal.classList.remove('open');
    modalImg.src = '';
  }}

  document.querySelectorAll('.card').forEach(function(card) {{
    card.addEventListener('click', function() {{
      openModal(parseInt(card.getAttribute('data-idx'), 10));
    }});
  }});

  document.querySelector('#modal .close').addEventListener('click', closeModal);

  modal.addEventListener('click', function(e) {{
    if (e.target === modal) closeModal();
  }});

  document.addEventListener('keydown', function(e) {{
    if (e.key === 'Escape' && modal.classList.contains('open')) closeModal();
  }});
</script>
</body>
</html>
"""
    with open(out_path, "w") as f:
        f.write(doc)


if __name__ == "__main__":
    import os
    sample = [
        {"scene_number": 1, "script_snippet": "A sample opening line about carrying old worry.",
         "image_url": "https://picsum.photos/seed/1/1280/720",
         "lane": "krea", "scene_type": "spiritual_moment",
         "image_basis": "a person straining to carry a heavy, crumbling stone", "basis_kind": "prompt"},
        {"scene_number": 2, "script_snippet": "A second scene about surrendering control.",
         "image_url": None,
         "lane": "krea", "scene_type": "transformation",
         "image_basis": "a person in a car seat as a radiant light takes the wheel",
         "basis_kind": "prompt", "mood_designated": True},
        {"scene_number": 3, "script_snippet": "A closing scene about breaking free.",
         "image_url": "https://picsum.photos/seed/3/1280/720",
         "lane": "krea", "scene_type": "revelation",
         "image_basis": "chains shaped like dollar signs shattering around a person",
         "basis_kind": "prompt"},
    ]
    out = os.path.join(os.path.dirname(__file__), "gallery-selftest.html")
    build_gallery(sample, out)
    assert os.path.exists(out)
    print(f"ok  wrote {out} ({len(sample)} sample cards, one missing-image placeholder)")
