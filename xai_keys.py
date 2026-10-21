"""xAI API keys — **IMAGE / VIDEO generation only**.

THREE SILOS (never mix):

  1. CHAT keys  — Vanessa/Mira/Sal/Ashley text (app._support_agent_key)
  2. VOICE keys — Ara/Eve TTS only (XAI_TTS_API_KEY)
  3. IMAGE keys — this module (XAI_API_KEYS pool)

Voice keys do not support chat. Chat keys do not support image or voice.
Image keys do not support chat or voice. Do not put speech keys in this pool.
"""

from __future__ import annotations

import os
import threading
from contextvars import ContextVar
from typing import List

_current: ContextVar[str | None] = ContextVar("xai_api_key", default=None)
_keys_cache: List[str] | None = None
_keys_lock = threading.Lock()
_rr_lock = threading.Lock()
_rr_index = 0

# Env names that are CHAT or VOICE — never load into the image pool
_FORBIDDEN_IN_IMAGE_POOL = frozenset({
    "XAI_VANESSA_API_KEY",
    "XAI_MIRA_API_KEY",
    "XAI_TTS_API_KEY",
    "XAI_STT_API_KEY",
    "XAI_VANESSA_STT_API_KEY",
    "XAI_VANESSA_TTS_API_KEY",

    "XAI_USER_SUPPORT_API_KEY",
    "XAI_FRONT_SUPPORT_API_KEY",
    "GROK_USER_SUPPORT_API_KEY",
    "XAI_DEBUG_SUPPORT_API_KEY",
    "XAI_SUPPORT_API_KEY",
    "GROK_SUPPORT_API_KEY",
    "SUPPORT_XAI_API_KEY",
    "XAI_ADMIN_MULTIAGENT_API_KEY",
    "XAI_ADMIN_COMPANION_API_KEY",
})


def _split_keys(raw: str) -> List[str]:
    if not raw:
        return []
    parts: List[str] = []
    for chunk in raw.replace("\n", ",").split(","):
        k = chunk.strip()
        if k and k not in parts:
            parts.append(k)
    return parts


def load_xai_keys() -> List[str]:
    """Image/video keys only. Never chat or TTS keys."""
    global _keys_cache
    with _keys_lock:
        if _keys_cache is not None:
            return _keys_cache
        keys: List[str] = []

        def _add_many(raw: str) -> None:
            for k in _split_keys(raw):
                if k not in keys:
                    keys.append(k)

        # ORIGINAL image/video keys only (Nick's media pool). Never chat/voice envs.
        _add_many(os.getenv("XAI_API_KEYS") or "")
        _add_many(os.getenv("XAI_IMAGE_API_KEYS") or "")
        _add_many(os.getenv("XAI_IMAGE_VIDEO_KEY") or "")
        _add_many(os.getenv("XAI_GENERATE_API_KEY") or "")
        # Do NOT add XAI_VANESSA_*, XAI_MIRA_*, XAI_TTS_*, Sal/Ashley chat keys.
        # Do NOT add generic XAI_API_KEY / ALL_MODELS (those get mixed with chat).

        _keys_cache = keys
        return keys


def reload_xai_keys() -> List[str]:
    global _keys_cache, _rr_index
    with _keys_lock:
        _keys_cache = None
    with _rr_lock:
        _rr_index = 0
    return load_xai_keys()


def max_concurrent_jobs() -> int:
    keys = load_xai_keys()
    raw = (os.getenv("STUDIO_MAX_CONCURRENT_JOBS") or "").strip()
    if raw:
        cap = max(1, int(raw))
    elif keys:
        cap = len(keys)
    else:
        cap = 5
    if keys:
        return min(cap, len(keys))
    return cap


def next_key() -> str:
    """Round-robin image keys only."""
    global _rr_index
    keys = load_xai_keys()
    if not keys:
        raise RuntimeError(
            "No IMAGE API keys configured. Set XAI_API_KEYS (image/video only). "
            "Do not put chat or TTS keys here."
        )
    with _rr_lock:
        # Every gunicorn worker process starts its own counter at 0, so
        # concurrent picture+video requests in different processes all hit
        # keys[0] together and rate-limit. Stagger each process's start.
        if _rr_index == 0:
            import secrets
            _rr_index = secrets.randbelow(len(keys) * 1000)
        k = keys[_rr_index % len(keys)]
        _rr_index += 1
        return k


def key_for_slot(slot: int) -> str:
    return next_key()


def use_key(key: str):
    return _current.set(key)


def reset_key(token) -> None:
    _current.reset(token)


def get_api_key() -> str:
    k = _current.get()
    if k:
        return k
    return next_key()


def xai_headers() -> dict:
    return {
        "Authorization": f"Bearer {get_api_key()}",
        "Content-Type": "application/json",
    }


def image_model_ids() -> List[str]:
    """Fast path first. Default ``grok-imagine-image`` (working live model).

    Do not default to ``grok-imagine-image-2.0`` — that broke Photos gens on
    2026-09-24. Opt in via ``XAI_IMAGE_MODEL`` only after Nick confirms 2.0 works.
    Quality only if ``XAI_IMAGE_MODEL_QUALITY`` is set — never auto-chain after timeout.
    """
    models: List[str] = []
    for m in (
        (os.getenv("XAI_IMAGE_MODEL") or "").strip(),
        "grok-imagine-image",
        # Optional only — set XAI_IMAGE_MODEL_QUALITY on Render if you want a 2nd model
        (os.getenv("XAI_IMAGE_MODEL_QUALITY") or "").strip(),
    ):
        if m and m not in models:
            models.append(m)
    return models


def video_model_ids() -> List[str]:
    models: List[str] = []
    for m in (
        (os.getenv("XAI_VIDEO_MODEL") or "").strip(),
        "grok-imagine-video",
    ):
        if m and m not in models:
            models.append(m)
    return models
