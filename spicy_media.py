"""
spicy_media.py — SpicyAPI provider for image + video (clean AND spicy, one module).

SpicyAPI is a unified gateway to many multimodal models. Clean vs spicy is just the model id
(e.g. bytedance/seedream-5.5/text-to-image  vs  alibaba/wan-3.0-spicy/image-to-video).

Verified against docs.spicyapi.ai/llms-full.txt (2026-11-14):
  Native task API base : https://api.spicyapi.ai/api/v1   (Bearer API key)
  Public catalog (no key): GET https://api.spicyapi.ai/console/v1/catalog/models
  Response envelope      : {code, msg, data, request_id} — branch on `code`, not HTTP status.
  Keyed catalog          : GET /models?modality=image&task=text-to-image[&includeSchema=1&includeExamples=1]
  One model record       : GET /models/{model}
  Exact price quote      : POST /jobs/quote {model, input}
  Submit a task          : POST /jobs/createTask  (header Idempotency-Key)  {model, input[, callBackUrl]} -> data.taskId
  Poll a task            : GET /jobs/recordInfo?taskId=  -> data.state (queued|running|succeeded|failed|...),
                           data.output.assets[].url (ready) / .pending
  Webhook                : pass callBackUrl (public HTTPS, signature-verified) instead of polling.
  Text models            : OpenAI/Anthropic/Gemini-compatible at /v1 (reply inline) — not handled here.
  Balance                : GET /api/v1/chat/credit

Funds are HELD (estimatedCost) at accept, charged at the capped quote; failed tasks normally release
the hold. Account must be email-verified + funded or calls return code 40310 / 40x.

Key: SPICY_API_KEY (env only, format sk-spicy-...). Never printed or committed.
"""
from __future__ import annotations

import math
import os
import time
import uuid
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import unquote

import requests

log = logging.getLogger("spicy_media")

ROOT = (os.environ.get("SPICY_API_BASE") or "https://api.spicyapi.ai").rstrip("/")
API = f"{ROOT}/api/v1"
CATALOG_URL = f"{ROOT}/console/v1/catalog/models"   # public, no key

_CATALOG_CACHE: Dict[str, Any] = {"ts": 0, "items": None}
_CATALOG_TTL = 600


class SpicyError(RuntimeError):
    pass


def _key() -> str:
    tok = (os.environ.get("SPICY_API_KEY") or "").strip()
    if not tok:
        raise SpicyError("SPICY_API_KEY is not set (env only; format sk-spicy-...).")
    return tok


def enabled() -> bool:
    return bool((os.environ.get("SPICY_API_KEY") or "").strip())


