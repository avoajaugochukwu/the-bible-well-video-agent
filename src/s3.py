"""Re-host a finicky image URL to our S3 bucket -> stable RAW public URL.

Copied from the old `shared/s3.py` almost verbatim for the heritage pipeline — own
bucket, own key prefix. News/Google (Serper) images 403 / hotlink-block at render
time. We fetch them with a browser UA, verify they're real images, upload to S3, and
hand back a RAW public url (bucket is public-read, matches the 7-day lifecycle). Our
OWN Krea images are already reliable and are NOT re-hosted.

Creds + bucket live in root .env (read via utils/env.py — no longer a
hardcoded path into a sibling repo). Uses the aws CLI (boto3 absent).
"""
import hashlib
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "utils"))
from images import ImageFetcher  # utils/
import env  # utils/

BUCKET = "yt-heritage-media"
_TTL = "604800"   # 7 days, matches the bucket lifecycle
_CTYPE = {"jpg": "image/jpeg", "png": "image/png", "gif": "image/gif",
          "webp": "image/webp", "bmp": "image/bmp"}


def _cfg() -> dict:
    return {
        "AWS_REGION": env.get("AWS_REGION"),
        "AWS_ACCESS_KEY_ID": env.require("AWS_ACCESS_KEY_ID"),
        "AWS_SECRET_ACCESS_KEY": env.require("AWS_SECRET_ACCESS_KEY"),
    }


def _img_ext(head: bytes) -> str | None:
    if head[:3] == b"\xff\xd8\xff":
        return "jpg"
    if head[:4] == b"\x89PNG":
        return "png"
    if head[:4] == b"GIF8":
        return "gif"
    if head[:2] == b"BM":
        return "bmp"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def upload_bytes(data: bytes, key_seed: str, prefix: str = "heritage") -> str | None:
    """Upload already-fetched image bytes to S3, return the RAW public url. `key_seed`
    is just hashed into the S3 key (typically the source url) — not re-fetched.
    None if the bytes aren't a decodable image or the upload fails."""
    ext = _img_ext(data[:12])
    if not ext or len(data) < 1024:                 # not an image / too small to be real
        return None
    c = _cfg()
    region = c.get("AWS_REGION") or "us-west-2"
    key = f"{prefix}/{hashlib.md5(key_seed.encode()).hexdigest()}.{ext}"
    env = {**os.environ, "AWS_ACCESS_KEY_ID": c["AWS_ACCESS_KEY_ID"],
           "AWS_SECRET_ACCESS_KEY": c["AWS_SECRET_ACCESS_KEY"], "AWS_DEFAULT_REGION": region}
    tmp = tempfile.NamedTemporaryFile(suffix="." + ext, delete=False).name
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        cp = subprocess.run(["aws", "s3", "cp", tmp, f"s3://{BUCKET}/{key}",
                             "--content-type", _CTYPE[ext], "--only-show-errors"],
                            env=env, capture_output=True)
        if cp.returncode != 0:
            return None
        # RAW url (bucket is public-read) — never presigned. Reliable + clean.
        return f"https://{BUCKET}.s3.{region}.amazonaws.com/{key}"
    except Exception:
        return None
    finally:
        os.path.exists(tmp) and os.unlink(tmp)


def upload_from_url(url: str, prefix: str = "heritage") -> str | None:
    """Fetch (direct, then browser-fallback if blocked), validate as image, upload
    to S3, return the RAW public url. None on any failure. Single-shot — for
    rehosting many urls at once (e.g. a whole sheet), use ImageFetcher.fetch_many()
    yourself and call upload_bytes() per result, so the browser only spins up once."""
    data = ImageFetcher().fetch(url)
    return upload_bytes(data, url, prefix) if data else None


def put_file(local: str, key: str) -> str | None:
    """Upload a LOCAL file to S3 under `key`, return its RAW public url. None on failure."""
    c = _cfg()
    region = c.get("AWS_REGION") or "us-west-2"
    env = {**os.environ, "AWS_ACCESS_KEY_ID": c["AWS_ACCESS_KEY_ID"],
           "AWS_SECRET_ACCESS_KEY": c["AWS_SECRET_ACCESS_KEY"], "AWS_DEFAULT_REGION": region}
    cp = subprocess.run(["aws", "s3", "cp", local, f"s3://{BUCKET}/{key}", "--only-show-errors"],
                        env=env, capture_output=True)
    return f"https://{BUCKET}.s3.{region}.amazonaws.com/{key}" if cp.returncode == 0 else None


def first_uploadable(urls: list[str], prefix: str = "heritage") -> str | None:
    """Re-host the first url that fetches+uploads cleanly (the 'replace if it can't be uploaded' rule)."""
    for u in urls:
        s3 = upload_from_url(u, prefix)
        if s3:
            return s3
    return None


if __name__ == "__main__":
    import urllib.request as R
    u = upload_from_url(
        "https://upload.wikimedia.org/wikipedia/en/f/fb/J.B._Beasley_and_Tracie_Hawlett_Murder_Victims.jpg")
    print("s3 presigned:", (u or "NONE")[:90])
    assert u and u.startswith("http"), u
    with R.urlopen(u, timeout=30) as r:
        assert r.status == 200 and r.headers.get_content_maintype() == "image"
    print("ok  re-hosted + publicly fetchable via presigned url")
