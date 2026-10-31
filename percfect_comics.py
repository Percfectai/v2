"""Perfect Comics studio for Percfectai/v2.

Serves the September 25 studio at /comics. Writer uses the chat silo.
Pictures use the image silo, grok-imagine-image-2.0, 1k.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any, Dict, List

import requests
from flask import Blueprint, abort, jsonify, request, send_from_directory
from flask_login import current_user

log = logging.getLogger(__name__)
bp = Blueprint("percfect_comics", __name__)
SPA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "comics")


def _cors_origin() -> str:
    origin = request.headers.get("Origin") or ""
    low = origin.lower()
    if low in ("capacitor://localhost", "https://localhost", "http://localhost"):
        return origin
    if low in ("https://percfectai.com", "https://www.percfectai.com") or low.endswith(".percfectai.com"):
        return origin
    if low in ("https://comicbot.si", "https://www.comicbot.si") or low.endswith(".comicbot.si"):
        return origin
    return ""


@bp.before_request
def _cors_preflight():
    if request.method == "OPTIONS" and _cors_origin():
        return ("", 204)


@bp.after_request
def _add_mobile_cors(resp):
    origin = _cors_origin()
    if origin:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Vary"] = "Origin"
    return resp
ASSET_EXTS = {
    ".js", ".css", ".map", ".png", ".jpg", ".jpeg", ".svg", ".webp",
    ".woff", ".woff2", ".json", ".webmanifest", ".ico", ".txt",
}

def _text_key() -> str:
    for env in (
        "XAI_COMIC_WRITER_API_KEY",
        "XAI_CARD_WRITER_API_KEY",
        "XAI_CHARACTER_CHAT_API_KEY",
        "XAI_BRIDGE_API_KEY",
    ):
        k = (os.getenv(env) or "").strip()
        if k and "," not in k:
            return k
    return ""

def _xai_text(system: str, user: str, *, max_tokens: int = 900, json_mode: bool = True) -> str:
    key = _text_key()
    if not key:
        raise RuntimeError("No xAI API key available for the comic writer.")
    body: Dict[str, Any] = {
        "model": os.getenv("XAI_COMIC_WRITER_MODEL") or "grok-4.5",
        "temperature": 0.85,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    r = requests.post(
        "https://api.x.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=body,
        timeout=60,
    )
    r.raise_for_status()
    return (((r.json().get("choices") or [{}])[0].get("message") or {}).get("content")) or ""

def _json_block(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except Exception:
        return {}

# ── Sept 25 Perfect Comics SPA (GitHub nickpelectrical/perfect-comics) ──────

_INK_STYLES = {
    "classic": "classic American comic book print, bold black ink outlines, flat colored fills, Ben-Day dots",
    "anime": "modern anime manga page, clean inked linework, cel shading, cinematic eyes, screentones",
    "realistic": "realistic painted comic page, cinematic lighting, detailed fabric and skin",
    "gta5": "satirical open-world game still as a comic page, saturated color, bold outline",
    "watercolor": "watercolor comic page, wet pigment blooms, paper grain, soft edges",
    "noir": "black-and-white noir comic, heavy ink shadows, one crimson accent",
    "pixel": "16-bit pixel art comic page, chunky pixels, limited palette",
    "cel": "cel-shaded game-comic page, crisp cartoon lighting, clean color holds",
    "oil": "oil painting comic page, thick impasto, gallery light",
    "cyberpunk": "cyberpunk neon comic page, rain, magenta and cyan rim light",
    "retro90s": "1990s foil-era superhero comic, extreme poses, bold ink, saturated fills",
    "sketch": "graphite pencil comic page, construction lines",
    "two-d": "flat 2D graphic comic page, vector shapes, limited palette",
    "three-d": "3D rendered comic page, studio CGI characters, sequential panels",
}
_INK_SAFETY = (
    "All-ages. No nudity, no sexual content, no gore. Original characters only. "
    "No readable letters, logos, watermarks, or barcodes."
)


def _spa_index():
    index_path = os.path.join(SPA_DIR, "index.html")
    if not os.path.isfile(index_path):
        abort(404)
    resp = send_from_directory(SPA_DIR, "index.html")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


def _serve_spa(filename: str | None = None):
    if not filename or filename in ("", "index.html"):
        return _spa_index()
    safe = os.path.normpath(filename).lstrip("/")
    if safe.startswith("..") or os.path.isabs(safe):
        abort(404)
    target = os.path.join(SPA_DIR, safe)
    if os.path.isfile(target):
        return send_from_directory(SPA_DIR, safe)
    ext = os.path.splitext(safe)[1].lower()
    if ext in ASSET_EXTS:
        abort(404)
    return _spa_index()


def _spa_auth():
    if not current_user.is_authenticated:
        return jsonify({"ok": False, "error": "Sign in to use Perfect Comics."}), 401
    return None


def _build_ink_prompt(data: Dict[str, Any]) -> str:
    style = _INK_STYLES.get(str(data.get("styleId") or ""), _INK_STYLES["classic"])
    title = (str(data.get("title") or "").strip() or "My Percfect Hero")
    cast = (str(data.get("cast") or "").strip() or "one original lead with a consistent costume")
    kind = str(data.get("kind") or "interior")
    page = int(data.get("page") or 0)
    beat = str(data.get("beat") or "").strip()
    note = str(data.get("note") or "").strip()
    if kind == "small":
        return " ".join([
            "Edit the attached comic page. Change ONLY this:",
            note or "a small costume detail",
            "Keep the same panels, poses, background, framing, and costumes except for that one change.",
            f"Preserve this art style: {style}.",
            "Do not add a title, captions, or readable letters.",
            _INK_SAFETY,
        ])
    if kind == "cover" or page == 0:
        try:
            issue_number = max(1, int(data.get("issueNumber") or 1))
        except (TypeError, ValueError):
            issue_number = 1
        visual = beat or cast
        return " ".join([
            "Professional comic book cover, standard US size portrait, full-bleed artwork.",
            f'Title: "{title}" in large, bold, stylized lettering across the top third of the cover.',
            f"Issue number: #{issue_number} in a clean corner box in the upper left.",
            f"Main visual: {visual}.",
            f"Characters you may name in the cover description: {cast}.",
            "When the description names one of those characters, use that character's sheet for the face and costume.",
            "Character sheet input: the first attached image is the character sheet. The top row is the main character, front then back then left then right. Use that sheet for the face and costume. Do not copy the sheet grid onto the cover.",
            f"Style: {style} digital comic book art, high detail, cinematic lighting, dramatic foreshortening, vibrant colors, professional cover quality, strong thumbnail readability.",
            "Additional elements: publisher logo area top right, barcode and price box bottom left, credits area bottom right.",
            "No white borders, clear space for the title, rule-of-thirds composition.",
            "All-ages. No nudity, no sexual content, no gore. Original characters only.",
        ])
    act = "beginning" if page <= 3 else "middle" if page <= 6 else "ending"
    lines = [
        f'Comic INTERIOR page {page} of 9, the {act} of "{title}".',
        "Draw a NEW page with 3 to 5 panels and a new layout.",
        f"Art style: {style}.",
        f"Characters on this page, same faces and costumes every panel: {cast}.",
        f"What happens on this page only: {beat}.",
        "If character photos are attached after the previous page, match those faces. Do not paste the photos into a panel.",
    ]
    act_summary = str(data.get("actSummary") or "").strip()
    if act_summary:
        lines.append(f"Act context, do not redraw earlier events: {act_summary}")
    if data.get("hasPrevPage"):
        lines.append(
            "The attached reference is the COVER. Do not make another cover. Use it only to match the character's face, costume, and art style."
            if page == 1
            else "The first attached reference is the PREVIOUS page. Match the characters and the art style. Do not copy its panels or redraw that same moment."
        )
    lines.append("Empty speech balloons only. No readable words, logos, or watermarks.")
    lines.append(_INK_SAFETY)
    return " ".join(lines)


def _comic_image(prompt: str, refs: List[str], model: str) -> Dict[str, Any]:
    from xai_keys import next_key

    api_key = (next_key() or "").strip()
    if not api_key:
        return {"ok": False, "error": "AI is not available"}
    clean_refs = [
        r for r in refs
        if isinstance(r, str) and (r.startswith("http") or r.startswith("data:"))
    ][:3]
    use_edits = bool(clean_refs)
    url = "https://api.x.ai/v1/images/edits" if use_edits else "https://api.x.ai/v1/images/generations"
    models = [model or "grok-imagine-image-2.0", "grok-imagine-image"]
    seen = []
    for m in models:
        if not m or m in seen:
            continue
        seen.append(m)
        payload: Dict[str, Any] = {
            "model": m,
            "prompt": prompt[:4000],
            "n": 1,
            "aspect_ratio": "3:4",
            "resolution": "1k",
            "response_format": "url",
        }
        if m == "grok-imagine-image-2.0":
            payload["quality"] = "medium"
        if use_edits:
            images = [{"url": r, "type": "image_url"} for r in clean_refs]
            if len(images) == 1:
                payload["image"] = images[0]
            else:
                payload["images"] = images
        try:
            res = requests.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=180,
            )
        except Exception as e:
            log.warning("comics ink request failed: %s", e)
            return {"ok": False, "error": "Image failed"}
        if res.status_code in (400, 404) and m == "grok-imagine-image-2.0":
            log.warning("comics ink model %s unavailable (%s), trying fallback", m, res.status_code)
            continue
        if not res.ok:
            detail = (res.text or "")[:180]
            return {"ok": False, "error": f"Image failed ({res.status_code}) {detail}"}
        body = res.json() if res.content else {}
        first = ((body.get("data") or [{}])[0]) if isinstance(body, dict) else {}
        image_url = first.get("url") or (
            f"data:image/png;base64,{first['b64_json']}" if first.get("b64_json") else ""
        )
        if not image_url:
            return {"ok": False, "error": "No image returned"}
        return {"ok": True, "url": image_url}
    return {"ok": False, "error": "Image failed"}


# ── Routes ───────────────────────────────────────────────────────────────────

@bp.route("/comics")
@bp.route("/comics/")
@bp.route("/build/comics")
@bp.route("/build/comics/")
@bp.route("/studios/comics")
@bp.route("/studios/comics/")
def comics_page():
    return _serve_spa()


@bp.route("/comics/api/rewrite", methods=["POST", "OPTIONS"])
@bp.route("/studios/comics/api/rewrite", methods=["POST", "OPTIONS"])
def comics_rewrite():
    denied = _spa_auth()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    target = str(body.get("target") or "")
    if target not in ("summary", "beginning", "middle", "ending", "cover", "page"):
        return jsonify({"ok": False, "error": "Bad rewrite target."}), 400
    style = _INK_STYLES.get(str(body.get("styleId") or ""), _INK_STYLES["classic"])
    invent = bool(body.get("invent"))
    shared = (
        f"Title: {str(body.get('title') or 'Untitled')[:80]}\n"
        f"Genre: {str(body.get('genre') or '')[:40]}\n"
        f"Art style: {style}\n"
        f"Cast: {str(body.get('cast') or 'original lead')[:800]}\n"
        f"Issue summary: {str(body.get('context') or '(none)')[:1500]}\n"
        f"Current text: {str(body.get('current') or '(empty)')[:2500]}\n"
    )
    if target in ("beginning", "middle", "ending"):
        prompt = (
            "You write one act of a comic, then split it into the three pages of that act.\n"
            'Return ONLY JSON: {"text":"act summary, 60-140 words","pages":["page one","page two","page three"]}.\n'
            "pages has exactly 3 strings. Each string is 1 or 2 sentences of what we SEE on that page.\n"
            "A new moment every page. Do not repeat a scene. No dialogue to letter.\n"
            f"Act: {target}. Page order is the order of the pages array.\n"
            + shared
            + ("Invent the act from the issue summary and cast." if invent else "Keep their intent. Do not change the story's direction.")
            + "\nAll-ages. No gore."
        )
        try:
            raw = _xai_text("Return only JSON.", prompt, max_tokens=900, json_mode=True)
        except Exception as e:
            log.warning("comics rewrite failed: %s", e)
            return jsonify({"ok": False, "error": "Writer failed"})
        data = _json_block(raw)
        text = str(data.get("text") or "").strip()
        pages = [str(p).strip() for p in (data.get("pages") or []) if str(p).strip()]
        if not text or len(pages) < 3:
            return jsonify({"ok": False, "error": "The act did not split into three pages."})
        return jsonify({"ok": True, "text": text, "pages": pages[:3]})
    prompt = (
        "You are the copy editor for Perfect Comics. Return ONLY the rewritten text, no JSON, no quotes.\n"
        f"Target box: {target}\n"
        + shared
        + (
            "Invent a vivid all-ages beat that fits genre and cast. 60–140 words."
            if invent
            else "Keep their intent. Sharpen visuals. Do not change the story's direction. 60–140 words."
        )
        + "\nAll-ages. No gore."
    )
    try:
        text = _xai_text("Return only the rewritten comic copy.", prompt, max_tokens=500, json_mode=False)
    except Exception as e:
        log.warning("comics rewrite failed: %s", e)
        return jsonify({"ok": False, "error": "Writer failed"})
    text = (text or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "Empty rewrite"})
    return jsonify({"ok": True, "text": text})


@bp.route("/comics/api/ink", methods=["POST", "OPTIONS"])
@bp.route("/studios/comics/api/ink", methods=["POST", "OPTIONS"])
def comics_ink():
    denied = _spa_auth()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    kind = str(body.get("kind") or "")
    if kind not in ("cover", "interior", "small", "rewrite"):
        return jsonify({"ok": False, "error": "Bad ink kind."}), 400
    try:
        page = int(body.get("page") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Bad page."}), 400
    if page < 0 or page > 9:
        return jsonify({"ok": False, "error": "Bad page."}), 400
    refs = body.get("refs") or []
    if not isinstance(refs, list):
        refs = []
    refs = [str(r)[:2_000_000] for r in refs[:5]]
    prompt = _build_ink_prompt(body)
    model = str(body.get("model") or "grok-imagine-image-2.0")
    if model not in ("grok-imagine-image", "grok-imagine-image-quality", "grok-imagine-image-2.0"):
        model = "grok-imagine-image-2.0"
    result = _comic_image(prompt, refs, model)
    return jsonify(result), (200 if result.get("ok") else 502)


@bp.route("/comics/api/plan", methods=["POST", "OPTIONS"])
@bp.route("/studios/comics/api/plan", methods=["POST", "OPTIONS"])
def comics_plan():
    denied = _spa_auth()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    prompt = (
        "You break one comic issue into ten visual beats for an image generator.\n"
        'Return ONLY JSON: {"beats":["...","..."]} with exactly 10 strings.\n'
        "Index 0 is the COVER: one splash, no panels.\n"
        "Indexes 1-3 are the beginning, 4-6 the middle, 7-9 the ending.\n"
        "Each string is 1 or 2 sentences of what we SEE on that page. A new moment every page. Do not repeat a scene.\n"
        "No dialogue to letter. All-ages. No gore.\n"
        f"Title: {str(body.get('title') or 'My Percfect Hero')[:80]}\n"
        f"Genre: {str(body.get('genre') or '')[:40]}\n"
        f"Cast: {str(body.get('cast') or 'original lead')[:800]}\n"
        f"Issue summary: {str(body.get('summary') or '(none)')[:2500]}\n"
        f"Beginning summary: {str(body.get('beginning') or '(use the issue summary)')[:1500]}\n"
        f"Middle summary: {str(body.get('middle') or '(use the issue summary)')[:1500]}\n"
        f"Ending summary: {str(body.get('ending') or '(use the issue summary)')[:1500]}"
    )
    try:
        text = _xai_text("Return only JSON.", prompt, max_tokens=900, json_mode=True)
    except Exception as e:
        log.warning("comics plan failed: %s", e)
        return jsonify({"ok": False, "error": "Writer failed"})
    data = _json_block(text)
    beats = [str(b).strip() for b in (data.get("beats") or []) if str(b).strip()]
    if len(beats) < 4:
        return jsonify({"ok": False, "error": "The page plan was too short"})
    return jsonify({"ok": True, "beats": beats[:10]})



def _load_collage_image(raw: str):
    """Load https or data:image for collage cells. Returns RGB PIL Image or None."""
    import io
    from PIL import Image

    raw = str(raw or "").strip()
    if not raw:
        return None
    try:
        if raw.startswith("data:image") and "," in raw:
            blob = base64.b64decode(raw.split(",", 1)[1])
            return Image.open(io.BytesIO(blob)).convert("RGB")
        if raw.startswith("https://") or raw.startswith("http://"):
            got = requests.get(raw, timeout=40)
            if not got.ok:
                return None
            return Image.open(io.BytesIO(got.content)).convert("RGB")
    except Exception:
        return None
    return None


def _collage_page(rows: list, *, bg=(14, 17, 22), cell: int = 512, cols: int = 4) -> str:
    """Paste character shots onto one JPEG. Does not touch the character builder."""
    import io
    from PIL import Image

    canvas = Image.new("RGB", (cell * cols, cell * max(1, len(rows))), bg)
    for r, urls in enumerate(rows[: max(1, len(rows))]):
        if not isinstance(urls, list):
            continue
        for c, url in enumerate(urls[:cols]):
            im = _load_collage_image(str(url or ""))
            if im is None:
                continue
            im.thumbnail((cell, cell))
            canvas.paste(im, (c * cell + (cell - im.width) // 2, r * cell + (cell - im.height) // 2))
    out = io.BytesIO()
    canvas.save(out, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode("ascii")


@bp.route("/comics/api/sheet", methods=["POST", "OPTIONS"])
@bp.route("/studios/comics/api/sheet", methods=["POST", "OPTIONS"])
def comics_sheet():
    denied = _spa_auth()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    top = body.get("top") if isinstance(body.get("top"), list) else []
    bottom = body.get("bottom") if isinstance(body.get("bottom"), list) else []
    if len(top) < 4:
        return jsonify({"ok": False, "error": "The main character needs four pictures."}), 400
    rows = [top[:4]]
    if len(bottom) >= 4:
        rows.append(bottom[:4])
    try:
        url = _collage_page(rows)
    except Exception as e:
        log.warning("comics sheet failed: %s", e)
        return jsonify({"ok": False, "error": "Could not put the pictures together."}), 502
    return jsonify({"ok": True, "url": url})


@bp.route("/comics/api/cast-sheet", methods=["POST", "OPTIONS"])
@bp.route("/studios/comics/api/cast-sheet", methods=["POST", "OPTIONS"])
def comics_cast_sheet():
    """One reference page: four character fronts in a 2×2 grid on white."""
    denied = _spa_auth()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    fronts = body.get("fronts") if isinstance(body.get("fronts"), list) else []
    urls = [str(u).strip() for u in fronts if isinstance(u, str) and u.strip()]
    if len(urls) < 4:
        return jsonify({"ok": False, "error": "Need four front shots — one per character."}), 400
    # 2×2: row1 = chars 1–2, row2 = chars 3–4
    rows = [urls[0:2], urls[2:4]]
    try:
        url = _collage_page(rows, bg=(255, 255, 255), cell=768, cols=2)
    except Exception as e:
        log.warning("comics cast-sheet failed: %s", e)
        return jsonify({"ok": False, "error": "Could not build the cast reference sheet."}), 502
    return jsonify({"ok": True, "url": url})


_TURN_POSES = {
    "front": "front view",
    "left": "left side view",
    "right": "right side view",
    "back": "back view",
}


@bp.route("/comics/api/turnaround", methods=["POST", "OPTIONS"])
@bp.route("/studios/comics/api/turnaround", methods=["POST", "OPTIONS"])
def comics_turnaround():
    """One full-body shot from a prompt or one photo, in the comic's art style."""
    denied = _spa_auth()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    pose_key = str(body.get("pose") or "").strip()
    pose = _TURN_POSES.get(pose_key)
    if not pose:
        return jsonify({"ok": False, "error": "Pick front, left, right, or back."}), 400
    style = _INK_STYLES.get(str(body.get("styleId") or ""), _INK_STYLES["classic"])
    details = str(body.get("prompt") or body.get("look") or "").strip()
    name = str(body.get("name") or "the character").strip()
    photo = str(body.get("photo") or "").strip()
    if not details and not photo:
        return jsonify({"ok": False, "error": "Add a description or a photo first."}), 400
    refs = [photo] if photo.startswith("http") or photo.startswith("data:") else []
    # Match the Characters build page: reference photo is identity truth → full-body on white.
    # Comic print style is layered on; we do not invent a different person.
    if refs:
        # Photo path — same idea as CHARACTER_SUPER_ACCURACY / CHARACTER_PROMPT on /characters
        prompt = " ".join([
            "Using the reference photo as the single source of truth, redraw this exact person",
            "or character as a clean full-body standing figure on a pure white background.",
            f"View: {pose} only. Casual standing pose, head to toe, image filling the frame.",
            "Match the reference as closely as possible: same face, same hairstyle, same skin tone,",
            "same body proportions, same outfit and colors. Do not invent a different person or change the identity.",
            f"Name label for continuity only: {name}.",
            f"Render this figure in this comic print style: {style}.",
            "Do not copy the photo's background — replace it with pure white.",
            "No scenery, no panels, no letters, no logos, no watermarks.",
            "High detail, sharp lines, consistent lighting.",
            _INK_SAFETY,
        ])
        if details:
            prompt += (
                f" Also apply these user details (keep identity and face locked to the reference photo): {details}"
            )
    else:
        prompt = " ".join([
            f"Full-body {pose} only of {name}, standing on a pure white background.",
            f"Details: {details}.",
            f"Art style: {style}.",
            "Head to toe visible, casual standing pose, image filling the frame.",
            "No scenery, no panels, no letters, no logos, no watermarks.",
            _INK_SAFETY,
        ])
    result = _comic_image(prompt, refs, "grok-imagine-image-2.0")
    if not result.get("ok") or not result.get("url"):
        return jsonify({"ok": False, "error": result.get("error") or f"Could not draw the {pose}."}), 502
    return jsonify({"ok": True, "pose": pose_key, "url": result["url"]})


