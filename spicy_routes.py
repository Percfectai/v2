"""
spicy_routes.py — Flask blueprint + studio hooks for the SpicyAPI media provider.

Registers (idempotent) via init_app(app):
  GET  /api/spicy/status
  GET  /api/spicy/models?modality=image|video&task=&spicy=1
  GET  /api/spicy/studio-models?modality=image|video&spicy=0
  POST /api/spicy/quote
  POST /api/spicy/generate

Also hooks Percfect Photos, Videos, and Extend (when a SpicyAPI model is selected)
without altering app.py or studio_task_handlers.py, and routes all SpicyAPI outputs
through spicy_moderation (safe -> percfectai.com; flagged -> private mature vault).
"""
from __future__ import annotations

import datetime
import re
from concurrent.futures import ThreadPoolExecutor
from flask import Blueprint, jsonify, request

import spicy_media

bp = Blueprint("spicy_media", __name__)

_BYPASS_MODELS = {"", "grok", "xai", "wan-2.2", "wan", "wan2.2", "12.2"}
_HOOKED_DISPATCH = False


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


@bp.route("/api/spicy/studio-models", methods=["GET"])
def spicy_studio_models():
    """Family-grouped models with options + credit pricing for Photos & Videos UI."""
    modality = (request.args.get("modality") or "image").strip().lower()
    include_spicy = (request.args.get("spicy") or "0").strip() in ("1", "true", "yes")
    try:
        models = spicy_media.studio_models(modality, include_spicy=include_spicy)
        return jsonify({
            "enabled": spicy_media.enabled(),
            "modality": modality,
            "count": len(models),
            "models": models,
        })
    except spicy_media.SpicyError as e:
        return jsonify({"enabled": spicy_media.enabled(), "error": str(e), "models": []}), 502


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
    inp = dict(params)
    if data.get("prompt"):
        inp["prompt"] = data["prompt"]
    if kind == "video" and data.get("image_url"):
        inp["image_url"] = data["image_url"]
    if kind == "image" and data.get("image_urls"):
        inp["image_urls"] = data["image_urls"]
    try:
        est = spicy_media.quote(model, inp)
    except spicy_media.SpicyError:
        est = {"list": spicy_media.list_price_for(model)}

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


# --- Studio interception + task handlers (cleanly keeps app.py untouched) ----
def _clean_spicy_ref_prompt(a, prompt: str) -> str:
    p = a._normalize_image_ref_tags(prompt or "")
    p = re.sub(r"<IMAGE_(\d+)>", r"image \1", p)
    return p.strip()


