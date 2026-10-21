"""Central registry of all studio generation task handlers."""

from __future__ import annotations

import datetime
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict

TASK_HANDLERS: Dict[str, Callable[[int, dict], dict]] = {}


def register(kind: str):
    def deco(fn: Callable[[int, dict], dict]):
        TASK_HANDLERS[kind] = fn
        return fn
    return deco


def dispatch(kind: str, user_id: int, payload: dict) -> dict:
    fn = TASK_HANDLERS.get(kind)
    if not fn:
        raise RuntimeError(f"No task handler registered for kind={kind!r}")
    return fn(user_id, payload)


def kinds() -> list[str]:
    return sorted(TASK_HANDLERS.keys())


def _app():
    import app as app_module
    return app_module


def _job_media_key() -> str:
    """Media key for this job thread (studio_jobs binds one via use_key).

    Prefer this for single-shot gens so we never double next_key().
    """
    from xai_keys import get_api_key
    return get_api_key()


def _fresh_media_key() -> str:
    """New media key for parallel workers (ThreadPool has no ContextVar)."""
    from xai_keys import next_key
    return next_key()


def _generate_character_xai(a, prompt: str, image_url=None, image_urls=None, api_key=None):
    refs = []
    if image_urls:
        refs = [u for u in image_urls if u]
    elif image_url:
        refs = [image_url]
    p = (prompt or "").rstrip()
    kw = {"aspect_ratio": "1:1", "force_aspect": True, "exact_prompt": True, "api_key": api_key}
    if len(refs) > 1:
        return a.generate_image_xai(p, image_urls=refs, **kw)
    if refs:
        return a.generate_image_xai(p, refs[0], **kw)
    return a.generate_image_xai(p, None, **kw)


# ── Studio ────────────────────────────────────────────────────

def _photo_source_images(payload: dict) -> list:
    """Normalize 0–N reference images for Percfect Pictures generate/batch."""
    source_image = payload.get("source_image")
    source_images = payload.get("source_images") or []
    if isinstance(source_images, str):
        source_images = [source_images]
    source_images = [u for u in source_images if u]
    if not source_images and source_image:
        source_images = [source_image]
    try:
        from credit_wallet import MAX_REFERENCE_PHOTOS
        max_n = int(MAX_REFERENCE_PHOTOS)
    except Exception:
        max_n = 3
    return source_images[:max_n]


def _generate_photo_xai(a, full_prompt: str, refs: list, aspect_ratio: str = "auto", api_key: str = None, exact: bool = False):
    # Photos size chip → Imagine aspect_ratio field (not prompt text)
    ar = (aspect_ratio or "auto").strip() or "auto"
    kw = {"aspect_ratio": ar, "api_key": api_key}
    if exact:
        kw["exact_prompt"] = True  # Card Studio: Nick's prompt goes out word for word
    if not refs:
        return a.generate_image_xai(full_prompt, None, **kw)
    if len(refs) == 1:
        return a.generate_image_xai(full_prompt, refs[0], **kw)
    return a.generate_image_xai(full_prompt, image_urls=refs, **kw)


@register("image")
def handle_image(user_id: int, payload: dict) -> dict:
    a = _app()
    full_prompt = payload["full_prompt"]
    refs = _photo_source_images(payload)
    is_admin = bool(payload.get("is_admin"))
    aspect_ratio = payload.get("aspect_ratio") or "auto"

    res = a.supabase.table("users").select("picture_credits,video_credits,images_today").eq("id", user_id).single().execute()
    user_data = res.data or {}

    # Explicit key for the HTTP call. Prefer get_api_key() so we reuse the key
    # already bound by studio_jobs (use_key(next_key())) — do NOT call next_key()
    # again here or we double-advance the round-robin and skip a media key.
    import time as _time
    t0 = _time.time()
    result = _generate_photo_xai(
        a, full_prompt, refs, aspect_ratio=aspect_ratio, api_key=_job_media_key(),
        exact=bool(payload.get("exact_prompt")),
    )
    t_xai = _time.time() - t0
    data = (result or {}).get("data") or []
    image_url = data[0].get("url") if data else None
    if not image_url:
        raise Exception(
            "No image was returned — this usually means the prompt was filtered. "
            "You were NOT charged a credit. Try rephrasing your prompt."
        )

    t1 = _time.time()
    image_url = a._persist_image(image_url)
    t_persist = _time.time() - t1
    try:
        log = getattr(a, "app", None)
        log = getattr(log, "logger", None) or getattr(a, "logger", None)
        if log:
            log.info(
                "handle_image timing user=%s refs=%s xai=%.1fs persist=%.1fs total=%.1fs",
                user_id, len(refs or []), t_xai, t_persist, _time.time() - t0,
            )
    except Exception:
        pass

    try:
        from credit_wallet import photo_generate_cost
        cost = int(payload.get("cost") or photo_generate_cost(len(refs)))
    except Exception:
        cost = 1
    if not is_admin:
        if not a._apply_spend(user_id, user_data, cost, {"images_today": int(user_data.get("images_today") or 0) + 1}):
            raise Exception("No credits remaining. Buy credits or redeem a coupon.")

    a.supabase.table("generations").insert({
        "user_id": user_id,
        "type": "image",
        "prompt": full_prompt,
        "output_url": image_url,
        "created_at": datetime.datetime.utcnow().isoformat(),
    }).execute()

    return {"url": image_url, "type": "image", "charged": cost}


@register("batch")
def handle_batch(user_id: int, payload: dict) -> dict:
    """Batch of N images — true multi-key parallel (one key per in-flight image).

    ThreadPoolExecutor workers do NOT inherit the job's ContextVar key, so each
    wave image must call next_key() itself. That is intentional (not double-burn
    of the same request) — only the single unused job-bound key is skipped.
    """
    a = _app()
    batch_n = max(1, min(10, int(payload.get("batch_n") or 10)))
    full_prompt = payload["full_prompt"]
    refs = _photo_source_images(payload)
    is_admin = bool(payload.get("is_admin"))
    aspect_ratio = payload.get("aspect_ratio") or "auto"

    res = a.supabase.table("users").select("picture_credits,video_credits,images_today").eq("id", user_id).single().execute()
    user_data = res.data or {}

    from xai_keys import load_xai_keys, next_key

    pool = load_xai_keys()
    # Full parallel: one worker per image, up to key pool size (15 keys → batch 10 in 1 wave)
    workers = max(1, min(batch_n, len(pool) if pool else 1))

    urls = []

    def _one(_i):
        try:
            key = next_key()
            r = _generate_photo_xai(
                a, full_prompt, refs, aspect_ratio=aspect_ratio, api_key=key
            )
            data = (r or {}).get("data") or []
            u = data[0].get("url") if data else None
            return a._persist_image(u) if u else None
        except Exception as exc:
            try:
                log = getattr(getattr(a, "app", None), "logger", None) or getattr(a, "logger", None)
                if log:
                    log.warning("batch image %s failed: %s", _i, exc)
            except Exception:
                pass
            return None

    # Wave-based fill. Allow a couple empty waves — transient key/filter flops
    # should not kill ×5 after one bad concurrent wave.
    remaining = batch_n
    attempts = 0
    max_attempts = batch_n * 4
    empty_waves = 0
    while remaining > 0 and attempts < max_attempts:
        wave = min(workers, remaining, max_attempts - attempts)
        if wave <= 0:
            break
        attempts += wave
        got = 0
        with ThreadPoolExecutor(max_workers=wave) as ex:
            for u in ex.map(_one, range(wave)):
                if u:
                    urls.append(u)
                    got += 1
                    remaining = batch_n - len(urls)
                    if remaining <= 0:
                        break
        if len(urls) >= batch_n:
            break
        if got == 0:
            empty_waves += 1
            if empty_waves >= 2 and not urls:
                break
            if empty_waves >= 3:
                break
        else:
            empty_waves = 0

    urls = urls[:batch_n]
    made = len(urls)
    if made and not is_admin:
        a._apply_spend(user_id, user_data, made, {"images_today": int(user_data.get("images_today") or 0) + made})

    now = datetime.datetime.utcnow().isoformat()
    for u in urls:
        try:
            a.supabase.table("generations").insert({
                "user_id": user_id, "type": "image",
                "prompt": full_prompt, "output_url": u, "created_at": now,
            }).execute()
        except Exception:
            pass

    if not made:
        raise Exception("None of the batch images generated — the prompt may have been filtered. You were NOT charged.")
    return {"urls": urls, "made": made, "failed": batch_n - made, "charged": made, "type": "batch"}


@register("video")
def handle_video(user_id: int, payload: dict) -> dict:
    a = _app()
    prompt = payload["prompt"]
    image_url = payload.get("image_url")
    reference_images = payload.get("reference_images") or None
    if isinstance(reference_images, list):
        reference_images = [u for u in reference_images if u]
        if len(reference_images) < 2:
            # 0–1 dense list → single image path
            if reference_images and not image_url:
                image_url = reference_images[0]
            reference_images = None
    else:
        reference_images = None
    duration = int(payload.get("duration") or 6)
    cost = int(payload.get("cost") or a.video_cost(duration))
    is_admin = bool(payload.get("is_admin"))
    model = (payload.get("model") or "grok").strip().lower()

    res = a.supabase.table("users").select("picture_credits,video_credits,videos_today").eq("id", user_id).single().execute()
    user_data = res.data or {}

    used_model = "grok-imagine-video"
    if model in ("wan-2.2", "wan", "wan2.2", "12.2"):
        # Replicate WAN 2.2 (NOT fal) — Videos page under Extend only
        # Duration forced to 200s — no other choice (Nick)
        import replicate_wan
        if not replicate_wan.is_configured():
            raise Exception(
                "REPLICATE_API_TOKEN not configured — set the Replicate key for WAN 2.2."
            )
        duration = int(getattr(replicate_wan, "WAN_DURATION_SEC", 200) or 200)
        cost = int(payload.get("cost") or a.video_cost(duration))
        # WAN path: first ref only (no multi-ref API)
        wan_img = image_url or ((reference_images or [None])[0])
        result = replicate_wan.generate_video_wan_replicate(
            prompt, image_url=wan_img, duration=duration
        )
        video_url = (result.get("video") or {}).get("url") or result.get("url")
        used_model = "wan-2.2"
    else:
        # 2+ refs → xAI reference-to-video; 0–1 → text / image-to-video
        result = a.generate_video_xai(
            prompt,
            image_url=image_url,
            duration=duration,
            api_key=_job_media_key(),
            reference_images=reference_images,
        )
        video_url = (result.get("video") or {}).get("url") \
            or result.get("url") \
            or (result.get("data") or [{}])[0].get("url")
        if reference_images:
            used_model = "grok-imagine-video-ref"
    if not video_url:
        raise Exception("Video generator returned no URL.")
    video_url = a._persist_video(video_url)

    if not is_admin:
        if not a._apply_spend(user_id, user_data, cost, {"videos_today": int(user_data.get("videos_today") or 0) + 1}):
            raise Exception("Not enough credits for this video length.")

    import video_chains as vc

    # Fresh generate = new chain. Re-roll / last-frame pass chain_id or continue_chain.
    if payload.get("chain_id") or payload.get("source_id") or payload.get("continue_chain"):
        chain_id = vc.resolve_video_chain_id(
            a.supabase,
            user_id,
            chain_id=payload.get("chain_id"),
            source_id=payload.get("source_id"),
            video_url=payload.get("source_video_url"),
        )
    else:
        chain_id = vc.new_video_chain_id()
    saved = vc.insert_video_generation(
        a.supabase, user_id, prompt, video_url, chain_id=chain_id,
    )

    out = {
        "url": video_url,
        "type": "video",
        "charged": cost,
        "model": used_model,
        "chain_id": saved.get("chain_id") or chain_id,
        "generation_id": saved.get("id"),
    }
    return out


