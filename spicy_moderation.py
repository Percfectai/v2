"""
spicy_moderation.py — Output moderation for SpicyAPI media + Mature Vault routing.

Every image/video generated via SpicyAPI on percfectai.com is inspected before it is
ever stored publicly or returned to the browser.
- Pass -> saved normally to percfectai.com (`previews` bucket + `generations`).
- Fail (or unverifiable — fail closed for Stripe safety) -> stored in the private
  Supabase `vault-media` bucket and recorded in `public.private_library_items` under
  the user's `user_id` so they can sign in with the same login on the mature site
  to retrieve their file.
"""
from __future__ import annotations

import base64
import datetime
import json
import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests

log = logging.getLogger("spicy_moderation")

MATURE_VAULT_BUCKET = (os.getenv("MATURE_VAULT_BUCKET") or "vault-media").strip() or "vault-media"
GEMINI_MOD_MODEL = (os.getenv("GEMINI_MODERATION_MODEL") or "gemini-2.5-flash").strip() or "gemini-2.5-flash"

_MOD_PROMPT = (
    "You are a strict content safety moderator for a mainstream Stripe-backed website. "
    "Inspect the attached media carefully. Return {\"safe\": false, \"reason\": \"...\"} if it "
    "contains ANY nudity (exposed genitals, breasts/nipples, bare buttocks), sexually explicit or "
    "pornographic content, sexually suggestive/erotic lingerie/fetish poses, graphic gore/violence, "
    "or harmful illegal content. Return {\"safe\": true, \"reason\": \"ok\"} ONLY if it is clearly "
    "safe-for-work (SFW) and suitable for a general-audience storefront. Reply strictly in JSON."
)

_SAFETY_NONE = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]


def mature_site_url() -> str:
    return (os.getenv("MATURE_SITE_URL") or "").strip()


def download_media_bytes(url: str, *, is_video: bool = False) -> Tuple[bytes, str]:
    """Download generated asset bytes and content-type from SpicyAPI CDN."""
    if not url:
        raise RuntimeError("Empty media URL")
    if url.startswith("data:"):
        hdr, b64 = url.split(",", 1)
        ctype = hdr.split(";")[0].replace("data:", "") or ("video/mp4" if is_video else "image/jpeg")
        return base64.b64decode(b64), ctype
    r = requests.get(url, timeout=60 if is_video else 30)
    r.raise_for_status()
    default_ct = "video/mp4" if is_video else "image/jpeg"
    ctype = (r.headers.get("Content-Type") or default_ct).split(";")[0].strip() or default_ct
    return r.content, ctype