def _spicy_before_request():
    if request.method != "POST":
        return None
    path = request.path
    if path not in (
        "/percfectstudios/generate-image",
        "/percfectstudios/generate-batch",
        "/percfectstudios/generate-video",
        "/percfectstudios/extend-video",
    ):
        return None
    raw_model = (request.form.get("model") or "grok").strip()
    if raw_model.lower() in _BYPASS_MODELS:
        return None

    from flask_login import current_user
    if not getattr(current_user, "is_authenticated", False):
        return jsonify({"error": "Log in to continue."}), 401
    if not spicy_media.enabled():
        return jsonify({"error": "SpicyAPI is not configured on this server (missing SPICY_API_KEY)."}), 503

    import app as a
    a.reset_daily_if_needed(current_user.id)
    resolution = (request.form.get("resolution") or "").strip() or None

    if path == "/percfectstudios/generate-image":
        res = a.supabase.table("users").select("picture_credits,video_credits,images_today").eq("id", current_user.id).single().execute()
        user_data = res.data or {}
        prompt = request.form.get("prompt", "").strip()
        style = request.form.get("style", "")
        split_n = a._parse_split_n(request.form.get("split_n") or request.form.get("split"))
        aspect = a._photo_aspect_ratio_from_request()
        slots = a._rehost_ref_slots(a._get_form_reference_slots(a.MAX_REFERENCE_PHOTOS))
        has_refs = any(slots)
        has_style = a._photo_style_is_set(style)
        if not prompt:
            if has_refs:
                prompt = a._photo_remake_prompt_for_aspect(aspect)
            elif has_style:
                prompt = ""
            else:
                prompt = a._photo_seed_prompt_for_aspect(aspect)
        if split_n:
            prompt = a._apply_split_screen_prompt(prompt, split_n)
        dense_refs = [u for u in slots if u]
        try:
            resolved_model, _ = spicy_media.resolve_model_route(raw_model, modality="image", num_refs=len(dense_refs))
        except spicy_media.SpicyError as e:
            return jsonify({"error": str(e)}), 400
        spicy_prompt = _clean_spicy_ref_prompt(a, a._apply_style(prompt, style))
        if not spicy_prompt:
            spicy_prompt = a._apply_style(a._photo_seed_prompt_for_aspect(aspect), style)
        est = spicy_media.estimate_credits(
            resolved_model, modality="image", resolution=resolution, aspect_ratio=aspect, num_refs=len(dense_refs)
        )
        cost = int(est["credits_total"])
        bal = a._user_credits(user_data)
        if not current_user.is_admin and bal < cost:
            return jsonify({"error": f"Not enough credits. This generate needs {cost} — you have {bal}."}), 402
        payload = {
            "provider": "spicy",
            "model": resolved_model,
            "resolution": resolution,
            "full_prompt": spicy_prompt,
            "source_image": dense_refs[0] if dense_refs else None,
            "source_images": dense_refs,
            "cost": cost,
            "is_admin": current_user.is_admin,
            "aspect_ratio": aspect,
            "split_n": split_n,
        }
        return jsonify(a.async_payload(a.enqueue(a.studio_jobs, current_user.id, "image", payload)))

    if path == "/percfectstudios/generate-batch":
        try:
            raw_n = int(float(str(request.form.get("batch_n") or request.form.get("count") or "10").strip()))
        except (TypeError, ValueError):
            raw_n = 10
        batch_n = 5 if raw_n == 5 else 10
        res = a.supabase.table("users").select("picture_credits,video_credits,images_today").eq("id", current_user.id).single().execute()
        user_data = res.data or {}
        prompt = request.form.get("prompt", "").strip()
        style = request.form.get("style", "")
        aspect = a._photo_aspect_ratio_from_request()
        slots = a._get_form_reference_slots(a.MAX_REFERENCE_PHOTOS)
        if not any(slots):
            raw = (a._get_form_image_url() or "").strip()
            if raw:
                slots[0] = raw
        slots = a._rehost_ref_slots(slots)
        has_refs = any(slots)
        has_style = a._photo_style_is_set(style)
        if not prompt:
            if has_refs:
                prompt = a._photo_remake_prompt_for_aspect(aspect)
            elif has_style:
                prompt = ""
            else:
                prompt = a._photo_seed_prompt_for_aspect(aspect)
        dense_refs = [u for u in slots if u]
        try:
            resolved_model, _ = spicy_media.resolve_model_route(raw_model, modality="image", num_refs=len(dense_refs))
        except spicy_media.SpicyError as e:
            return jsonify({"error": str(e)}), 400
        spicy_prompt = _clean_spicy_ref_prompt(a, a._apply_style(prompt, style))
        if not spicy_prompt:
            spicy_prompt = a._apply_style(a._photo_seed_prompt_for_aspect(aspect), style)
        est = spicy_media.estimate_credits(
            resolved_model, modality="image", resolution=resolution, aspect_ratio=aspect, num_refs=len(dense_refs)
        )
        per_cost = int(est["credits_total"])
        total_cost = per_cost * batch_n
        bal = a._user_credits(user_data)
        if not current_user.is_admin and bal < total_cost:
            return jsonify({"error": f"A batch of {batch_n} on this model needs {total_cost} credits — you have {bal}."}), 402
        payload = {
            "provider": "spicy",
            "model": resolved_model,
            "resolution": resolution,
            "per_image_cost": per_cost,
            "full_prompt": spicy_prompt,
            "source_images": dense_refs,
            "source_image": dense_refs[0] if dense_refs else None,
            "batch_n": batch_n,
            "is_admin": current_user.is_admin,
            "aspect_ratio": aspect,
        }
        return jsonify(a.async_payload(a.enqueue(a.studio_jobs, current_user.id, "batch", payload)))

    if path == "/percfectstudios/generate-video":
        res = a.supabase.table("users").select("picture_credits,video_credits,videos_today").eq("id", current_user.id).single().execute()
        user_data = res.data or {}
        prompt = request.form.get("prompt", "").strip()
        try:
            slots = a._rehost_ref_slots(a._get_form_reference_slots(4))
        except Exception:
            slots = [None, None, None, None]
        legacy = a._get_form_image_url()
        if legacy and not slots[0]:
            slots[0] = legacy
        dense_refs = [u for u in slots if u]
        try:
            resolved_model, _ = spicy_media.resolve_model_route(raw_model, modality="video", num_refs=len(dense_refs))
        except spicy_media.SpicyError as e:
            return jsonify({"error": str(e)}), 400
        try:
            raw_dur = int(request.form.get("duration", 6))
        except (TypeError, ValueError):
            raw_dur = 6
        duration = spicy_media.clamp_duration(resolved_model, raw_dur)
        aspect = (request.form.get("aspect_ratio") or "").strip() or None
        raw_aud = request.form.get("generate_audio")
        generate_audio = None if raw_aud in (None, "") else (str(raw_aud).strip().lower() in ("1", "true", "yes", "on"))
        clean_prompt = _clean_spicy_ref_prompt(a, prompt)
        if not clean_prompt and dense_refs:
            clean_prompt = "animate this"
        if not clean_prompt:
            return jsonify({"error": "Prompt is required."}), 400
        est = spicy_media.estimate_credits(
            resolved_model, modality="video", resolution=resolution, duration=duration,
            generate_audio=generate_audio, aspect_ratio=aspect,
        )
        cost = int(est["credits_total"])
        bal = a._user_credits(user_data)
        if not current_user.is_admin and bal < cost:
            return jsonify({"error": f"Not enough credits. This {duration}s video needs {cost} credits — you have {bal}."}), 402
        chain_id = (request.form.get("chain_id") or "").strip()
        source_id = (request.form.get("source_id") or "").strip()
        continue_chain = (request.form.get("continue_chain") or "").strip().lower() in ("1", "true", "yes", "on")
        payload = {
            "provider": "spicy",
            "model": resolved_model,
            "resolution": resolution,
            "aspect_ratio": aspect,
            "generate_audio": generate_audio,
            "prompt": clean_prompt,
            "image_url": dense_refs[0] if dense_refs else None,
            "reference_images": dense_refs if len(dense_refs) >= 2 else None,
            "duration": duration,
            "cost": cost,
            "is_admin": current_user.is_admin,
            "chain_id": chain_id or None,
            "source_id": source_id or None,
            "continue_chain": continue_chain,
            "source_video_url": (request.form.get("source_video_url") or "").strip() or None,
        }
        return jsonify(a.async_payload(a.enqueue(a.studio_jobs, current_user.id, "video", payload)))

    # /percfectstudios/extend-video
    res = a.supabase.table("users").select("picture_credits,video_credits,videos_today").eq("id", current_user.id).single().execute()
    user_data = res.data or {}
    video_url = (request.form.get("video_url") or "").strip()
    video_file = request.files.get("video_file")
    if not video_url and video_file and video_file.filename:
        try:
            raw = a._ensure_mp4_bytes(video_file.read(), filename=(video_file.filename or "").lower())
            video_url = a._persist_video_bytes(raw, content_type="video/mp4")
        except Exception:
            return jsonify({"error": "Could not upload your video — try a shorter MP4 or paste a URL."}), 500
    if not video_url:
        return jsonify({"error": "No video to extend."}), 400
    prompt = (request.form.get("prompt") or "").strip() or "Continue the video naturally, keeping the same subject, motion, style and lighting."
    try:
        resolved_model, _ = spicy_media.resolve_model_route(raw_model, modality="video", is_extend=True)
    except spicy_media.SpicyError as e:
        return jsonify({"error": str(e)}), 400
    try:
        raw_secs = int(request.form.get("duration", a.EXTEND_SECONDS))
    except (TypeError, ValueError):
        raw_secs = a.EXTEND_SECONDS
    secs = spicy_media.clamp_duration(resolved_model, raw_secs)
    est = spicy_media.estimate_credits(resolved_model, modality="video", resolution=resolution, duration=secs)
    cost = int(est["credits_total"])
    bal = a._user_credits(user_data)
    if not current_user.is_admin and bal < cost:
        return jsonify({"error": f"Extending by {secs}s on this model needs {cost} credits — you have {bal}."}), 402
    payload = {
        "provider": "spicy",
        "model": resolved_model,
        "resolution": resolution,
        "prompt": prompt,
        "video_url": video_url,
        "secs": secs,
        "cost": cost,
        "is_admin": current_user.is_admin,
        "chain_id": (request.form.get("chain_id") or "").strip() or None,
        "source_id": (request.form.get("source_id") or "").strip() or None,
    }
    return jsonify(a.async_payload(a.enqueue(a.studio_jobs, current_user.id, "extend", payload)))


