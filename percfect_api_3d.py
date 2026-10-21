"""Percfect API v1 — 3D: four shots in, one GLB out.

    POST /api/v1/3d          (Bearer key) a finished character (form `job_id`)
                             OR your own shots (files `front` [required],
                             `left`, `back`, `right`) -> 202 {job_id}
    GET  /api/v1/3d/<id>     (Bearer key) status, then {"glb": url}

The 3D provider is swappable: only _provider_start / _provider_poll know
about it (Meshy-6 multi-image via PoYo today). 3D stays OFF until
PERCFECT_3D_ENABLED=1 is set on Render, so nobody is charged while the
provider account is empty or the backend is still being chosen.
"""
import os
import threading
import uuid

import requests
from flask import g, jsonify, request

import percfect_api as api
import percfect_api_store as store

# Price per 3D model in Percfect credits — Nick hasn't picked it yet
# (provider cost is ~$0.30 ≈ 4–6 credits). Only charged once 3D is switched on.
MODEL_3D_CREDITS = int(os.environ.get("PERCFECT_3D_CREDITS") or 15)
VIEWS = ("front", "left", "back", "right")


def enabled() -> bool:
    return (os.environ.get("PERCFECT_3D_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")


# ---------------------------- provider (meshy | tripo | replicate) ----------------------------
# Pick the engine with env PERCFECT_3D_PROVIDER. The provider name is stamped onto
# the task id so polling still routes correctly if the default is switched mid-job.

def _provider_start(views: dict) -> str:
    """Start a 3D task from {front, left, back, right} public URLs; return its id."""
    import percfect_3d_providers as p
    name = p.current()
    return f"{name}:{p.start(name, views)}"


def _provider_poll(task_id: str):
    """(status, glb_url, error): status is running | success | failed."""
    import percfect_3d_providers as p
    name, sep, raw = task_id.partition(":")
    if not sep:  # legacy id with no provider prefix → whatever is current
        name, raw = p.current(), task_id
    return p.poll(name, raw)


# ---------------------------- helpers ----------------------------

def _save_glb(url: str) -> str:
    """Provider links expire; keep our own copy."""
    a = api._app()
    r = requests.get(url, timeout=300)
    r.raise_for_status()
    path = f"glb/{uuid.uuid4().hex}.glb"
    a.supabase.storage.from_("previews").upload(
        path, r.content, file_options={"content-type": "model/gltf-binary", "upsert": "true"})
    return f"{a.SUPABASE_URL}/storage/v1/object/public/previews/{path}"


def _upload_view(file_storage) -> str:
    if file_storage.mimetype not in api.ALLOWED_TYPES:
        raise ValueError(f"{file_storage.name} must be PNG, JPEG, or WEBP")
    data = file_storage.read(api.MAX_UPLOAD_BYTES + 1)
    if len(data) > api.MAX_UPLOAD_BYTES:
        raise ValueError(f"{file_storage.name} is too large (15 MB max)")
    return api._app()._persist_image_bytes(api._to_jpeg(data), ext="jpg", content_type="image/jpeg")


def _fail(job, msg):
    """Mark failed once and refund the hold."""
    if not store.job_claim(job["id"], job["stage"], {"stage": "done", "status": "failed",
                                                      "error": msg, "held": 0}):
        return
    if int(job.get("held") or 0) > 0:
        api.refund_credits(job["user_id"], int(job["held"]))
    job.update({"stage": "done", "status": "failed", "error": msg})


def _finish(job, glb_url):
    try:
        mine = _save_glb(glb_url)
    except Exception as e:
        _fail(job, f"could not save the 3D model: {e}")
        return
    store.job_claim(job["id"], "saving", {"stage": "done", "status": "success",
                                          "outputs": {"glb": mine},
                                          "spent": int(job.get("held") or 0), "held": 0})


# ---------------------------- routes ----------------------------

@api.api_bp.post("/api/v1/3d")
@api.require_api_key
def create_3d():
    if not enabled():
        return api._err("3D models are coming soon", 503)
    uid = g.api_user_id
    source_id = (request.form.get("job_id") or "").strip()
    try:
        if source_id:
            src = store.job_get(source_id, uid)
            if not src or src.get("kind") == "3d" or src.get("status") != "success":
                return api._err("that character isn't finished (or isn't yours)", 404)
            views = {v: (src.get("outputs") or {}).get(v) for v in VIEWS}
        else:
            if "front" not in request.files:
                return api._err("send a finished character (field 'job_id') "
                                "or your shots (files 'front', 'left', 'back', 'right')", 400)
            views = {v: _upload_view(request.files[v]) for v in VIEWS if v in request.files}
    except ValueError as e:
        return api._err(str(e), 400)
    if not views.get("front"):
        return api._err("a front shot is required", 400)

    if store.active_job_count(uid) >= api.MAX_ACTIVE_JOBS:
        return api._err(f"max {api.MAX_ACTIVE_JOBS} jobs at once, wait for one to finish", 429)
    cost = 0 if api._is_admin(uid) else MODEL_3D_CREDITS
    if cost and not api.hold_credits(uid, cost):
        return api._err(f"not enough credits (needs {cost})", 402)

    try:
        task_id = _provider_start(views)
    except Exception as e:
        api._app().app.logger.error("api 3d start failed: %s", e)
        if cost:
            api.refund_credits(uid, cost)
        return api._err("could not start the 3D model, you were not charged", 502)

    job = store.job_insert({"user_id": uid, "api_key_id": g.api_key_id, "kind": "3d",
                            "stage": "modeling", "status": "running", "views": views,
                            "internal_job_id": task_id, "held": cost, "spent": 0})
    return jsonify({"job_id": job["id"], "model": api.MODEL_NAME, "status": "running",
                    "credits_charged": cost}), 202


def _advance_3d(job):
    """Poll the provider and move a 3D job forward one step (poll-safe)."""
    job_id = job["id"]
    if job["stage"] == "views":
        if api._is_stale(job):  # angle thread died before the provider started
            _fail(job, "could not prepare the character's angles")
        return
    if job["stage"] == "modeling":
        try:
            st, glb, err = _provider_poll(job["internal_job_id"])
        except Exception:
            st, glb, err = "running", None, None  # provider blip: ask again next poll
        if st == "failed":
            _fail(job, err or "3D generation failed")
        elif st == "success" and store.job_claim(job_id, "modeling", {"stage": "saving"}):
            job["stage"] = "saving"
            # Downloading + re-uploading the GLB can take a while; don't block the poll.
            threading.Thread(target=_finish, args=(dict(job), glb), daemon=True).start()
    elif job["stage"] == "saving" and api._is_stale(job):
        store.job_retry_stage(job_id, "saving", "modeling")


def _status_body(job):
    status = job["status"] if job["stage"] == "done" else "running"
    return {"job_id": job["id"], "model": api.MODEL_NAME, "status": status,
            "outputs": job.get("outputs") if status == "success" else None,
            "error": api.public_error(job.get("error"))}


@api.api_bp.get("/api/v1/3d/<job_id>")
@api.require_api_key
def get_3d(job_id):
    job = store.job_get(job_id, g.api_user_id)
    if not job or job.get("kind") != "3d":
        return api._err("job not found", 404)
    _advance_3d(job)
    return jsonify(_status_body(job))


# ---------------------------- Characters page button ----------------------------
# "Make character 3D" on /studios/percfectcharacter (logged-in session, not an API key).

def _views_then_start(job, primary, spin):
    """Background: proper left/back/right from the character's 360, then start the
    3D provider. The roster's saved angles are 0/120/240° frames — wrong for 3D."""
    try:
        views = {"front": primary, **api._snap_sides(spin)}
        task_id = _provider_start(views)
    except Exception as e:
        api._app().app.logger.error("character 3d start failed: %s", e)
        _fail(job, "could not start the 3D model, credits refunded")
        return
    store.job_claim(job["id"], "views", {"stage": "modeling", "views": views,
                                         "internal_job_id": task_id})


@api.api_bp.post("/studios/percfectcharacter/make-3d")
def site_make_3d():
    uid = api._site_uid()
    if not uid:
        return api._err("log in first", 401)
    if not enabled():
        return api._err("3D models are coming soon", 503)
    char_id = (request.get_json(silent=True) or {}).get("character_id")
    rows = (api.db().table("characters").select("id,primary_image_url,spin_video_url")
            .eq("id", char_id).eq("user_id", uid).limit(1).execute().data)
    if not rows:
        return api._err("character not found", 404)
    char = rows[0]
    if not char.get("spin_video_url") or not char.get("primary_image_url"):
        return api._err("finish this character's 360 first", 400)

    if store.active_job_count(uid) >= api.MAX_ACTIVE_JOBS:
        return api._err(f"max {api.MAX_ACTIVE_JOBS} jobs at once, wait for one to finish", 429)
    cost = 0 if api._is_admin(uid) else MODEL_3D_CREDITS
    if cost and not api.hold_credits(uid, cost):
        return api._err(f"3D needs {cost} credits", 402)

    job = store.job_insert({"user_id": uid, "kind": "3d", "stage": "views", "status": "running",
                            "character_id": char["id"], "held": cost, "spent": 0})
    threading.Thread(target=_views_then_start,
                     args=(dict(job), char["primary_image_url"], char["spin_video_url"]),
                     daemon=True).start()
    return jsonify({"job_id": job["id"], "status": "running", "credits_charged": cost}), 202


@api.api_bp.get("/studios/percfectcharacter/make-3d/<job_id>")
def site_make_3d_status(job_id):
    uid = api._site_uid()
    if not uid:
        return api._err("log in first", 401)
    job = store.job_get(job_id, uid)
    if not job or job.get("kind") != "3d":
        return api._err("job not found", 404)
    _advance_3d(job)
    return jsonify(_status_body(job))
