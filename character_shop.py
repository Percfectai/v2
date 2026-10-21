"""Premade character shop — list up to ~25 finished characters for sale.

Catalog is stored in Supabase Storage (previews/shop/premade_catalog.json) with a
repo JSON fallback. Buyers spend credits; we clone a snapshot onto their roster.
"""

from __future__ import annotations

import datetime
import json
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

SHOP_STORAGE_BUCKET = "previews"
SHOP_STORAGE_PATH = "shop/premade_catalog.json"
SHOP_MAX_DEFAULT = 25
# Owner-set default price for premade listings (wallet credits).
# Product: Trading Cards + shop buy — 30 credits for now (Nick 2026-08-12).
SHOP_PRICE_DEFAULT = 30
VERSIONS_META_FLAG = "__percfect_versions__"
WATERMARK_LABEL = "PERCFECT"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def empty_catalog(max_listings: int = SHOP_MAX_DEFAULT, default_price: int = SHOP_PRICE_DEFAULT) -> dict:
    return {
        "version": 1,
        "max_listings": max_listings,
        "default_price_credits": default_price,
        "listings": [],
        "updated_at": _now_iso(),
    }


def _parse_catalog_bytes(raw) -> Optional[dict]:
    if not raw:
        return None
    try:
        data = json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
    except Exception:
        return None
    if isinstance(data, dict) and isinstance(data.get("listings"), list):
        return data
    return None


def _load_local_catalog(fallback_path: str = None) -> Optional[dict]:
    if not fallback_path:
        return None
    try:
        with open(fallback_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("listings"), list):
            return data
    except Exception:
        return None
    return None


def load_catalog(supabase, app_logger=None, fallback_path: str = None) -> dict:
    """Load catalog from storage; fall back to on-disk JSON or empty.

    Local file wins when it sets force_local=true (used when storage write is
    blocked by RLS but we need to unlist / update the shop from the repo).
    """
    storage_cat = None
    try:
        raw = supabase.storage.from_(SHOP_STORAGE_BUCKET).download(SHOP_STORAGE_PATH)
        storage_cat = _parse_catalog_bytes(raw)
    except Exception as e:
        if app_logger:
            app_logger.debug("shop catalog storage miss: %s", e)

    local_cat = _load_local_catalog(fallback_path)
    if local_cat and local_cat.get("force_local"):
        return local_cat
    if storage_cat:
        return storage_cat
    if local_cat:
        return local_cat
    return empty_catalog()


def save_catalog(supabase, catalog: dict, app_logger=None, fallback_path: str = None) -> None:
    catalog = dict(catalog or empty_catalog())
    catalog["updated_at"] = _now_iso()
    catalog.setdefault("version", 1)
    catalog.setdefault("max_listings", SHOP_MAX_DEFAULT)
    catalog.setdefault("default_price_credits", SHOP_PRICE_DEFAULT)
    if not isinstance(catalog.get("listings"), list):
        catalog["listings"] = []
    # Clear force_local after a successful admin save so storage is source of truth again
    catalog.pop("force_local", None)
    body = json.dumps(catalog, ensure_ascii=False, indent=2).encode("utf-8")
    storage_ok = False
    try:
        supabase.storage.from_(SHOP_STORAGE_BUCKET).upload(
            SHOP_STORAGE_PATH,
            body,
            file_options={"content-type": "application/json", "upsert": "true"},
        )
        storage_ok = True
    except Exception as e:
        try:
            supabase.storage.from_(SHOP_STORAGE_BUCKET).update(
                SHOP_STORAGE_PATH,
                body,
                file_options={"content-type": "application/json", "upsert": "true"},
            )
            storage_ok = True
        except Exception as e2:
            if app_logger:
                app_logger.warning("shop catalog storage save failed: %s / %s", e, e2)
    # Always mirror to local fallback so unlist works without service_role
    path = fallback_path
    if not path:
        try:
            path = str(Path(__file__).resolve().parent / "static" / "data" / "premade_shop.json")
        except Exception:
            path = None
    if path:
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            local = dict(catalog)
            if not storage_ok:
                local["force_local"] = True
            with open(path, "w", encoding="utf-8") as f:
                json.dump(local, f, ensure_ascii=False, indent=2)
        except Exception as e3:
            if app_logger:
                app_logger.warning("shop catalog local save failed: %s", e3)
            if not storage_ok:
                raise
    elif not storage_ok:
        raise RuntimeError("Could not save shop catalog to storage or disk.")


