 generate the # Krea art-style test — Pixar-adjacent semi-realistic render

Reference: user-supplied screenshot, semi-realistic 3D character render (natural eye
size, skin texture/freckles, realistic proportions) — not full chibi/Pixar-cartoon.

10-image test batch: `style-tests/pixar-test/gallery.html` (+ `results.json` for urls) —
kept outside `runs/` since that dir gets periodically wiped.
Script used: see git history / regenerate with `src/krea.py:krea_photo()`.

## Style prompt (prepended to each scene prompt)

Rejected — too playful/chibi:
```
3D Pixar-style animated movie render, semi-stylized cartoon realism, big expressive
eyes, soft subsurface-scattered skin shading, warm cinematic lighting, ultra detailed,
```

Working version:
```
semi-realistic 3D character render, natural human proportions, realistic eye size,
detailed skin texture with subtle freckles and pores, soft subsurface-scattered skin
shading, Unreal Engine 5 cinematic render quality, warm natural lighting, ultra
detailed, not chibi, not exaggerated cartoon proportions,
```

## negative_prompt

```
photorealistic live-action photo, big anime eyes, chibi, exaggerated cartoon
proportions, text, watermark
```

## What changed and why

- Dropped "Pixar" / "cartoon realism" / "big expressive eyes" — pulled the render
  toward toy-store/chibi proportions.
- Added "natural human proportions" + "realistic eye size" + "not chibi, not
  exaggerated cartoon proportions" — direct proportion anchors.
- Added "detailed skin texture with subtle freckles and pores" — matches the
  reference's texture, avoids the plastic/smooth cartoon skin look.
- Swapped "3D Pixar-style animated movie render" for "semi-realistic 3D character
  render" + "Unreal Engine 5 cinematic render quality" — anchors toward
  game-engine/cinematic realism instead of animated-movie cartoon.
