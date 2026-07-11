"""Script -> ONE narration MP3 via the Voice Generator Service (submit/poll/download).

POST /tts/synthesize {text,voice} -> {jobId}; poll /tts/jobs/{jobId} until completed;
download /tts/jobs/{jobId}/download (302->S3). One call, whole script, no chunking.
Endpoint/voice come from `env.py` (TTS_ENDPOINT / TTS_VOICE, root .env).
"""
import json
import time
import urllib.request

import env as _e


def synthesize(text: str, out_path: str, voice: str | None = None,
               poll: int = 5, timeout_s: int = 1800) -> str:
    base = _e.get("TTS_ENDPOINT", "https://voice-generator-service-production.up.railway.app")
    voice = voice or _e.get("TTS_VOICE", "T-C-Bill-Oxley")
    body = json.dumps({"text": text, "voice": voice}).encode()
    req = urllib.request.Request(f"{base}/tts/synthesize", data=body,
                                 headers={"Content-Type": "application/json"})
    jid = json.load(urllib.request.urlopen(req, timeout=60))["jobId"]
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        st = json.load(urllib.request.urlopen(f"{base}/tts/jobs/{jid}", timeout=60))
        if st.get("status") == "completed":
            urllib.request.urlretrieve(f"{base}/tts/jobs/{jid}/download", out_path)  # follows 302
            return out_path
        if st.get("status") == "failed":
            raise RuntimeError(f"tts failed: {st.get('error')}")   # too long -> report, do NOT chunk
        time.sleep(poll)
    raise TimeoutError(f"tts job {jid} unfinished in {timeout_s}s")


if __name__ == "__main__":
    # liveness only (no synth — that costs/takes minutes): voices endpoint should be up
    base = _e.get("TTS_ENDPOINT", "https://voice-generator-service-production.up.railway.app")
    with urllib.request.urlopen(f"{base}/tts/voices", timeout=30) as r:
        assert r.status == 200
    print("ok  TTS service up")
