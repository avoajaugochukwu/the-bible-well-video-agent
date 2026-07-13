"""gpt-image-2 client: prompt -> flat 2D cartoon PNG -> S3 public URL.

Swapped in for Krea (src/krea.py) on the flat-cartoon/whiteboard style pivot.
OpenAI's images API has no negative_prompt param (unlike Krea) — callers fold
negatives into the prompt itself as a trailing "Avoid:" clause. gpt-image-2
only returns b64_json (no hosted url), so the PNG is saved locally then
re-hosted via src/s3.py:put_file() same as every other image in this pipeline.
"""
import base64
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "utils"))

import env  # utils/
import s3   # src/

MODEL = "gpt-image-2"
SIZE = "1280x720"
QUALITY = "low"


def generate_image(prompt: str, negative_prompt: str = "", retries: int = 4) -> str:
    """One flat 2D cartoon still -> S3 RAW public url. Retries the whole call —
    gpt-image's moderation block is stochastic, a fresh call often clears it."""
    from openai import OpenAI

    full_prompt = prompt[:4000]
    if negative_prompt:
        full_prompt += f". Avoid: {negative_prompt[:1000]}"

    client = OpenAI(api_key=env.require("OPENAI_API_KEY"))
    res = None
    for attempt in range(retries):
        try:
            res = client.images.generate(model=MODEL, prompt=full_prompt, size=SIZE, quality=QUALITY)
            break
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(3 * 2 ** attempt)

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
    try:
        with open(tmp, "wb") as f:
            f.write(base64.b64decode(res.data[0].b64_json))
        url = s3.put_file(tmp, f"bible-well/{os.path.basename(tmp)}")
        if not url:
            raise RuntimeError("gpt-image-2: S3 upload failed")
        return url
    finally:
        os.path.exists(tmp) and os.unlink(tmp)


if __name__ == "__main__":
    url = generate_image(
        "simple 2D vector illustration, clean black outlines, flat colors, "
        "minimalist design, a friendly cartoon person waving, plain light background"
    )
    assert url.startswith("http"), url
    print(f"ok  {url}")