# --- Task execution + moderation routing -------------------------------------
def _spicy_quote_cost(model: str, inp: dict, modality: str, fallback_cost: int) -> int:
    try:
        q = spicy_media.quote(model, inp)
        return spicy_media.credits_from_quote(q, modality=modality, fallback_credits=fallback_cost)
    except Exception:
        return max(1, int(fallback_cost or 1))


def _spicy_progress_cb(a):
    try:
        cv = getattr(a, "_video_job_progress_cb", None)
        return cv.get() if cv is not None else None
    except Exception:
        return None


def _finalize_spicy_asset(a, user_id: int, src_url: str, *, media_type: str, prompt: str, model_id: str) -> dict:
    import spicy_moderation as sm
    is_video = (media_type or "").lower() == "video"
    raw_bytes, ctype = sm.download_media_bytes(src_url, is_video=is_video)
    mod = sm.moderate_media_bytes(raw_bytes, media_type="video" if is_video else "image", content_type=ctype, prompt=prompt)
    if mod.get("safe") is True:
        if is_video:
            public_url = a._persist_video_bytes(raw_bytes, content_type=ctype or "video/mp4")
        else:
            ext = "png" if "png" in (ctype or "") else ("webp" if "webp" in (ctype or "") else "jpg")
            public_url = a._persist_image_bytes(raw_bytes, ext=ext, content_type=ctype or "image/jpeg")
        return {"safe": True, "url": public_url}
    vault_id = sm.send_to_mature_vault(
        a.supabase, user_id, raw_bytes,
        media_type="video" if is_video else "image",
        content_type=ctype, prompt=prompt, model_id=model_id,
        moderation_reason=str(mod.get("reason") or "flagged"),
        frames=mod.get("frames"),
    )
    return {"safe": False, "vault_item_id": vault_id, "mature_site_url": sm.mature_site_url(), "reason": str(mod.get("reason") or "flagged")}


