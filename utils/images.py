"""Get an image no matter how, batched, and hand back the raw bytes.

Direct HTTP fetch first (cheap, works for most sources). Whatever fails direct
fetch gets ONE shared headless-browser session for the rest of the batch — not
one browser per image. A real browser succeeds where a bare urllib GET gets
hotlink/bot-blocked because it sends a genuine Referer/UA/TLS fingerprint and
runs JS, same as a human loading the page and hitting "copy image" — we just
read the bytes off the network response instead of a canvas (a JS canvas read
would throw "tainted canvas" on a cross-origin image without CORS anyway; the
browser's own copy-image feature isn't bound by that page-JS restriction, and
neither is reading the raw network response here).

Usage:
    fetched = ImageFetcher().fetch_many(urls)   # {url: bytes|None}
    data = ImageFetcher().fetch(one_url)        # bytes|None
"""
import io
import urllib.request

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")


def _autocrop_to_content(img):
    """Trim flat-background padding down to the actual subject's bounding box —
    e.g. a full-body reference generated on a wide 16:9 canvas has large empty
    gray margins left/right of an upright figure; those pixels cost edit-call
    tokens for nothing. Classic Pillow autocrop recipe: diff against the
    corner's background color, threshold out compression noise, crop to
    whatever's left. No-op (returns img unchanged) if nothing differs enough
    from the background to find a bounding box."""
    from PIL import Image, ImageChops

    bg = Image.new(img.mode, img.size, img.getpixel((0, 0)))
    diff = ImageChops.difference(img, bg)
    diff = ImageChops.add(diff, diff, 2.0, -30)  # boost real edges, drop soft/noise pixels
    bbox = diff.getbbox()
    if not bbox:
        return img
    pad = round(0.02 * max(img.size))
    left, top, right, bottom = bbox
    return img.crop((
        max(0, left - pad), max(0, top - pad),
        min(img.width, right + pad), min(img.height, bottom + pad),
    ))


def shrink_for_upload(data: bytes, max_dimension: int = 768, quality: int = 80) -> bytes:
    """Downscale + re-encode a reference image before sending it as an image-edit
    input — identity carries fine at a fraction of the original pixels/bytes, and
    edit-call cost scales with input size. Autocrops flat-background padding to an
    upright rectangle around the actual subject first, then caps the longest edge
    at max_dimension, then re-encodes as JPEG at `quality` (drops PNG's larger,
    unneeded alpha channel for an opaque character reference)."""
    from PIL import Image

    img = Image.open(io.BytesIO(data)).convert("RGB")
    img = _autocrop_to_content(img)
    w, h = img.size
    scale = min(1.0, max_dimension / max(w, h))
    if scale < 1.0:
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()


def looks_image(data: bytes) -> bool:
    h = data[:12]
    return bool(data) and (
        h[:3] == b"\xff\xd8\xff" or h[:8] == b"\x89PNG\r\n\x1a\n"
        or h[:6] in (b"GIF87a", b"GIF89a") or h[:2] == b"BM"
        or (h[:4] == b"RIFF" and h[8:12] == b"WEBP"))


def _direct_fetch(url: str, timeout: int = 30) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "image/*"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
    except Exception:
        return None
    return data if looks_image(data) and len(data) >= 1024 else None


class ImageFetcher:
    """fetch_many() is the primary API — always call it with the whole batch you
    need so the browser fallback (if it's needed at all) only spins up once."""

    def fetch(self, url: str) -> bytes | None:
        return self.fetch_many([url])[url]

    def fetch_many(self, urls: list[str]) -> dict:
        out = {u: _direct_fetch(u) for u in dict.fromkeys(urls)}   # de-dup, keep order
        failed = [u for u, data in out.items() if data is None]
        if failed:
            out.update(self._browser_fetch_many(failed))
        return out

    def _browser_fetch_many(self, urls: list[str]) -> dict:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print(f"images: playwright not installed, {len(urls)} blocked url(s) stay unfetched "
                  "(pip install playwright && playwright install chromium)", flush=True)
            return {u: None for u in urls}

        out = {}
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(user_agent=_UA)
            for u in urls:
                try:
                    resp = page.goto(u, timeout=30_000)
                    data = resp.body() if resp and resp.ok else None
                    out[u] = data if data and looks_image(data) else None
                    print(f"images: browser fetch {'ok' if out[u] else 'failed'} for {u[:70]}", flush=True)
                except Exception as e:
                    print(f"images: browser fetch failed for {u[:70]}: {e}", flush=True)
                    out[u] = None
            browser.close()
        return out


if __name__ == "__main__":
    fetcher = ImageFetcher()
    ok = fetcher.fetch("https://www.python.org/static/img/python-logo.png")
    assert ok and looks_image(ok), "direct fetch of a plain public image should just work"
    print(f"ok  direct fetch: {len(ok)} bytes")

    batch = fetcher.fetch_many([
        "https://www.python.org/static/img/python-logo.png",
        "https://not-a-real-domain-xyz123.invalid/nope.jpg",
    ])
    assert batch[list(batch)[0]] is not None
    assert batch[list(batch)[1]] is None
    print("ok  batch fetch: 1 hit, 1 clean miss (browser fallback attempted + also failed, as expected)")
