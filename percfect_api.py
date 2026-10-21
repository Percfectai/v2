"""
Percfect API v1: key generator + protected character endpoint.

Endpoints
  Account (logged-in website user):
    POST   /account/api-keys          -> create a key (full key shown ONCE)
    GET    /account/api-keys          -> list keys (prefix only)
    DELETE /account/api-keys/<id>     -> revoke a key
  Public API (Bearer pk_live_... key):
    POST   /api/v1/characters         -> one image in, starts the character job
    GET    /api/v1/characters/<id>    -> status + four shots (+ 360 if asked)
    GET    /api/v1/me                 -> credit balance check

One API job runs the SAME two jobs the Build-a-Character page runs:
  1. character_one  (photo → front shot still)
  2. character_pack (front → 360 spin - side - side - back)
Then left/back/right are snapped from the spin at 90/180/270°; front stays
the generated still. Billing: the full price (character_generate_cost +
character_pack_credit_cost) is HELD from the wallet when the job starts,
with a compare-and-swap so parallel requests can't spend the same credits.
The handlers then run with billing off (their is_admin flag only gates
billing), and the hold is refunded in full if any step fails.
Nothing here touches the character prompt or credit pricing.
"""
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from io import BytesIO

from flask import Blueprint, g, jsonify, request
from flask_login import current_user

import percfect_api_store as store

api_bp = Blueprint("percfect_api", __name__)

MODEL_NAME = "PercfectAI v1"  # the only model name customers ever see
KEY_PREFIX = "pk_live_"
MAX_KEYS_PER_USER = 5
MAX_ACTIVE_JOBS = 3
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp"}
STALE_STAGE_SECONDS = 5 * 60
MAX_PROMPT_CHARS = 1000

# Nick's edit wording, word for word (2026-10-02). Their change fills the blank.
PREVIEW_EDIT_PROMPT = (

)

# The 360 spin's direction varies per video (some turn clockwise, some
# counter-clockwise), so fixed timestamps can't say which side is which.
# We snapshot still frame 3 photos from the video.
# "left" = 1.5s
# "right" = 4.5s
# "back" = 3s
# Tripo wants front, left, back, right.
SPIN_SECONDS = 6.0
SPIN_SECONDS_TOLERANCE = 1.0
SPIN_SAMPLE_FRAMES = 24
MIN_TURN_FLOW = 0.15  # px/frame; weaker than this = can't tell the direction
VIEW_LABELS = ("front", "front-quarter", "side", "back-quarter", "back", "unclear")



def _app():
    import app as app_module
    return app_module 


def db():
    return _app().supabase


def _user_row(user_id, cols="picture_credits,video_credits,is_admin"):
    res = db().table("users").select(cols).eq("id", user_id).limit(1).execute()
    return (res.data or [None])[0] or {}


def get_balance(user_id) -> int:
    from credit_wallet import credit_balance
    return credit_balance(_user_row(user_id))


def front_cost() -> int:
    from credit_wallet import character_generate_cost
    return int(character_generate_cost(1))


def pack_cost() -> int:
    return int(_app().character_pack_credit_cost())


def edit_cost() -> int:
    """One preview edit = one image, same as the front shot."""
    from credit_wallet import IMAGE_CREDIT_COST
    return int(IMAGE_CREDIT_COST)


def credits_for_character() -> int:
    """Front shot + full pack — both read from the live pricing code."""
    return front_cost() + pack_cost()


def _wallet_cas(user_id, change) -> bool:
    """Apply change(row) -> new credit columns (or None) with compare-and-swap,
    so two requests can't both spend the same credits."""
    for _ in range(5):
        row = _user_row(user_id, "picture_credits,video_credits")
        new_vals = change(row)
        if new_vals is None:
            return False
        res = (db().table("users").update(new_vals).eq("id", user_id)
               .eq("picture_credits", int(row.get("picture_credits") or 0))
               .eq("video_credits", int(row.get("video_credits") or 0))
               .execute())
        if res.data:
            return True
    raise RuntimeError("wallet busy, try again")


def hold_credits(user_id, amount) -> bool:
    from credit_wallet import deduct_update
    return _wallet_cas(user_id, lambda row: deduct_update(row, amount))


def refund_credits(user_id, amount):
    from credit_wallet import add_credits_update
    _wallet_cas(user_id, lambda row: add_credits_update(row, amount))


