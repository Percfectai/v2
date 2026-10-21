"""3D character generation via PoYo Meshy-6 multi-image — routes for /api/3d/*.

Wire into app.py (surgical — do NOT replace existing routes):

    import three_d_character_gen
    three_d_character_gen.init_app(app)

Endpoints:
  GET  /api/3d/generate-character/config  — {configured, mock, model}
  POST /api/3d/generate-character         — start multi-image job (login-gated)
  GET  /api/3d/generate-character/<id>    — poll job; on success stores GLB
  GET  /api/3d/characters                 — list user roster GLBs
  POST /api/3d/upload-character           — manual GLB upload → same roster
    (only registered if not already present on the app)

Auth: session cookie (same-origin). Admin-first is fine; any logged-in user works.
Degrades gracefully when POYO_API_KEY is missing (503 + clear message).
Mock pipeline: set POYO_MESHY_MOCK=1 to exercise end-to-end without a key.

Multi-image model: meshy-6-multi-image-to-3d (1–4 views: front required;
back / left / right optional). Docs:
https://docs.poyo.ai/api-manual/3d-series/meshy-6-3d
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import Blueprint, current_app, jsonify, request, session

import poyo_client
from poyo_client import PoyoError

bp = Blueprint("three_d_character_gen", __name__)

# Default fallback character used by mock mode + empty roster seed
DEFAULT_GLB = "/motion-lab/meshy6_character.glb"

# In-process job cache (also file-backed under data/3d_gen_jobs/)
_JOBS: Dict[str, Dict[str, Any]] = {}

# Ordered multi-image slots (front required; others optional)
VIEW_SLOTS = ("front", "back", "left", "right")


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _data_dir() -> Path:
    d = _repo_root() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _jobs_dir() -> Path:
    d = _data_dir() / "3d_gen_jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _chars_root() -> Path:
    """On-disk GLB roster (same path family as upload-character flow)."""
    d = _repo_root() / "static" / "user_glb_characters"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _registry_path() -> Path:
    return _data_dir() / "user_glb_characters.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_segment(value: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", (value or "anon").strip())[:80]
    return s or "anon"


def _current_user_id() -> Optional[str]:
    """Resolve logged-in user from common session keys used in this app."""
    for key in ("user_id", "uid", "userId", "id", "email", "username", "user"):
        val = session.get(key)
        if val is None:
            continue
        if isinstance(val, dict):
            for k2 in ("id", "user_id", "email", "username"):
                if val.get(k2):
                    return str(val.get(k2))
            continue
        s = str(val).strip()
        if s:
            return s
    # Flask-Login style
    try:
        from flask_login import current_user  # type: ignore

        if getattr(current_user, "is_authenticated", False):
            for attr in ("id", "user_id", "email", "username"):
                v = getattr(current_user, attr, None)
                if v:
                    return str(v)
    except Exception:
        pass
    return None


def _is_admin(user_id: Optional[str] = None) -> bool:
    if session.get("is_admin") or session.get("admin"):
        return True
    role = str(session.get("role") or session.get("user_role") or "").lower()
    if role in ("admin", "owner", "superadmin"):
        return True
    uid = (user_id or _current_user_id() or "").lower()
    admin_emails = (
        os.environ.get("ADMIN_EMAILS")
        or os.environ.get("ADMIN_EMAIL")
        or ""
    ).lower()
    if uid and uid in admin_emails:
        return True
    return False


def _require_login() -> Tuple[Optional[str], Optional[Any]]:
    """Return (user_id, error_response). error_response is a Flask response if denied."""
    uid = _current_user_id()
    if not uid:
        return None, (jsonify(error="Log in to generate 3D characters.", login_required=True), 401)
    return uid, None


def _mock_enabled() -> bool:
    return (os.environ.get("POYO_MESHY_MOCK") or "").strip() in ("1", "true", "yes", "on")


def _load_registry() -> Dict[str, List[Dict[str, Any]]]:
    path = _registry_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            # normalize values to lists
            out: Dict[str, List[Dict[str, Any]]] = {}
            for k, v in data.items():
                if isinstance(v, list):
                    out[str(k)] = [x for x in v if isinstance(x, dict)]
            return out
    except Exception:
        pass
    return {}


def _save_registry(reg: Dict[str, List[Dict[str, Any]]]) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, indent=2), encoding="utf-8")
    tmp.replace(path)


def store_user_glb_character(
    user_id: str,
    *,
    glb_bytes: Optional[bytes] = None,
    glb_url: Optional[str] = None,
    name: str = "Character",
    source: str = "upload",
    poyo_task_id: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Persist a GLB into the user roster (shared by upload + generate flows).

    Provide either glb_bytes or a fetchable glb_url.
    Returns the roster entry dict.
    """
    user_id = str(user_id or "anon")
    char_id = uuid.uuid4().hex[:12]
    user_dir = _chars_root() / _safe_segment(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{char_id}.glb"
    dest = user_dir / filename

    if glb_bytes is None:
        url = (glb_url or "").strip()
        if not url:
            raise ValueError("store_user_glb_character requires glb_bytes or glb_url")
        # Local static path
        if url.startswith("/") and not url.startswith("//"):
            local = _repo_root() / "static" / url.lstrip("/")
            # also allow /motion-lab/... served as static sibling
            alt = _repo_root() / url.lstrip("/")
            static_ml = _repo_root() / "static" / url.lstrip("/")
            picked = None
            for candidate in (local, alt, static_ml, _repo_root() / "static" / "motion-lab" / Path(url).name):
                if candidate.is_file():
                    picked = candidate
                    break
            if picked is not None:
                glb_bytes = picked.read_bytes()
            else:
                # Try absolute site fetch only for http(s)
                raise ValueError(f"Local GLB not found for {url}")
        elif url.startswith("http://") or url.startswith("https://"):
            r = requests.get(url, timeout=120)
            if not r.ok:
                raise ValueError(f"Failed to download GLB HTTP {r.status_code}")
            glb_bytes = r.content
        else:
            raise ValueError("glb_url must be http(s) or site-relative path")

    if not glb_bytes or len(glb_bytes) < 64:
        raise ValueError("GLB payload too small or empty")

    dest.write_bytes(glb_bytes)
    public_url = f"/static/user_glb_characters/{_safe_segment(user_id)}/{filename}"

    entry: Dict[str, Any] = {
        "id": char_id,
        "name": (name or "Character").strip()[:80] or "Character",
        "glb_url": public_url,
        "source": source,
        "created_at": _utc_now(),
        "user_id": user_id,
    }
    if poyo_task_id:
        entry["poyo_task_id"] = poyo_task_id
    if extra:
        entry["extra"] = extra

    reg = _load_registry()
    bucket = reg.setdefault(user_id, [])
    bucket.insert(0, entry)
    # Cap roster growth
    reg[user_id] = bucket[:100]
    _save_registry(reg)

    # Per-user index for easy inspection
    index_path = user_dir / "index.json"
    try:
        index_path.write_text(json.dumps(reg[user_id], indent=2), encoding="utf-8")
    except Exception:
        pass

    return entry


def list_user_characters(user_id: str) -> List[Dict[str, Any]]:
    reg = _load_registry()
    return list(reg.get(str(user_id), []))


def _job_path(job_id: str) -> Path:
    return _jobs_dir() / f"{_safe_segment(job_id)}.json"


def _save_job(job: Dict[str, Any]) -> None:
    job_id = str(job.get("id") or "")
    if not job_id:
        return
    _JOBS[job_id] = job
    try:
        _job_path(job_id).write_text(json.dumps(job, indent=2), encoding="utf-8")
    except Exception:
        pass


def _load_job(job_id: str) -> Optional[Dict[str, Any]]:
    if job_id in _JOBS:
        return _JOBS[job_id]
    path = _job_path(job_id)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _JOBS[job_id] = data
                return data
        except Exception:
            return None
    return None


def _public_base_url() -> str:
    """Absolute origin for rehosting uploads so PoYo can fetch them."""
    # Prefer brand domain (SITE_URL) over Render internal host so PoYo can fetch
    # rehosted /static/… sources when the request is multi-worker / no request ctx.
    env = (
        os.environ.get("PUBLIC_BASE_URL")
        or os.environ.get("SITE_URL")
        or os.environ.get("RENDER_EXTERNAL_URL")
        or ""
    ).strip()
    if env:
        return env.rstrip("/")
    try:
        return request.url_root.rstrip("/")
    except Exception:
        return ""


def _rehost_upload(file_storage, user_id: str) -> str:
    """Save uploaded image under static/ and return a public https URL when possible."""
    raw = file_storage.read()
    if not raw:
        raise ValueError("Empty upload")
    ext = Path(file_storage.filename or "source.png").suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        ext = ".png"
    rel_dir = _chars_root() / _safe_segment(user_id) / "sources"
    rel_dir.mkdir(parents=True, exist_ok=True)
    name = f"src_{uuid.uuid4().hex[:10]}{ext}"
    dest = rel_dir / name
    dest.write_bytes(raw)
    rel_url = f"/static/user_glb_characters/{_safe_segment(user_id)}/sources/{name}"
    base = _public_base_url()
    if base:
        return f"{base}{rel_url}"
    return rel_url


def _absolutize_image_url(image_url: str) -> str:
    """Ensure PoYo can fetch the image (public http(s))."""
    image_url = (image_url or "").strip()
    if not image_url:
        return ""
    if image_url.startswith("/") and not image_url.startswith("//"):
        base = _public_base_url()
        if not base:
            raise ValueError("Could not build a public URL for the image. Set PUBLIC_BASE_URL.")
        return f"{base}{image_url}"
    return image_url


def _views_from_library_character(user_id: str, character_id: Any) -> Tuple[Dict[str, str], str, Optional[str]]:
    """Pull front/left/right/back from an existing Characters roster row.

    Every library character already has 4 orthographic shots + spin — never ask
    the user to re-upload. images[] order is CHARACTER_POSES: front, left, right, back.

    Returns (slot_map, character_name, error_message).
    """
    if character_id is None or str(character_id).strip() == "":
        return {}, "", "character_id required"
    try:
        from flask_login import current_user  # type: ignore
        uid_int = None
        if getattr(current_user, "is_authenticated", False):
            try:
                uid_int = int(current_user.id)
            except (TypeError, ValueError):
                uid_int = current_user.id
    except Exception:
        uid_int = None

    # Prefer app.supabase (same DB as Characters page)
    try:
        import app as app_mod
        sb = getattr(app_mod, "supabase", None)
    except Exception:
        sb = None
    if sb is None:
        return {}, "", "Characters database unavailable"

    cid = character_id
    try:
        if str(cid).isdigit():
            cid = int(cid)
    except (TypeError, ValueError):
        pass

    try:
        q = (
            sb.table("characters")
            .select("id,name,images,primary_image_url,user_id")
            .eq("id", cid)
            .limit(1)
        )
        # Scope to owner when we have a numeric user id
        if uid_int is not None:
            q = q.eq("user_id", uid_int)
        res = q.execute()
        row = (res.data or [None])[0]
    except Exception as e:
        return {}, "", f"Could not load character: {e}"

    if not row:
        return {}, "", "Character not found (must be one of your Characters roster cards)."

    images = row.get("images") or []
    if not isinstance(images, list):
        images = []
    images = [u for u in images if isinstance(u, str) and u.strip()]
    primary = (row.get("primary_image_url") or "").strip()
    if not images and primary:
        images = [primary]

    # CHARACTER_POSES order: front, left, right, back
    pose_order = ("front", "left", "right", "back")
    slot_map: Dict[str, str] = {}
    for i, pose in enumerate(pose_order):
        if i < len(images) and images[i]:
            slot_map[pose] = images[i].strip()
    if "front" not in slot_map and primary:
        slot_map["front"] = primary

    if "front" not in slot_map:
        return {}, "", "Character has no front image — open Characters and rebuild the pack first."

    # Absolutize via app helper when relative /media or ephemeral
    try:
        publicize = getattr(app_mod, "_public_image_url_for_xai", None)
        if callable(publicize):
            slot_map = {k: publicize(v) or v for k, v in slot_map.items()}
    except Exception:
        pass

    name = (row.get("name") or "Character").strip()[:80] or "Character"
    return slot_map, name, None


def _collect_view_urls(user_id: str) -> Tuple[List[str], Dict[str, str], Optional[str]]:
    """Parse multipart/JSON for front/back/left/right (+ legacy single image).

    CRITICAL: if character_id is set, auto-pull the 4 library views and skip
    manual upload (manual slots are fallback only).

    Returns (ordered_urls, slot_map, error_message).
    ordered_urls: only filled slots, order front→back→left→right (max 4).
    """
    slot_map: Dict[str, str] = {}
    err: Optional[str] = None

    def _set_slot(slot: str, url: str) -> None:
        u = (url or "").strip()
        if u:
            slot_map[slot] = u

    # --- Preferred path: existing Characters roster id ---
    char_id = None
    if request.content_type and "multipart/form-data" in (request.content_type or ""):
        char_id = (
            request.form.get("character_id")
            or request.form.get("char_id")
            or request.form.get("library_character_id")
            or ""
        ).strip() or None
    else:
        body0 = request.get_json(silent=True) or {}
        raw = body0.get("character_id") or body0.get("char_id") or body0.get("library_character_id")
        if raw is not None and str(raw).strip() != "":
            char_id = raw

    if char_id is not None:
        lib_map, _lib_name, lib_err = _views_from_library_character(user_id, char_id)
        if lib_err:
            return [], {}, lib_err
        # VIEW_SLOTS order for Meshy: front, back, left, right
        for slot in VIEW_SLOTS:
            if slot in lib_map:
                slot_map[slot] = lib_map[slot]
        ordered = [slot_map[s] for s in VIEW_SLOTS if s in slot_map]
        return ordered, slot_map, None

    if request.content_type and "multipart/form-data" in (request.content_type or ""):
        # Named file fields: image_front / image_back / … and legacy image/file/photo → front
        for slot in VIEW_SLOTS:
            f = (
                request.files.get(f"image_{slot}")
                or request.files.get(f"{slot}")
                or request.files.get(f"photo_{slot}")
            )
            if f and f.filename:
                try:
                    _set_slot(slot, _rehost_upload(f, user_id))
                except Exception as e:
                    return [], {}, f"Upload failed ({slot}): {e}"
            # URL fields alongside files
            url_field = (
                request.form.get(f"image_url_{slot}")
                or request.form.get(f"{slot}_url")
                or request.form.get(f"url_{slot}")
                or ""
            ).strip()
            if url_field and slot not in slot_map:
                _set_slot(slot, url_field)

        # Legacy single upload → front
        if "front" not in slot_map:
            f = request.files.get("image") or request.files.get("file") or request.files.get("photo")
            if f and f.filename:
                try:
                    _set_slot("front", _rehost_upload(f, user_id))
                except Exception as e:
                    return [], {}, f"Upload failed: {e}"
        legacy_url = (
            request.form.get("image_url") or request.form.get("url") or ""
        ).strip()
        if legacy_url and "front" not in slot_map:
            _set_slot("front", legacy_url)

        # Optional JSON array of URLs in form field image_urls
        raw_list = request.form.get("image_urls") or ""
        if raw_list and not slot_map:
            try:
                parsed = json.loads(raw_list)
                if isinstance(parsed, list):
                    for i, u in enumerate(parsed[:4]):
                        if i < len(VIEW_SLOTS) and u:
                            _set_slot(VIEW_SLOTS[i], str(u).strip())
            except Exception:
                pass
    else:
        body = request.get_json(silent=True) or {}
        # Named slots
        for slot in VIEW_SLOTS:
            u = (
                body.get(f"image_url_{slot}")
                or body.get(f"{slot}_image_url")
                or body.get(f"{slot}_url")
                or body.get(slot)
                or ""
            )
            if isinstance(u, str) and u.strip():
                _set_slot(slot, u.strip())
        # image_urls array
        arr = body.get("image_urls") or body.get("images") or []
        if isinstance(arr, list):
            for i, u in enumerate(arr[:4]):
                if i < len(VIEW_SLOTS) and u and VIEW_SLOTS[i] not in slot_map:
                    _set_slot(VIEW_SLOTS[i], str(u).strip())
        # Legacy single
        legacy = str(body.get("image_url") or body.get("url") or "").strip()
        if legacy and "front" not in slot_map:
            _set_slot("front", legacy)

    ordered = [slot_map[s] for s in VIEW_SLOTS if s in slot_map]
    return ordered, slot_map, err


def _start_mock_job(user_id: str, name: str, options: Dict[str, Any]) -> Dict[str, Any]:
    job_id = f"mock_{uuid.uuid4().hex[:12]}"
    job = {
        "id": job_id,
        "user_id": user_id,
        "status": "processing",
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "name": name,
        "options": options,
        "mock": True,
        "poyo_task_id": None,
        "polls": 0,
        "message": "Mock Meshy-6 multi-image generation started…",
    }
    _save_job(job)
    return job


def _advance_mock_job(job: Dict[str, Any]) -> Dict[str, Any]:
    polls = int(job.get("polls") or 0) + 1
    job["polls"] = polls
    job["updated_at"] = _utc_now()
    if polls < 2:
        job["status"] = "processing"
        job["message"] = f"Mock generating 3D character… (step {polls}/2)"
        _save_job(job)
        return job

    # Complete: copy default GLB into roster
    try:
        entry = store_user_glb_character(
            job["user_id"],
            glb_url=DEFAULT_GLB,
            name=job.get("name") or "Mock Character",
            source="meshy-6-multi-mock",
            poyo_task_id=job.get("id"),
        )
        job["status"] = "done"
        job["message"] = "Mock generation complete"
        job["character"] = entry
        job["glb_url"] = entry["glb_url"]
    except Exception as e:
        # If default asset missing on disk, still point at the known URL
        entry = {
            "id": uuid.uuid4().hex[:12],
            "name": job.get("name") or "Mock Character",
            "glb_url": DEFAULT_GLB,
            "source": "meshy-6-multi-mock",
            "created_at": _utc_now(),
            "user_id": job["user_id"],
            "note": f"fallback (store failed: {e})",
        }
        reg = _load_registry()
        reg.setdefault(job["user_id"], []).insert(0, entry)
        _save_registry(reg)
        job["status"] = "done"
        job["message"] = "Mock generation complete (default GLB)"
        job["character"] = entry
        job["glb_url"] = DEFAULT_GLB
    _save_job(job)
    return job


def _poll_live_job(job: Dict[str, Any]) -> Dict[str, Any]:
    if job.get("status") in ("done", "failed"):
        return job

    task_id = job.get("poyo_task_id")
    if not task_id:
        job["status"] = "failed"
        job["error"] = "Missing PoYo task id"
        job["updated_at"] = _utc_now()
        _save_job(job)
        return job

    try:
        data = poyo_client.get_task(task_id)
    except PoyoError as e:
        job["message"] = str(e)
        job["updated_at"] = _utc_now()
        # Keep processing on transient poll errors
        _save_job(job)
        return job

    st = poyo_client._status_of(data)
    terminal_ok = {"succeeded", "success", "completed", "complete", "done", "finished"}
    terminal_bad = {"failed", "error", "canceled", "cancelled", "rejected"}

    if st in terminal_bad:
        # Official PoYo status: { code, data: { status, error_message, … } }
        data_inner = data.get("data") if isinstance(data.get("data"), dict) else {}
        err = (
            data.get("error")
            or data.get("message")
            or data.get("fail_reason")
            or data_inner.get("error")
            or data_inner.get("message")
            or data_inner.get("fail_reason")
            or data_inner.get("error_message")
            or st
        )
        if isinstance(err, dict):
            err = err.get("message") or err.get("type") or str(err)
        job["status"] = "failed"
        job["error"] = f"PoYo task {st}: {err}"
        job["updated_at"] = _utc_now()
        _save_job(job)
        return job

    if st not in terminal_ok:
        job["status"] = "processing"
        job["message"] = f"Generating 3D character… ({st or 'running'})"
        job["poyo_status"] = st
        job["updated_at"] = _utc_now()
        _save_job(job)
        return job

    glb_url = poyo_client._output_glb_url(data)
    if not glb_url:
        job["status"] = "failed"
        job["error"] = (
            f"PoYo task completed but no GLB URL found (keys={list(data.keys())[:16]})"
        )
        job["updated_at"] = _utc_now()
        _save_job(job)
        return job

    try:
        entry = store_user_glb_character(
            job["user_id"],
            glb_url=glb_url,
            name=job.get("name") or "Meshy Character",
            source="meshy-6-multi",
            poyo_task_id=task_id,
            extra={"remote_glb_url": glb_url, "views": job.get("image_urls")},
        )
        job["status"] = "done"
        job["message"] = "3D character ready"
        job["character"] = entry
        job["glb_url"] = entry["glb_url"]
        job["remote_glb_url"] = glb_url
    except Exception as e:
        # PoYo CDN URL is still usable for ~24h — do not fail the whole job
        # if local disk rehost fails (Render ephemeral / write error).
        entry = {
            "id": uuid.uuid4().hex[:12],
            "name": job.get("name") or "Meshy Character",
            "glb_url": glb_url,
            "source": "meshy-6-multi-remote",
            "created_at": _utc_now(),
            "user_id": job["user_id"],
            "poyo_task_id": task_id,
            "note": f"remote CDN (local store failed: {e})",
            "extra": {"remote_glb_url": glb_url},
        }
        try:
            reg = _load_registry()
            reg.setdefault(str(job["user_id"]), []).insert(0, entry)
            reg[str(job["user_id"])] = reg[str(job["user_id"])][:100]
            _save_registry(reg)
        except Exception:
            pass
        job["status"] = "done"
        job["message"] = "3D character ready (CDN URL — rehost failed, dock now)"
        job["character"] = entry
        job["glb_url"] = glb_url
        job["remote_glb_url"] = glb_url
        job["store_warning"] = str(e)
    job["updated_at"] = _utc_now()
    _save_job(job)
    return job


@bp.route("/api/3d/generate-character/config", methods=["GET"])
def generate_character_config():
    """Public-ish config probe for the /3d UI (no secrets)."""
    return jsonify(
        {
            "ok": True,
            "configured": poyo_client.is_configured(),
            "mock": _mock_enabled(),
            "model": poyo_client.POYO_MODEL_MESHY_6,
            "views": list(VIEW_SLOTS),
            "max_images": 4,
            "front_required": True,
            "cost_credits_hint": 60,
            "rigging_default": True,
            "library_character_views": True,
            "message": (
                None
                if poyo_client.is_configured() or _mock_enabled()
                else "POYO_API_KEY is not set — 3D generation unavailable until the key is added on Render."
            ),
        }
    )


@bp.route("/api/3d/library-characters", methods=["GET"])
def list_library_characters_for_3d():
    """List the user's Characters roster cards (4-view packs) for 3D generate.

    Does NOT re-upload photos — frontend sends character_id; backend pulls views.
    """
    user_id, err = _require_login()
    if err:
        return err
    # Prefer flask-login numeric id (matches characters.user_id); fall back to session.
    uid = None
    try:
        from flask_login import current_user  # type: ignore
        if getattr(current_user, "is_authenticated", False):
            uid = current_user.id
    except Exception:
        uid = None
    if uid is None and user_id is not None:
        # Session may hold int id as string
        try:
            uid = int(str(user_id).strip()) if str(user_id).strip().isdigit() else user_id
        except (TypeError, ValueError):
            uid = user_id
    if uid is None:
        return jsonify(error="Log in required", login_required=True), 401
    try:
        import app as app_mod
        res = (
            app_mod.supabase.table("characters")
            .select("id,name,primary_image_url,images,spin_video_url,created_at")
            .eq("user_id", uid)
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        )
        rows = res.data or []
    except Exception as e:
        return jsonify(error=f"Could not list characters: {e}", characters=[]), 500

    out = []
    for r in rows:
        imgs = r.get("images") or []
        if not isinstance(imgs, list):
            imgs = []
        # Keep only non-empty string URLs; order is CHARACTER_POSES: front, left, right, back
        img_urls = [u.strip() for u in imgs if isinstance(u, str) and u.strip()]
        n_views = len(img_urls)
        if n_views < 1 and r.get("primary_image_url"):
            n_views = 1
            if not img_urls:
                img_urls = [str(r.get("primary_image_url")).strip()]
        out.append(
            {
                "id": r.get("id"),
                "name": r.get("name") or "Character",
                "primary_image_url": r.get("primary_image_url"),
                # Frontend thumbs + readiness need the actual URLs (was omitted → empty cards)
                "images": img_urls[:4],
                "view_count": n_views,
                "has_spin": bool(r.get("spin_video_url")),
                # Product path needs full 4-angle pack (Meshy multi-image accepts 1–4; we require 4)
                "ready_for_3d": n_views >= 4,
            }
        )
    return jsonify({"ok": True, "characters": out, "count": len(out)})


@bp.route("/api/3d/generate-character", methods=["POST"])
def generate_character():
    """Start Meshy-6 multi-image→3D job. Login-gated. Returns {job_id}.

    Accepts 1–4 views (front required unless mock):
      multipart: image_front / image_back / image_left / image_right
                 + image_url_front / … or legacy image + image_url
      JSON: image_urls[], or image_url_front / front_image_url / …, or image_url
      options: rig / enable_rigging (default true), rigging_height_meters, name
    """
    user_id, err = _require_login()
    if err:
        return err

    mock = _mock_enabled()
    if not poyo_client.is_configured() and not mock:
        return (
            jsonify(
                error=(
                    "POYO_API_KEY is not configured. 3D character generation is unavailable "
                    "until the key is set on Render. The rest of the /3d page still works."
                ),
                configured=False,
            ),
            503,
        )

    # Parse body (JSON or multipart)
    name = "Character"
    options: Dict[str, Any] = {"rig": True}
    library_char_id = None

    if request.content_type and "multipart/form-data" in (request.content_type or ""):
        name = (request.form.get("name") or name).strip() or name
        library_char_id = (
            request.form.get("character_id")
            or request.form.get("char_id")
            or ""
        ).strip() or None
        rig_raw = request.form.get("rig", request.form.get("enable_rigging", "true"))
        options["rig"] = str(rig_raw).lower() not in ("0", "false", "no", "off")
        h_raw = request.form.get("rigging_height_meters") or request.form.get("height_meters")
        if h_raw not in (None, ""):
            options["rigging_height_meters"] = h_raw
        if request.form.get("topology"):
            options["topology"] = request.form.get("topology")
        if request.form.get("target_polycount") is not None:
            options["target_polycount"] = request.form.get("target_polycount")
    else:
        body = request.get_json(silent=True) or {}
        name = str(body.get("name") or name).strip() or name
        raw_cid = body.get("character_id") or body.get("char_id")
        if raw_cid is not None and str(raw_cid).strip() != "":
            library_char_id = raw_cid
        if "rig" in body or "enable_rigging" in body or "rigging" in body:
            options["rig"] = bool(
                body.get("rig", body.get("enable_rigging", body.get("rigging", True)))
            )
        else:
            # Default ON
            options["rig"] = True
        if body.get("rigging_height_meters") is not None or body.get("height_meters") is not None:
            options["rigging_height_meters"] = body.get(
                "rigging_height_meters", body.get("height_meters")
            )
        if body.get("topology"):
            options["topology"] = body["topology"]
        if body.get("target_polycount") is not None:
            options["target_polycount"] = body["target_polycount"]

    # Prefer library character name when pulling auto views
    if library_char_id is not None and (not name or name in ("Character", "Meshy Character")):
        _lib_map, lib_name, _ = _views_from_library_character(user_id, library_char_id)
        if lib_name:
            name = lib_name

    ordered_urls, slot_map, collect_err = _collect_view_urls(user_id)
    if collect_err:
        return jsonify(error=collect_err), 400

    if not ordered_urls and not mock:
        return jsonify(
            error=(
                "Pick a Characters library card (uses its 4 views automatically), "
                "or open Manual views and provide at least a Front photo."
            )
        ), 400

    # Mock path (pipeline shape test without key / without billing)
    if mock:
        job = _start_mock_job(user_id, name, {**options, "views": list(slot_map.keys())})
        return jsonify(
            {
                "ok": True,
                "async": True,
                "job_id": job["id"],
                "status": job["status"],
                "mock": True,
                "message": job.get("message"),
                "views": list(slot_map.keys()) or ["front"],
            }
        ), 202

    # Live PoYo path — absolutize every URL
    abs_urls: List[str] = []
    try:
        for u in ordered_urls:
            abs_u = _absolutize_image_url(u)
            if not (abs_u.startswith("https://") or abs_u.startswith("http://")):
                return jsonify(error=f"image_url must be a public http(s) URL: {u[:64]}"), 400
            abs_urls.append(abs_u)
    except ValueError as e:
        return jsonify(error=str(e)), 400

    if not abs_urls:
        return jsonify(error="No usable image URLs after rehost."), 400

    # Rig + animation ON by default — Meshy attaches walk/idle clips to GLB (no extra fee).
    meshy_opts: Dict[str, Any] = {
        "enable_rigging": bool(options.get("rig", True)),
        "enable_texture": True,
        "enable_pbr": True,
        "enable_animation": bool(options.get("animation", options.get("enable_animation", True))),
    }
    if options.get("topology"):
        meshy_opts["topology"] = options["topology"]
    if options.get("target_polycount") is not None:
        meshy_opts["target_polycount"] = options["target_polycount"]
    if options.get("rigging_height_meters") is not None:
        meshy_opts["rigging_height_meters"] = options["rigging_height_meters"]

    # Attach named slots for gateways that prefer them
    for i, slot in enumerate(VIEW_SLOTS):
        if slot in slot_map and i < len(abs_urls):
            # map by order of filled slots already in abs_urls — re-derive from slot_map order
            pass
    # Rebuild abs list strictly in VIEW_SLOTS order from slot_map
    ordered_abs: List[str] = []
    named: Dict[str, str] = {}
    for slot in VIEW_SLOTS:
        if slot not in slot_map:
            continue
        try:
            au = _absolutize_image_url(slot_map[slot])
        except ValueError as e:
            return jsonify(error=str(e)), 400
        ordered_abs.append(au)
        named[f"{slot}_image_url"] = au
    abs_urls = ordered_abs or abs_urls
    meshy_opts.update(named)

    try:
        created = poyo_client.create_meshy_task(image_urls=abs_urls, options=meshy_opts)
        poyo_task_id = poyo_client._task_id_from_create(created)
    except PoyoError as e:
        return jsonify(error=str(e), configured=True), 502
    except Exception as e:
        return jsonify(error=f"PoYo create failed: {e}"), 502

    job_id = uuid.uuid4().hex[:16]
    job = {
        "id": job_id,
        "user_id": user_id,
        "status": "processing",
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "name": name,
        "options": meshy_opts,
        "image_urls": abs_urls,
        "views": [s for s in VIEW_SLOTS if s in slot_map],
        "mock": False,
        "poyo_task_id": poyo_task_id,
        "message": (
            f"PoYo Meshy-6 multi-image task created ({len(abs_urls)} view"
            f"{'s' if len(abs_urls) != 1 else ''}) — generating (often several minutes)…"
        ),
    }

    # Inline completion (rare)
    inline = poyo_client._output_glb_url(created)
    st = poyo_client._status_of(created)
    if inline and st in {"succeeded", "success", "completed", "complete", "done", "finished"}:
        try:
            entry = store_user_glb_character(
                user_id,
                glb_url=inline,
                name=name,
                source="meshy-6-multi",
                poyo_task_id=poyo_task_id,
                extra={"remote_glb_url": inline, "views": job["views"]},
            )
            job["status"] = "done"
            job["character"] = entry
            job["glb_url"] = entry["glb_url"]
            job["message"] = "3D character ready"
        except Exception as e:
            job["status"] = "failed"
            job["error"] = f"Store failed: {e}"

    _save_job(job)
    code = 200 if job["status"] == "done" else 202
    return jsonify(
        {
            "ok": True,
            "async": job["status"] != "done",
            "job_id": job_id,
            "status": job["status"],
            "poyo_task_id": poyo_task_id,
            "message": job.get("message"),
            "character": job.get("character"),
            "glb_url": job.get("glb_url"),
            "views": job.get("views"),
            "image_count": len(abs_urls),
        }
    ), code


@bp.route("/api/3d/generate-character/<job_id>", methods=["GET"])
def generate_character_status(job_id: str):
    """Poll generation job; on success GLB is stored in user roster."""
    user_id, err = _require_login()
    if err:
        return err

    job = _load_job(job_id)
    if not job:
        return jsonify(error="Job not found", status="error"), 404

    # Ownership check (admins may inspect)
    if str(job.get("user_id")) != str(user_id) and not _is_admin(user_id):
        return jsonify(error="Job not found", status="error"), 404

    if job.get("mock"):
        job = _advance_mock_job(job)
    elif job.get("status") not in ("done", "failed"):
        job = _poll_live_job(job)

    payload = {
        "ok": job.get("status") == "done",
        "job_id": job.get("id"),
        "status": job.get("status"),
        "message": job.get("message"),
        "error": job.get("error"),
        "mock": bool(job.get("mock")),
        "character": job.get("character"),
        "glb_url": job.get("glb_url"),
        "remote_glb_url": job.get("remote_glb_url"),
        "store_warning": job.get("store_warning"),
        "poyo_task_id": job.get("poyo_task_id"),
        "updated_at": job.get("updated_at"),
        "views": job.get("views"),
    }
    return jsonify(payload)


@bp.route("/api/3d/characters", methods=["GET"])
def list_characters():
    """List GLB characters for the logged-in user (generated + uploaded)."""
    user_id, err = _require_login()
    if err:
        return err
    chars = list_user_characters(user_id)
    return jsonify({"ok": True, "characters": chars, "count": len(chars)})


@bp.route("/api/3d/upload-character", methods=["POST"])
def upload_character():
    """Manual GLB upload into the same roster used by Meshy generation.

    Safe to expose even if an older upload route exists — init_app skips
    duplicate endpoint registration when the rule is already mapped.
    """
    user_id, err = _require_login()
    if err:
        return err

    name = "Uploaded Character"
    glb_bytes = None

    if request.content_type and "multipart/form-data" in (request.content_type or ""):
        name = (request.form.get("name") or name).strip() or name
        f = request.files.get("glb") or request.files.get("file") or request.files.get("character")
        if not f or not f.filename:
            return jsonify(error="Upload a .glb file"), 400
        glb_bytes = f.read()
    else:
        body = request.get_json(silent=True) or {}
        name = str(body.get("name") or name).strip() or name
        url = str(body.get("glb_url") or body.get("url") or "").strip()
        if not url:
            return jsonify(error="Provide glb file upload or glb_url"), 400
        try:
            entry = store_user_glb_character(
                user_id, glb_url=url, name=name, source="upload"
            )
            return jsonify({"ok": True, "character": entry})
        except Exception as e:
            return jsonify(error=str(e)), 400

    try:
        entry = store_user_glb_character(
            user_id, glb_bytes=glb_bytes, name=name, source="upload"
        )
    except Exception as e:
        return jsonify(error=str(e)), 400
    return jsonify({"ok": True, "character": entry})


def init_app(app) -> None:
    """Register blueprint on the Flask app (idempotent)."""
    # Avoid double-register in reloader
    name = bp.name
    if name in getattr(app, "blueprints", {}):
        return
    app.register_blueprint(bp)

    # Ensure data dirs exist at boot
    try:
        _chars_root()
        _jobs_dir()
    except Exception:
        pass
