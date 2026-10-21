"""Perchance bot engine — wraps Pollinations for princess image generation.

Used by _generate_princess_backend() in app.py as the primary image source.
"""

import time
import urllib.parse

import requests


def generate_one_sync(prompt: str, negative_prompt: str = "") -> bytes:
    """Generate one image synchronously via the Pollinations free API."""
    encoded = urllib.parse.quote(prompt, safe="")
    neg = urllib.parse.quote(negative_prompt or "", safe="")
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width=768&height=768&nologo=true&model=flux&seed=-1&safe=false"
    )
    if neg:
        url += f"&negative={neg}"

    last_err: Exception | None = None
    for attempt in range(4):
        try:
            resp = requests.get(url, timeout=120)
            if resp.status_code == 429 and attempt < 3:
                time.sleep(min(10, 2 + attempt * 3))
                continue
            if resp.status_code in (502, 503, 504) and attempt < 3:
                time.sleep(2 ** min(attempt, 3))
                continue
            if not resp.ok:
                raise Exception(f"Perchance generate error {resp.status_code}")
            ct = (resp.headers.get("content-type") or "").lower()
            if not ct.startswith("image/"):
                raise Exception("Non-image response from generator")
            if len(resp.content) < 5_000:
                raise Exception("Response too small — probably not a real image")
            return resp.content
        except requests.RequestException as e:
            last_err = e
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise Exception(f"Generate request failed: {e}") from e
    raise Exception(str(last_err or "Generation failed after retries"))