@register("extend")
def handle_extend(user_id: int, payload: dict) -> dict:
    a = _app()
    prompt = payload["prompt"]
    video_url = payload["video_url"]
    secs = int(payload.get("secs") or a.EXTEND_SECONDS)
    # Extend rate is separate from base gen (Nick: 6 cr/s → +6s = 36)
    try:
        from credit_wallet import extend_video_cost
        cost = int(payload.get("cost") or extend_video_cost(secs))
    except Exception:
        cost = int(payload.get("cost") or a.video_cost(secs))
    is_admin = bool(payload.get("is_admin"))

    res = a.supabase.table("users").select("picture_credits,video_credits,videos_today").eq("id", user_id).single().execute()
    user_data = res.data or {}

    result = a.extend_video_xai(prompt, video_url, secs, api_key=_job_media_key())
    new_url = (result.get("video") or {}).get("url") \
        or result.get("url") \
        or (result.get("data") or [{}])[0].get("url")
    if not new_url:
        raise Exception("no video url returned")
    new_url = a._persist_video(new_url)

    if not is_admin:
        if not a._apply_spend(user_id, user_data, cost, {"videos_today": int(user_data.get("videos_today") or 0) + 1}):
            raise Exception("Not enough credits to extend this video.")

    import video_chains as vc

    chain_id = vc.resolve_video_chain_id(
        a.supabase,
        user_id,
        chain_id=payload.get("chain_id"),
        source_id=payload.get("source_id"),
        video_url=video_url,
    )
    saved = vc.insert_video_generation(
        a.supabase,
        user_id,
        f"[+{secs}s extend] {prompt}",
        new_url,
        chain_id=chain_id,
    )

    return {
        "url": new_url,
        "type": "video",
        "extended": True,
        "charged": cost,
        "chain_id": saved.get("chain_id") or chain_id,
        "generation_id": saved.get("id"),
    }


@register("arena")
def handle_arena(user_id: int, payload: dict) -> dict:
    a = _app()
    prompt = payload["prompt"]
    composite = payload["composite"]
    duration = int(payload.get("duration") or 6)
    cost = int(payload.get("cost") or a.video_cost(duration))
    is_admin = bool(payload.get("is_admin"))
    # Battle Cards: tickets charged at enqueue; cost is 0 credits
    is_battle = (payload.get("source") or "") == "battle_cards"

    res = a.supabase.table("users").select("picture_credits,video_credits,videos_today").eq("id", user_id).single().execute()
    user_data = res.data or {}

    try:
        result = a.generate_video_xai(prompt, composite, duration, api_key=_job_media_key())
        video_url = (result.get("video") or {}).get("url") \
            or result.get("url") \
            or (result.get("data") or [{}])[0].get("url")
        video_url = a._persist_video(video_url)
    except Exception:
        # Battle entry tickets are charged up front: no fight video means they go back.
        if is_battle and not is_admin:
            try:
                a._grant_tickets(user_id, int(payload.get("ticket_cost") or 0), "battle entry refunded (video failed)")
            except Exception:
                pass
        raise

    if not is_admin and cost > 0:
        if not a._apply_spend(user_id, user_data, cost, {"videos_today": int(user_data.get("videos_today") or 0) + 1}):
            raise Exception(f"This needs {cost} credits — you don't have enough.")

    a.supabase.table("generations").insert({
        "user_id": user_id, "type": "video",
        "prompt": prompt, "output_url": video_url,
        "created_at": datetime.datetime.utcnow().isoformat(),
    }).execute()

    out = {"url": video_url, "charged": cost if not is_battle else 0}
    if is_battle:
        out["ticket_cost"] = int(payload.get("ticket_cost") or 0)
        win = int(payload.get("ticket_win") or 0)
        out["ticket_win"] = win
        out["winner_name"] = payload.get("winner_name")
        out["battle_mode"] = payload.get("battle_mode")
        out["winner_char_id"] = payload.get("winner_char_id")
        out["loser_char_id"] = payload.get("loser_char_id")
        msgs = []
        if win > 0 and not is_admin:
            try:
                new_tix = a._grant_tickets(user_id, win, "battle win")
                out["tickets"] = new_tix
                msgs.append(f"+{win} tickets")
            except Exception:
                pass
        # Lost while fighting a higher level: half the entry back (handoff 4.5).
        refund = int(payload.get("ticket_refund") or 0)
        if refund > 0 and not is_admin:
            try:
                out["tickets"] = a._grant_tickets(user_id, refund, "battle refund (fought up)")
                msgs.append(f"+{refund} tickets back for fighting up")
            except Exception:
                pass
        # Card XP / levels — abilities unlock at 1, 2, 3, 4
        progress_notes = []
        try:
            for award in payload.get("xp_awards") or []:
                prog = a._award_card_xp(user_id, award["char_id"], int(award["xp"]))
                if prog:
                    out.setdefault("progress", {})[str(award["char_id"])] = dict(prog, gained=int(award["xp"]))
                    progress_notes.append(f"Lv{prog.get('level')} · +{int(award['xp'])} XP")
        except Exception:
            pass
        try:
            wcid = payload.get("winner_char_id")
            lcid = payload.get("loser_char_id")
            wxp = int(payload.get("card_xp_win") or 0)
            lxp = int(payload.get("card_xp_loss") or 0)
            if wcid and wxp:
                prog = a._award_card_xp(user_id, wcid, wxp)
                if prog:
                    out["winner_progress"] = prog
                    unlocked = prog.get("unlocked_count") or 0
                    progress_notes.append(
                        f"Lv{prog.get('level')} · +{wxp} XP · {unlocked}/4 abilities"
                    )
            if lcid and lxp and str(lcid) != str(wcid):
                prog = a._award_card_xp(user_id, lcid, lxp)
                if prog:
                    out["loser_progress"] = prog
                    progress_notes.append(
                        f"loser Lv{prog.get('level')} · +{lxp} XP"
                    )
        except Exception:
            pass
        wname = payload.get("winner_name") or "card"
        if payload.get("dice_line"):
            wname = f"{wname} ({payload['dice_line']})"
        if msgs or progress_notes:
            out["message"] = f"Winner: {wname}" + (
                " · " + " · ".join(msgs + progress_notes) if (msgs or progress_notes) else ""
            )
        else:
            out["message"] = f"Winner: {wname}"
    if payload.get("lewd_pick"):
        out["lewd_pick"] = payload["lewd_pick"]
    return out


def _motion_extract_seed_urls(a, user_id: int, char_video_url: str) -> list:
    """Download extract plate → up to 3 face-first white-card seed URLs."""
    import tempfile
    import uuid
    from pathlib import Path

    import requests

    import motion_extract_assets as mea

    tmp = Path(tempfile.mkdtemp(prefix="motion_char_seed_"))
    vid_path = tmp / "character.mp4"
    r = requests.get(char_video_url, timeout=180)
    r.raise_for_status()
    vid_path.write_bytes(r.content)

    try:
        if hasattr(mea, "character_seed_triple_pngs"):
            seed_blobs = mea.character_seed_triple_pngs(str(vid_path))
        else:
            seed_blobs = [mea.character_seed_jpeg(str(vid_path))]
    except Exception as e:
        raise Exception(f"Could not pull seed frames from character extract: {e}") from e

    seed_urls = []
    for i, seed_bytes in enumerate(seed_blobs):
        is_png = seed_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        ext = "png" if is_png else "jpg"
        ctype = "image/png" if is_png else "image/jpeg"
        seed_path = f"motion_seed/{user_id}_{uuid.uuid4().hex}_{i}.{ext}"
        a.supabase.storage.from_("previews").upload(
            seed_path, seed_bytes,
            file_options={"content-type": ctype, "upsert": "true"},
        )
        seed_urls.append(f"{a.SUPABASE_URL}/storage/v1/object/public/previews/{seed_path}")
    if not seed_urls:
        raise Exception("No seed frames produced from extract.")
    return seed_urls


@register("motion_build_character_preview")
def handle_motion_build_character_preview(user_id: int, payload: dict) -> dict:
    """Step 1 only: extract seeds → front photo (Character generate-one).

    Costs 1 credit (same as Character page first shot). Does NOT build sides/back/360
    and does NOT save to roster — user must approve before the 50-credit pack.
    """
    from credit_wallet import credit_balance

    a = _app()
    is_admin = bool(payload.get("is_admin"))
    char_video_url = payload.get("character_video")
    name = (payload.get("name") or "Motion Character")[:80]
    gender = payload.get("gender") or ""
    preview_cost = 1

    if not char_video_url:
        raise Exception("Missing character extract video.")

    res = a.supabase.table("users").select(
        "picture_credits,video_credits,images_today"
    ).eq("id", user_id).single().execute()
    u = res.data or {}
    bal = credit_balance(u)
    if not is_admin and bal < preview_cost:
        raise Exception(f"First photo needs {preview_cost} credit — you have {bal}.")

    # Rehost extract if still on ephemeral analyzer disk
    try:
        if hasattr(a, "_rehost_motion_asset") and "/outputs/" in str(char_video_url):
            char_video_url = a._rehost_motion_asset(char_video_url, kind="video")
    except Exception:
        pass

    seed_urls = _motion_extract_seed_urls(a, user_id, char_video_url)

    # Charge 1 credit like Character generate-one (is_admin=False)
    try:
        one = handle_character_one(user_id, {
            "source_image": seed_urls[0],
            "source_images": seed_urls,
            "description": "",
            "gender": gender,
            "is_admin": is_admin,
        })
    except Exception as e:
        raise Exception(
            f"First photo failed: {e}. You were NOT charged."
        ) from e

    return {
        "ok": True,
        "step": "preview",
        "url": one["url"],
        "prompt": one.get("prompt") or "",
        "seed_url": seed_urls[0],
        "seed_urls": seed_urls,
        "name": name,
        "gender": gender,
        "source": "motion_extract",
        "source_mode": "upload",
        "type": "image",
        "charged": 0 if is_admin else preview_cost,
        "preview_cost": preview_cost,
        "pack_cost": int(getattr(a, "CHARACTER_PACK_CREDIT_COST", 50) or 50),
        "complete": False,
        "needs_approval": True,
        "message": "Review this front photo. Approve only if you like it — pack (sides + back + 360) is 50 credits.",
    }


