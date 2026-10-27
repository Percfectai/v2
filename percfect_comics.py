"""Perfect Comics studio for Percfectai/v2.

Serves the September 25 studio at /comics. Writer uses the chat silo.
Pictures use the image silo, grok-imagine-image-2.0, 1k.
"""
from __future__ import annotations

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
        return " ".join([
            f'Comic book COVER for "{title}". This is a single full-bleed splash, not a panel grid, not an interior page.',
            f"Art style: {style}.",
            f"Characters, keep their faces and costumes exactly like this description: {cast}.",
            f"What the cover shows: {beat or title}.",
            "No title lettering, no logos, no captions. Leave the top third clear of faces and action so a title can sit there later.",
            "If a character photo is attached, match that face and costume. Do not copy its background or pose.",
            _INK_SAFETY,
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
@bp.route("/studios/comics")
@bp.route("/studios/comics/")
def comics_page():
    return _serve_spa()


@bp.route("/comics/api/rewrite", methods=["POST"])
@bp.route("/studios/comics/api/rewrite", methods=["POST"])
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
    prompt = (
        "You are the copy editor for Perfect Comics. Return ONLY the rewritten text, no JSON, no quotes.\n"
        f"Target box: {target}\n"
        f"Title: {str(body.get('title') or 'Untitled')[:80]}\n"
        f"Genre: {str(body.get('genre') or '')[:40]}\n"
        f"Art style: {style}\n"
        f"Cast: {str(body.get('cast') or 'original lead')[:800]}\n"
        f"Context: {str(body.get('context') or '(none)')[:1500]}\n"
        f"Current text: {str(body.get('current') or '(empty)')[:2500]}\n"
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


@bp.route("/comics/api/ink", methods=["POST"])
@bp.route("/studios/comics/api/ink", methods=["POST"])
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


@bp.route("/comics/api/plan", methods=["POST"])
@bp.route("/studios/comics/api/plan", methods=["POST"])
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



@bp.route("/comics/<path:filename>")
@bp.route("/studios/comics/<path:filename>")
def comics_file(filename):
    return _serve_spa(filename)


def init_app(flask_app) -> None:
    if bp.name not in getattr(flask_app, "blueprints", {}):
        flask_app.register_blueprint(bp)