def _headers(extra: Optional[dict] = None) -> dict:
    h = {"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h


def _call(method: str, path: str, *, idempotency_key: Optional[str] = None, **kw) -> Dict[str, Any]:
    """Native task API call. Returns `data`; raises on business code != 200."""
    hdr = _headers({"Idempotency-Key": idempotency_key} if idempotency_key else None)
    r = requests.request(method, f"{API}{path}", headers=hdr, timeout=kw.pop("timeout", 60), **kw)
    try:
        body = r.json()
    except Exception:
        raise SpicyError(f"{method} {path} -> {r.status_code}, non-JSON: {r.text[:200]}")
    if body.get("code") != 200:
        raise SpicyError(f'{body.get("code")} {body.get("msg")} (request_id={body.get("request_id")})')
    return body.get("data") or {}


# --- public catalog (drives the dropdown + list price; no key) --------------
def fetch_catalog(force: bool = False) -> List[Dict[str, Any]]:
    now = time.time()
    if not force and _CATALOG_CACHE["items"] is not None and now - _CATALOG_CACHE["ts"] < _CATALOG_TTL:
        return _CATALOG_CACHE["items"]
    r = requests.get(CATALOG_URL, timeout=30)
    if not r.ok:
        raise SpicyError(f"catalog fetch failed ({r.status_code})")
    items = ((r.json() or {}).get("data") or {}).get("items") or []
    _CATALOG_CACHE.update(ts=now, items=items)
    return items


def _price_str(m: Dict[str, Any]) -> str:
    p = m.get("price") or {}
    amt, unit = p.get("amount"), p.get("unit")
    return f"${amt}/{(unit or '').replace('per_', '')}" if amt else ""


def dropdown_models(modality: str = "image", task: Optional[str] = None,
                    include_spicy: bool = True) -> List[Dict[str, Any]]:
    """Public catalog shaped for a UI dropdown: id, label, LIST price, spicy flag, input fields.
    List price is the cheapest tier — use quote() for the exact charge of a real request."""
    out = []
    for m in fetch_catalog():
        if m.get("modality") != modality or m.get("status") != "live" or not m.get("callable", True):
            continue
        if task and task not in (m.get("tasks") or []):
            continue
        spicy = bool(m.get("mature"))
        if spicy and not include_spicy:
            continue
        out.append({
            "id": m.get("model"),
            "label": m.get("displayName") or m.get("model"),
            "family": m.get("familyDisplayName"),
            "tasks": m.get("tasks") or [],
            "spicy": spicy,
            "price": _price_str(m),
            "price_raw": m.get("price"),
            "input_fields": m.get("inputFields") or [],
        })
    out.sort(key=lambda x: (x["spicy"], x["label"] or ""))
    return out


def list_price_for(model_id: str) -> Optional[Dict[str, Any]]:
    """LIST price object from the public catalog (cheapest tier). For the exact charge, use quote()."""
    for m in fetch_catalog():
        if m.get("model") == model_id:
            return m.get("price")
    return None


# --- Studio pricing, family grouping, route resolution & input mapping -------
IMAGE_USD_PER_CREDIT = 0.015
VIDEO_USD_PER_CREDIT = 0.012

STUDIO_IMAGE_FAMILIES = (
    "bytedance/seedream-5.5",
)

STUDIO_VIDEO_FAMILIES = (
    "minimax/h3",
)

FEATURED_IMAGE_FAMILIES = STUDIO_IMAGE_FAMILIES
FEATURED_VIDEO_FAMILIES = STUDIO_VIDEO_FAMILIES

_IMAGE_GEN_TASKS = {"text-to-image", "image-to-image", "image-edit"}
_VIDEO_GEN_TASKS = {"text-to-video", "image-to-video", "reference-to-video", "video-extend"}

_ASPECT_DIMS = {
    "1:1": (1024, 1024),
    "9:16": (768, 1344),
    "3:4": (896, 1152),
    "16:9": (1344, 768),
    "4:3": (1152, 896),
    "3:2": (1248, 832),
    "2:3": (832, 1248),
    "21:9": (1536, 640),
}


def catalog_record(model_id: str) -> Optional[Dict[str, Any]]:
    """Return public catalog entry for a full model id, or None."""
    mid = (model_id or "").strip()
    if not mid:
        return None
    for m in fetch_catalog():
        if m.get("model") == mid:
            return m
    return None


def usd_to_credits(amount_usd: float, *, modality: str = "image") -> int:
    try:
        amt = float(amount_usd or 0)
    except (TypeError, ValueError):
        amt = 0.0
    if modality == "video":
        if amt <= 0:
            return 3
        return max(2, int(math.ceil(amt / VIDEO_USD_PER_CREDIT)))
    if amt <= 0:
        return 1
    return max(1, int(math.ceil(amt / IMAGE_USD_PER_CREDIT)))


def _parse_variant_key(vk: str) -> Dict[str, str]:
    raw = (vk or "").strip()
    if not raw:
        return {}
    if "=" in raw or ";" in raw:
        out: Dict[str, str] = {}
        for part in raw.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k.strip()] = unquote(v.strip()).lower()
        return out
    return {"_bare": raw.lower()}