@register("motion_build_character")
def handle_motion_build_character(user_id: int, payload: dict) -> dict:
    """Step 2: approved front → finalize (L/R/back) + 360 spin · 50 credits.

    Same Character finalize + spin handlers. Only runs after user liked the first photo.
    """
    from credit_wallet import credit_balance

    a = _app()
    is_admin = bool(payload.get("is_admin"))
    primary = (payload.get("primary_image_url") or payload.get("url") or "").strip()
    front_prompt = payload.get("prompt") or ""
    name = (payload.get("name") or "Motion Character")[:80]
    gender = payload.get("gender") or ""
    pack_cost = int(getattr(a, "CHARACTER_PACK_CREDIT_COST", 50) or 50)
    seed_urls = payload.get("seed_urls") or []
    seed_url = payload.get("seed_url") or (seed_urls[0] if seed_urls else "")

    if not primary:
        raise Exception("Approve a front photo first (missing primary_image_url).")

    res = a.supabase.table("users").select(
        "picture_credits,video_credits,images_today,videos_today"
    ).eq("id", user_id).single().execute()
    u = res.data or {}
    bal = credit_balance(u)
    if not is_admin and bal < pack_cost:
        raise Exception(
            f"Full pack (sides + back + 360) needs {pack_cost} credits — you have {bal}."
        )

    # ── Kick off the 360 spin video NOW, in parallel with the 3 angle photos ──
    # The xAI spin only needs the approved FRONT image (the 4 angles are just the
    # local-turntable fallback), and one is video while the other is photos, so
    # with the key pool there is zero reason to run them back-to-back. This
    # halves phase-2 wall time. char_id doesn't exist yet — attach after finalize.
    spin_image = primary
    if hasattr(a, "_public_image_url_for_xai"):
        spin_image = a._public_image_url_for_xai(primary)
    spin_duration = int(getattr(a, "CHARACTER_SPIN_DURATION_SEC", 6) or 6)

    def _early_spin() -> str:
        result = a.generate_video_xai(
            a.CHARACTER_SPIN_PROMPT, spin_image, spin_duration,
            api_key=_fresh_media_key(),
        )
        url = (result.get("video") or {}).get("url") \
            or result.get("url") \
            or (result.get("data") or [{}])[0].get("url")
        if not url:
            raise Exception(f"xAI returned no spin video URL: {str(result)[:300]}")
        return a._persist_video(url)

    spin_ex = ThreadPoolExecutor(max_workers=1)
    spin_fut = spin_ex.submit(_early_spin)

    # ── Finalize angles ──
    try:
        fin = handle_character_finalize(user_id, {
            "primary_image_url": primary,
            "prompt": front_prompt,
            "gender": gender,
            "name": name,
            "source_mode": "upload",
            "is_admin": True,  # pack billed once after spin
        })
    except Exception as e:
        spin_fut.cancel()
        spin_ex.shutdown(wait=False)
        raise Exception(
            f"Sides/back failed: {e}. You were NOT charged the pack."
        ) from e

    images = fin.get("images") or []
    char = fin.get("character") or {}
    char_id = char.get("id")
    if not char_id:
        raise Exception("Could not save character. You were NOT charged the pack.")
    if len(images) < 4:
        raise Exception(
            "Not all 4 angles generated. You were NOT charged the pack — try Approve again."
            + (f" {fin.get('warning')}" if fin.get("warning") else "")
        )

    # ── 360 spin: collect the parallel render started before the angles ──
    video_url = None
    spin_error = None
    try:
        video_url = spin_fut.result()
        # Attach to the just-created character (what handle_spin would have done)
        try:
            a.supabase.table("characters").update({
                "spin_video_url": video_url,
            }).eq("id", char_id).execute()
            a.supabase.table("generations").insert({
                "user_id": user_id, "type": "video",
                "prompt": a.CHARACTER_SPIN_PROMPT, "output_url": video_url,
                "created_at": datetime.datetime.utcnow().isoformat(),
            }).execute()
        except Exception:
            pass
    except Exception as e:
        spin_error = str(e)
    finally:
        spin_ex.shutdown(wait=False)

    if not video_url:
        # Parallel render failed (often moderation) — handle_spin has the full
        # rescue path: soft re-prompt on moderation + local 4-angle turntable
        try:
            spin = handle_spin(user_id, {"char_id": char_id, "is_admin": True})
            video_url = spin.get("url")
            if video_url:
                spin_error = None
            else:
                raise Exception("No spin video URL returned.")
        except Exception as e:
            spin_error = f"{spin_error + ' · ' if spin_error else ''}{e}"

    charged = 0
    if video_url and not is_admin:
        res2 = a.supabase.table("users").select(
            "picture_credits,video_credits,images_today,videos_today"
        ).eq("id", user_id).single().execute()
        u2 = res2.data or u
        if a._apply_spend(user_id, u2, pack_cost, {
            "images_today": int(u2.get("images_today") or 0) + 4,
            "videos_today": int(u2.get("videos_today") or 0) + 1,
        }):
            charged = pack_cost
        else:
            spin_error = (
                (spin_error + " · " if spin_error else "")
                + f"Wallet short of {pack_cost} credits at charge time."
            )

    cres = a.supabase.table("characters").select("*").eq("id", char_id).maybe_single().execute()
    final_char = (cres.data if cres else None) or char
    if video_url and isinstance(final_char, dict):
        final_char = {**final_char, "spin_video_url": video_url, "images": images}

    out = {
        "ok": True,
        "step": "pack",
        "character": a._serialize_character(final_char) if final_char else char,
        "images": images,
        "url": (final_char or {}).get("primary_image_url") or primary,
        "spin_video_url": video_url,
        "seed_url": seed_url,
        "seed_urls": seed_urls or ([seed_url] if seed_url else []),
        "prompt": front_prompt,
        "source": "motion_extract",
        "source_mode": "upload",
        "type": "character",
        "charged": charged,
        "pack_cost": pack_cost,
        "download_url": f"/studios/percfectcharacter/download/{char_id}",
        "complete": bool(video_url) and (is_admin or charged == pack_cost),
        "needs_approval": False,
        "engine": {
            "front": "approved_preview",
            "angles": "character_finalize",
            "spin": "spin",
        },
    }
    if spin_error or not video_url:
        out["warning"] = (
            f"Angles saved, but 360° spin failed"
            + (f" ({spin_error})" if spin_error else "")
            + ". Pack not fully charged — finish 360 from Characters."
        )
        out["complete"] = False
    return out


@register("motion_save_background")
def handle_motion_save_background(user_id: int, payload: dict) -> dict:
    """BG extract plate → photo-system fill-in-the-blanks → library Backgrounds + Arena.

    Same image pipeline as Studio (generate_image_xai edit). Saves a generation row
    tagged \"Motion filled background: …\" so /api/my-library lists it under Backgrounds
    and Arena can drag it in from the sidebar.
    """
    import datetime
    import tempfile
    import uuid
    from pathlib import Path

    import requests

    import motion_extract_assets as mea
    from credit_wallet import credit_balance

    a = _app()
    is_admin = bool(payload.get("is_admin"))
    bg_url = payload.get("background_video")
    label = (payload.get("label") or "Motion scene")[:80]

    if not bg_url:
        raise Exception("Missing background extract video.")

    res = a.supabase.table("users").select(
        "picture_credits,video_credits,images_today"
    ).eq("id", user_id).single().execute()
    u = res.data or {}
    bal = credit_balance(u)
    if not is_admin and bal < 1:
        raise Exception("Filling a background needs 1 credit.")

    import time as _time

    t0 = _time.time()
    tmp = Path(tempfile.mkdtemp(prefix="motion_bg_still_"))
    vid_path = tmp / "background.mp4"
    # Same speed bar as Photos: don't hang 180s downloading plate video
    r = requests.get(bg_url, timeout=45, stream=True)
    r.raise_for_status()
    with open(vid_path, "wb") as vf:
        for chunk in r.iter_content(chunk_size=256 * 1024):
            if chunk:
                vf.write(chunk)
    t_dl = _time.time() - t0

    # 3 stills from start / mid / end (best scene in each third; best-first order)
    t1 = _time.time()
    try:
        if hasattr(mea, "background_seed_triple_jpegs"):
            seed_blobs = mea.background_seed_triple_jpegs(str(vid_path))
        elif hasattr(mea, "background_seed_jpeg"):
            seed_blobs = [mea.background_seed_jpeg(str(vid_path))]
        else:
            seed_blobs = [mea.background_still_jpeg(str(vid_path))]
    except Exception as e:
        raise Exception(f"Could not pull background stills from the extract: {e}") from e
    t_still = _time.time() - t1

    seed_urls = []
    for i, jpeg in enumerate(seed_blobs):
        seed_path = f"motion_bg_seed/{user_id}_{uuid.uuid4().hex}_{i}.jpg"
        a.supabase.storage.from_("previews").upload(
            seed_path, jpeg,
            file_options={"content-type": "image/jpeg", "upsert": "true"},
        )
        seed_urls.append(f"{a.SUPABASE_URL}/storage/v1/object/public/previews/{seed_path}")

    seed_url = seed_urls[0]
    fill_prompt = getattr(a, "MOTION_BG_FILL_PROMPT", None) or (
        "Fill in the blanks: reconstruct missing areas, black holes, and cutouts where "
        "people were removed. Complete empty background, no people, match original scene."
    )
    try:
        # GO image path: same as Photos — job media key + fail-fast generate_image_xai
        mk = _job_media_key()
        t2 = _time.time()
        if len(seed_urls) > 1:
            filled_raw = a.generate_image_xai(
                fill_prompt, image_urls=seed_urls, aspect_ratio="1:1", api_key=mk,
            )["data"][0]["url"]
        else:
            filled_raw = a.generate_image_xai(
                fill_prompt, seed_url, api_key=mk,
            )["data"][0]["url"]
        t_xai = _time.time() - t2
        t3 = _time.time()
        image_url = a._persist_image(filled_raw)
        t_persist = _time.time() - t3
        try:
            log = getattr(getattr(a, "app", None), "logger", None) or getattr(a, "logger", None)
            if log:
                log.info(
                    "motion_save_background timing user=%s seeds=%s dl=%.1fs still=%.1fs xai=%.1fs persist=%.1fs total=%.1fs",
                    user_id, len(seed_urls), t_dl, t_still, t_xai, t_persist, _time.time() - t0,
                )
        except Exception:
            pass
    except Exception as e:
        raise Exception(
            f"Background fill failed: {e}. You were NOT charged."
        ) from e

    if not is_admin:
        if not a._apply_spend(user_id, u, 1, {
            "images_today": int(u.get("images_today") or 0) + 1,
        }):
            raise Exception("No credits remaining. Buy credits or redeem a coupon.")

    # Library tag — must start with this so Backgrounds tab + Arena pick it up
    lib_prompt = f"Motion filled background: {label}"
    try:
        a.supabase.table("generations").insert({
            "user_id": user_id, "type": "image",
            "prompt": lib_prompt,
            "output_url": image_url,
            "created_at": datetime.datetime.utcnow().isoformat(),
        }).execute()
    except Exception:
        pass

    return {
        "url": image_url,
        "type": "image",
        "kind": "background",
        "charged": 0 if is_admin else 1,
        "arena_ready": True,
        "label": label,
        "library": "backgrounds",
        "seed_url": seed_url,
        "seed_urls": seed_urls,
        "refs": len(seed_urls),
        "message": "Background filled and saved to your library · drag onto Arena as backdrop.",
    }