# ===================== helpers =====================

def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _err(msg, code):
    return jsonify({"error": msg}), code


# Which AI services Percfect uses is Percfect's business: errors shown to API
# customers never name a provider or model.
_PROVIDER_WORDS = re.compile(
    r"xai|x\.ai|grok|poyo|meshy|tripo|openai|gpt|gemini|google|claude|anthropic|"
    r"replicate|flux|stability|runway|kling|luma|api key|api_key", re.IGNORECASE)


def public_error(msg):
    """Customer-safe error text: generic if it names any service behind Percfect."""
    if not msg:
        return msg
    msg = str(msg)
    if _PROVIDER_WORDS.search(msg):
        refunded = " Credits refunded." if "refund" in msg.lower() else ""
        return "Generation failed, please try again." + refunded
    return msg[:300]


def _site_uid():
    """Logged-in site user, only for requests from our own pages.
    The site has no CSRF tokens; JSON / DELETE + SameSite=Lax already block
    cross-site use, and this Origin check is a second lock."""
    origin = request.headers.get("Origin")
    if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
        return None
    if current_user and current_user.is_authenticated:
        return int(current_user.id)
    return None


# ---------------------------- key generator ----------------------------

@api_bp.post("/account/api-keys")
def create_key():
    uid = _site_uid()
    if not uid:
        return _err("login required", 401)
    if not request.is_json:
        return _err("send JSON", 400)

    if store.key_active_count(uid) >= MAX_KEYS_PER_USER:
        return _err(f"max {MAX_KEYS_PER_USER} active keys, revoke one first", 400)

    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    name = str((request.get_json(silent=True) or {}).get("name") or "default").strip()[:40] or "default"
    row = store.key_insert(uid, name, raw[:14], _hash(raw))

    # The only time the full key is ever returned.
    return jsonify({"id": row["id"], "name": name, "key": raw,
                    "key_prefix": raw[:14],
                    "note": "Copy this now. It will not be shown again."}), 201


@api_bp.get("/account/api-keys")
def list_keys():
    uid = _site_uid()
    if not uid:
        return _err("login required", 401)
    return jsonify({"keys": store.key_list(uid), "character_credits": credits_for_character()})


@api_bp.delete("/account/api-keys/<key_id>")
def revoke_key(key_id):
    uid = _site_uid()
    if not uid:
        return _err("login required", 401)
    store.key_revoke(uid, key_id)
    return jsonify({"revoked": key_id})


# ---------------------------- key check ----------------------------