def variant_usd_price(
    rec: Dict[str, Any],
    *,
    resolution: Optional[str] = None,
    duration: Optional[int] = None,
    generate_audio: Optional[bool] = None,
    aspect_ratio: Optional[str] = None,
) -> Tuple[float, str]:
    """Resolve best-matching (amount_usd, unit) from a catalog record's price.variants."""
    price = (rec or {}).get("price") or {}
    base_unit = (price.get("unit") or "per_image").strip()
    try:
        base_amt = float(price.get("amount") or 0)
    except (TypeError, ValueError):
        base_amt = 0.0

    variants = price.get("variants") or []
    if not variants:
        return base_amt, base_unit

    res_l = (resolution or "").strip().lower() or None
    dur_s = str(int(duration)) if duration is not None else None
    aud_s = ("true" if generate_audio else "false") if generate_audio is not None else None
    ar_l = (aspect_ratio or "").strip().lower() or None
    if ar_l == "auto":
        ar_l = None

    best_score = -1
    best_amt = base_amt
    best_unit = base_unit

    for v in variants:
        vk = str(v.get("variant") or "")
        parsed = _parse_variant_key(vk)
        score = 0
        conflict = False
        if "_bare" in parsed:
            b = parsed["_bare"]
            if res_l and b == res_l:
                score += 4
            elif dur_s and b == dur_s:
                score += 4
            elif aud_s and b == aud_s:
                score += 2
            elif b and res_l and b != res_l and dur_s and b != dur_s:
                score -= 1
        elif parsed:
            if "resolution" in parsed and res_l:
                if parsed["resolution"] == res_l:
                    score += 4
                else:
                    conflict = True
            if "duration_seconds" in parsed and dur_s:
                if parsed["duration_seconds"] == dur_s:
                    score += 4
                else:
                    conflict = True
            if "generate_audio" in parsed and aud_s:
                if parsed["generate_audio"] == aud_s:
                    score += 2
                else:
                    conflict = True
            if "aspect_ratio" in parsed and ar_l:
                if parsed["aspect_ratio"] == ar_l:
                    score += 1
                else:
                    conflict = True
        if conflict:
            continue
        if score > best_score:
            try:
                v_amt = float(v.get("amount") or base_amt)
            except (TypeError, ValueError):
                v_amt = base_amt
            best_score = score
            best_amt = v_amt
            best_unit = (v.get("unit") or base_unit).strip()

    return best_amt, best_unit


def estimate_credits(
    model_id: str,
    *,
    modality: Optional[str] = None,
    resolution: Optional[str] = None,
    duration: Optional[int] = None,
    generate_audio: Optional[bool] = None,
    aspect_ratio: Optional[str] = None,
    num_refs: int = 0,
) -> Dict[str, Any]:
    """Compute Percfect credit cost from the SpicyAPI catalog (with variant matching)."""
    rec = catalog_record(model_id)
    if not rec:
        # Try resolving as family id
        try:
            _, rec = resolve_model_route(model_id, modality=modality or "image", num_refs=num_refs)
        except SpicyError:
            rec = None
    mod = modality or (rec or {}).get("modality") or "image"
    if not rec:
        d = max(1, int(duration or 6))
        return {
            "credits_total": (3 * d) if mod == "video" else 1,
            "credits_per_unit": 3 if mod == "video" else 1,
            "unit": "second" if mod == "video" else "image",
            "usd_amount": 0.0,
        }

    amt, unit = variant_usd_price(
        rec,
        resolution=resolution,
        duration=duration,
        generate_audio=generate_audio,
        aspect_ratio=aspect_ratio,
    )
    if mod == "video":
        d = max(1, int(duration or 6))
        if unit == "per_second":
            per_sec = usd_to_credits(amt, modality="video")
            return {
                "credits_total": per_sec * d,
                "credits_per_unit": per_sec,
                "unit": "second",
                "usd_amount": round(amt * d, 6),
            }
        total = max(3, int(math.ceil(amt / VIDEO_USD_PER_CREDIT))) if amt > 0 else (3 * d)
        return {
            "credits_total": total,
            "credits_per_unit": total,
            "unit": "request",
            "usd_amount": round(amt, 6),
        }

    total = usd_to_credits(amt, modality="image")
    return {
        "credits_total": total,
        "credits_per_unit": total,
        "unit": "image",
        "usd_amount": round(amt, 6),
    }


def credits_from_quote(quote_data: Optional[Dict[str, Any]], *, modality: str = "image", fallback_credits: int = 1) -> int:
    """Convert a live /jobs/quote response into Percfect credits."""
    if not isinstance(quote_data, dict):
        return max(1, int(fallback_credits or 1))
    raw = None
    for k in ("estimatedCost", "amount", "cost", "total", "price"):
        v = quote_data.get(k)
        if v is not None and v != "":
            try:
                raw = float(v)
                break
            except (TypeError, ValueError):
                continue
    if raw is None or raw <= 0:
        return max(1, int(fallback_credits or 1))
    if modality == "video":
        return max(2, int(math.ceil(raw / VIDEO_USD_PER_CREDIT)))
    return max(1, int(math.ceil(raw / IMAGE_USD_PER_CREDIT)))


