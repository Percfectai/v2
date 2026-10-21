"""
Minimal per-provider chat wrappers for Percfect Posts.

Scope: description + tags generation ONLY. Image/video generation stays on
the existing xAI Imagine path (/api/imagine) — do not route that here.

Each function takes (api_key, image_url, user_hint) and returns
{"description": str, "tags": [str, ...]} or raises Exception on failure.
Vision-capable chat models are used so the provider can look at the actual
image/video-thumbnail; verify current model names periodically — providers
rename/retire these.
"""

import json
import re

import requests

TIMEOUT = 25

WAND_PROMPT = (
    "Look at this image and write a short, upbeat social-media caption "
    "(1-2 sentences) plus 5-10 relevant hashtag-free tags. "
    "Reply as compact JSON only: {{\"description\": \"...\", \"tags\": [\"...\"]}}. "
    "Context from the creator: {hint}"
)


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("No JSON object found in model response")
    return json.loads(match.group(0))


def call_openai(api_key: str, image_url: str, hint: str) -> dict:
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "gpt-4o-mini",  # verify current vision-capable model name
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": WAND_PROMPT.format(hint=hint or "none")},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }],
            "max_tokens": 300,
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]
    return _extract_json(text)


def call_claude(api_key: str, image_url: str, hint: str) -> dict:
    # Claude's vision input needs base64 image bytes, not a bare URL, unless
    # the URL is fetched server-side first. Fetch + inline it here.
    img_resp = requests.get(image_url, timeout=TIMEOUT)
    img_resp.raise_for_status()
    import base64
    b64 = base64.b64encode(img_resp.content).decode()
    media_type = img_resp.headers.get("Content-Type", "image/jpeg").split(";")[0]

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-5",  # verify current model string
            "max_tokens": 300,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                    {"type": "text", "text": WAND_PROMPT.format(hint=hint or "none")},
                ],
            }],
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    text = resp.json()["content"][0]["text"]
    return _extract_json(text)


def call_gemini(api_key: str, image_url: str, hint: str) -> dict:
    img_resp = requests.get(image_url, timeout=TIMEOUT)
    img_resp.raise_for_status()
    import base64
    b64 = base64.b64encode(img_resp.content).decode()
    mime = img_resp.headers.get("Content-Type", "image/jpeg").split(";")[0]

    resp = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash:generateContent?key={api_key}",  # verify current model name
        json={
            "contents": [{
                "parts": [
                    {"text": WAND_PROMPT.format(hint=hint or "none")},
                    {"inline_data": {"mime_type": mime, "data": b64}},
                ],
            }],
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    return _extract_json(text)


def call_grok(api_key: str, image_url: str, hint: str) -> dict:
    resp = requests.post(
        "https://api.x.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "grok-vision-beta",  # verify current vision-capable model name
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": WAND_PROMPT.format(hint=hint or "none")},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }],
            "max_tokens": 300,
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]
    return _extract_json(text)


PROVIDER_CALLERS = {
    "openai": call_openai,
    "claude": call_claude,
    "gemini": call_gemini,
    "grok": call_grok,
}

# Priority order when more than one provider is enabled — first one wins.
WAND_PRIORITY = ["grok", "claude", "gemini", "openai"]


def test_key(provider: str, api_key: str) -> bool:
    """Cheap text-only ping per provider — no image round-trip needed to test a key."""
    if provider == "openai":
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Reply with OK"}], "max_tokens": 5},
            timeout=TIMEOUT,
        )
    elif provider == "claude":
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
            json={"model": "claude-sonnet-4-5", "max_tokens": 5, "messages": [{"role": "user", "content": "Reply with OK"}]},
            timeout=TIMEOUT,
        )
    elif provider == "gemini":
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}",
            json={"contents": [{"parts": [{"text": "Reply with OK"}]}]},
            timeout=TIMEOUT,
        )
    elif provider == "grok":
        r = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "grok-beta", "messages": [{"role": "user", "content": "Reply with OK"}], "max_tokens": 5},
            timeout=TIMEOUT,
        )
    else:
        raise ValueError(f"Unknown provider: {provider}")
    return r.status_code < 400