def require_api_key(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer " + KEY_PREFIX):
            return _err("missing or malformed API key", 401)
        raw = auth.split(" ", 1)[1].strip()
        h = _hash(raw)
        rec = store.key_by_hash(h)
        if not rec or rec.get("revoked_at"):
            return _err("invalid or revoked API key", 401)
        g.api_key_id = rec["id"]
        g.api_user_id = int(rec["user_id"])
        return fn(*args, **kwargs)
    return wrapper


# ---------------------------- pipeline stages ----------------------------

def _to_jpeg(data: bytes) -> bytes:
    """Validate the upload is a real image and normalize it (WEBP → JPEG for xAI)."""
    from PIL import Image, ImageOps

    im = Image.open(BytesIO(data))
    im = ImageOps.exif_transpose(im)
    if im.mode not in ("RGB", "L"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        rgba = im.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[-1])
        im = bg
    out = BytesIO()
    im.convert("RGB").save(out, format="JPEG", quality=92)
    return out.getvalue()


# Credits are held up front, so the handlers run with billing off. In both
# character handlers is_admin only gates the balance check and the charge.
BILLING_OFF = {"is_admin": True}


def _start_front(user_id, image_url, description="") -> str:
    """Same payload the Build-a-Character 'Generate' button sends: one photo
    (typed words ignored) or, with no photo, the typed description."""
    from credit_wallet import character_generate_cost
    from studio_enqueue import enqueue

    payload = {
        "source_image": image_url,
        "source_images": [image_url] if image_url else [],
        "description": "" if image_url else description,
        "gender": "",
        "super_accuracy": False,
        "cost": character_generate_cost(1 if image_url else 0),
        "ref_count": 1 if image_url else 0,
        "seed_image_url": "",
        "search_query": "",
        "source_page_image": "",
        **BILLING_OFF,
    }
    return enqueue(_app().studio_jobs, user_id, "character_one", payload)


def _start_pack(user_id, front_url, prompt) -> str:
    """Same payload the character page's pack step sends after approve."""
    from studio_enqueue import enqueue

    a = _app()
    payload = {
        "primary_image_url": front_url,
        "prompt": prompt or "",
        "gender": "",
        "name": "API Character",
        "source_mode": "upload",
        "pack_cost": a.character_pack_credit_cost(),
        **BILLING_OFF,
    }
    return enqueue(a.studio_jobs, user_id, "character_pack", payload)


def _spin_frames(spin_url) -> list:
    """SPIN_SAMPLE_FRAMES evenly spaced JPEG frames; raises if the spin isn't ~6s."""
    import os
    import tempfile

    import cv2
    import requests

    r = requests.get(spin_url, timeout=120)
    r.raise_for_status()
    fd, path = tempfile.mkstemp(suffix=".mp4")
    try:
        os.write(fd, r.content)
        os.close(fd)
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            raise ValueError("could not open the 360 spin video")
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        seconds = total / fps if fps > 0 else 0
        if abs(seconds - SPIN_SECONDS) > SPIN_SECONDS_TOLERANCE:
            raise ValueError(
                f"the 360 spin came back {seconds:.1f}s long instead of {SPIN_SECONDS:.0f}s")
        frames = []
        for i in range(SPIN_SAMPLE_FRAMES):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(i * (total - 1) / (SPIN_SAMPLE_FRAMES - 1)))
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
            if ok:
                frames.append(jpg.tobytes())
        cap.release()
        if len(frames) < SPIN_SAMPLE_FRAMES // 2:
            raise ValueError("could not read enough frames from the 360 spin")
        return frames
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _label_frames(frames) -> list:
    """One VIEW_LABELS entry per frame, from the xAI vision chat model."""
    import base64
    import json

    import requests
    from PIL import Image

    import card_studio

    content = [{"type": "text", "text": f"{len(frames)} frames:"}]
    for i, data in enumerate(frames):
        im = Image.open(BytesIO(data))
        im.thumbnail((320, 320))
        buf = BytesIO()
        im.convert("RGB").save(buf, format="JPEG", quality=80)
        content.append({"type": "text", "text": f"Frame {i}:"})
        content.append({"type": "image_url", "image_url": {
            "url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}})
    r = requests.post(
        "https://api.x.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {card_studio._writer_key()}"},
        json={
            "model": card_studio.WRITER_MODEL,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": FRAME_LABEL_PROMPT},
                         {"role": "user", "content": content}],
        },
        timeout=120,
    )
    r.raise_for_status()
    text = r.json()["choices"][0]["message"]["content"]
    labels = json.loads(text[text.find("{"): text.rfind("}") + 1]).get("frames") or []
    labels = [str(x).strip().lower() for x in labels]
    if len(labels) != len(frames):
        raise ValueError("the angle check didn't label every frame")
    return [x if x in VIEW_LABELS else "unclear" for x in labels]


def _middle_of_longest_run(labels, want, lo=0, hi=None):
    """Middle frame of the longest run labelled `want` within [lo, hi)."""
    hi = len(labels) if hi is None else hi
    best, run = [], []
    for i in range(lo, hi + 1):
        if i < hi and labels[i] == want:
            run.append(i)
        else:
            if len(run) > len(best):
                best = run
            run = []
    return best[len(best) // 2] if best else None


def _turn_flow(frames) -> float:
    """Median sideways motion of the figure's middle band over every pair of
    consecutive frames. The surface nearest the camera moves the way the figure
    turns, so > 0 means the first side view faces image-right. Per-step values
    are noisy (hair, props swing), so we take the median over the whole spin."""
    import cv2
    import numpy as np

    grays = [cv2.cvtColor(cv2.imdecode(np.frombuffer(d, np.uint8), cv2.IMREAD_COLOR),
                          cv2.COLOR_BGR2GRAY) for d in frames]
    vals = []
    for a, b in zip(grays, grays[1:]):
        flow = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 3, 25, 3, 5, 1.2, 0)
        h = a.shape[0]
        band = np.zeros(a.shape, bool)
        band[int(h * 0.2):int(h * 0.6), :] = True
        dx = flow[..., 0][band & (a < 235)]  # figure pixels only, not the white backdrop
        if dx.size:
            vals.append(float(np.median(dx)))
    return float(np.median(vals)) if vals else 0.0


def _snap_sides(spin_url) -> dict:
    """left/back/right from the spin. Raises a clear error rather than
    returning a wrong, mirrored or duplicate angle."""
    frames = _spin_frames(spin_url)
    labels = _label_frames(frames)
    back = _middle_of_longest_run(labels, "back")
    if back is None:
        raise ValueError("the 360 spin has no clean back view")
    first = _middle_of_longest_run(labels, "side", 0, back)
    second = _middle_of_longest_run(labels, "side", back + 1)
    if first is None or second is None:
        raise ValueError("the 360 spin has no clean side view on both sides")
    turn = _turn_flow(frames)
    if abs(turn) < MIN_TURN_FLOW:
        raise ValueError("couldn't tell which way the 360 spin turns")
    right, left = (first, second) if turn > 0 else (second, first)
    picks = {"left": left, "back": back, "right": right}
    return {v: _app()._persist_image_bytes(frames[i], ext="jpg", content_type="image/jpeg")
            for v, i in picks.items()}


def _claim(job_id, from_stage, update) -> bool:
    """Move a job to its next stage only if no other poll already did (poll-safe)."""
    return store.job_claim(job_id, from_stage, update)


# Billing: "held" = credits taken for the step in flight, refunded if it fails;
# "spent" = credits for steps that delivered.
#   fast job:   hold front+pack at start
#   preview:    hold front at start → each edit holds edit_cost → approve holds pack

def _fail(job, msg):
    """Mark failed once and refund whatever is held."""
    if not _claim(job["id"], job["stage"], {"status": "failed", "stage": "done",
                                            "error": msg, "held": 0}):
        return
    held = int(job.get("held") or 0)
    if held > 0:
        try:
            refund_credits(job["user_id"], held)
        except Exception as e:
            _app().app.logger.error("api refund failed job=%s amount=%s: %s", job["id"], held, e)
    job.update({"status": "failed", "stage": "done", "error": msg, "held": 0})


def _is_stale(job) -> bool:
    try:
        t = datetime.fromisoformat(str(job.get("updated_at")).replace("Z", "+00:00"))
    except Exception:
        return False
    return datetime.now(timezone.utc) - t > timedelta(seconds=STALE_STAGE_SECONDS)


def _spent(job) -> int:
    return int(job.get("spent") or 0) + int(job.get("held") or 0)


def _launch_pack(job):
    """pack_starting → pack: start the 360 from the approved front."""
    try:
        pack_id = _start_pack(int(job["user_id"]), job["front_url"], job.get("front_prompt"))
    except Exception as e:
        _fail(job, f"could not start the 360 step: {e}")
        return
    _claim(job["id"], "pack_starting", {"stage": "pack", "internal_job_id": pack_id})
    job.update({"stage": "pack", "internal_job_id": pack_id})


def _advance(job):
    """Poll the current internal job and move the API job forward one step."""
    a = _app()
    uid = int(job["user_id"])
    stage = job["stage"]

    if stage == "preview":
        return  # waiting for the user to edit or approve
    if stage in ("pack_starting", "angles", "editing"):
        if _is_stale(job):  # a poll or thread died mid-step
            if stage == "editing":
                held = int(job.get("held") or 0)
                if _claim(job["id"], "editing", {"stage": "preview", "held": 0,
                                                 "edit_error": "edit timed out, credits refunded"}) and held:
                    refund_credits(uid, held)
            else:
                store.job_retry_stage(job["id"], stage, "front" if stage == "pack_starting" else "pack")
        return

    live = a.studio_jobs.status(job["internal_job_id"], uid) or {}
    st = live.get("status")
    if st == "failed":
        _fail(job, live.get("error") or "generation failed")
        return
    if not st:
        # Lookup hiccup (no status at all): keep waiting unless it lasts 15 minutes.
        try:
            t = datetime.fromisoformat(str(job.get("updated_at")).replace("Z", "+00:00"))
            lost = datetime.now(timezone.utc) - t > timedelta(minutes=15)
        except Exception:
            lost = False
        if lost:
            _fail(job, live.get("error") or "the job was lost, please retry")
        return
    if st != "done":
        if st == "processing":
            job["status"] = "running"  # shown to the client only, not saved
        return

    if stage == "front":
        front_url = live.get("url")
        if not front_url:
            _fail(job, "no front shot was returned")
            return
        if job.get("preview"):
            # Front delivered: its credits are spent; wait for edit / approve.
            update = {"stage": "preview", "status": "preview", "front_url": front_url,
                      "front_prompt": live.get("prompt"), "spent": _spent(job), "held": 0}
            if _claim(job["id"], "front", update):
                job.update(update)
            return
        update = {"stage": "pack_starting", "status": "running", "front_url": front_url,
                  "front_prompt": live.get("prompt")}
        if not _claim(job["id"], "front", update):
            return
        job.update(update)
        _launch_pack(job)
        return

    if stage == "pack":
        spin = live.get("spin_video_url") or live.get("url")
        if not spin:
            _fail(job, "no 360 spin was returned")
            return
        if not _claim(job["id"], "pack", {"stage": "angles"}):
            return
        job["stage"] = "angles"
        # The angle step takes a minute or more (video download, vision check,
        # frame uploads), so it runs in the background and polls return at once.
        # If this thread dies, the stale-stage check sends the job back to "pack".
        import threading
        threading.Thread(target=_finish_angles, args=(dict(job), spin), daemon=True).start()


def _finish_angles(job, spin):
    try:
        views = {"front": job.get("front_url"), **_snap_sides(spin)}
    except Exception as e:
        _fail(job, str(e))
        return
    if job.get("include_360"):
        views["spin_360"] = spin
    _claim(job["id"], "angles", {"stage": "done", "status": "success", "outputs": views,
                                 "spent": _spent(job), "held": 0})


def _run_edit(job, change):
    """Preview edit: Nick's edit wording on the current front, then back to preview."""
    from studio_task_handlers import _fresh_media_key, _generate_character_xai

    a = _app()
    try:
        r = _generate_character_xai(a, PREVIEW_EDIT_PROMPT.format(change=change),
                                    image_url=job["front_url"], api_key=_fresh_media_key())
        data = (r or {}).get("data") or []
        if not data or not data[0].get("url"):
            raise ValueError("no image came back (the change may have been filtered)")
        url = a._persist_image(data[0]["url"])
    except Exception as e:
        held = int(job.get("held") or 0)
        if _claim(job["id"], "editing", {"stage": "preview", "held": 0,
                                         "edit_error": f"edit failed, credits refunded: {e}"}) and held:
            refund_credits(job["user_id"], held)
        return
    _claim(job["id"], "editing", {"stage": "preview", "front_url": url, "edit_error": None,
                                  "spent": _spent(job), "held": 0})


# ---------------------------- public API ----------------------------

def _is_admin(uid) -> bool:
    return bool(_user_row(uid, "is_admin").get("is_admin"))


def _job_or_404(job_id):
    job = store.job_get(job_id, g.api_user_id)
    if not job or job.get("kind") == "3d":
        return None, _err("job not found", 404)
    return job, None


@api_bp.get("/api/v1/me")
@require_api_key
def me():
    try:  # 3D price shown on the character page; never let it break /me
        from percfect_api_3d import MODEL_3D_CREDITS
        credits_3d = int(MODEL_3D_CREDITS)
    except Exception:
        credits_3d = None
    return jsonify({"model": MODEL_NAME, "credits": get_balance(g.api_user_id),
                    "character_credits": credits_for_character(),
                    "preview_credits": front_cost(), "edit_credits": edit_cost(),
                    "approve_credits": pack_cost(), "model_3d_credits": credits_3d})


@api_bp.post("/api/v1/characters")
@require_api_key
def create_character():
    """One photo (field 'image') OR a typed description (field 'prompt').
    With a photo, typed words are ignored. preview=true stops after the front."""
    f = request.files.get("image")
    description = (request.form.get("prompt") or "").strip()[:MAX_PROMPT_CHARS]
    data = None
    if f:
        if f.mimetype not in ALLOWED_TYPES:
            return _err("image must be PNG, JPEG, or WEBP", 400)
        data = f.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            return _err("image too large (15 MB max)", 413)
        try:
            data = _to_jpeg(data)
        except Exception:
            return _err("could not read that image", 400)
    elif not description:
        return _err("send one image (field 'image') or a description (field 'prompt')", 400)

    include_360 = request.form.get("include_360", "false").lower() == "true"
    preview = request.form.get("preview", "false").lower() == "true"
    uid = g.api_user_id
    admin = _is_admin(uid)
    cost = 0 if admin else (front_cost() if preview else credits_for_character())

    if store.active_job_count(uid) >= MAX_ACTIVE_JOBS:
        return _err(f"max {MAX_ACTIVE_JOBS} characters building at once, wait for one to finish", 429)

    # Hold the price of this step now; refunded in full if it fails.
    if cost and not hold_credits(uid, cost):
        return _err(f"not enough credits (needs {cost})", 402)

    a = _app()
    job = None
    try:
        image_url = (a._persist_image_bytes(data, ext="jpg", content_type="image/jpeg")
                     if data else None)
        internal_id = _start_front(uid, image_url, description)
        job = store.job_insert({
            "user_id": uid,
            "api_key_id": g.api_key_id,
            "status": "queued",
            "stage": "front",
            "preview": preview,
            "include_360": include_360,
            "internal_job_id": internal_id,
            "held": cost,
            "spent": 0,
        })
    except Exception as e:
        a.app.logger.error("api character start failed: %s", e)
        if job:  # don't leave a half-made job counting against the limit
            store.job_claim(job["id"], "front", {"stage": "done", "status": "failed",
                                                 "error": "could not start", "held": 0})
        if cost:
            refund_credits(uid, cost)
        return _err("could not start the character, you were not charged", 500)

    return jsonify({"job_id": job["id"], "model": MODEL_NAME, "status": "queued",
                    "credits_charged": cost}), 202


@api_bp.post("/api/v1/characters/<job_id>/edit")
@require_api_key
def edit_character(job_id):
    """Preview only: change the front ('put her in a red shirt')."""
    job, err = _job_or_404(job_id)
    if err:
        return err
    body = request.get_json(silent=True) or request.form
    change = str(body.get("change") or "").strip()[:MAX_PROMPT_CHARS]
    if not change:
        return _err("say what to change (field 'change')", 400)
    if job["stage"] != "preview":
        return _err("this character isn't waiting for edits", 409)
    uid = g.api_user_id
    cost = 0 if _is_admin(uid) else edit_cost()
    if cost and not hold_credits(uid, cost):
        return _err(f"not enough credits (needs {cost})", 402)
    if not _claim(job_id, "preview", {"stage": "editing", "held": cost, "edit_error": None}):
        if cost:
            refund_credits(uid, cost)
        return _err("this character is busy, try again", 409)
    job.update({"stage": "editing", "held": cost})
    import threading
    threading.Thread(target=_run_edit, args=(dict(job), change), daemon=True).start()
    return jsonify({"job_id": job_id, "status": "editing", "credits_charged": cost}), 202


@api_bp.post("/api/v1/characters/<job_id>/approve")
@require_api_key
def approve_character(job_id):
    """Preview only: front looks right → make the 360 and the 4 shots."""
    job, err = _job_or_404(job_id)
    if err:
        return err
    if job["stage"] != "preview":
        return _err("this character isn't waiting for approval", 409)
    uid = g.api_user_id
    cost = 0 if _is_admin(uid) else pack_cost()
    if cost and not hold_credits(uid, cost):
        return _err(f"not enough credits (needs {cost})", 402)
    update = {"stage": "pack_starting", "status": "running", "held": cost}
    if not _claim(job_id, "preview", update):
        if cost:
            refund_credits(uid, cost)
        return _err("this character is busy, try again", 409)
    job.update(update)
    _launch_pack(job)
    return jsonify({"job_id": job_id, "status": "running", "credits_charged": cost}), 202


@api_bp.get("/api/v1/characters/<job_id>")
@require_api_key
def get_character(job_id):
    job, err = _job_or_404(job_id)
    if err:
        return err

    if job["stage"] != "done":
        try:
            _advance(job)
        except Exception as e:
            _app().app.logger.error("api advance failed job=%s: %s", job_id, e)

    stage = job["stage"]
    if job["status"] in ("success", "failed"):
        status = job["status"]
    elif stage in ("preview", "editing"):
        status = stage
    else:
        status = "running" if job["status"] == "running" or stage != "front" else "queued"
    outputs = None
    if status == "success":
        outputs = job.get("outputs")
    elif status in ("preview", "editing"):
        outputs = {"front": job.get("front_url")}
    return jsonify({"job_id": job_id, "model": MODEL_NAME, "status": status, "outputs": outputs,
                    "error": public_error(job.get("error")),
                    "edit_error": public_error(job.get("edit_error"))})