def _extract_duration_spec(rec: Dict[str, Any]) -> Dict[str, Any]:
    ospec = rec.get("outputSpecs") or {}
    dspec = ospec.get("duration_seconds") or {}
    raw_enum = [int(x) for x in (dspec.get("enum") or []) if isinstance(x, (int, float)) and int(x) > 0]
    if raw_enum:
        raw_enum = sorted(set(raw_enum))
        dmin, dmax = raw_enum[0], raw_enum[-1]
        if len(raw_enum) <= 8:
            opts = raw_enum
        else:
            candidates = [3, 4, 5, 6, 8, 10, 12, 15, 20, 30]
            opts = [c for c in candidates if c in raw_enum] or raw_enum[:6]
        return {"min": dmin, "max": dmax, "enum": raw_enum, "options": opts}
    dmin = int(dspec.get("minimum") or 4)
    dmax = int(dspec.get("maximum") or 15)
    if dmax < dmin:
        dmax = dmin
    candidates = [3, 4, 5, 6, 8, 10, 12, 15, 20, 30]
    opts = [c for c in candidates if dmin <= c <= dmax]
    if not opts:
        opts = [dmin] if dmin == dmax else [dmin, dmax]
    return {"min": dmin, "max": dmax, "enum": None, "options": opts}


def _extract_resolutions(rec: Dict[str, Any]) -> List[str]:
    ospec = rec.get("outputSpecs") or {}
    res_enum = (ospec.get("resolution") or {}).get("enum") or []
    if res_enum:
        return [str(r) for r in res_enum if r]
    found: List[str] = []
    for v in ((rec.get("price") or {}).get("variants") or []):
        parsed = _parse_variant_key(str(v.get("variant") or ""))
        r = parsed.get("resolution") or parsed.get("_bare")
        if r and (r.endswith("p") or r.endswith("k")) and r not in found:
            found.append(r)
    return found