def active_listings(catalog: dict) -> List[dict]:
    out = []
    for item in (catalog or {}).get("listings") or []:
        if not isinstance(item, dict):
            continue
        if item.get("active") is False:
            continue
        out.append(item)
    out.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return out


def find_listing(catalog: dict, listing_id: str) -> Optional[dict]:
    lid = str(listing_id or "").strip()
    if not lid:
        return None
    for item in (catalog or {}).get("listings") or []:
        if str(item.get("id")) == lid and item.get("active") is not False:
            return item
    return None


def public_listing_view(item: dict) -> dict:
    """Public shop card data — watermarked previews only (no clean masters, no free spin)."""
    # Prefer watermarked fields; never expose full-res masters in the API/page
    preview_imgs = item.get("preview_images") or []
    if isinstance(preview_imgs, list):
        preview_imgs = [u for u in preview_imgs if isinstance(u, str) and u][:8]
    else:
        preview_imgs = []
    preview_primary = (
        item.get("preview_image_url")
        or (preview_imgs[0] if preview_imgs else "")
        or ""
    )
    # Fallback only if listing is old and has no watermark yet (CSS still marks the card)
    if not preview_primary:
        raw = item.get("primary_image_url") or ""
        imgs = item.get("images") or []
        if isinstance(imgs, list) and imgs and isinstance(imgs[0], str):
            raw = raw or imgs[0]
        preview_primary = raw
        preview_imgs = [raw] if raw else []
    return {
        "id": item.get("id"),
        "name": item.get("name") or "Premade character",
        "blurb": item.get("blurb") or "",
        "gender": item.get("gender") or "",
        "price_credits": int(item.get("price_credits") or SHOP_PRICE_DEFAULT),
        "primary_image_url": preview_primary,
        "images": preview_imgs,
        # Never ship free spin video on the shop page — unlock on purchase
        "spin_video_url": "",
        "has_spin": bool(item.get("spin_video_url")),
        "watermarked": True,
        "featured": bool(item.get("featured")),
        "created_at": item.get("created_at"),
    }


