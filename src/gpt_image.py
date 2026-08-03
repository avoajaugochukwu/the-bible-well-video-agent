"""gpt-image-2 client: prompt -> PNG -> S3 public URL.

OpenAI's Images API has no negative-prompt channel. Callers must express safe,
positive composition constraints in the main prompt; explicit comma-separated
negative lists are intentionally not appended because they can themselves trip
input moderation. gpt-image-2 only returns b64_json (no hosted URL), so the PNG
is saved locally and re-hosted via src/s3.py:put_file().
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


def edit_image(prompt: str, reference_images: list[bytes], retries: int = 4, size: str = SIZE) -> str:
    """i2i: edit gpt-image-2's own reference conditioning using one or more
    character reference images, so identity comes from the image rather than
    restated appearance text. Returns the new still's raw public S3 URL.

    ``size`` defaults to the pipeline's scene-frame ratio (16:9) but callers whose
    output isn't a video frame (e.g. a portrait full-body character reference) can
    pass one of gpt-image-2's other supported sizes."""
    from openai import OpenAI

    full_prompt = prompt[:5000]

    client = OpenAI(api_key=env.require("OPENAI_API_KEY"))
    tmp_paths = []
    try:
        for data in reference_images:
            f = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            f.write(data)
            f.close()
            tmp_paths.append(f.name)

        res = None
        for attempt in range(retries):
            files = [open(p, "rb") for p in tmp_paths]
            try:
                res = client.images.edit(
                    model=MODEL, image=files, prompt=full_prompt, size=size, quality=QUALITY,
                )
                break
            except Exception as ex:
                status = getattr(ex, "status_code", None)
                if status is not None and status < 500 and status != 429:
                    raise
                if attempt == retries - 1:
                    raise
                time.sleep(3 * 2 ** attempt)
            finally:
                for fh in files:
                    fh.close()

        out = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
        try:
            with open(out, "wb") as f:
                f.write(base64.b64decode(res.data[0].b64_json))
            url = s3.put_file(out, f"bible-well/{os.path.basename(out)}")
            if not url:
                raise RuntimeError("gpt-image-2 edit: S3 upload failed")
            return url
        finally:
            os.path.exists(out) and os.unlink(out)
    finally:
        for p in tmp_paths:
            os.path.exists(p) and os.unlink(p)


def generate_image(prompt: str, negative_prompt: str = "", retries: int = 4, size: str = SIZE) -> str:
    """Generate one still and return its raw public S3 URL.

    ``negative_prompt`` remains for compatibility with old callers but is ignored:
    the API does not support it, and folding explicit safety terms into the ordinary
    prompt was a source of moderation false positives. ``size`` defaults to the
    pipeline's scene-frame ratio (16:9) but callers whose output isn't a video frame
    (e.g. a portrait full-body character reference) can pass one of gpt-image-2's
    other supported sizes.
    """
    from openai import OpenAI

    full_prompt = prompt[:5000]

    client = OpenAI(api_key=env.require("OPENAI_API_KEY"))
    res = None
    for attempt in range(retries):
        try:
            res = client.images.generate(model=MODEL, prompt=full_prompt, size=size, quality=QUALITY)
            break
        except Exception as ex:
            status = getattr(ex, "status_code", None)
            # Repeating the identical prompt cannot repair a moderation or other
            # client-side rejection. Let the compositor change prompt strategy.
            if status is not None and status < 500 and status != 429:
                raise
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