# Handoff: a finished comic is $20 and "credits are dollars" for comics unlock.
COMICS_ISSUE_CREDIT_COST = 20


@bp.route("/comics/api/unlock", methods=["POST", "OPTIONS"])
@bp.route("/studios/comics/api/unlock", methods=["POST", "OPTIONS"])
def comics_unlock():
    """Spend Percfect wallet credits to unlock the full comic (clean pages + 2 edits each).

    Body: { issueId: str, free?: bool }
    Free 5th comic (client-computed) charges 0. Otherwise charges COMICS_ISSUE_CREDIT_COST.
    """
    if _spa_auth():
        return jsonify({"ok": False, "error": "Sign in to unlock this comic.", "login_required": True}), 401
    payload = request.get_json(silent=True) or {}
    issue_id = str(payload.get("issueId") or "").strip()
    if not issue_id:
        return jsonify({"ok": False, "error": "Missing issue id."}), 400
    free = bool(payload.get("free"))
    cost = 0 if free else COMICS_ISSUE_CREDIT_COST
    try:
        import app as app_mod
        app_mod.reset_daily_if_needed(current_user.id)
        res = (
            app_mod.supabase.table("users")
            .select("picture_credits,video_credits")
            .eq("id", current_user.id)
            .single()
            .execute()
        )
        user_data = res.data or {}
        bal = app_mod._user_credits(user_data)
        if cost > 0:
            if not app_mod._apply_spend(current_user.id, user_data, cost):
                return jsonify({
                    "ok": False,
                    "error": f"Need {cost} credits to unlock. You have {bal}.",
                    "credits": bal,
                }), 402
            bal = max(0, bal - cost)
        log.info("comics unlock user=%s issue=%s charged=%s bal=%s", current_user.id, issue_id, cost, bal)
        return jsonify({"ok": True, "credits": bal, "charged": cost, "free": free})
    except Exception as e:
        log.warning("comics unlock failed: %s", e)
        return jsonify({"ok": False, "error": "Could not unlock right now."}), 500