def studio_models(modality: str = "image", include_spicy: bool = True, only_allowed: bool = True) -> List[Dict[str, Any]]:
    """Family-grouped generation models for Photos & Videos UI, with dynamic options + credit pricing."""
    mod = (modality or "image").strip().lower()
    wanted = _VIDEO_GEN_TASKS if mod == "video" else _IMAGE_GEN_TASKS
    featured_order = FEATURED_VIDEO_FAMILIES if mod == "video" else FEATURED_IMAGE_FAMILIES
    allowed_set = set(featured_order) if only_allowed else None
    featured_idx = {fid: i for i, fid in enumerate(featured_order)}

    grouped: Dict[str, Dict[str, Any]] = {}
    for m in fetch_catalog():
        if m.get("modality") != mod or m.get("status") != "live" or not m.get("callable", True):
            continue
        tasks = set(m.get("tasks") or [])
        if not (tasks & wanted):
            continue
        spicy = bool(m.get("mature"))
        if spicy and not include_spicy:
            continue
        mid = m.get("model") or ""
        if "/" not in mid:
            continue
        fid = mid.rsplit("/", 1)[0]
        if allowed_set is not None and fid not in allowed_set:
            continue
        entry = grouped.setdefault(fid, {
            "id": fid,
            "label": m.get("familyDisplayName") or fid.split("/")[-1],
            "provider": m.get("provider") or "",
            "spicy": spicy,
            "featured": fid in featured_idx,
            "featured_rank": featured_idx.get(fid, 9999),
            "routes": {},
            "records": {},
        })
        if "text-to-image" in tasks or "text-to-video" in tasks:
            entry["routes"]["text"] = mid
            entry["records"]["text"] = m
        if "image-to-image" in tasks or "image-edit" in tasks:
            entry["routes"]["edit"] = mid
            entry["records"]["edit"] = m
        if "image-to-video" in tasks:
            entry["routes"]["image"] = mid
            entry["records"]["image"] = m
        if "reference-to-video" in tasks:
            entry["routes"]["reference"] = mid
            entry["records"]["reference"] = m
        if "video-extend" in tasks:
            entry["routes"]["extend"] = mid
            entry["records"]["extend"] = m

    out: List[Dict[str, Any]] = []
    for fid, g in grouped.items():
        routes = g["routes"]
        recs = g["records"]
        # Pick primary record for specs/pricing preview
        primary = (
            recs.get("text")
            or recs.get("image")
            or recs.get("edit")
            or recs.get("reference")
            or recs.get("extend")
        )
        if not primary:
            continue
        fields = set(primary.get("inputFields") or [])
        ospec = primary.get("outputSpecs") or {}
        resolutions = _extract_resolutions(primary)
        default_res = None
        pv = str((primary.get("price") or {}).get("variant") or "").strip()
        if pv and pv in resolutions:
            default_res = pv
        elif pv and "=" in pv:
            pv_res = _parse_variant_key(pv).get("resolution")
            if pv_res and pv_res in resolutions:
                default_res = pv_res
        if not default_res and resolutions:
            default_res = resolutions[0]
        if fid == "bytedance/seedream-5.5" and "2k" in resolutions:
            default_res = "2k"

        ar_enum = [str(a) for a in ((ospec.get("aspect_ratio") or {}).get("enum") or []) if a]
        dur_spec = _extract_duration_spec(primary) if mod == "video" else None

        # Precompute credit pricing table per resolution / duration for instant UI updates
        est_default = estimate_credits(
            primary["model"],
            modality=mod,
            resolution=default_res,
            duration=(dur_spec["options"][0] if dur_spec and dur_spec["options"] else 6) if mod == "video" else None,
        )
        res_credits: Dict[str, int] = {}
        for r in (resolutions or [""]):
            key = r or "default"
            e = estimate_credits(
                primary["model"],
                modality=mod,
                resolution=r or None,
                duration=(dur_spec["options"][0] if dur_spec and dur_spec["options"] else 6) if mod == "video" else None,
            )
            res_credits[key] = e["credits_per_unit"]

        dur_credits: Dict[str, Dict[str, int]] = {}
        if mod == "video" and dur_spec:
            for r in (resolutions or [""]):
                rkey = r or "default"
                dmap: Dict[str, int] = {}
                for d in dur_spec["options"]:
                    de = estimate_credits(primary["model"], modality="video", resolution=r or None, duration=d)
                    dmap[str(d)] = de["credits_total"]
                dur_credits[rkey] = dmap

        requires_ref = ("text" not in routes) and bool(routes.get("edit") or routes.get("image") or routes.get("reference"))
        text_only = ("text" in routes) and not (routes.get("edit") or routes.get("image") or routes.get("reference"))

        out.append({
            "id": fid,
            "default_model_id": primary["model"],
            "label": g["label"],
            "provider": g["provider"],
            "spicy": g["spicy"],
            "featured": g["featured"],
            "featured_rank": g["featured_rank"],
            "routes": routes,
            "tasks": sorted(routes.keys()),
            "requires_ref": requires_ref,
            "text_only": text_only,
            "resolutions": resolutions,
            "default_resolution": default_res,
            "aspect_ratios": ar_enum,
            "durations": dur_spec,
            "supports_audio": "generate_audio" in fields,
            "pricing": {
                "unit": est_default["unit"],
                "default_credits": est_default["credits_per_unit"],
                "sample_total": est_default["credits_total"],
                "by_resolution": res_credits,
                "by_duration": dur_credits,
            },
        })

    out.sort(key=lambda x: (
        0 if x["featured"] else 1,
        x["featured_rank"],
        0 if x["spicy"] else 1,
        x["label"].lower(),
    ))
    return out