def _moderated_redirect_payload(*, media_type: str, model_id: str, cost: int, finalized: dict) -> dict:
    return {
        "moderated_redirect": True,
        "mature_site_url": finalized.get("mature_site_url") or "",
        "vault_item_id": finalized.get("vault_item_id"),
        "type": media_type,
        "charged": cost,
        "model": model_id,
        "message": (
            "This creation did not pass percfectai.com's content moderation, so it was sent "
            "straight to your private vault on the mature website. Sign in there with your "
            "same login to view and download your file."
        ),
    }


def _dispatch_spicy(kind: str, user_id: int, payload: dict) -> dict:
    import app as a
    import video_chains as vc
    is_admin = bool(payload.get("is_admin"))
    spicy_model = payload["model"]

    if kind == "image":
        full_prompt = payload["full_prompt"]
        refs = [u for u in (payload.get("source_images") or []) if u]
        res = a.supabase.table("users").select("picture_credits,video_credits,images_today").eq("id", user_id).single().execute()
        user_data = res.data or {}
        inp = spicy_media.build_image_input(
            spicy_model, full_prompt, image_urls=refs,
            aspect_ratio=payload.get("aspect_ratio") or "auto", resolution=payload.get("resolution"),
        )
        cost = _spicy_quote_cost(spicy_model, inp, "image", int(payload.get("cost") or 1))
        if not is_admin and a._user_credits(user_data) < cost:
            raise Exception(f"Not enough credits (needs {cost}).")
        out = spicy_media.generate(spicy_model, inp, timeout_s=300)
        raw_url = (out.get("urls") or [None])[0]
        if not raw_url:
            raise Exception("SpicyAPI returned no image URL. You were not charged.")
        finalized = _finalize_spicy_asset(a, user_id, raw_url, media_type="image", prompt=full_prompt, model_id=spicy_model)
        if not is_admin and not a._apply_spend(user_id, user_data, cost, {"images_today": int(user_data.get("images_today") or 0) + 1}):
            raise Exception("No credits remaining. Buy credits or redeem a coupon.")
        if not finalized["safe"]:
            return _moderated_redirect_payload(media_type="image", model_id=spicy_model, cost=cost, finalized=finalized)
        image_url = finalized["url"]
        a.supabase.table("generations").insert({
            "user_id": user_id, "type": "image", "prompt": full_prompt,
            "output_url": image_url, "created_at": datetime.datetime.utcnow().isoformat(),
        }).execute()
        return {"url": image_url, "type": "image", "charged": cost, "model": spicy_model}

    if kind == "batch":
        batch_n = max(1, min(10, int(payload.get("batch_n") or 10)))
        full_prompt = payload["full_prompt"]
        refs = [u for u in (payload.get("source_images") or []) if u]
        res = a.supabase.table("users").select("picture_credits,video_credits,images_today").eq("id", user_id).single().execute()
        user_data = res.data or {}
        inp = spicy_media.build_image_input(
            spicy_model, full_prompt, image_urls=refs,
            aspect_ratio=payload.get("aspect_ratio") or "auto", resolution=payload.get("resolution"),
        )
        per_cost = _spicy_quote_cost(spicy_model, inp, "image", int(payload.get("per_image_cost") or 1))
        if not is_admin and a._user_credits(user_data) < per_cost:
            raise Exception(f"Not enough credits (needs {per_cost} per image).")

        def _one(_i):
            try:
                out = spicy_media.generate(spicy_model, inp, timeout_s=300)
                u = (out.get("urls") or [None])[0]
                return _finalize_spicy_asset(a, user_id, u, media_type="image", prompt=full_prompt, model_id=spicy_model) if u else None
            except Exception:
                return None

        urls, moderated = [], []
        with ThreadPoolExecutor(max_workers=min(5, batch_n)) as ex:
            for item in ex.map(_one, range(batch_n)):
                if not item:
                    continue
                if item.get("safe"):
                    urls.append(item["url"])
                else:
                    moderated.append(item)
        total_made = len(urls) + len(moderated)
        if not total_made:
            raise Exception("None of the batch images generated. You were NOT charged.")
        total_charged = total_made * per_cost
        if not is_admin:
            a._apply_spend(user_id, user_data, total_charged, {"images_today": int(user_data.get("images_today") or 0) + total_made})
        now = datetime.datetime.utcnow().isoformat()
        for u in urls:
            try:
                a.supabase.table("generations").insert({
                    "user_id": user_id, "type": "image", "prompt": full_prompt, "output_url": u, "created_at": now,
                }).execute()
            except Exception:
                pass
        return {
            "urls": urls, "made": len(urls), "moderated_count": len(moderated),
            "moderated_redirect": bool(moderated) and not urls,
            "mature_site_url": (moderated[0].get("mature_site_url") if moderated else "") or "",
            "failed": batch_n - total_made, "charged": total_charged, "type": "batch", "model": spicy_model,
        }

    if kind == "video":
        prompt = payload["prompt"]
        duration = int(payload.get("duration") or 6)
        res = a.supabase.table("users").select("picture_credits,video_credits,videos_today").eq("id", user_id).single().execute()
        user_data = res.data or {}
        inp = spicy_media.build_video_input(
            spicy_model, prompt, image_url=payload.get("image_url"),
            reference_images=payload.get("reference_images"), duration=duration,
            resolution=payload.get("resolution"), aspect_ratio=payload.get("aspect_ratio"),
            generate_audio=payload.get("generate_audio"),
        )
        cost = _spicy_quote_cost(spicy_model, inp, "video", int(payload.get("cost") or 18))
        if not is_admin and a._user_credits(user_data) < cost:
            raise Exception(f"Not enough credits for this video (needs {cost}).")
        out = spicy_media.generate(spicy_model, inp, timeout_s=900, progress_cb=_spicy_progress_cb(a))
        raw_url = (out.get("urls") or [None])[0]
        if not raw_url:
            raise Exception("Video generator returned no URL.")
        finalized = _finalize_spicy_asset(a, user_id, raw_url, media_type="video", prompt=prompt, model_id=spicy_model)
        if not is_admin and not a._apply_spend(user_id, user_data, cost, {"videos_today": int(user_data.get("videos_today") or 0) + 1}):
            raise Exception("Not enough credits for this video length.")
        if not finalized["safe"]:
            return _moderated_redirect_payload(media_type="video", model_id=spicy_model, cost=cost, finalized=finalized)
        video_url = finalized["url"]
        if payload.get("chain_id") or payload.get("source_id") or payload.get("continue_chain"):
            chain_id = vc.resolve_video_chain_id(
                a.supabase, user_id, chain_id=payload.get("chain_id"),
                source_id=payload.get("source_id"), video_url=payload.get("source_video_url"),
            )
        else:
            chain_id = vc.new_video_chain_id()
        saved = vc.insert_video_generation(a.supabase, user_id, prompt, video_url, chain_id=chain_id)
        return {"url": video_url, "type": "video", "charged": cost, "model": spicy_model,
                "chain_id": saved.get("chain_id") or chain_id, "generation_id": saved.get("id")}

    if kind == "extend":
        prompt = payload["prompt"]
        video_url = payload["video_url"]
        secs = int(payload.get("secs") or a.EXTEND_SECONDS)
        res = a.supabase.table("users").select("picture_credits,video_credits,videos_today").eq("id", user_id).single().execute()
        user_data = res.data or {}
        inp = spicy_media.build_video_input(
            spicy_model, prompt, video_url=video_url, duration=secs, resolution=payload.get("resolution"),
        )
        cost = _spicy_quote_cost(spicy_model, inp, "video", int(payload.get("cost") or 36))
        if not is_admin and a._user_credits(user_data) < cost:
            raise Exception(f"Not enough credits to extend this video (needs {cost}).")
        out = spicy_media.generate(spicy_model, inp, timeout_s=900, progress_cb=_spicy_progress_cb(a))
        raw_url = (out.get("urls") or [None])[0]
        if not raw_url:
            raise Exception("no video url returned")
        finalized = _finalize_spicy_asset(a, user_id, raw_url, media_type="video", prompt=f"[+{secs}s extend] {prompt}", model_id=spicy_model)
        if not is_admin and not a._apply_spend(user_id, user_data, cost, {"videos_today": int(user_data.get("videos_today") or 0) + 1}):
            raise Exception("Not enough credits to extend this video.")
        if not finalized["safe"]:
            return _moderated_redirect_payload(media_type="video", model_id=spicy_model, cost=cost, finalized=finalized)
        new_url = finalized["url"]
        chain_id = vc.resolve_video_chain_id(
            a.supabase, user_id, chain_id=payload.get("chain_id"),
            source_id=payload.get("source_id"), video_url=video_url,
        )
        saved = vc.insert_video_generation(a.supabase, user_id, f"[+{secs}s extend] {prompt}", new_url, chain_id=chain_id)
        return {"url": new_url, "type": "video", "extended": True, "charged": cost, "model": spicy_model,
                "chain_id": saved.get("chain_id") or chain_id, "generation_id": saved.get("id")}

    raise RuntimeError(f"Unsupported spicy kind={kind!r}")


def _install_dispatch_hook() -> None:
    global _HOOKED_DISPATCH
    if _HOOKED_DISPATCH:
        return
    import studio_task_handlers as sth
    orig_dispatch = sth.dispatch

    def _wrapped_dispatch(kind: str, user_id: int, payload: dict) -> dict:
        if isinstance(payload, dict) and payload.get("provider") == "spicy" and kind in ("image", "batch", "video", "extend"):
            return _dispatch_spicy(kind, user_id, payload)
        return orig_dispatch(kind, user_id, payload)

    sth.dispatch = _wrapped_dispatch
    _HOOKED_DISPATCH = True


def init_app(app) -> None:
    if "spicy_media" not in app.blueprints:
        app.register_blueprint(bp)
    if not getattr(app, "_spicy_studio_hooked", False):
        app.before_request(_spicy_before_request)
        app._spicy_studio_hooked = True
    _install_dispatch_hook()
