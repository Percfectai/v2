"""3D character generation via PoYo Meshy-6 multi-image + per-user GLB library.

NOTE: Live /api/3d/* is registered by three_d_character_gen.py (library
character_id path). This blueprint is the alternate/compat module for
direct image upload → PoYo Meshy-6. Do not double-register both on the
same app without different prefixes.

Product model: meshy-6-multi-image-to-3d
  POST https://api.poyo.ai/api/generate/submit
  GET  https://api.poyo.ai/api/generate/status/{task_id}
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional
from urllib.parse import urlparse

import requests
from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from poyo_client import (
    PoyoError,
    _output_glb_url,
    _status_of,
    _task_id_from_create,
    create_meshy_task,
    download_url_to_path,
    get_task,
    is_configured,
    is_mock,
    poyo_model,
)

logger = logging.getLogger(__name__)

bp = Blueprint("p3d_characters", __name__, url_prefix="/api/3d")

_jobs_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}

_SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")
_TERMINAL_OK = frozenset({"success", "succeeded", "completed", "complete", "done", "finished"})
_TERMINAL_BAD = frozenset({"failed", "error", "canceled", "cancelled", "rejected"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _user_id() -> str:
    return str(getattr(current_user, "id", "0"))


def _library_path() -> Path:
    root = Path(current_app.root_path)
    p = root / "data" / "user_3d_characters.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text('{"users": {}}\n', encoding="utf-8")
    return p


def _read_library() -> dict[str, Any]:
    path = _library_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"users": {}}
        data.setdefault("users", {})
        return data
    except Exception:
        return {"users": {}}


def _write_library(data: dict[str, Any]) -> None:
    path = _library_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def _user_asset_dir(user_id: str) -> Path:
    root = Path(current_app.root_path) / "static" / "user_3d" / _SAFE_NAME.sub("_", user_id)[:64]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _public_character(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": c.get("id"),
        "name": c.get("name") or "Character",
        "glb_url": c.get("glb_url") or c.get("model_url") or "",
        "thumbnail_url": c.get("thumbnail_url") or c.get("poster_url") or "",
        "source": c.get("source") or "meshy-6-multi",
        "created_at": c.get("created_at"),
        "rigged": bool(c.get("rigged", True)),
        "poyo_task_id": c.get("poyo_task_id"),
    }


def _append_character(user_id: str, character: dict[str, Any]) -> dict[str, Any]:
    lib = _read_library()
    users = lib.setdefault("users", {})
    bucket = users.setdefault(str(user_id), {"characters": []})
    chars = bucket.setdefault("characters", [])
    chars.insert(0, character)
    bucket["characters"] = chars[:100]
    _write_library(lib)
    return character


def _get_job(job_id: str) -> dict[str, Any] | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def _update_job(job_id: str, **fields: Any) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job.update(fields)
        job["updated_at"] = time.time()


def _resolve_one_image(image_url: str | None, file_storage) -> str:
    """Return public https URL or data URI for one image."""
    if file_storage and getattr(file_storage, "filename", None):
        raw = file_storage.read()
        if not raw:
            raise ValueError("Empty image upload")
        if len(raw) > 12 * 1024 * 1024:
            raise ValueError("Image too large (max 12MB)")
        mime = file_storage.mimetype or "image/png"
        if mime not in ("image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"):
            mime = "image/png"
        import base64

        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:{mime};base64,{b64}"

    if not image_url or not str(image_url).strip():
        raise ValueError("Provide image file or image_url")

    image_url = str(image_url).strip()
    if image_url.startswith("data:image/"):
        return image_url

    parsed = urlparse(image_url)
    if image_url.startswith("/static/") or (
        parsed.path.startswith("/static/") and not parsed.scheme
    ):
        # Local static → data URI (create_meshy rehosts data: to public URL)
        root = Path(current_app.root_path)
        rel = parsed.path if parsed.path.startswith("/static/") else image_url
        disk = root / rel.lstrip("/")
        if not disk.is_file():
            raise ValueError(f"Local image not found: {rel}")
        raw = disk.read_bytes()
        import base64
        import mimetypes

        mime = mimetypes.guess_type(str(disk))[0] or "image/png"
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:{mime};base64,{b64}"

    if parsed.scheme in ("http", "https"):
        return image_url

    raise ValueError("image_url must be https:// or /static/… path or data URI")


def _collect_image_refs() -> List[str]:
    """Collect 1–4 image refs from JSON or multipart (front/back/left/right order preferred)."""
    refs: List[str] = []

    if request.content_type and "multipart/form-data" in (request.content_type or ""):
        # Named slots
        for key in (
            "image_front",
            "image_back",
            "image_left",
            "image_right",
            "image",
            "file",
        ):
            f = request.files.get(key)
            if f and getattr(f, "filename", None):
                refs.append(_resolve_one_image(None, f))
            if len(refs) >= 4:
                break
        # URL slots
        if not refs:
            for key in (
                "image_url_front",
                "image_url_back",
                "image_url_left",
                "image_url_right",
                "image_url",
                "image",
            ):
                u = (request.form.get(key) or "").strip()
                if u:
                    refs.append(_resolve_one_image(u, None))
                if len(refs) >= 4:
                    break
    else:
        data = request.get_json(silent=True) or {}
        # Preferred: image_urls list
        raw_list = data.get("image_urls") or data.get("images") or []
        if isinstance(raw_list, list):
            for u in raw_list[:4]:
                if u:
                    refs.append(_resolve_one_image(str(u), None))
        if not refs:
            for key in (
                "image_url_front",
                "image_url_back",
                "image_url_left",
                "image_url_right",
                "image_url",
                "image",
            ):
                u = data.get(key)
                if u:
                    refs.append(_resolve_one_image(str(u), None))
                if len(refs) >= 4:
                    break

    # Cap 1–4
    refs = [r for r in refs if r][:4]
    return refs


def _worker(app, job_id: str, user_id: str, image_refs: List[str], name: str, rig: bool) -> None:
    with app.app_context():
        try:
            _update_job(
                job_id,
                status="running",
                message="Submitting to PoYo Meshy-6 multi-image…",
                progress=5,
            )
            opts = {
                "enable_rigging": True,
                "enable_animation": bool(rig),
                "enable_safety_checker": False,
                "should_texture": True,
                "enable_pbr": True,
            }
            created = create_meshy_task(image_urls=image_refs, options=opts)
            poyo_task_id = _task_id_from_create(created)
            _update_job(
                job_id,
                poyo_task_id=poyo_task_id,
                message="Meshy-6 generating mesh (often several minutes)…",
                progress=15,
            )

            deadline = time.time() + 15 * 60
            model_url = None
            last_status = ""
            while time.time() < deadline:
                raw = get_task(poyo_task_id)
                status = _status_of(raw)
                last_status = status
                # progress if present
                data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
                prog = data.get("progress") if isinstance(data, dict) else None
                msg = f"Meshy-6 status: {status or 'pending'}"
                fields: dict[str, Any] = {"message": msg[:240], "poyo_status": status}
                if isinstance(prog, (int, float)):
                    # progress may be 0–1 or 0–100
                    p = float(prog)
                    if p <= 1.0:
                        p *= 100
                    fields["progress"] = max(15, min(90, int(p)))
                _update_job(job_id, **fields)

                if status in _TERMINAL_OK:
                    model_url = _output_glb_url(raw)
                    break
                if status in _TERMINAL_BAD:
                    err = ""
                    if isinstance(data, dict):
                        err = str(data.get("error") or data.get("message") or "")
                    raise PoyoError(err or f"Task {status}")
                time.sleep(3.0)

            if not model_url:
                raise PoyoError(
                    f"Meshy-6 finished without GLB URL (last status={last_status or 'timeout'})"
                )

            _update_job(job_id, status="running", message="Downloading GLB…", progress=92)
            dest_dir = _user_asset_dir(user_id)
            fname = f"{job_id}.glb"
            dest = dest_dir / fname
            download_url_to_path(str(model_url), dest)
            public_url = f"/static/user_3d/{_SAFE_NAME.sub('_', user_id)[:64]}/{fname}"

            character = {
                "id": job_id,
                "name": name,
                "glb_url": public_url,
                "source_model_url": str(model_url)[:500],
                "source": "meshy-6-multi",
                "poyo_task_id": poyo_task_id,
                "rigged": True,
                "created_at": _utc_now(),
                "user_id": user_id,
                "view_count": len(image_refs),
            }
            _append_character(user_id, character)
            _update_job(
                job_id,
                status="done",
                message="3D character ready",
                progress=100,
                glb_url=public_url,
                character=_public_character(character),
            )
        except Exception as e:
            logger.exception("3d generate job %s failed", job_id)
            _update_job(
                job_id,
                status="failed",
                error=str(e)[:500],
                message=str(e)[:240],
                progress=0,
            )


@bp.get("/generate-character/config")
def generate_config():
    """Public-ish config probe for the /3d panel (no secrets)."""
    return jsonify(
        {
            "ok": True,
            "configured": is_configured(),
            "mock": is_mock(),
            "model": poyo_model(),
            "provider": "poyo",
            "max_images": 4,
            "views": ["front", "back", "left", "right"],
            "message": (
                "PoYo Meshy-6 multi-image ready"
                if is_configured()
                else "POYO_API_KEY not set — generation disabled until key is on Render"
            ),
        }
    )


@bp.get("/characters")
@bp.get("/my-characters")
@login_required
def list_user_characters():
    """List default-eligible user GLBs for the /3d roster picker."""
    uid = _user_id()
    lib = _read_library()
    chars = lib.get("users", {}).get(str(uid), {}).get("characters") or []
    out = [_public_character(c) for c in chars if c.get("glb_url") or c.get("model_url")]
    return jsonify({"ok": True, "characters": out})


@bp.post("/generate-character")
@login_required
def generate_character():
    """Start PoYo Meshy-6 multi-image job (1–4 image_urls or uploads)."""
    if not is_configured() and not is_mock():
        return jsonify(
            {
                "error": "POYO_API_KEY not configured",
                "message": "Set POYO_API_KEY on Render to enable Meshy-6 generation.",
            }
        ), 503

    name = "Meshy Character"
    rig = True
    if request.content_type and "multipart/form-data" in (request.content_type or ""):
        name = (request.form.get("name") or name).strip()[:80] or name
        rig = str(request.form.get("rig", "true")).lower() not in {"0", "false", "no"}
    else:
        data = request.get_json(silent=True) or {}
        name = str(data.get("name") or name).strip()[:80] or name
        rig = bool(data.get("rig", True))

    try:
        if is_mock():
            image_refs = ["https://example.com/mock-character.png"]
        else:
            image_refs = _collect_image_refs()
            if not image_refs:
                return jsonify(
                    {
                        "error": (
                            "Need 1–4 images for PoYo Meshy-6 multi-image. "
                            "Send image_urls[] or multipart image_front/back/left/right."
                        )
                    }
                ), 400
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("image resolve failed")
        return jsonify({"error": f"Could not read image: {e}"}), 400

    job_id = uuid.uuid4().hex[:16]
    uid = _user_id()
    with _jobs_lock:
        _jobs[job_id] = {
            "id": job_id,
            "user_id": uid,
            "status": "queued",
            "message": "Queued",
            "progress": 0,
            "name": name,
            "views": len(image_refs),
            "created_at": time.time(),
            "updated_at": time.time(),
        }

    app = current_app._get_current_object()
    t = threading.Thread(
        target=_worker,
        args=(app, job_id, uid, image_refs, name, rig),
        daemon=True,
        name=f"poyo-meshy6-{job_id}",
    )
    t.start()

    if is_mock():
        for _ in range(20):
            job = _get_job(job_id)
            if job and job.get("status") in {"done", "failed"}:
                break
            time.sleep(0.05)
        job = _get_job(job_id) or {}
        if job.get("status") == "done":
            return jsonify(
                {
                    "ok": True,
                    "job_id": job_id,
                    "status": "done",
                    "glb_url": job.get("glb_url"),
                    "character": job.get("character"),
                    "message": "Mock character ready",
                }
            )
        if job.get("status") == "failed":
            return jsonify({"error": job.get("error") or "failed", "job_id": job_id}), 500

    return jsonify(
        {
            "ok": True,
            "job_id": job_id,
            "status": "queued",
            "views": len(image_refs),
            "model": poyo_model(),
            "message": "PoYo Meshy-6 task started — poll GET /api/3d/generate-character/<job_id>",
            "poll_url": f"/api/3d/generate-character/{job_id}",
        }
    ), 202


@bp.get("/generate-character/<job_id>")
@login_required
def generate_character_status(job_id: str):
    job = _get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if str(job.get("user_id")) != _user_id() and not getattr(current_user, "is_admin", False):
        return jsonify({"error": "Forbidden"}), 403

    status = job.get("status") or "unknown"
    body: dict[str, Any] = {
        "job_id": job_id,
        "status": status,
        "message": job.get("message"),
        "progress": job.get("progress", 0),
        "poyo_task_id": job.get("poyo_task_id"),
        "poyo_status": job.get("poyo_status"),
    }
    if status == "done":
        body["glb_url"] = job.get("glb_url")
        body["character"] = job.get("character")
    if status == "failed":
        body["error"] = job.get("error") or job.get("message")
    return jsonify(body)


def init_app(app) -> None:
    """Register blueprint only if three_d_character_gen is not already owning /api/3d."""
    # Prefer the library character_id product blueprint when present
    if "three_d_character_gen" in app.blueprints:
        logger.info(
            "routes.3d_characters: skip register — three_d_character_gen owns /api/3d"
        )
        return
    if "p3d_characters" not in app.blueprints:
        app.register_blueprint(bp)
    try:
        with app.app_context():
            _library_path()
    except Exception:
        logger.exception("3d characters library init failed")