def resolve_model_route(
    model_or_family: str,
    *,
    modality: str = "image",
    num_refs: int = 0,
    is_extend: bool = False,
) -> Tuple[str, Dict[str, Any]]:
    """Resolve a family id OR full model id to the best callable endpoint for the input refs."""
    raw = (model_or_family or "").strip()
    if not raw:
        raise SpicyError("No model specified.")

    # Direct model id match
    direct = catalog_record(raw)
    if direct:
        fid = raw.rsplit("/", 1)[0] if "/" in raw else raw
        tasks = set(direct.get("tasks") or [])
        if modality == "image":
            if num_refs > 0 and "text-to-image" in tasks:
                sib = catalog_record(f"{fid}/edit") or catalog_record(f"{fid}/image-to-image")
                if sib:
                    return sib["model"], sib
                raise SpicyError(f"{direct.get('familyDisplayName') or raw} is text-to-image only — remove reference photos or choose an Edit/Seedream model.")
            if num_refs == 0 and tasks & {"image-to-image", "image-edit"}:
                sib = catalog_record(f"{fid}/text-to-image")
                if sib:
                    return sib["model"], sib
                raise SpicyError(f"{direct.get('familyDisplayName') or raw} requires at least 1 reference photo.")
        elif modality == "video":
            if is_extend and "video-extend" not in tasks:
                sib = catalog_record(f"{fid}/video-extend")
                if sib:
                    return sib["model"], sib
                raise SpicyError(f"{direct.get('familyDisplayName') or raw} does not support video extend.")
            if num_refs >= 2 and "reference-to-video" not in tasks:
                sib = catalog_record(f"{fid}/reference-to-video") or catalog_record(f"{fid}/image-to-video")
                if sib:
                    return sib["model"], sib
            if num_refs == 1 and "image-to-video" not in tasks:
                sib = catalog_record(f"{fid}/image-to-video") or catalog_record(f"{fid}/reference-to-video")
                if sib:
                    return sib["model"], sib
            if num_refs == 0 and "text-to-video" not in tasks and not is_extend:
                sib = catalog_record(f"{fid}/text-to-video")
                if sib:
                    return sib["model"], sib
                raise SpicyError(f"{direct.get('familyDisplayName') or raw} requires at least 1 reference photo in References.")
        return direct["model"], direct

    # Family id match
    for fam in studio_models(modality, include_spicy=True, only_allowed=False):
        if fam["id"] == raw:
            routes = fam["routes"]
            if modality == "image":
                if num_refs > 0:
                    chosen = routes.get("edit")
                    if not chosen:
                        raise SpicyError(f"{fam['label']} is text-only — remove reference photos or pick Seedream / an Edit model.")
                else:
                    chosen = routes.get("text")
                    if not chosen:
                        raise SpicyError(f"{fam['label']} requires at least 1 reference photo.")
            else:
                if is_extend:
                    chosen = routes.get("extend")
                    if not chosen:
                        raise SpicyError(f"{fam['label']} does not support video extend.")
                elif num_refs >= 2:
                    chosen = routes.get("reference") or routes.get("image")
                    if not chosen:
                        raise SpicyError(f"{fam['label']} does not accept reference photos.")
                elif num_refs == 1:
                    chosen = routes.get("image") or routes.get("reference")
                    if not chosen:
                        raise SpicyError(f"{fam['label']} is text-to-video only — clear reference photos.")
                else:
                    chosen = routes.get("text")
                    if not chosen:
                        raise SpicyError(f"{fam['label']} requires at least 1 reference photo in References.")
            rec = catalog_record(chosen)
            if not rec:
                raise SpicyError(f"Model {chosen} not found in catalog.")
            return chosen, rec

    raise SpicyError(f"Unknown SpicyAPI model: {raw}")


def clamp_duration(model_id: str, duration: Any) -> int:
    try:
        d = int(duration or 6)
    except (TypeError, ValueError):
        d = 6
    rec = catalog_record(model_id)
    if not rec:
        return max(1, min(30, d))
    spec = _extract_duration_spec(rec)
    if spec.get("enum"):
        return min(spec["enum"], key=lambda x: abs(x - d))
    return max(spec["min"], min(spec["max"], d))