def _extract_video_frames(video_bytes: bytes) -> List[bytes]:
    """Extract up to 3 representative JPEG frames from a video clip using ffmpeg."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not video_bytes:
        return []
    frames: List[bytes] = []
    with tempfile.TemporaryDirectory(prefix="spicy_mod_") as tmp:
        vid_path = os.path.join(tmp, "clip.mp4")
        with open(vid_path, "wb") as f:
            f.write(video_bytes)
        # Probe duration via ffprobe if available
        dur = 0.0
        ffprobe = shutil.which("ffprobe")
        if ffprobe:
            try:
                p = subprocess.run(
                    [ffprobe, "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", vid_path],
                    capture_output=True, text=True, timeout=10,
                )
                dur = float((p.stdout or "").strip() or 0)
            except Exception:
                dur = 0.0
        stamps = [max(0.2, dur * 0.15), max(0.5, dur * 0.5), max(0.8, dur * 0.85)] if dur > 1.2 else [0.2, 1.0]
        for idx, ts in enumerate(stamps):
            out_jpg = os.path.join(tmp, f"f_{idx}.jpg")
            try:
                subprocess.run(
                    [ffmpeg, "-y", "-ss", f"{ts:.2f}", "-i", vid_path,
                     "-frames:v", "1", "-q:v", "3", out_jpg],
                    capture_output=True, timeout=15,
                )
                if os.path.exists(out_jpg) and os.path.getsize(out_jpg) > 0:
                    with open(out_jpg, "rb") as jf:
                        frames.append(jf.read())
            except Exception:
                continue
    return frames


def moderate_media_bytes(
    media_bytes: bytes,
    *,
    media_type: str = "image",
    content_type: str = "image/jpeg",
    prompt: str = "",
) -> Dict[str, Any]:
    """Inspect image or video bytes via Gemini Vision.

    Fails CLOSED (safe=False) if GEMINI_API_KEY is missing, the API errors,
    Gemini refuses due to safety, or the output cannot be verified SFW.
    Returns {safe: bool, reason: str, frames: list[bytes]}.
    """
    key = (os.getenv("GEMINI_API_KEY") or "").strip()
    is_video = (media_type or "").lower() == "video"
    frames: List[bytes] = []
    if is_video:
        frames = _extract_video_frames(media_bytes)
        if not frames:
            return {"safe": False, "reason": "Could not extract video frames for moderation", "frames": []}
    if not key:
        return {"safe": False, "reason": "Moderation key not configured", "frames": frames}

    parts: List[Dict[str, Any]] = []
    if is_video:
        for fr in frames:
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(fr).decode("ascii")}})
    else:
        mime = content_type if content_type.startswith("image/") else "image/jpeg"
        parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(media_bytes).decode("ascii")}})

    prompt_ctx = f"\nGeneration prompt context: {prompt[:400]}" if prompt else ""
    parts.append({"text": _MOD_PROMPT + prompt_ctx})

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MOD_MODEL}:generateContent?key={key}"
    payload = {
        "contents": [{"parts": parts}],
        "safetySettings": _SAFETY_NONE,
        "generationConfig": {
            "temperature": 0.0,
            "responseMimeType": "application/json",
        },
    }
    try:
        r = requests.post(url, json=payload, timeout=30)
        if not r.ok:
            log.warning("Gemini moderation HTTP %s: %s", r.status_code, r.text[:200])
            return {"safe": False, "reason": f"Moderator unavailable ({r.status_code})", "frames": frames}
        data = r.json()
        fb = data.get("promptFeedback") or {}
        if fb.get("blockReason"):
            return {"safe": False, "reason": f"Blocked by safety filter ({fb.get('blockReason')})", "frames": frames}
        cand = (data.get("candidates") or [{}])[0]
        fin = str(cand.get("finishReason") or "").upper()
        if fin in ("SAFETY", "PROHIBITED_CONTENT", "RECITATION", "SPII"):
            return {"safe": False, "reason": f"Flagged by safety filter ({fin})", "frames": frames}
        text = ""
        for p in (cand.get("content") or {}).get("parts") or []:
            if "text" in p:
                text += p["text"]
        parsed = json.loads(text.strip())
        safe = parsed.get("safe") is True
        reason = str(parsed.get("reason") or ("ok" if safe else "flagged"))
        return {"safe": safe, "reason": reason, "frames": frames}
    except Exception as exc:
        log.warning("Gemini moderation check error (failing closed): %s", exc)
        return {"safe": False, "reason": "Moderation verification failed", "frames": frames}


def send_to_mature_vault(
    supabase: Any,
    user_id: int,
    media_bytes: bytes,
    *,
    media_type: str,
    content_type: str,
    prompt: str,
    model_id: str,
    moderation_reason: str,
    frames: Optional[List[bytes]] = None,
) -> Optional[str]:
    """Upload moderated media to private `vault-media` bucket and insert into `public.private_library_items`."""
    is_video = (media_type or "").lower() == "video"
    if is_video:
        ext = "mp4"
    elif "png" in (content_type or ""):
        ext = "png"
    elif "webp" in (content_type or ""):
        ext = "webp"
    else:
        ext = "jpg"

    uid_str = str(user_id)
    obj_path = f"{uid_str}/{uuid.uuid4().hex}.{ext}"
    supabase.storage.from_(MATURE_VAULT_BUCKET).upload(
        obj_path,
        media_bytes,
        file_options={"content-type": content_type or ("video/mp4" if is_video else "image/jpeg"), "upsert": "true"},
    )

    thumb_path = None
    if is_video and frames:
        try:
            t_path = f"{uid_str}/thumb_{uuid.uuid4().hex}.jpg"
            supabase.storage.from_(MATURE_VAULT_BUCKET).upload(
                t_path,
                frames[0],
                file_options={"content-type": "image/jpeg", "upsert": "true"},
            )
            thumb_path = t_path
        except Exception:
            thumb_path = None

    row = {
        "user_id": int(user_id),
        "title": (prompt or "Moderated Creation").strip()[:120] or "Moderated Creation",
        "prompt": (prompt or "").strip(),
        "media_type": "video" if is_video else "image",
        "media_url": None,
        "storage_path": obj_path,
        "thumbnail_url": thumb_path,
        "collection": "Moderated",
        "tags": ["spicyapi", "moderated", model_id],
        "source_app": "percfectai",
        "metadata": {
            "bucket": MATURE_VAULT_BUCKET,
            "object_path": obj_path,
            "thumbnail_path": thumb_path,
            "model": model_id,
            "moderation_reason": moderation_reason,
            "moderated_at": datetime.datetime.utcnow().isoformat(),
        },
    }
    res = supabase.table("private_library_items").insert(row).execute()
    inserted = (res.data or [{}])[0] if getattr(res, "data", None) else {}
    return inserted.get("id")
