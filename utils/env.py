"""One env-var lookup for the heritage pipeline: os.environ, then the repo-root
`.env` file (all keys — Baserow, OpenAI, AWS, ClickUp, etc. — live in that single
file now). Replaces the hand-rolled "read file, find KEY=" parser that used to be
copy-pasted in ~8 different modules across this repo.
"""
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_ENV_FILES = (os.path.join(_ROOT, ".env"),)


def get(key: str, default: str | None = None) -> str | None:
    if os.environ.get(key):
        return os.environ[key]
    for path in _ENV_FILES:
        if not os.path.exists(path):
            continue
        for line in open(path):
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return default


def require(key: str) -> str:
    v = get(key)
    if not v:
        raise RuntimeError(f"no {key} (set env or add it to the root .env)")
    return v


if __name__ == "__main__":
    assert get("NOT_A_REAL_KEY_XYZ") is None
    assert get("NOT_A_REAL_KEY_XYZ", "fallback") == "fallback"
    print("ok  env lookup checks os.environ then root .env")