def build_image_input(
    model_id: str,
    prompt: str,
    *,
    image_urls: Optional[List[str]] = None,
    aspect_ratio: Optional[str] = None,
    resolution: Optional[str] = None,
) -> Dict[str, Any]:
    rec = catalog_record(model_id) or {}
    fields = set(rec.get("inputFields") or [])
    ospec = rec.get("outputSpecs") or {}
    inp: Dict[str, Any] = {}
    if not fields or "prompt" in fields:
        inp["prompt"] = (prompt or "").strip() or "high quality image"

    refs = [u for u in (image_urls or []) if u]
    if refs:
        if "image_urls" in fields:
            inp["image_urls"] = refs
        elif "reference_image_urls" in fields:
            inp["reference_image_urls"] = refs
        elif "image_url" in fields:
            inp["image_url"] = refs[0]

    res_enum = _extract_resolutions(rec)
    if resolution and ("resolution" in fields or not fields):
        if not res_enum or resolution in res_enum:
            inp["resolution"] = resolution

    ar = (aspect_ratio or "").strip()
    if ar and ar.lower() != "auto":
        if "aspect_ratio" in fields:
            ar_enum = (ospec.get("aspect_ratio") or {}).get("enum") or []
            if not ar_enum or ar in ar_enum:
                inp["aspect_ratio"] = ar
        elif "width" in fields and "height" in fields and ar in _ASPECT_DIMS:
            w, h = _ASPECT_DIMS[ar]
            inp["width"] = w
            inp["height"] = h
    return inp


def build_video_input(
    model_id: str,
    prompt: str,
    *,
    image_url: Optional[str] = None,
    reference_images: Optional[List[str]] = None,
    video_url: Optional[str] = None,
    duration: int = 6,
    resolution: Optional[str] = None,
    aspect_ratio: Optional[str] = None,
    generate_audio: Optional[bool] = None,
) -> Dict[str, Any]:
    rec = catalog_record(model_id) or {}
    fields = set(rec.get("inputFields") or [])
    ospec = rec.get("outputSpecs") or {}
    inp: Dict[str, Any] = {}
    if not fields or "prompt" in fields:
        inp["prompt"] = (prompt or "").strip() or "animate this"

    dur = clamp_duration(model_id, duration)
    if "duration_seconds" in fields or not fields:
        inp["duration_seconds"] = dur

    refs = [u for u in (reference_images or []) if u]
    if not refs and image_url:
        refs = [image_url]

    if video_url and "video_url" in fields:
        inp["video_url"] = video_url

    if refs:
        if "reference_image_urls" in fields:
            inp["reference_image_urls"] = refs
        elif "image_urls" in fields:
            inp["image_urls"] = refs
        elif "image_url" in fields:
            inp["image_url"] = refs[0]

    res_enum = _extract_resolutions(rec)
    if resolution and "resolution" in fields:
        if not res_enum or resolution in res_enum:
            inp["resolution"] = resolution

    ar = (aspect_ratio or "").strip()
    if ar and ar.lower() != "auto" and "aspect_ratio" in fields:
        ar_enum = (ospec.get("aspect_ratio") or {}).get("enum") or []
        if not ar_enum or ar in ar_enum:
            inp["aspect_ratio"] = ar

    if generate_audio is not None and "generate_audio" in fields:
        inp["generate_audio"] = bool(generate_audio)

    return inp


# --- keyed catalog + quote --------------------------------------------------
def list_models(modality: Optional[str] = None, task: Optional[str] = None,
                include_schema: bool = False, include_examples: bool = False) -> List[Dict[str, Any]]:
    """Models THIS key can actually call (the only source of truth for callable IDs)."""
    q = []
    if modality:
        q.append(f"modality={modality}")
    if task:
        q.append(f"task={task}")
    if include_schema:
        q.append("includeSchema=1")
    if include_examples:
        q.append("includeExamples=1")
    data = _call("GET", "/models" + ("?" + "&".join(q) if q else ""))
    return data.get("items") or []


def model_record(model_id: str) -> Dict[str, Any]:
    return _call("GET", f"/models/{model_id}")


def quote(model: str, input: Dict[str, Any]) -> Dict[str, Any]:
    """Exact price for this exact request (authoritative — set credit cost from this)."""
    return _call("POST", "/jobs/quote", json={"model": model, "input": input})


def credit_balance() -> Dict[str, Any]:
    r = requests.get(f"{API}/chat/credit", headers=_headers(), timeout=30)
    try:
        body = r.json()
    except Exception:
        raise SpicyError(f"credit check -> {r.status_code}")
    if body.get("code") != 200:
        raise SpicyError(f'{body.get("code")} {body.get("msg")}')
    return body.get("data") or {}


