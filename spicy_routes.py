"""
spicy_routes.py — Flask blueprint for the SpicyAPI media provider.

Registers (idempotent) via init_app(app):
  GET  /api/spicy/status                      → {enabled, has_key}         (no secrets)
  GET  /api/spicy/models?modality=image|video&task=&spicy=1  → dropdown data + prices (public)
  POST /api/spicy/generate                    → run a generation (login-gated)

The models endpoint feeds the dropdown (templates/partials/spicy_model_picker.html).
Prices come straight from the catalog so the UI shows cost and the app can set the
per-generation CREDIT COST from price (see _credit_note below — wire into your wallet).

Gate /generate behind login + credit check, matching the rest of the app.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

import spicy_media

bp = Blueprint("spicy_media", __name__)


def _logged_in_user_id():
    """Resolve user id like the rest of the 3D stack; None if not logged in."""
    try:
        import three_d_character_gen
        uid = three_d_character_gen._current_user_id()
        if uid:
            return str(uid)
    except Exception:
        pass
    try:
        from flask_login import current_user
        if getattr(current_user, "is_authenticated", False):
            return str(current_user.get_id())
    except Exception:
        pass
    return None


@bp.route("/api/spicy/status", methods=["GET"])
def spicy_status():
    return jsonify({"enabled": spicy_media.enabled()})


@bp.route("/api/spicy/models", methods=["GET"])
def spicy_models():
    """Dropdown data. Public (model names + prices are not secret). Hide spicy with ?spicy=0."""
    modality = (request.args.get("modality") or "image").strip().lower()
    task = (request.args.get("task") or "").strip() or None
    include_spicy = (request.args.get("spicy") or "1").strip() not in ("0", "false", "no")
    try:
        models = spicy_media.dropdown_models(modality, task=task, include_spicy=include_spicy)
        return jsonify({"modality": modality, "count": len(models), "models": models})
    except spicy_media.SpicyError as e:
        return jsonify({"error": str(e), "models": []}), 502


@bp.route("/api/spicy/quote", methods=["POST"])
def spicy_quote():
    """Exact price for a request (authoritative). Body: {model, input}. Login-gated."""
    if not _logged_in_user_id():
        return jsonify({"error": "login required"}), 401
    if not spicy_media.enabled():
        return jsonify({"error": "SpicyAPI disabled — set SPICY_API_KEY"}), 503
    data = request.get_json(silent=True) or {}
    model = (data.get("model") or "").strip()
    if not model:
        return jsonify({"error": "model required"}), 400
    try:
        return jsonify({"ok": True, "quote": spicy_media.quote(model, data.get("input") or {})})
    except spicy_media.SpicyError as e:
        return jsonify({"ok": False, "error": str(e)}), 502


@bp.route("/api/spicy/generate", methods=["POST"])
def spicy_generate():
    uid = _logged_in_user_id()
    if not uid:
        return jsonify({"error": "login required"}), 401
    if not request.is_json:
        return jsonify({"error": "JSON body required"}), 415
    if not spicy_media.enabled():
        return jsonify({"error": "SpicyAPI disabled — set SPICY_API_KEY"}), 503
    data = request.get_json(silent=True) or {}
    kind = (data.get("kind") or "image").strip().lower()
    model = (data.get("model") or "").strip()
    if not model:
        return jsonify({"error": "model required (a catalog id)"}), 400

    params = {k: v for k, v in (data.get("params") or {}).items()}
    # Build the model input, then get the AUTHORITATIVE price via quote().
    inp = dict(params)
    if data.get("prompt"):
        inp["prompt"] = data["prompt"]
    if kind == "video" and data.get("image_url"):
        inp["image_url"] = data["image_url"]
    if kind == "image" and data.get("image_urls"):
        inp["image_urls"] = data["image_urls"]
    try:
        est = spicy_media.quote(model, inp)   # exact charge for THIS request
    except spicy_media.SpicyError:
        est = {"list": spicy_media.list_price_for(model)}  # fall back to list price

    # --- CREDIT COST ------------------------------------------------------
    # Charge the user's wallet from `est` (quote) BEFORE generating; funds are held upstream
    # and released on failure, so refund the wallet on SpicyError. Wire to your credit_wallet here.
    try:
        if kind == "video":
            out = spicy_media.generate_video(model, prompt=data.get("prompt"),
                                             image_url=data.get("image_url"), **params)
        else:
            out = spicy_media.generate_image(model, data.get("prompt") or "",
                                             image_urls=data.get("image_urls"), **params)
        return jsonify({"ok": True, "model": model, "quote": est,
                        "task_id": out.get("task_id"), "urls": out.get("urls")})
    except spicy_media.SpicyError as e:
        return jsonify({"ok": False, "error": str(e)}), 502


def init_app(app) -> None:
    if "spicy_media" in app.blueprints:
        return
    app.register_blueprint(bp)