@register("motion_retarget")
def handle_motion_retarget(user_id: int, payload: dict) -> dict:
    """Roster characters mimic an uploaded performance (CPU skeletal retarget).

    Hardened: rehosts analyzer assets if still on ephemeral /outputs, never dies
    on missing character motion_profile, clear errors for every failure stage.
    """
    import tempfile
    from pathlib import Path

    import requests

    import motion_retarget as mr

    a = _app()
    is_admin = bool(payload.get("is_admin"))
    cost = int(payload.get("cost") or 6)
    characters = payload.get("characters") or []
    bg_url = payload.get("background_video")
    md1_url = payload.get("motion_data")
    md2_url = payload.get("motion_data_2")
    duration_sec = float(payload.get("duration_sec") or 6)

    if not characters or not bg_url or not md1_url:
        raise Exception("Missing character or analysis outputs for retarget. Run Analyze first.")

    res = a.supabase.table("users").select(
        "picture_credits,video_credits,videos_today"
    ).eq("id", user_id).single().execute()
    user_data = res.data or {}
    if not is_admin and a._user_credits(user_data) < cost:
        raise Exception(f"Retarget needs {cost} credits — you have {a._user_credits(user_data)}.")

    # Rehost still-ephemeral analyzer URLs before download (belt + suspenders)
    try:
        if hasattr(a, "_rehost_motion_asset"):
            if bg_url and "/outputs/" in str(bg_url):
                bg_url = a._rehost_motion_asset(bg_url, kind="video")
            if md1_url and "/outputs/" in str(md1_url):
                md1_url = a._rehost_motion_asset(md1_url, kind="json")
            if md2_url and "/outputs/" in str(md2_url):
                md2_url = a._rehost_motion_asset(md2_url, kind="json")
    except Exception:
        pass

    tmp = Path(tempfile.mkdtemp(prefix="motion_retarget_job_"))

    def _dl(url: str, name: str) -> Path:
        if not url:
            raise Exception(f"Missing URL for {name}. Re-run extract.")
        try:
            r = requests.get(url, timeout=180)
        except Exception as e:
            raise Exception(
                f"Could not download {name} ({e}). Re-run Analyze, then overlay."
            ) from e
        if r.status_code == 404:
            raise Exception(
                f"{name} expired (404). Re-run Analyze on Motion, then overlay again."
            )
        if not r.ok:
            raise Exception(f"Could not download {name} (HTTP {r.status_code}). Re-run extract.")
        p = tmp / name
        p.write_bytes(r.content)
        if p.stat().st_size < 64:
            raise Exception(f"{name} download was empty. Re-run extract.")
        return p

    bg_path = _dl(bg_url, "background.mp4")
    try:
        md1_raw = requests.get(md1_url, timeout=120)
    except Exception as e:
        raise Exception(f"Could not download motion track ({e}). Re-run extract.") from e
    if md1_raw.status_code == 404:
        raise Exception("Motion JSON expired (404). Re-run Analyze, then overlay.")
    if not md1_raw.ok:
        raise Exception(f"Motion JSON download failed (HTTP {md1_raw.status_code}).")
    try:
        track1 = md1_raw.json()
    except Exception as e:
        raise Exception(f"Motion JSON invalid: {e}") from e
    if not isinstance(track1, list):
        track1 = (track1 or {}).get("frames") or (track1 or {}).get("motion") or []
    if not track1:
        raise Exception("Motion track is empty — re-run extract.")
    tracks = [track1]

    want_dual = len(characters) >= 2 and bool(md2_url)
    if want_dual:
        try:
            md2_raw = requests.get(md2_url, timeout=120)
            if md2_raw.ok:
                track2 = md2_raw.json()
                if not isinstance(track2, list):
                    track2 = (track2 or {}).get("frames") or (track2 or {}).get("motion") or []
                if track2:
                    tracks.append(track2)
                else:
                    want_dual = False
            else:
                want_dual = False
        except Exception:
            want_dual = False
        if want_dual:
            ids = [str(c.get("id")) for c in characters[:2]]
            if len(ids) < 2 or ids[0] == ids[1]:
                # Soft fall back to first character only
                characters = characters[:1]
                tracks = tracks[:1]
                want_dual = False

    n_tracks = len(tracks)
    char_slice = characters[:n_tracks]
    cutouts = []
    profiles = []
    char_images = []
    for ch in char_slice:
        imgs = ch.get("images") or []
        url = None
        for candidate in list(imgs) + [ch.get("primary_image_url")]:
            if candidate:
                url = candidate
                break
        if not url:
            raise Exception(f"Character {ch.get('name') or ch.get('id')} has no image on file.")
        try:
            im = a._load_image_any(url)
        except Exception as e:
            # Try primary if images[0] was broken
            alt = ch.get("primary_image_url")
            if alt and alt != url:
                try:
                    im = a._load_image_any(alt)
                except Exception:
                    raise Exception(
                        f"Could not load character image for {ch.get('name') or ch.get('id')}: {e}"
                    ) from e
            else:
                raise Exception(
                    f"Could not load character image for {ch.get('name') or ch.get('id')}: {e}"
                ) from e
        char_images.append(im.convert("RGB"))
        # Pose optional — defaults always work (not why overlay failed before)
        profile = None
        try:
            profile = mr.analyze_character_image(im)
        except Exception:
            profile = None
        if not profile or not isinstance(profile, dict):
            profile = ch.get("motion_profile") if isinstance(ch.get("motion_profile"), dict) else None
        if not profile or not profile.get("anchor"):
            profile = mr.default_profile()
        profiles.append(profile)
        cutouts.append(im)
    if not cutouts:
        raise Exception("No character shots to analyze for overlay.")

    fps = payload.get("fps")
    try:
        fps_f = float(fps) if fps not in (None, "", "null") else None
    except (TypeError, ValueError):
        fps_f = None

    try:
        video_bytes = mr.retarget_video(
            str(bg_path),
            tracks[: len(cutouts)],
            cutouts,
            profiles,
            fps_override=fps_f,
            max_frames=900,
            key_out_white=getattr(a, "_key_out_white", None),
            character_images=char_images,
        )
    except Exception as e:
        raise Exception(f"Skeletal overlay failed: {e}") from e
    if not video_bytes or len(video_bytes) < 500:
        raise Exception("Overlay produced an empty video — re-run Analyze with a clearer clip.")
    video_url = a._persist_video_bytes(video_bytes)

    charged = 0
    if not is_admin:
        if not a._apply_spend(
            user_id, user_data, cost,
            {"videos_today": int(user_data.get("videos_today") or 0) + 1},
        ):
            raise Exception(f"Retarget needs {cost} credits — you don't have enough.")
        charged = cost

    names = ", ".join((c.get("name") or "character") for c in char_slice)
    pose_src = ", ".join((p.get("source") or "?") for p in profiles) if profiles else "?"
    prompt = (
        f"Skeletal overlay: {names} on plate"
        + (f" (job {payload.get('analysis_job_id')})" if payload.get("analysis_job_id") else "")
        + f" · char pose={pose_src} · tracks={len(tracks)} · {duration_sec:.1f}s"
    )
    try:
        a.supabase.table("generations").insert({
            "user_id": user_id, "type": "video",
            "prompt": prompt, "output_url": video_url,
            "created_at": datetime.datetime.utcnow().isoformat(),
        }).execute()
    except Exception:
        pass

    return {
        "url": video_url,
        "charged": charged,
        "mode": "retarget",
        "type": "video",
        "tracks": len(tracks),
        "characters": len(char_slice),
        "pose_sources": [p.get("source") for p in profiles],
        "overlay_engine": "percfect_overlay_v2",
    }