# --- submit / poll ----------------------------------------------------------
def create_task(model: str, input: Dict[str, Any], *, idempotency_key: Optional[str] = None,
                call_back_url: Optional[str] = None) -> str:
    """Submit a generation task. Returns taskId. Pass call_back_url for webhook delivery."""
    body: Dict[str, Any] = {"model": model, "input": input}
    if call_back_url:
        body["callBackUrl"] = call_back_url
    data = _call("POST", "/jobs/createTask",
                 idempotency_key=idempotency_key or str(uuid.uuid4()), json=body)
    tid = data.get("taskId") or data.get("task_id")
    if not tid:
        raise SpicyError(f"createTask returned no taskId: {data}")
    return tid


def record_info(task_id: str) -> Dict[str, Any]:
    return _call("GET", "/jobs/recordInfo", params={"taskId": task_id})


def wait_for_task(
    task_id: str,
    timeout_s: int = 600,
    *,
    progress_cb: Optional[Callable[[int, str], None]] = None,
) -> List[str]:
    """Poll with backoff (2s×1.5, cap 15s) until terminal. Returns asset URLs. Webhooks are better in prod."""
    deadline = time.monotonic() + timeout_s
    wait = 2.0
    polls = 0
    while time.monotonic() < deadline:
        time.sleep(wait)
        wait = min(wait * 1.5, 15.0)
        polls += 1
        task = record_info(task_id)
        st = task.get("state")
        if progress_cb is not None:
            try:
                raw_pct = task.get("progress")
                if raw_pct is not None:
                    pct = int(float(raw_pct) * (100 if float(raw_pct) <= 1 else 1))
                elif st == "queued":
                    pct = 10
                elif st == "running":
                    pct = min(88, 25 + polls * 8)
                else:
                    pct = 95
                progress_cb(pct, "Rendering…" if st == "running" else ("In queue…" if st == "queued" else str(st or "")))
            except Exception:
                pass
        if st == "succeeded":
            assets = (task.get("output") or {}).get("assets") or []
            urls = [a["url"] for a in assets if a.get("url")]
            if urls:
                if progress_cb is not None:
                    try:
                        progress_cb(100, "Done")
                    except Exception:
                        pass
                return urls
            if any(a.get("pending") for a in assets):
                continue
            raise SpicyError("task succeeded but result is unavailable")
        if st not in ("queued", "running"):
            raise SpicyError(f'{st}: {task.get("errorMessage", "no detail")}')
    raise SpicyError(f"task {task_id} timed out after {timeout_s}s")


def generate(model: str, input: Dict[str, Any], *, call_back_url: Optional[str] = None,
             idempotency_key: Optional[str] = None, timeout_s: int = 600,
             progress_cb: Optional[Callable[[int, str], None]] = None) -> Dict[str, Any]:
    """Create a task and (unless a webhook is given) wait for the result.
    Returns {task_id, urls} — urls is [] when call_back_url is set (result arrives by webhook)."""
    tid = create_task(model, input, idempotency_key=idempotency_key, call_back_url=call_back_url)
    if call_back_url:
        return {"task_id": tid, "urls": [], "webhook": True}
    return {"task_id": tid, "urls": wait_for_task(tid, timeout_s, progress_cb=progress_cb)}


# --- convenience wrappers (input shape is per-model; see model examples/schema) ---
def generate_image(model: str, prompt: str, *, image_urls: Optional[List[str]] = None,
                   call_back_url: Optional[str] = None, **params) -> Dict[str, Any]:
    inp: Dict[str, Any] = {"prompt": prompt, **params}
    if image_urls:
        inp["image_urls"] = image_urls
    return generate(model, inp, call_back_url=call_back_url)


def generate_video(model: str, *, prompt: Optional[str] = None, image_url: Optional[str] = None,
                   call_back_url: Optional[str] = None, timeout_s: int = 1200, **params) -> Dict[str, Any]:
    inp: Dict[str, Any] = {**params}
    if prompt:
        inp["prompt"] = prompt
    if image_url:
        inp["image_url"] = image_url
    return generate(model, inp, call_back_url=call_back_url, timeout_s=timeout_s)


if __name__ == "__main__":
    import json
    print("IMAGE dropdown (public, no key):")
    print(json.dumps(dropdown_models("image")[:6], indent=2))
    print("enabled (key set):", enabled())