def _make_percfect_watermark_bytes(image_bytes: bytes) -> bytes:
    """Visible PERCFECT watermark (readable character, not free to steal)."""
    from io import BytesIO
    from PIL import Image, ImageDraw, ImageFont, ImageEnhance

    base = Image.open(BytesIO(image_bytes)).convert("RGBA")
    w, h = base.size
    # Slight dim so watermark reads clearly
    base = ImageEnhance.Brightness(base).enhance(0.92)
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    label = WATERMARK_LABEL
    font_size = max(28, int(min(w, h) * 0.09))
    font = None
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ):
        try:
            font = ImageFont.truetype(path, font_size)
            break
        except Exception:
            pass
    if font is None:
        font = ImageFont.load_default()

    # Diagonal tile of PERCFECT across the image
    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    step_x = max(tw + 40, int(w * 0.35))
    step_y = max(th + 50, int(h * 0.22))
    # Draw on a larger canvas then rotate
    tile = Image.new("RGBA", (w * 2, h * 2), (0, 0, 0, 0))
    tdraw = ImageDraw.Draw(tile)
    for y in range(0, h * 2, step_y):
        for x in range(0, w * 2, step_x):
            tdraw.text((x + 2, y + 2), label, fill=(0, 0, 0, 90), font=font)
            tdraw.text((x, y), label, fill=(255, 255, 255, 140), font=font)
    tile = tile.rotate(28, expand=0, center=(w, h))
    # Crop center back to base size
    left = (tile.width - w) // 2
    top = (tile.height - h) // 2
    tile = tile.crop((left, top, left + w, top + h))
    # Center brand stamp
    cx, cy = (w - tw) // 2, (h - th) // 2
    draw = ImageDraw.Draw(overlay)
    pad = max(8, font_size // 4)
    draw.rectangle(
        (cx - pad, cy - pad, cx + tw + pad, cy + th + pad),
        fill=(0, 0, 0, 100),
    )
    draw.text((cx + 2, cy + 2), label, fill=(0, 0, 0, 160), font=font)
    draw.text((cx, cy), label, fill=(255, 255, 255, 210), font=font)
    out_img = Image.alpha_composite(Image.alpha_composite(base, tile), overlay).convert("RGB")
    out = BytesIO()
    out_img.save(out, format="JPEG", quality=88)
    return out.getvalue()


def watermark_and_rehost(supabase, src_url: str, public_base: str = None) -> str:
    """Download master still → PERCFECT watermark → upload to previews/shop/wm/."""
    import os
    import requests
    from io import BytesIO

    if not src_url:
        raise ValueError("No image URL to watermark")
    # Already a shop watermark asset
    if "/shop/wm/" in src_url:
        return src_url
    headers = {
        "User-Agent": "PercfectShopWatermark/1.0",
        "Accept": "image/*,*/*",
    }
    r = requests.get(src_url, timeout=45, headers=headers)
    r.raise_for_status()
    wm_bytes = _make_percfect_watermark_bytes(r.content)
    path = f"shop/wm/{uuid.uuid4().hex}.jpg"
    supabase.storage.from_(SHOP_STORAGE_BUCKET).upload(
        path,
        wm_bytes,
        file_options={"content-type": "image/jpeg", "upsert": "true"},
    )
    base = (public_base or os.getenv("SUPABASE_URL") or "").rstrip("/")
    if base:
        return f"{base}/storage/v1/object/public/{SHOP_STORAGE_BUCKET}/{path}"
    return f"/media/previews/{path}"


def apply_shop_watermarks(listing: dict, supabase, max_angles: int = 4) -> dict:
    """Attach preview_* watermarked URLs; keep clean masters for purchase delivery."""
    listing = dict(listing or {})
    masters = [u for u in (listing.get("images") or []) if isinstance(u, str) and u]
    primary = listing.get("primary_image_url") or (masters[0] if masters else "")
    if primary and primary not in masters:
        masters = [primary] + masters
    # Dedupe preserve order
    seen = set()
    ordered = []
    for u in masters:
        if u in seen:
            continue
        seen.add(u)
        ordered.append(u)
    preview_imgs = []
    for u in ordered[: max(1, max_angles)]:
        try:
            preview_imgs.append(watermark_and_rehost(supabase, u))
        except Exception:
            # If watermark fails, still mark card via CSS; don't leak by using master
            continue
    if not preview_imgs and primary:
        try:
            preview_imgs = [watermark_and_rehost(supabase, primary)]
        except Exception:
            preview_imgs = []
    listing["preview_images"] = preview_imgs
    listing["preview_image_url"] = preview_imgs[0] if preview_imgs else ""
    listing["watermarked"] = True
    return listing


def _pack_images(shots: list, versions: list = None, active_version_id: str = "v1") -> list:
    urls = [x for x in (shots or []) if isinstance(x, str) and x]
    if not versions:
        return urls
    clean = []
    for v in versions:
        if not isinstance(v, dict):
            continue
        vimgs = [x for x in (v.get("images") or []) if isinstance(x, str) and x]
        primary = v.get("primary_image_url") or (vimgs[0] if vimgs else "")
        if not primary:
            continue
        clean.append({
            "id": str(v.get("id") or f"v{len(clean)+1}"),
            "label": (v.get("label") or v.get("id") or "Look")[:80],
            "images": vimgs if vimgs else [primary],
            "primary_image_url": primary,
            "spin_video_url": v.get("spin_video_url"),
        })
    meta = {
        VERSIONS_META_FLAG: True,
        "versions": clean,
        "active_version_id": str(active_version_id or "v1"),
    }
    return urls + [meta]


def snapshot_from_serialized(
    ser: dict,
    *,
    source_character_id=None,
    price_credits: int = SHOP_PRICE_DEFAULT,
    blurb: str = "",
    featured: bool = False,
    listed_by: int = None,
) -> dict:
    """Build a durable shop listing from a serialized character dict."""
    ser = ser or {}
    imgs = [u for u in (ser.get("images") or []) if isinstance(u, str) and u]
    primary = ser.get("primary_image_url") or (imgs[0] if imgs else "")
    if not primary:
        raise ValueError("Character needs a primary image before listing.")
    if not imgs:
        imgs = [primary]

    versions = ser.get("versions") or []
    clean_vers = []
    for v in versions:
        if not isinstance(v, dict):
            continue
        vimgs = [x for x in (v.get("images") or []) if isinstance(x, str) and x]
        vp = v.get("primary_image_url") or (vimgs[0] if vimgs else "")
        if not vp:
            continue
        clean_vers.append({
            "id": str(v.get("id") or f"v{len(clean_vers)+1}"),
            "label": (v.get("label") or v.get("id") or "Look")[:80],
            "images": vimgs if vimgs else [vp],
            "primary_image_url": vp,
            "spin_video_url": v.get("spin_video_url"),
        })
    if not clean_vers:
        clean_vers = [{
            "id": "v1",
            "label": "Original",
            "images": imgs,
            "primary_image_url": primary,
            "spin_video_url": ser.get("spin_video_url"),
        }]

    return {
        "id": f"pm_{uuid.uuid4().hex[:12]}",
        "source_character_id": source_character_id if source_character_id is not None else ser.get("id"),
        "listed_by": listed_by,
        "name": (ser.get("name") or "Premade character")[:80],
        "blurb": (blurb or "")[:280],
        "gender": ser.get("gender") or "",
        "price_credits": max(1, min(500, int(price_credits or SHOP_PRICE_DEFAULT))),
        "primary_image_url": primary,
        "images": imgs,
        "spin_video_url": ser.get("spin_video_url") or "",
        "versions": clean_vers,
        "active_version_id": ser.get("active_version_id") or "v1",
        "prompt": (ser.get("prompt") or "")[:2000],
        "featured": bool(featured),
        "active": True,
        "created_at": _now_iso(),
    }


def clone_insert_row(listing: dict, buyer_id: int) -> dict:
    """characters-table insert row for a purchased premade (no versions columns required)."""
    imgs = [u for u in (listing.get("images") or []) if isinstance(u, str) and u]
    primary = listing.get("primary_image_url") or (imgs[0] if imgs else None)
    if not primary:
        raise ValueError("This listing has no images to deliver.")
    if not imgs:
        imgs = [primary]

    versions = listing.get("versions") or [{
        "id": "v1",
        "label": "Original",
        "images": imgs,
        "primary_image_url": primary,
        "spin_video_url": listing.get("spin_video_url"),
    }]
    active = listing.get("active_version_id") or "v1"
    packed = _pack_images(imgs, versions, active)
    prompt = (listing.get("prompt") or "").strip()
    tag = f"[premade_shop:{listing.get('id')}]"
    if tag not in prompt:
        prompt = (prompt + ("\n\n" if prompt else "") + tag).strip()[:2000]

    return {
        "user_id": buyer_id,
        "name": (listing.get("name") or "Premade character")[:80],
        "gender": listing.get("gender") or None,
        "images": packed,
        "primary_image_url": primary,
        "spin_video_url": listing.get("spin_video_url") or None,
        "prompt": prompt,
        "source_mode": "shop",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }


def publish_listing(catalog: dict, listing: dict) -> dict:
    cat = deepcopy(catalog) if catalog else empty_catalog()
    listings = list(cat.get("listings") or [])
    max_n = int(cat.get("max_listings") or SHOP_MAX_DEFAULT)
    active_n = sum(1 for x in listings if x.get("active") is not False)
    # Allow replace of same source without counting toward full
    src_id = listing.get("source_character_id")
    if src_id is not None:
        listings = [
            x for x in listings
            if not (x.get("active") is not False and str(x.get("source_character_id")) == str(src_id))
        ]
        active_n = sum(1 for x in listings if x.get("active") is not False)
    if active_n >= max_n:
        raise ValueError(f"Shop is full ({max_n} premade slots). Unlist one first.")
    listings.append(listing)
    cat["listings"] = listings
    return cat


def unlist_listing(catalog: dict, listing_id: str) -> dict:
    cat = deepcopy(catalog) if catalog else empty_catalog()
    lid = str(listing_id)
    changed = False
    for item in cat.get("listings") or []:
        if str(item.get("id")) == lid:
            item["active"] = False
            item["unlisted_at"] = _now_iso()
            changed = True
            break
    if not changed:
        raise ValueError("Listing not found.")
    return cat