@register("spin")
def handle_spin(user_id: int, payload: dict) -> dict:
    import os

    from credit_wallet import credit_balance

    a = _app()
    char_id = payload["char_id"]
    is_admin = bool(payload.get("is_admin"))
    pack_included = bool(payload.get("pack_included"))
    # Pack path already gated credits on the frontend (4+360) — skip second debit
    free_spin = is_admin or pack_included
    duration = int(payload.get("duration") or getattr(a, "CHARACTER_SPIN_DURATION_SEC", 6) or 6)
    cost = 0 if free_spin else int(payload.get("cost") or a.video_cost(duration))

    cres = (
        a.supabase.table("characters")
        .select("*")
        .eq("id", char_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    char = (cres.data or [None])[0]
    if not char:
        raise Exception("Character not found.")
    image_url = char.get("primary_image_url")
    if not image_url:
        raise Exception("This character has no image.")
    # Critical for pack flow: angles may leave relative /media or temp URLs
    if hasattr(a, "_public_image_url_for_xai"):
        image_url = a._public_image_url_for_xai(image_url)
    elif hasattr(a, "_persist_image"):
        image_url = a._persist_image(image_url)

    res = a.supabase.table("users").select(
        "picture_credits,video_credits,videos_today"
    ).eq("id", user_id).single().execute()
    user_data = res.data or {}
    bal = credit_balance(user_data)
    if not free_spin and bal < cost:
        raise Exception(f"360 spin needs {cost} credits — you have {bal}.")

    def _diy_spin_from_angles() -> str:
        """Local turntable from 4 ortho shots — works when xAI video is moderated."""
        imgs = char.get("images") or []
        if not isinstance(imgs, list):
            imgs = []
        urls = [u for u in imgs if isinstance(u, str) and u][:4]
        if len(urls) < 4 and image_url:
            # single primary only — still try 4 copies (flat spin) is worse; need 4
            pass
        if len(urls) < 4:
            raise Exception("Need 4 angle shots for local 360 fallback.")
        from percfect_spin_renderer import render_timeline_spin_from_images
        import requests
        from io import BytesIO
        from PIL import Image

        def _load(u: str) -> Image.Image:
            r = requests.get(u, timeout=90)
            r.raise_for_status()
            return Image.open(BytesIO(r.content)).convert("RGB")

        imgs = [_load(u) for u in urls]
        mp4 = render_timeline_spin_from_images(
            imgs, duration_sec=min(6.0, float(duration or 6))
        )
        if not mp4:
            raise Exception("Local spin renderer returned empty video.")
        return a._persist_video_bytes(mp4, content_type="video/mp4")

    video_url = None
    xai_err = None
    prefer_diy = (os.environ.get("CHARACTER_SPIN_DIY") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    if prefer_diy:
        try:
            video_url = _diy_spin_from_angles()
        except Exception as e:
            xai_err = f"DIY spin failed: {e}"

    if not video_url:
        # CRITICAL: pin spin to a FRESH media key — never reuse the job-bound photo key.
        # Pack flow (angles then spin) was burning the same key → rate-limit / silent fail
        # right after the 3-angle wave. 25-key pool: always take next_key() for video.
        key = _fresh_media_key()
        key_tail = (key or "")[-8:] if key else "?"
        result = None
        try:
            log = getattr(getattr(a, "app", None), "logger", None)
            if log:
                log.info(
                    "spin xAI start char=%s duration=%s key_tail=%s image=%s",
                    char_id, duration, key_tail, (image_url or "")[:120],
                )
        except Exception:
            pass
        try:
            result = a.generate_video_xai(
                a.CHARACTER_SPIN_PROMPT, image_url, duration, api_key=key
            )
        except Exception as e1:
            xai_err = str(e1)
            try:
                log = getattr(getattr(a, "app", None), "logger", None)
                if log:
                    log.error(
                        "spin xAI failed char=%s key_tail=%s err=%s",
                        char_id, key_tail, xai_err[:800],
                    )
            except Exception:
                pass
            # Soft re-prompt ONLY on moderation — other errors skip a full 2nd video wait
            msg1 = str(e1).lower()
            if any(k in msg1 for k in ("moderat", "rejected", "safety", "policy", "blocked")):
                soft = (
                    "Slow product turntable of the same stylized game character figure, "
                    "white studio backdrop, smooth 360 degree spin, character select UI style, "
                    "keep outfit and face identical to reference, no text."
                )
                # Second attempt also gets its own key (moderation is per-request, not key)
                key2 = _fresh_media_key()
                try:
                    result = a.generate_video_xai(soft, image_url, duration, api_key=key2)
                    xai_err = None
                except Exception as e2:
                    xai_err = str(e2) or str(e1)
                    try:
                        log = getattr(getattr(a, "app", None), "logger", None)
                        if log:
                            log.error(
                                "spin xAI soft-retry failed char=%s err=%s",
                                char_id, xai_err[:800],
                            )
                    except Exception:
                        pass
                    result = None
            else:
                result = None

        if result:
            video_url = (result.get("video") or {}).get("url") \
                or result.get("url") \
                or (result.get("data") or [{}])[0].get("url")
            if not video_url:
                out = result.get("output") or result.get("result") or {}
                if isinstance(out, dict):
                    video_url = (out.get("video") or {}).get("url") or out.get("url")
                if isinstance(out, list) and out:
                    video_url = (out[0] or {}).get("url") if isinstance(out[0], dict) else None
            if video_url:
                video_url = a._persist_video(video_url)
            else:
                xai_err = xai_err or f"xAI returned no video URL: {str(result)[:400]}"
                try:
                    log = getattr(getattr(a, "app", None), "logger", None)
                    if log:
                        log.error("spin empty result char=%s: %s", char_id, xai_err[:500])
                except Exception:
                    pass

    # After xAI moderation / failure, fall back to local 4-angle turntable
    if not video_url:
        try:
            video_url = _diy_spin_from_angles()
        except Exception as e:
            msg = xai_err or str(e)
            if msg and ("moderation" in msg.lower() or "rejected" in msg.lower()):
                raise Exception(
                    "360° was blocked by the video filter and local fallback also failed "
                    f"({e}). Your 4 angles are saved — Retry 360 from the roster. "
                    "You were NOT charged for the spin."
                ) from e
            raise Exception(
                f"360° spin failed: {msg}. Angles are saved — retry from roster. "
                "You were NOT charged for the spin."
            ) from e

    if not free_spin and cost > 0:
        if not a._apply_spend(
            user_id, user_data, cost,
            {"videos_today": int(user_data.get("videos_today") or 0) + 1},
        ):
            raise Exception("No credits remaining.")

    try:
        a.supabase.table("characters").update({
            "spin_video_url": video_url,
            "primary_image_url": image_url or char.get("primary_image_url"),
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }).eq("id", char_id).execute()
    except Exception:
        a.supabase.table("characters").update({
            "spin_video_url": video_url,
        }).eq("id", char_id).execute()

    try:
        a.supabase.table("generations").insert({
            "user_id": user_id, "type": "video",
            "prompt": a.CHARACTER_SPIN_PROMPT, "output_url": video_url,
            "created_at": datetime.datetime.utcnow().isoformat(),
        }).execute()
    except Exception:
        pass

    return {
        "url": video_url,
        "spin_video_url": video_url,
        "type": "video",
        "charged": cost,
        "download_url": f"/studios/percfectcharacter/download/{char_id}",
    }

@register("fight")
def handle_fight(user_id: int, payload: dict) -> dict:
    from credit_wallet import credit_balance

    a = _app()
    ids = payload.get("character_ids") or []
    is_admin = bool(payload.get("is_admin"))
    duration = 6
    cost = int(payload.get("cost") or a.video_cost(duration))

    res = a.supabase.table("users").select(
        "picture_credits,video_credits,videos_today,username"
    ).eq("id", user_id).single().execute()
    u = res.data or {}
    bal = credit_balance(u)
    if not is_admin and bal < cost:
        raise Exception(f"A fight needs {cost} credits — you have {bal}.")

    cres = a.supabase.table("characters").select("*").in_("id", ids).eq("user_id", user_id).execute()
    rows = {str(c["id"]): c for c in (cres.data or [])}
    primaries = [rows[i]["primary_image_url"] for i in ids if i in rows and rows[i].get("primary_image_url")]
    names = [(rows[i].get("name") or "Character") for i in ids if i in rows]
    if len(primaries) != 2:
        raise Exception("Couldn't load both characters.")

    composite = a.composite_characters(primaries)
    result = a.generate_video_xai(
        a.character_action_prompt("fight"), composite, duration, api_key=_job_media_key()
    )
    video_url = (result.get("video") or {}).get("url") or result.get("url") \
        or (result.get("data") or [{}])[0].get("url")
    if not video_url:
        raise Exception("The fight video didn't generate. You were NOT charged.")
    video_url = a._persist_video(video_url)

    if not is_admin:
        if not a._apply_spend(
            user_id, u, cost,
            {"videos_today": int(u.get("videos_today") or 0) + 1},
        ):
            raise Exception("No credits remaining.")

    row = a.supabase.table("chat_messages").insert({
        "user_id": user_id, "username": u.get("username") or "",
        "body": f"⚔️ {names[0]} vs {names[1]}!", "type": "fight", "media_url": video_url,
    }).execute()
    msg = (row.data or [{}])[0]
    return {"message": msg, "url": video_url, "type": "video", "charged": cost}

@register("api_video")
def handle_api_video(user_id: int, payload: dict) -> dict:
    from credit_wallet import credit_balance

    a = _app()
    prompt = payload["prompt"]
    image_url = payload.get("image_url")
    duration = int(payload.get("duration") or 6)
    cost = int(payload.get("cost") or a.video_cost(duration))

    res = a.supabase.table("users").select(
        "picture_credits,video_credits,videos_today"
    ).eq("id", user_id).single().execute()
    user = res.data or {}
    bal = credit_balance(user)
    if bal < cost:
        raise Exception(f"Not enough credits. You have {bal}, need {cost}.")

    result = a.generate_video_xai(prompt, image_url, duration, api_key=_job_media_key())
    video_url = (result.get("video") or {}).get("url") \
        or result.get("url") \
        or (result.get("data") or [{}])[0].get("url")
    video_url = a._persist_video(video_url)

    if not a._apply_spend(
        user_id, user, cost,
        {"videos_today": int(user.get("videos_today") or 0) + 1},
    ):
        raise Exception("No credits remaining.")

    a.supabase.table("generations").insert({
        "user_id": user_id, "type": "video",
        "prompt": prompt, "output_url": video_url,
        "created_at": datetime.datetime.utcnow().isoformat(),
    }).execute()

    return {"url": video_url, "type": "video", "charged": cost}

@register("api_image")
def handle_api_image(user_id: int, payload: dict) -> dict:
    a = _app()
    prompt = payload["prompt"]
    num_images = int(payload.get("num_images") or 10)

    urls = a.generate_image_fal(prompt, num_images)
    if not urls:
        raise Exception("No images returned from fal")

    now = datetime.datetime.utcnow().isoformat()
    for url in urls:
        a.supabase.table("generations").insert({
            "user_id": user_id, "type": "image",
            "prompt": prompt, "output_url": url, "created_at": now,
        }).execute()

    return {"urls": urls, "url": urls[0], "type": "image"}


# ── Characters ────────────────────────────────────────────────

@register("character_precision_seed")
def handle_character_precision_seed(user_id: int, payload: dict) -> dict:
    """Percfect Precision step 1: search picture of {name} → first usable rehosted seed.

    No credits charged here — step 2 (character_one super_accuracy) charges 5.
    """
    a = _app()
    description = (payload.get("description") or "").strip()
    if not description:
        raise Exception(
            "Percfect Precision needs the character name so we can search "
            "for a picture of it."
        )
    try:
        web_refs = a.find_picture_of_references(description, max_refs=5)
    except Exception as e:
        raise Exception(
            str(e)
            or "Percfect Precision search failed (looks for a picture of your name)."
        )
    if not web_refs:
        raise Exception(
            f'Percfect Precision could not find a picture of "{description[:80]}". '
            "Try a clearer name."
        )
    # First successfully rehosted still in search order (product contract)
    seed = web_refs[0]
    try:
        a.app.logger.info(
            "Precision seed chosen query=%r source=%s",
            (seed.get("search_query") or "")[:80],
            (seed.get("source_url") or "")[:160],
        )
    except Exception:
        pass
    return {
        "ok": True,
        "seed_image_url": seed.get("url"),
        "reference_image_url": seed.get("url"),
        "source_page_image": seed.get("source_url"),
        "search_query": seed.get("search_query") or f"A portrait of {description}",
        "type": "precision_seed",
        "charged": 0,
    }


@register("character_one")
def handle_character_one(user_id: int, payload: dict) -> dict:
    """Regular generate-one OR Percfect Precision web-seed rebuild.

    Regular: 1 credit flat (one ref free). Percfect Precision: 5 credits flat.
    Characters allow **one** reference photo only.
    """
    from credit_wallet import (
        PERCFECT_PRECISION_COST,
        character_generate_cost,
        credit_balance,
    )

    a = _app()
    is_admin = bool(payload.get("is_admin"))
    source_image = payload.get("source_image")
    source_images = payload.get("source_images") or []
    if isinstance(source_images, str):
        source_images = [source_images]
    # Characters product: hard cap 1 reference
    source_images = [u for u in source_images if u][:1]
    if not source_images and source_image:
        source_images = [source_image]
    source_images = source_images[:1]
    if source_images and not source_image:
        source_image = source_images[0]
    elif source_images:
        source_image = source_images[0]
    description = payload.get("description") or ""
    gender = payload.get("gender") or ""
    super_accuracy = bool(payload.get("super_accuracy"))
    n_refs = 0 if super_accuracy else len(source_images)
    # Server is source of truth — never trust client undercharge
    cost = character_generate_cost(n_refs, super_accuracy=super_accuracy)
    if super_accuracy:
        cost = int(PERCFECT_PRECISION_COST)

    res = a.supabase.table("users").select(
        "picture_credits,video_credits,images_today"
    ).eq("id", user_id).single().execute()
    u = res.data or {}
    bal = credit_balance(u)
    if not is_admin and bal < cost:
        raise Exception(
            f"{'Percfect Precision needs' if super_accuracy else 'You need'} {cost} "
            f"credit{'s' if cost != 1 else ''} — you have {bal}."
        )

    search_meta = None
    if super_accuracy:
        # Percfect Precision — prompt box is GOOGLE ONLY (a portrait of {name}).
        # xAI generate: DEFAULT one-ref character prompt + Google seed photo.
        # Backend ignores frontend prompt text for gen (empty desc to build_character_prompt).
        # Cost = 5 flat. No user upload.
        preseed = (payload.get("seed_image_url") or "").strip()
        # description may arrive empty on gen step (client should not send it); only
        # needed if we must re-search without a preseed.
        search_text = (description or "").strip()
        if preseed:
            web_refs = [{
                "url": preseed,
                "source_url": (payload.get("source_page_image") or "").strip() or preseed,
                "search_query": (payload.get("search_query") or "").strip()
                    or (f"A portrait of {search_text}" if search_text else "A portrait of"),
            }]
        else:
            if not search_text:
                raise Exception(
                    "Percfect Precision needs a name to search, or a seed photo already found."
                )
            try:
                web_refs = a.find_picture_of_references(search_text, max_refs=5)
            except Exception as e:
                raise Exception(
                    str(e)
                    or 'Percfect Precision search failed (looks for a portrait of your prompt). '
                       'Regular Generate still works.'
                )
            if not web_refs:
                raise Exception(
                    f'Percfect Precision could not find a portrait of "{search_text[:80]}". '
                    "Try a clearer name, or use regular Generate with your own photo."
                )

        # Identity from seed photo only — NEVER inject name or gender into xAI.
        prompt = getattr(a, "CHARACTER_SUPER_ACCURACY_PROMPT", None) or a.build_character_prompt(
            "", "", has_image=True, num_refs=1
        )

        last_err = None
        url = None
        mk = _job_media_key()
        for ref in web_refs:
            try:
                try:
                    a.app.logger.info(
                        "Precision xAI gen seed=%s query=%r",
                        (ref.get("source_url") or ref.get("url") or "")[:120],
                        (ref.get("search_query") or "")[:80],
                    )
                except Exception:
                    pass
                r = _generate_character_xai(a, prompt, image_url=ref.get("url"), api_key=mk)
                data = (r or {}).get("data") or []
                if not data or not data[0].get("url"):
                    raise Exception("xAI returned no image for this reference.")
                url = a._persist_image(data[0]["url"])
                search_meta = ref
                source_image = ref.get("url")
                break
            except Exception as e:
                last_err = e
                try:
                    a.app.logger.warning(
                        "super_accuracy gen failed on ref %s: %s",
                        (ref.get("source_url") or "")[:80], e,
                    )
                except Exception:
                    pass
                continue
        if not url:
            raise Exception(
                "Percfect Precision found web photos but could not rebuild from them. "
                + (str(last_err) if last_err else "Try a clearer name or photo.")
                + " Regular Generate still works without Percfect Precision."
            )
        source_images = []
        # Do not treat Description-box text as character description for Precision
        description = ""
    else:
        has_img = bool(source_image or source_images)
        n = len(source_images) if source_images else (1 if source_image else 0)
        # gender stored on character later — never in the image prompt
        prompt = a.build_character_prompt(description, "", has_img, num_refs=n)
        mk = _job_media_key()
        r = _generate_character_xai(
            a,
            prompt,
            image_url=source_image or (source_images[0] if source_images else None),
            api_key=mk,
        )
        data = (r or {}).get("data") or []
        if not data or not data[0].get("url"):
            raise Exception(
                "No image was returned — the prompt may have been filtered. "
                "You were NOT charged. Try rephrasing or attach a photo."
            )
        url = a._persist_image(data[0]["url"])

    if not is_admin:
        if not a._apply_spend(
            user_id, u, cost,
            {"images_today": int(u.get("images_today") or 0) + cost},
        ):
            raise Exception("No credits remaining. Buy credits or redeem a coupon.")

    # Front-end keeps user_description for roster/profile; full prompt is for xAI only
    user_desc = (description or "").strip()[:280]
    out = {
        "url": url,
        "prompt": prompt,
        "user_description": user_desc,
        "display_prompt": (
            a.user_facing_character_prompt(prompt)
            if hasattr(a, "user_facing_character_prompt")
            else user_desc
        ) or user_desc,
        "type": "image",
        "charged": cost,
        "super_accuracy": super_accuracy,
        "ref_count": n_refs,
    }
    if source_images:
        out["source_images"] = source_images
    if search_meta:
        out["reference_image_url"] = search_meta.get("url")
        out["search_query"] = search_meta.get("search_query")
        out["source_page_image"] = search_meta.get("source_url")
    if super_accuracy and source_image:
        out["seed_image_url"] = source_image
    return out


def _snapshot_angles_from_spin_video(a, video_url: str, n: int = 4) -> list:
    """Pull n evenly spaced frames from a 360 spin video → persist stills (no WM).

    Order approx front / side / back / side for a full yaw. Used after pack purchase
    so angles come from the video, not a second image-gen wave.
    """
    import os
    import tempfile

    import cv2
    import requests
    from io import BytesIO
    from PIL import Image

    if not video_url:
        raise Exception("No spin video to snapshot angles from.")
    r = requests.get(video_url, timeout=120)
    r.raise_for_status()
    content = r.content
    if not content or len(content) < 1000:
        raise Exception("Spin video download was empty.")

    path = None
    urls = []
    try:
        fd, path = tempfile.mkstemp(suffix=".mp4")
        os.write(fd, content)
        os.close(fd)
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            raise Exception("Could not open spin video for frames.")
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if total < 1:
            # fallback: read until end counting
            total = 0
            while True:
                ok, _ = cap.read()
                if not ok:
                    break
                total += 1
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        if total < 1:
            raise Exception("Spin video has no frames.")
        n = max(1, min(8, int(n or 4)))
        for i in range(n):
            # first frame + evenly around the spin (0, 1/3, 2/3, last for n=4)
            if n == 1:
                idx = 0
            else:
                idx = int(round(i * (total - 1) / (n - 1)))
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, min(total - 1, idx)))
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            im = Image.fromarray(rgb)
            buf = BytesIO()
            im.save(buf, format="JPEG", quality=92)
            data = buf.getvalue()
            if hasattr(a, "_persist_image_bytes"):
                u = a._persist_image_bytes(data, ext="jpg", content_type="image/jpeg")
            else:
                # data-uri then persist_image if needed
                import base64
                b64 = base64.b64encode(data).decode("ascii")
                u = a._persist_image(f"data:image/jpeg;base64,{b64}")
            if u:
                urls.append(u)
        cap.release()
    finally:
        if path:
            try:
                os.unlink(path)
            except Exception:
                pass
    if len(urls) < 1:
        raise Exception("Could not snapshot any frames from the 360 video.")
    # Ensure we have n slots: pad with last if short
    while len(urls) < n and urls:
        urls.append(urls[-1])
    return urls[:n]


@register("character_pack")
def handle_character_pack(user_id: int, payload: dict) -> dict:
    """Purchase pack: 360 video FIRST from approved front, then 4 stills from that video.

    Separate from preview (few credits). Charges CHARACTER_PACK_CREDIT_COST once.
    No watermark on pack masters.
    """
    from credit_wallet import credit_balance

    a = _app()
    is_admin = bool(payload.get("is_admin"))
    primary = (payload.get("primary_image_url") or "").strip()
    prompt = payload.get("prompt") or ""
    gender = payload.get("gender") or ""
    name = (payload.get("name") or "Unnamed Character")[:80]
    source_mode = payload.get("source_mode") or "describe"
    if not primary:
        raise Exception("Approve a first shot before buying the pack.")

    pack_cost = int(
        payload.get("pack_cost")
        or getattr(a, "CHARACTER_PACK_CREDIT_COST", 40)
        or 40
    )
    res = a.supabase.table("users").select(
        "picture_credits,video_credits,images_today,videos_today"
    ).eq("id", user_id).single().execute()
    u = res.data or {}
    bal = credit_balance(u)
    if not is_admin and bal < pack_cost:
        raise Exception(
            f"Full pack (360 + 4 clean stills) needs {pack_cost} credits — you have {bal}."
        )

    # Public primary for xAI spin
    if hasattr(a, "_public_image_url_for_xai"):
        try:
            primary = a._public_image_url_for_xai(primary) or primary
        except Exception:
            pass
    primary = a._persist_image(primary) if hasattr(a, "_persist_image") else primary

    save_prompt = ""
    if hasattr(a, "user_facing_character_prompt"):
        save_prompt = a.user_facing_character_prompt(prompt) or ""
    if not save_prompt:
        save_prompt = (
            payload.get("user_description") or payload.get("description") or ""
        ).strip()[:280]

    motion_profile = None
    try:
        motion_profile = a.build_motion_profile(primary)
    except Exception:
        motion_profile = None

    insert_row = {
        "user_id": user_id,
        "name": name,
        "gender": gender,
        "images": [primary],
        "primary_image_url": primary,
        "spin_video_url": None,
        "prompt": save_prompt,
        "source_mode": source_mode,
    }
    try:
        row = a.supabase.table("characters").insert({
            **insert_row,
            **({"motion_profile": motion_profile} if motion_profile is not None else {}),
        }).execute()
    except Exception:
        row = a.supabase.table("characters").insert(insert_row).execute()
    char = row.data[0]
    char_id = char.get("id")

    # ── 1) 360 video FIRST (from approved front still) ──
    duration = int(getattr(a, "CHARACTER_SPIN_DURATION_SEC", 6) or 6)
    video_url = None
    xai_err = None
    key = _fresh_media_key()
    try:
        result = a.generate_video_xai(
            a.CHARACTER_SPIN_PROMPT, primary, duration, api_key=key
        )
        video_url = (result.get("video") or {}).get("url") or result.get("url")
        if not video_url:
            out = result.get("output") or result.get("result") or {}
            if isinstance(out, dict):
                video_url = (out.get("video") or {}).get("url") or out.get("url")
        if video_url:
            video_url = a._persist_video(video_url)
        else:
            xai_err = "xAI returned no video URL"
    except Exception as e:
        xai_err = str(e)
        # soft re-prompt only on moderation (existing spin pattern) — use Nick's soft string as-is
        msg1 = str(e).lower()
        if any(k in msg1 for k in ("moderat", "rejected", "safety", "policy", "blocked")):
            soft = (
                "Slow product turntable of the same stylized game character figure, "
                "white studio backdrop, smooth 360 degree spin, character select UI style, "
                "keep outfit and face identical to reference, no text."
            )
            try:
                result = a.generate_video_xai(soft, primary, duration, api_key=_fresh_media_key())
                video_url = (result.get("video") or {}).get("url") or result.get("url")
                if video_url:
                    video_url = a._persist_video(video_url)
                    xai_err = None
            except Exception as e2:
                xai_err = str(e2) or xai_err

    if not video_url:
        # Leave roster row with front only so user can retry 360 later
        raise Exception(
            f"360° spin failed first ({xai_err or 'unknown'}). "
            "Front shot is saved — Retry 360 from the roster, then angles can be snapped."
        )

    # ── 2) Snapshot 4 stills FROM the 360 video (not a second image-gen) ──
    try:
        images = _snapshot_angles_from_spin_video(a, video_url, n=4)
    except Exception as e:
        # Spin succeeded — keep it; angles fallback to primary x4 so pack still delivers
        try:
            a.app.logger.warning("pack snapshot from video failed: %s", e)
        except Exception:
            pass
        images = [primary, primary, primary, primary]

    # Prefer approved front as image[0] if snapshots drifted
    if images and primary:
        images[0] = primary

    try:
        a.supabase.table("characters").update({
            "images": images,
            "primary_image_url": primary,
            "spin_video_url": video_url,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }).eq("id", char_id).execute()
    except Exception:
        a.supabase.table("characters").update({
            "images": images,
            "spin_video_url": video_url,
        }).eq("id", char_id).execute()

    if not is_admin:
        if not a._apply_spend(
            user_id, u, pack_cost,
            {
                "images_today": int(u.get("images_today") or 0) + 1,
                "videos_today": int(u.get("videos_today") or 0) + 1,
            },
        ):
            raise Exception("No credits remaining after pack. Contact support if charged incorrectly.")

    try:
        a.supabase.table("generations").insert({
            "user_id": user_id,
            "type": "video",
            "prompt": a.CHARACTER_SPIN_PROMPT,
            "output_url": video_url,
            "created_at": datetime.datetime.utcnow().isoformat(),
        }).execute()
    except Exception:
        pass

    cres = (
        a.supabase.table("characters")
        .select("*")
        .eq("id", char_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    char_out = (cres.data or [char])[0]
    return {
        "ok": True,
        "character": a._serialize_character(char_out),
        "images": images,
        "url": video_url,
        "spin_video_url": video_url,
        "type": "character_pack",
        "charged": 0 if is_admin else pack_cost,
        "download_url": f"/studios/percfectcharacter/download/{char_id}",
    }


@register("character_finalize")
def handle_character_finalize(user_id: int, payload: dict) -> dict:
    """Legacy: gen L/R/back via image-edit. Prefer character_pack (360 first → snapshot 4)."""
    from credit_wallet import credit_balance

    a = _app()
    is_admin = bool(payload.get("is_admin"))
    primary = payload["primary_image_url"]
    prompt = payload.get("prompt") or ""
    gender = payload.get("gender") or ""
    name = (payload.get("name") or "Unnamed Character")[:80]
    source_mode = payload.get("source_mode") or "describe"

    res = a.supabase.table("users").select(
        "picture_credits,video_credits,images_today"
    ).eq("id", user_id).single().execute()
    u = res.data or {}
    extra_n = 3
    bal = credit_balance(u)
    if not is_admin and bal < extra_n:
        raise Exception(f"You need {extra_n} credits to build the full character — you have {bal}.")

    # L / R / back only — reference is the APPROVED front shot (primary), not the
    # user's original upload photo.
    extras = a.CHARACTER_POSES[1:]

    def _make_shot(desc):
        # Parallel workers: fresh media key each (no ContextVar across threads)
        # image_url=primary → approved front still the user just approved
        rr = _generate_character_xai(
            a, a.pose_edit_prompt(desc), image_url=primary, api_key=_fresh_media_key()
        )
        data = (rr or {}).get("data") or []
        if not data or not data[0].get("url"):
            raise Exception("pose gen returned no image")
        return data[0]["url"]

    results = [None] * len(extras)
    shot_errors = []
    with ThreadPoolExecutor(max_workers=len(extras)) as ex:
        futs = {ex.submit(_make_shot, desc): (i, key) for i, (key, desc) in enumerate(extras)}
        for fut in futs:
            i, key = futs[fut]
            try:
                results[i] = fut.result()
            except Exception as e:
                shot_errors.append(f"{key}: {e}")

    images = [primary] + [r for r in results if r]
    with ThreadPoolExecutor(max_workers=len(images)) as ex:
        images = list(ex.map(a._persist_image, images))
    primary = images[0]

    if not is_admin:
        spent_img = max(0, len(images) - 1)
        if spent_img and not a._apply_spend(
            user_id, u, spent_img,
            {"images_today": int(u.get("images_today") or 0) + spent_img},
        ):
            raise Exception("No credits remaining after build. Contact support if charged incorrectly.")

    motion_profile = a.build_motion_profile(primary)
    # Store only user-facing description — never the full secret-sauce engine prompt
    save_prompt = ""
    if hasattr(a, "user_facing_character_prompt"):
        save_prompt = a.user_facing_character_prompt(prompt) or ""
    if not save_prompt:
        # Client may send the raw user box separately
        save_prompt = (payload.get("user_description") or payload.get("description") or "").strip()[:280]
    insert_row = {
        "user_id": user_id, "name": name, "gender": gender,
        "images": images, "primary_image_url": primary,
        "spin_video_url": None, "prompt": save_prompt, "source_mode": source_mode,
    }
    try:
        row = a.supabase.table("characters").insert({
            **insert_row, "motion_profile": motion_profile,
        }).execute()
    except Exception:
        # Column may not exist until migration 20260708_characters_motion_profile.sql
        row = a.supabase.table("characters").insert(insert_row).execute()

    out = {
        "ok": True,
        "character": a._serialize_character(row.data[0]),
        "images": images,
        "type": "character",
    }
    if shot_errors:
        out["warning"] = f"{len(shot_errors)} of {len(extras)} extra shots failed."
        out["shot_errors"] = shot_errors
    return out


@register("character_refine")
def handle_character_refine(user_id: int, payload: dict) -> dict:
    a = _app()
    is_admin = bool(payload.get("is_admin"))
    char_id = payload["char_id"]
    correction = payload["correction"]
    slot = int(payload["slot"])

    from credit_wallet import credit_balance

    res = a.supabase.table("users").select(
        "picture_credits,video_credits,images_today"
    ).eq("id", user_id).single().execute()
    u = res.data or {}
    if not is_admin and credit_balance(u) < 1:
        raise Exception(f"You need 1 credit — you have {credit_balance(u)}.")

    cres = a.supabase.table("characters").select("*").eq("id", char_id).eq("user_id", user_id).maybe_single().execute()
    char = cres.data if cres else None
    if not char:
        raise Exception("Character not found.")
    char = a._hydrate_character_row(char)
    images = list(char.get("images") or [])
    if slot < 0 or slot >= len(images):
        raise Exception("Pick which photo to fix.")

    pose_desc = a.CHARACTER_POSES[slot][1] if slot < len(a.CHARACTER_POSES) else (
        "full front view, facing forward, character facing straightforward at the camera"
    )
    # Optional refine only — user typed a fix for a bad shot (not required for normal gen).
    edit_prompt = (
        f"Optional fix request (apply only this): {correction}. "
        f"Keep the EXACT same character identity and the same camera angle: {pose_desc}. "
        "Apply only the requested fix — do not invent a different person. Full body, "
        "plain white background, consistent face, outfit (except what the fix asks for), "
        "colors and proportions, clean 3D animated style."
    )
    r = _generate_character_xai(
        a, edit_prompt, image_url=images[slot], api_key=_job_media_key()
    )
    data = (r or {}).get("data") or []
    if not data or not data[0].get("url"):
        raise Exception("Refine returned no image. You were NOT charged.")
    images[slot] = a._persist_image(data[0]["url"])
    primary = images[0] if slot == 0 else char.get("primary_image_url")

    if not is_admin:
        if not a._apply_spend(
            user_id, u, 1,
            {"images_today": int(u.get("images_today") or 0) + 1},
        ):
            raise Exception("No credits remaining.")

    # Keep version pack in sync (active look's shots)
    versions = a._character_versions(char)
    active_id = char.get("active_version_id") or "v1"
    for v in versions:
        if str(v.get("id")) == str(active_id):
            v["images"] = list(images)
            if slot == 0:
                v["primary_image_url"] = images[0]
            elif not v.get("primary_image_url"):
                v["primary_image_url"] = images[0] if images else v.get("primary_image_url")
            break
    with_cols, fallback = a._character_save_payload(
        images, versions, active_id, primary=primary or (images[0] if images else None)
    )
    a._update_character_row(char_id, user_id, with_cols, fallback)

    return {"ok": True, "images": images, "slot": slot, "type": "image", "charged": 1}


@register("character_restyle")
def handle_character_restyle(user_id: int, payload: dict) -> dict:
    """Create Version 2+ on the SAME player card (not a new roster entry).

    Always full look at VERSION_FULL_COST (10) — no separate prop tier.
    For a separate roster card + own 360, use character_split_version (30).
    """
    a = _app()
    is_admin = bool(payload.get("is_admin"))
    char_id = payload["char_id"]
    try:
        char_id = int(char_id)
    except (TypeError, ValueError):
        pass
    change = (
        payload.get("change")
        or payload.get("outfit")
        or payload.get("adjust")
        or ""
    ).strip()
    if not change:
        raise Exception("Describe the new outfit (e.g. red leather jacket and boots).")

    # Always full outfit rebuild on same card
    tier = "full"
    cost = int(getattr(a, "VERSION_FULL_COST", 10))
    try:
        asked = int(payload.get("cost") or 0)
        if asked >= cost:
            cost = asked
    except (TypeError, ValueError):
        pass

    from credit_wallet import credit_balance

    res = a.supabase.table("users").select(
        "picture_credits,video_credits,images_today"
    ).eq("id", user_id).single().execute()
    u = res.data or {}
    bal = credit_balance(u)
    if not is_admin and bal < cost:
        raise Exception(f"New outfit needs {cost} credits — you have {bal}.")

    cres = (
        a.supabase.table("characters")
        .select("*")
        .eq("id", char_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    char = (cres.data or [None])[0]
    if not char or not char.get("primary_image_url"):
        raise Exception("Character not found.")
    char = a._hydrate_character_row(char)

    versions = list(a._character_versions(char))
    base = a._resolve_character_version(char, char.get("active_version_id") or "v1")
    src = base.get("primary_image_url") or char["primary_image_url"]

    # New outfit only — same character identity; front facing like character page.
    front_prompt = (
        f"Show the EXACT same character — identical face, body shape, and proportions — "
        f"wearing this new outfit only: {change}. "
        f"Full front view, facing forward, character facing straightforward at the camera, "
        f"full body, standing in a casual pose, plain white background, clean high-quality "
        f"3D animated style, consistent lighting, no distortion. Keep identity locked; "
        f"only the outfit / clothing / look described changes — nothing else."
    )
    pose_extra = f", wearing the same new outfit: {change}"

    r0 = _generate_character_xai(
        a, front_prompt, image_url=src, api_key=_job_media_key()
    )
    data0 = (r0 or {}).get("data") or []
    if not data0 or not data0[0].get("url"):
        raise Exception("Outfit front shot failed. You were NOT charged.")
    new_front = data0[0]["url"]
    extras = a.CHARACTER_POSES[1:]

    def _mk(desc):
        desc_with = f"{desc}{pose_extra}"
        rr = _generate_character_xai(
            a,
            a.pose_edit_prompt(desc_with),
            image_url=new_front,
            api_key=_fresh_media_key(),
        )
        d = (rr or {}).get("data") or []
        if not d or not d[0].get("url"):
            raise Exception("pose gen returned no image")
        return d[0]["url"]

    results = [None] * len(extras)
    shot_errors = []
    with ThreadPoolExecutor(max_workers=len(extras)) as ex:
        futs = {ex.submit(_mk, desc): (i, key) for i, (key, desc) in enumerate(extras)}
        for f in futs:
            i, key = futs[f]
            try:
                results[i] = f.result()
            except Exception as e:
                shot_errors.append(f"{key}: {e}")

    if any(r is None for r in results):
        raise Exception(
            "Could not build all 4 angles for this outfit. You were NOT charged. "
            + ("; ".join(shot_errors[:3]) if shot_errors else "Try again.")
        )

    images = [new_front] + list(results)
    with ThreadPoolExecutor(max_workers=len(images)) as ex:
        images = list(ex.map(a._persist_image, images))
    new_front = images[0]

    nums = []
    for v in versions:
        vid = str(v.get("id") or "")
        if vid.startswith("v") and vid[1:].isdigit():
            nums.append(int(vid[1:]))
    next_n = max(nums) + 1 if nums else 2
    new_vid = f"v{next_n}"
    # User-facing label = outfit text (not "Version 2")
    label = (change[:40] + ("…" if len(change) > 40 else "")) or f"Outfit {next_n}"
    new_version = {
        "id": new_vid,
        "label": label,
        "images": images,
        "primary_image_url": new_front,
        "spin_video_url": None,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "tier": tier,
    }
    versions = list(versions) + [new_version]

    if not is_admin:
        if not a._apply_spend(
            user_id, u, cost,
            {"images_today": int(u.get("images_today") or 0) + cost},
        ):
            raise Exception("No credits remaining.")

    with_cols, fallback = a._character_save_payload(
        images, versions, new_vid, primary=new_front
    )
    saved = a._update_character_row(char_id, user_id, with_cols, fallback)

    if not saved:
        raise Exception("Outfit built but could not save the character. Contact support.")

    # Include url (primary) so job poll flatten works even if only .url is checked
    return {
        "ok": True,
        "url": new_front,
        "character": a._serialize_character(saved),
        "images": images,
        "charged": cost,
        "version_id": new_vid,
        "tier": tier,
        "type": "character",
        "message": f"Saved new outfit on this character (same roster entry).",
        "versions": a._character_versions(saved),
    }


@register("character_adjust")
def handle_character_adjust(user_id: int, payload: dict) -> dict:
    """Alias: Version 2+ appearance change on the same character."""
    change = (payload.get("adjust") or payload.get("outfit") or payload.get("change") or "").strip()
    payload = dict(payload)
    payload["change"] = change
    payload["outfit"] = change
    return handle_character_restyle(user_id, payload)


@register("character_split_version")
def handle_character_split_version(user_id: int, payload: dict) -> dict:
    """Promote a Version look → NEW separate player card + dedicated 360° spin.

    Cost VERSION_SPLIT_COST (30). Source character keeps all Versions.
    """
    import datetime
    from credit_wallet import credit_balance

    a = _app()
    is_admin = bool(payload.get("is_admin"))
    char_id = payload.get("char_id")
    version_id = (payload.get("version_id") or "").strip() or None
    cost = int(payload.get("cost") or getattr(a, "VERSION_SPLIT_COST", 30))
    try:
        asked = int(payload.get("cost") or 0)
        if asked >= cost:
            cost = asked
    except (TypeError, ValueError):
        pass

    res = a.supabase.table("users").select(
        "picture_credits,video_credits,images_today,videos_today"
    ).eq("id", user_id).single().execute()
    u = res.data or {}
    bal = credit_balance(u)
    if not is_admin and bal < cost:
        raise Exception(
            f"Separate player card needs {cost} credits — you have {bal}."
        )

    cres = (
        a.supabase.table("characters")
        .select("*")
        .eq("id", char_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    char = (cres.data or [None])[0]
    if not char:
        raise Exception("Character not found.")
    char = a._hydrate_character_row(char)

    look_id = version_id or char.get("active_version_id") or "v1"
    look = a._resolve_character_version(char, look_id)
    images = [x for x in (look.get("images") or []) if isinstance(x, str) and x]
    primary = look.get("primary_image_url") or (images[0] if images else None)
    if not primary:
        raise Exception("This Version has no front image to clone.")
    if not images:
        images = [primary]

    base_name = (payload.get("name") or "").strip()
    if not base_name:
        base_name = (char.get("name") or "Character").strip()
        label = (look.get("label") or look_id or "").strip()
        if label and label.lower() not in ("original", "v1"):
            base_name = f"{base_name} · {label[:32]}"
    base_name = base_name[:80]

    # New card starts as Original (v1) with this look's shots — clean separate player
    insert_row = {
        "user_id": user_id,
        "name": base_name,
        "prompt": char.get("prompt") or "",
        "gender": char.get("gender") or "",
        "primary_image_url": primary,
        "images": images[:4],
        "source_mode": char.get("source_mode") or "upload",
    }
    # Optional columns when present
    try:
        insert_row["active_version_id"] = "v1"
    except Exception:
        pass

    try:
        ins = a.supabase.table("characters").insert(insert_row).execute()
        new_char = (ins.data or [None])[0]
    except Exception as e:
        # Retry without optional columns
        insert_row.pop("active_version_id", None)
        try:
            ins = a.supabase.table("characters").insert(insert_row).execute()
            new_char = (ins.data or [None])[0]
        except Exception as e2:
            raise Exception(f"Could not create separate player card: {e2}") from e2

    if not new_char or not new_char.get("id"):
        raise Exception("Separate player card insert failed.")

    new_id = new_char["id"]
    spin_url = None
    spin_err = None
    try:
        # Fresh video key — do not reuse the photo key from the split job
        vkey = _fresh_media_key()
        result = a.generate_video_xai(
            a.CHARACTER_SPIN_PROMPT, primary, 6, api_key=vkey
        )
        spin_url = (
            (result.get("video") or {}).get("url")
            or result.get("url")
            or (result.get("data") or [{}])[0].get("url")
        )
        if spin_url:
            spin_url = a._persist_video(spin_url)
            a.supabase.table("characters").update(
                {"spin_video_url": spin_url}
            ).eq("id", new_id).eq("user_id", user_id).execute()
        else:
            spin_err = f"xAI returned no video URL: {str(result)[:200]}"
            try:
                a.app.logger.error("split-version spin empty for %s: %s", new_id, spin_err)
            except Exception:
                pass
    except Exception as e:
        spin_err = str(e)[:400]
        try:
            a.app.logger.error("split-version spin failed for %s: %s", new_id, e)
        except Exception:
            pass

    if not is_admin:
        if not a._apply_spend(
            user_id, u, cost,
            {
                "images_today": int(u.get("images_today") or 0) + 1,
                "videos_today": int(u.get("videos_today") or 0) + (1 if spin_url else 0),
            },
        ):
            raise Exception("No credits remaining.")

    # Reload full row
    fres = (
        a.supabase.table("characters")
        .select("*")
        .eq("id", new_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    saved = (fres.data or [None])[0] or new_char
    msg = f"New player card “{base_name}” created"
    if spin_url:
        msg += " with its own 360° spin."
    else:
        msg += " (360° spin pending — use roster 🎥 if needed)."
        if spin_err:
            msg += f" Spin note: {spin_err}"

    return {
        "ok": True,
        "character": a._serialize_character(saved),
        "source_character_id": char_id,
        "source_version_id": look_id,
        "charged": cost,
        "spin_video_url": spin_url,
        "type": "character",
        "message": msg,
    }


# ── Other generators ──────────────────────────────────────────

@register("princess_image")
def handle_princess_image(user_id: int, payload: dict) -> dict:
    a = _app()
    full_prompt = payload["full_prompt"]
    guest = bool(payload.get("guest"))

    result = a.generate_image_xai(full_prompt, api_key=_job_media_key())
    image_url = result["data"][0]["url"]
    image_url = a._persist_image(image_url)

    remaining = None
    if guest:
        a._increment_princess_guest_usage()
        remaining, _ = a._princess_guest_remaining()
    elif user_id:
        try:
            a.supabase.table("generations").insert({
                "user_id": user_id,
                "type": "image",
                "prompt": full_prompt,
                "output_url": image_url,
                "created_at": datetime.datetime.utcnow().isoformat(),
            }).execute()
        except Exception:
            pass

    return {"url": image_url, "prompt": full_prompt, "remaining": remaining, "type": "image"}


@register("picture_logo")
def handle_picture_logo(user_id: int, payload: dict) -> dict:
    from credit_wallet import credit_balance

    a = _app()
    is_admin = bool(payload.get("is_admin"))
    prompt = payload["prompt"]

    res = a.supabase.table("users").select(
        "picture_credits,video_credits,images_today"
    ).eq("id", user_id).single().execute()
    user_data = res.data or {}
    if not is_admin and credit_balance(user_data) < 1:
        raise Exception(f"You need 1 credit — you have {credit_balance(user_data)}.")

    result = a.generate_image_xai(prompt, api_key=_job_media_key())
    data = (result or {}).get("data") or []
    image_url = data[0].get("url") if data else None
    if not image_url:
        raise Exception("No logo was returned — try rewording. You were NOT charged.")
    image_url = a._persist_image(image_url)

    if not is_admin:
        if not a._apply_spend(
            user_id, user_data, 1,
            {"images_today": int(user_data.get("images_today") or 0) + 1},
        ):
            raise Exception("No credits remaining.")

    return {"ok": True, "logo_url": image_url, "type": "image", "charged": 1}


@register("trading_card")
def handle_trading_card(user_id: int, payload: dict) -> dict:
    """GTA-loading-screen style trading card art for one roster character.

    Identity locked to source image. Percfect P+crown mark (not Rockstar R).
    Cost: 2 credits (1 gen + 1 ref identity) unless admin.
    """
    from credit_wallet import credit_balance, photo_generate_cost

    a = _app()
    is_admin = bool(payload.get("is_admin"))
    char_id = payload.get("char_id")
    name = (payload.get("name") or "Unknown").strip()[:80]
    gender = (payload.get("gender") or "").strip().lower()
    source = (payload.get("source_image") or payload.get("primary_image_url") or "").strip()
    refs = _photo_source_images(payload)
    if source and source not in refs:
        refs = [source] + list(refs)
    logo = (payload.get("logo_url") or "").strip()
    if logo and logo not in refs:
        refs = list(refs) + [logo]
    refs = [u for u in refs if u][:3]
    full_prompt = (payload.get("full_prompt") or "").strip()
    stats = payload.get("stats") or {}

    if not refs and not source:
        raise Exception("Character needs a portrait first.")
    if not full_prompt:
        raise Exception("Missing card art prompt.")

    cost = int(payload.get("cost") or photo_generate_cost(1))  # base + 1 identity (logo free)
    res = a.supabase.table("users").select(
        "picture_credits,video_credits,images_today"
    ).eq("id", user_id).single().execute()
    user_data = res.data or {}
    bal = credit_balance(user_data)
    if not is_admin and bal < cost:
        raise Exception(f"Trading card needs {cost} credits — you have {bal}.")

    # Verify ownership when char_id present
    if char_id is not None and str(char_id).strip() != "":
        try:
            cid = int(char_id)
        except (TypeError, ValueError):
            cid = char_id
        cres = (
            a.supabase.table("characters")
            .select("id,user_id,primary_image_url,name,gender")
            .eq("id", cid)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        row = (cres.data or [None])[0]
        if not row:
            raise Exception("Character not found on your roster.")
        if not source:
            source = (row.get("primary_image_url") or "").strip()
            if source and source not in refs:
                refs = [source] + refs
        if not name or name == "Unknown":
            name = (row.get("name") or name).strip()
        if not gender:
            gender = (row.get("gender") or "").strip().lower()

    # Multi-ref: character first, then Percfect P👑 logo
    # Reuse job-bound key — avoid double next_key with studio_jobs.
    result = _generate_photo_xai(
        a,
        full_prompt,
        refs or [source],
        aspect_ratio=payload.get("aspect_ratio") or "3:4",
        api_key=_job_media_key(),
    )
    data = (result or {}).get("data") or []
    image_url = data[0].get("url") if data else None
    if not image_url:
        raise Exception(
            "No card art returned (filter or API). You were NOT charged. Try again."
        )
    image_url = a._persist_image(image_url)

    if not is_admin:
        if not a._apply_spend(
            user_id,
            user_data,
            cost,
            {"images_today": int(user_data.get("images_today") or 0) + 1},
        ):
            raise Exception("No credits remaining.")

    try:
        a.supabase.table("generations").insert({
            "user_id": user_id,
            "type": "image",
            "prompt": f"[trading_card] {name} · {gender or '?'} · {full_prompt[:400]}",
            "output_url": image_url,
            "created_at": datetime.datetime.utcnow().isoformat(),
        }).execute()
    except Exception:
        pass

    return {
        "ok": True,
        "url": image_url,
        "type": "trading_card",
        "char_id": char_id,
        "name": name,
        "gender": gender,
        "stats": stats,
        "charged": 0 if is_admin else cost,
    }