@bp.route("/comics/api/save-character", methods=["POST", "OPTIONS"])
@bp.route("/studios/comics/api/save-character", methods=["POST", "OPTIONS"])
def comics_save_character():
    """Save four comic reference shots onto the user's character library. Does not run the character builder."""
    denied = _spa_auth()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    name = str(body.get("name") or "").strip()[:80] or "Character"
    look = str(body.get("look") or "").strip()[:280]
    raw = body.get("images") if isinstance(body.get("images"), list) else []
    images = [str(u).strip() for u in raw if isinstance(u, str) and u.strip()][:4]
    if len(images) < 4:
        return jsonify({"ok": False, "error": "Four shots are required: front, left side, right side, back."}), 400
    try:
        import app as app_mod
        stored = [app_mod._persist_image(src) for src in images]
    except Exception as e:
        log.warning("comics save character persist failed: %s", e)
        return jsonify({"ok": False, "error": "Could not store the pictures."}), 500
    if any(not u or u.startswith("data:") for u in stored):
        return jsonify({"ok": False, "error": "Could not store the pictures."}), 500
    insert_row = {
        "user_id": current_user.id,
        "name": name,
        "gender": "",
        "images": stored,
        "primary_image_url": stored[0],
        "prompt": look,
        "source_mode": "comic",
    }
    try:
        import app as app_mod
        row = app_mod.supabase.table("characters").insert(insert_row).execute()
        saved = (row.data or [None])[0]
    except Exception as e:
        log.warning("comics save character insert failed: %s", e)
        return jsonify({"ok": False, "error": "Could not save the character."}), 500
    if not saved or not saved.get("id"):
        return jsonify({"ok": False, "error": "Could not save the character."}), 500
    return jsonify({"ok": True, "id": saved["id"], "name": name, "images": stored})


@bp.route("/comics/<path:filename>")
@bp.route("/studios/comics/<path:filename>")
def comics_file(filename):
    return _serve_spa(filename)


def init_app(flask_app) -> None:
    if bp.name not in getattr(flask_app, "blueprints", {}):
        flask_app.register_blueprint(bp)
