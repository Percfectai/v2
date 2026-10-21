"""
Percfect Posts — publish layer and Chrome extension bridge for percfectai.com.
"""

from __future__ import annotations

import datetime
from functools import wraps
import os
import uuid
import requests

from flask import Blueprint, current_app, g, jsonify, redirect, render_template, request
from flask_login import current_user

from percfect_posts_studio import register_studio_routes, serve_spa

from ai_key_crypto import decrypt_key, encrypt_key
from ai_providers import PROVIDER_CALLERS, WAND_PRIORITY, test_key

percfect_posts_bp = Blueprint("percfect_posts", __name__)

PROVIDERS = ("grok", "gemini", "claude", "openai")


def _supabase():
    return current_app.extensions["percfect_supabase"]


@percfect_posts_bp.record_once
def _bind_supabase(setup_state):
    """Grabs the app's existing `supabase` client once at registration time."""
    app = setup_state.app
    if not hasattr(app, "extensions"):
        app.extensions = {}
    if "percfect_supabase" not in app.extensions:
        try:
            from app import supabase as _sb
        except Exception as exc:
            raise RuntimeError(
                "percfect_posts_bp needs app.py's `supabase` client importable."
            ) from exc
        app.extensions["percfect_supabase"] = _sb


def login_or_api_key_required(f):
    """Accepts either Flask-Login session cookie OR X-API-Key header."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if getattr(current_user, "is_authenticated", False):
            g.current_user_id = current_user.id
            return f(*args, **kwargs)

        api_key = request.headers.get("X-API-Key")
        if api_key:
            supabase = _supabase()
            try:
                res = (
                    supabase.table("users")
                    .select("id")
                    .or_(f"api_key1.eq.{api_key},api_key2.eq.{api_key}")
                    .limit(1)
                    .execute()
                )
                if res.data:
                    g.current_user_id = res.data[0]["id"]
                    return f(*args, **kwargs)
            except Exception:
                current_app.logger.exception("API key authentication lookup failed")

        return jsonify({"error": "Not authenticated"}), 401
    return decorated


def _get_uid():
    return getattr(g, "current_user_id", None) or current_user.id


# ── Pages ─────────────────────────────────────────────────────────────

@percfect_posts_bp.route("/percfectposts")
def percfect_posts_page():
    # Streamline V5 redesign (Jinja template extending base.html).
    return render_template("percfect_posts.html")


@percfect_posts_bp.route("/percfectposts/classic")
def percfect_posts_page_classic():
    # Previous static SPA, kept reachable for rollback/comparison.
    return serve_spa()


@percfect_posts_bp.route("/percfectpostss")
@percfect_posts_bp.route("/perfecpostss")
@percfect_posts_bp.route("/perfectposts")
@percfect_posts_bp.route("/percfectpost")
def percfect_posts_typo():
    return redirect("/percfectposts", code=302)


# ── Ingest & Library Endpoints ────────────────────────────────────────

@percfect_posts_bp.route("/api/percfectposts/upload-media", methods=["POST"])
@login_or_api_key_required
def percfect_posts_upload():
    """Ingests scraped URLs or direct image uploads into Supabase storage & generations."""
    supabase = _supabase()
    uid = _get_uid()
    media_id = str(uuid.uuid4())
    stored_url = None
    source_page = None

    if request.is_json:
        data = request.get_json() or {}
        media_url = data.get("media_url")
        source_page = data.get("source_page")
        title = data.get("title") or "Captured Web Media"

        if not media_url:
            return jsonify({"error": "media_url is required"}), 400

        try:
            resp = requests.get(media_url, timeout=12)
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
            ext = ".png" if "png" in content_type else ".jpg"
            storage_path = f"{uid}/{media_id}{ext}"

            supabase.storage.from_("generations").upload(
                path=storage_path,
                file=resp.content,
                file_options={"content-type": content_type}
            )
            stored_url = supabase.storage.from_("generations").get_public_url(storage_path)
        except Exception:
            stored_url = media_url

    elif "file" in request.files:
        file = request.files["file"]
        title = request.form.get("title") or file.filename or "Uploaded Photo"
        ext = os.path.splitext(file.filename)[1].lower() or ".jpg"
        storage_path = f"{uid}/{media_id}{ext}"
        content_type = file.content_type or "image/jpeg"

        try:
            supabase.storage.from_("generations").upload(
                path=storage_path,
                file=file.read(),
                file_options={"content-type": content_type}
            )
            stored_url = supabase.storage.from_("generations").get_public_url(storage_path)
        except Exception as e:
            return jsonify({"error": f"Upload failed: {str(e)}"}), 500
    else:
        return jsonify({"error": "No media provided"}), 400

    record = {
        "user_id": uid,
        "type": "image",
        "prompt": title,
        "output_url": stored_url,
        "preview_url": stored_url,
        "source": "percfectposts",
        "unlocked": True,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    try:
        supabase.table("generations").insert(record).execute()
    except Exception as e:
        current_app.logger.exception("Insert to generations failed: %s", e)

    return jsonify({
        "ok": True,
        "media": {
            "id": media_id,
            "url": stored_url,
            "thumb": stored_url,
            "name": title,
            "type": "image",
            "upscale_url": f"/studios/percfectphotos?edit_id={media_id}&action=upscale",
            "watermark_url": f"/studios/percfectphotos?edit_id={media_id}&action=watermark"
        }
    }), 201


# ── Publishing & History ──────────────────────────────────────────────

@percfect_posts_bp.route("/api/percfectposts/site-profile", methods=["GET"])
def percfect_posts_site_profile():
    """Socials the user typed in Settings, so the Posts app shows the same handles."""
    if not getattr(current_user, "is_authenticated", False):
        return jsonify({"logged_in": False, "socials": {}})
    socials = {}
    try:
        row = (
            _supabase().table("users")
            .select("username,social_twitter,social_instagram,social_tiktok,social_youtube,social_website")
            .eq("id", current_user.id).single().execute()
        ).data or {}
        for key in ("twitter", "instagram", "tiktok", "youtube", "website"):
            val = (row.get(f"social_{key}") or "").strip()
            if val:
                socials[key] = val
    except Exception:
        current_app.logger.exception("Posts site-profile lookup failed")
    return jsonify({"logged_in": True, "username": current_user.username, "socials": socials})


@percfect_posts_bp.route("/api/percfectposts/history", methods=["GET"])
@login_or_api_key_required
def percfect_posts_history():
    supabase = _supabase()
    uid = _get_uid()
    try:
        res = (
            supabase.table("post_history")
            .select("file_id,file_kind,network,status,method,url,posted_at")
            .eq("user_id", uid)
            .execute()
        )
    except Exception:
        current_app.logger.exception("History query failed for %s", uid)
        return jsonify({}), 200

    by_file: dict[str, list[dict]] = {}
    for row in res.data or []:
        by_file.setdefault(row["file_id"], []).append({
            "network": row["network"],
            "status": row["status"],
            "method": row["method"],
            "url": row.get("url"),
            "posted_at": row.get("posted_at"),
        })
    return jsonify(by_file)


@percfect_posts_bp.route("/api/percfectposts/mark", methods=["POST"])
@login_or_api_key_required
def percfect_posts_mark():
    supabase = _supabase()
    uid = _get_uid()
    data = request.get_json(silent=True) or {}

    file_id = str(data.get("file_id") or "").strip()
    file_kind = str(data.get("file_kind") or "").strip()
    network = str(data.get("network") or "").strip()
    status = str(data.get("status") or "posted").strip()
    method = str(data.get("method") or "manual").strip()
    url = data.get("url")

    if not file_id or not file_kind or not network:
        return jsonify({"error": "file_id, file_kind, and network required"}), 400

    row = {
        "user_id": uid,
        "file_id": file_id,
        "file_kind": file_kind,
        "network": network,
        "status": status,
        "method": method,
        "url": url,
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    try:
        supabase.table("post_history").upsert(
            row, on_conflict="user_id,file_id,network"
        ).execute()
    except Exception as e:
        return jsonify({"error": str(e)[:200]}), 500

    return jsonify({"ok": True})


# ── AI Providers & Wand ───────────────────────────────────────────────

@percfect_posts_bp.route("/api/percfectposts/ai-keys", methods=["GET"])
@login_or_api_key_required
def percfect_posts_ai_keys_list():
    supabase = _supabase()
    uid = _get_uid()
    try:
        res = (
            supabase.table("ai_provider_keys")
            .select("provider,enabled,use_platform_key,last_tested_at,last_test_ok")
            .eq("user_id", uid)
            .execute()
        )
        res_data = res.data or []
    except Exception:
        res_data = []

    by_provider = {row["provider"]: row for row in res_data}
    out = []
    for p in PROVIDERS:
        row = by_provider.get(p, {})
        out.append({
            "provider": p,
            "enabled": bool(row.get("enabled")),
            "has_key": bool(row.get("use_platform_key")) or (p in by_provider),
            "use_platform_key": bool(row.get("use_platform_key")),
            "last_test_ok": row.get("last_test_ok"),
        })
    return jsonify(out)


@percfect_posts_bp.route("/api/percfectposts/ai-keys", methods=["POST"])
@login_or_api_key_required
def percfect_posts_ai_keys_save():
    supabase = _supabase()
    uid = _get_uid()
    data = request.get_json(silent=True) or {}
    provider = str(data.get("provider") or "").strip()
    if provider not in PROVIDERS:
        return jsonify({"error": f"provider must be one of {PROVIDERS}"}), 400
    enabled = bool(data.get("enabled"))
    use_platform_key = bool(data.get("use_platform_key")) and provider == "grok"
    raw_key = data.get("api_key")
    row = {
        "user_id": uid,
        "provider": provider,
        "enabled": enabled,
        "use_platform_key": use_platform_key,
    }
    if raw_key:
        row["key_encrypted"] = encrypt_key(raw_key)
    elif not use_platform_key and enabled:
        return jsonify({"error": "Paste an API key, or use the platform key (Grok only)"}), 400
    try:
        supabase.table("ai_provider_keys").upsert(row, on_conflict="user_id,provider").execute()
    except Exception as e:
        current_app.logger.exception("ai-keys save failed for %s", uid)
        return jsonify({"error": str(e)[:200]}), 500
    return jsonify({"ok": True})


@percfect_posts_bp.route("/api/percfectposts/ai-keys/test", methods=["POST"])
@login_or_api_key_required
def percfect_posts_ai_keys_test():
    supabase = _supabase()
    uid = _get_uid()
    data = request.get_json(silent=True) or {}
    provider = str(data.get("provider") or "").strip()
    if provider not in PROVIDERS:
        return jsonify({"error": f"provider must be one of {PROVIDERS}"}), 400
    try:
        res = (
            supabase.table("ai_provider_keys")
            .select("key_encrypted,use_platform_key")
            .eq("user_id", uid).eq("provider", provider)
            .single().execute()
        )
        row = res.data or {}
    except Exception:
        row = {}
    if row.get("use_platform_key") and provider == "grok":
        platform_key = current_app.config.get("PLATFORM_XAI_KEY")
        if not platform_key:
            return jsonify({"ok": False, "error": "Platform xAI key not configured on the server"}), 500
        ok = test_key("grok", platform_key)
    else:
        raw = decrypt_key(row.get("key_encrypted") or "")
        if not raw:
            return jsonify({"ok": False, "error": "No key on file for this provider"}), 400
        try:
            ok = test_key(provider, raw)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)[:200]}), 200
    try:
        supabase.table("ai_provider_keys").update({
            "last_tested_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "last_test_ok": ok,
        }).eq("user_id", uid).eq("provider", provider).execute()
    except Exception:
        current_app.logger.exception("ai-keys test-result save failed for %s", uid)
    return jsonify({"ok": ok})


@percfect_posts_bp.route("/api/percfectposts/wand", methods=["POST"])
@login_or_api_key_required
def percfect_posts_wand():
    supabase = _supabase()
    uid = _get_uid()
    data = request.get_json(silent=True) or {}
    image_url = str(data.get("image_url") or "").strip()
    hint = str(data.get("hint") or "").strip()

    if not image_url:
        return jsonify({"error": "image_url is required"}), 400

    try:
        res = (
            supabase.table("ai_provider_keys")
            .select("provider,enabled,use_platform_key,key_encrypted")
            .eq("user_id", uid).eq("enabled", True)
            .execute()
        )
        enabled_rows = {row["provider"]: row for row in (res.data or [])}
    except Exception:
        return jsonify({"error": "Could not check AI keys"}), 500

    for provider in WAND_PRIORITY:
        row = enabled_rows.get(provider)
        if not row:
            continue
        if row.get("use_platform_key") and provider == "grok":
            key = current_app.config.get("PLATFORM_XAI_KEY")
        else:
            key = decrypt_key(row.get("key_encrypted") or "")
        if not key:
            continue
        try:
            result = PROVIDER_CALLERS[provider](key, image_url, hint)
            result["provider_used"] = provider
            return jsonify(result)
        except Exception as e:
            current_app.logger.warning("Wand %s failed: %s", provider, e)
            continue

    return jsonify({
        "error": "No connected AI chat key worked. Connect one in AI chats first."
    }), 400


register_studio_routes(percfect_posts_bp, login_or_api_key_required)