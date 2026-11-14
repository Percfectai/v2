"""
tripo_pipeline.py — Build a rigged + animated character with Tripo (v2 openapi).

Pipeline (Nick's spec: BUILD → 360 → multi-img → Tripo 3D GLB → FBX ANIMATED RIGGED →
agent controls the rig → Three.js board → chat):

    4 view images (front required + at least one more)
        → multiview_to_model      (static textured mesh)
        → animate_prerigcheck     (is it riggable? what rig type?)
        → animate_rig             (Tripo rigs it for free — biped skeleton)
        → animate_retarget        (preset clips, batched ≤5 per call)
        → download                (rigged GLB + animated GLB(s) carrying the clips)

The rigged GLB drops onto Gemini's three.js board; static/js/rivals/character_controller.js
plays the clips.

Tripo only (Meshy retired for this flow). Rigging is Tripo's built-in step — we do NOT roll
our own. Key: TRIPO_API_KEY in the environment (never hardcoded, never committed).

⚠️ RUNTIME: build_animated_character() blocks for minutes (each stage polls up to 15 min).
   Do NOT call it directly from a Flask request — run it in the background job runner and let
   the page poll a status, the same way three_d_character_gen does its PoYo jobs.

Docs: Tripo v2 openapi — /upload, /task, /task/{id};
      animate_prerigcheck / animate_rig (v2.5-20260210) / animate_retarget.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import socket
import time
import uuid
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

log = logging.getLogger("tripo_pipeline")

TRIPO_BASE = (os.environ.get("TRIPO_API_BASE") or "https://api.tripo3d.ai/v2/openapi").rstrip("/")
RIG_MODEL_VERSION = "v2.5-20260210"          # v2.0 is offline; must use v2.5
VIEW_ORDER = ("front", "left", "back", "right")
MAX_PRESETS_PER_RETARGET = 5                 # Tripo retarget cap; we batch above this

# Fighter set → Tripo v2.5 biped presets. block/attack_heavy have no v2.5 preset →
# the controller's procedural motion covers them.
ANIMATION_SET: Dict[str, str] = {
    "idle": "preset:idle",
    "walk": "preset:walk",
    "run": "preset:run",
    "jump": "preset:jump",
    "attack_light": "preset:slash",
    "hit_react": "preset:hurt",
    "ko": "preset:fall",
    "dodge": "preset:dive",
}
DEMO_SET = ["idle", "walk", "run", "jump", "attack_light"]
FULL_SET = list(ANIMATION_SET.keys())

POLL_INTERVAL_S = 4
POLL_TIMEOUT_S = 900
_RETRIES = 3
_CONTENT_TYPES = {
    b"\xff\xd8\xff": ("jpeg", "image/jpeg"),
    b"\x89PNG": ("png", "image/png"),
    b"RIFF": ("webp", "image/webp"),   # RIFF....WEBP
}


class TripoError(RuntimeError):
    pass


def _key() -> str:
    tok = (os.environ.get("TRIPO_API_KEY") or "").strip()
    if not tok:
        raise TripoError("TRIPO_API_KEY is not set (put it in the environment, never in code).")
    return tok


def _headers(json: bool = False) -> dict:
    h = {"Authorization": f"Bearer {_key()}"}
    if json:
        h["Content-Type"] = "application/json"
    return h


def _req(method: str, url: str, **kw) -> requests.Response:
    """HTTP with small retries for transient errors and 429 backoff (honors Retry-After)."""
    last_exc: Optional[Exception] = None
    for attempt in range(_RETRIES):
        try:
            r = requests.request(method, url, timeout=kw.pop("timeout", 60), **kw)
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code == 429:
            wait_s = float(r.headers.get("Retry-After") or (2 * (attempt + 1)))
            log.warning("tripo 429; backing off %ss", wait_s)
            time.sleep(min(wait_s, 30))
            continue
        return r
    if last_exc:
        raise TripoError(f"network error after {_RETRIES} tries: {last_exc}")
    raise TripoError("rate limited after retries")


def _post_task(payload: dict) -> str:
    r = _req("POST", f"{TRIPO_BASE}/task", headers=_headers(json=True), json=payload)
    if not r.ok:
        raise TripoError(f"task create failed ({r.status_code}): {r.text[:300]}")
    data = (r.json() or {}).get("data") or {}
    tid = data.get("task_id") or data.get("id")
    if not tid:
        raise TripoError(f"task create returned no id: {r.text[:300]}")
    return tid


# --- image upload (SSRF-guarded) -------------------------------------------
def _allowed_image_hosts() -> set:
    hosts = set()
    extra = os.environ.get("TRIPO_ALLOWED_IMAGE_HOSTS") or ""
    for h in extra.split(","):
        h = h.strip().lower()
        if h:
            hosts.add(h)
    for env in ("PUBLIC_BASE_URL", "SITE_URL", "SUPABASE_URL"):
        v = (os.environ.get(env) or "").strip()
        if v:
            host = urlparse(v if "//" in v else "https://" + v).hostname
            if host:
                hosts.add(host.lower())
    return hosts


def _host_is_private(host: str) -> bool:
    try:
        for res in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(res[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return True
    except Exception:
        return True  # unresolvable → treat as unsafe
    return False


def _check_image_url(url: str) -> None:
    """Only fetch images from the site's own hosts; block internal/loopback addresses."""
    p = urlparse(url or "")
    if p.scheme not in ("http", "https") or not p.hostname:
        raise TripoError(f"refusing non-http(s) image url: {url[:80]}")
    host = p.hostname.lower()
    allowed = _allowed_image_hosts()
    if not allowed:
        raise TripoError("no allowed image hosts configured (set SITE_URL/PUBLIC_BASE_URL/SUPABASE_URL "
                         "or TRIPO_ALLOWED_IMAGE_HOSTS) — refusing to fetch arbitrary URLs")
    if not any(host == a or host.endswith("." + a) for a in allowed):
        raise TripoError(f"image host not allowed: {host}")
    if _host_is_private(host):
        raise TripoError(f"image host resolves to a private address: {host}")


def _sniff_type(content: bytes) -> Tuple[str, str]:
    for magic, (t, ct) in _CONTENT_TYPES.items():
        if content[:len(magic)] == magic:
            if t == "webp" and content[8:12] != b"WEBP":
                continue
            return t, ct
    return "jpeg", "image/jpeg"  # default


def upload_image(url: str) -> Dict[str, str]:
    """Upload a site-hosted image URL or local file path to Tripo; return {file_token, type}."""
    # Check if it's a local file path (no http/https scheme)
    p = urlparse(url or "")
    if p.scheme in ("", "file") or (p.scheme == "" and os.path.isfile(url)):
        # Local file path
        if not os.path.isfile(url):
            raise TripoError(f"local file not found: {url}")
        with open(url, "rb") as f:
            img_content = f.read()
    else:
        # URL — check and fetch
        _check_image_url(url)
        img = _req("GET", url, timeout=60)
        if not img.ok:
            raise TripoError(f"could not fetch view image {url[:80]} ({img.status_code})")
        img_content = img.content

    ftype, ctype = _sniff_type(img_content)
    files = {"file": (f"{uuid.uuid4().hex}.{ftype}", img_content, ctype)}
    r = _req("POST", f"{TRIPO_BASE}/upload", headers=_headers(), files=files)
    if not r.ok:
        raise TripoError(f"upload failed ({r.status_code}): {r.text[:300]}")
    data = (r.json() or {}).get("data") or {}
    token = data.get("image_token") or data.get("file_token") or data.get("token")
    if not token:
        raise TripoError(f"upload returned no token: {r.text[:300]}")
    return {"file_token": token, "type": ftype}


# --- polling ----------------------------------------------------------------
def get_task(task_id: str) -> dict:
    r = _req("GET", f"{TRIPO_BASE}/task/{task_id}", headers=_headers(), timeout=30)
    if not r.ok:
        raise TripoError(f"task query failed ({r.status_code}): {r.text[:300]}")
    return (r.json() or {}).get("data") or {}


def wait(task_id: str, label: str = "task") -> dict:
    """Poll until finalized; return the task's full data dict. Raise on failure."""
    deadline = time.time() + POLL_TIMEOUT_S
    while time.time() < deadline:
        data = get_task(task_id)
        status = (data.get("status") or "").lower()
        if status == "success":
            return data
        if status in ("failed", "banned", "expired", "cancelled", "unknown"):
            raise TripoError(f"{label} {task_id} {status}: {data.get('output') or data}")
        log.info("tripo %s %s… %s%%", label, status, data.get("progress", 0))
        time.sleep(POLL_INTERVAL_S)
    raise TripoError(f"{label} {task_id} timed out after {POLL_TIMEOUT_S}s")


# --- pipeline steps ---------------------------------------------------------
def start_multiview_to_model(views: Dict[str, str]) -> str:
    """views = {front,left,back,right: site image URL}. Tripo needs front + at least one more."""
    present = [v for v in VIEW_ORDER if views.get(v)]
    if "front" not in present or len(present) < 2:
        raise TripoError("multiview_to_model needs 'front' plus at least one other view")
    files = []
    for v in VIEW_ORDER:
        u = views.get(v)
        if u:
            up = upload_image(u)
            files.append({"type": up["type"], "file_token": up["file_token"]})
        else:
            files.append({})  # keep 4 entries in order; omitted view = empty entry
    return _post_task({"type": "multiview_to_model", "files": files})


def prerig_check(model_task_id: str) -> Tuple[bool, str, dict]:
    """Return (riggable, rig_type, raw_output). `riggable` location is not firmly documented —
    we log the raw output so the first live run confirms it."""
    tid = _post_task({"type": "animate_prerigcheck", "original_model_task_id": model_task_id})
    data = wait(tid, "prerigcheck")
    out = data.get("output") or {}
    log.info("tripo prerigcheck raw output: %s", out)
    riggable = out.get("riggable")
    if riggable is None:  # tolerate alternative shapes until confirmed live
        riggable = out.get("is_riggable", data.get("riggable"))
    return bool(riggable), (out.get("rig_type") or "biped"), out


def rig(model_task_id: str, out_format: str = "glb", rig_type: str = "biped") -> str:
    return _post_task({
        "type": "animate_rig",
        "original_model_task_id": model_task_id,
        "model_version": RIG_MODEL_VERSION,
        "out_format": out_format,
        "rig_type": rig_type,
        "spec": "tripo",  # only 'tripo' spec supports retarget
    })


def retarget(rig_task_id: str, animations: List[str], out_format: str = "glb",
             bake: bool = True, in_place: bool = False) -> Tuple[str, List[str]]:
    """Apply up to 5 preset clips. Returns (task_id, clip_names_actually_sent)."""
    names = animations[:MAX_PRESETS_PER_RETARGET]
    presets = [ANIMATION_SET.get(a, a) for a in names]
    payload = {
        "type": "animate_retarget",
        "original_model_task_id": rig_task_id,
        "out_format": out_format,
        "export_with_geometry": True,
        "animate_in_place": in_place,
        "animations": presets,
    }
    if out_format == "glb":
        payload["bake_animation"] = bake
    return _post_task(payload), names


def _model_url(data: dict) -> Optional[str]:
    out = data.get("output") or {}
    for k in ("model", "pbr_model", "base_model"):
        u = out.get(k)
        if isinstance(u, str) and u.startswith("http"):
            return u
    return None


def download(url: str, dest_dir: str, name: str) -> str:
    os.makedirs(dest_dir, exist_ok=True)
    ext = ".fbx" if ".fbx" in url.lower() else ".glb"
    path = os.path.join(dest_dir, f"{name}{ext}")
    r = _req("GET", url, timeout=120)
    if not r.ok:
        raise TripoError(f"download failed ({r.status_code}) for {url[:80]}")
    with open(path, "wb") as f:
        f.write(r.content)
    return path


def _chunks(seq: List[str], n: int) -> List[List[str]]:
    return [seq[i:i + n] for i in range(0, len(seq), n)]


# --- orchestration (run in a background job, NOT a web request) -------------
def build_animated_character(
    views: Dict[str, str],
    animation_set: Optional[List[str]] = None,
    out_format: str = "glb",
    dest_dir: Optional[str] = None,
    character_id: Optional[str] = None,
) -> Dict[str, object]:
    """
    Full pipeline: views → rigged + animated character.

    Returns {
      "character_id", "model_task_id", "rig_task_id", "riggable", "rig_type",
      "rigged_url", "rigged_path",
      "animated": [ {"url", "path"?, "clips": [names actually applied]} , ... ],   # one per ≤5 batch
    }
    Only clips that were actually applied are reported. If the mesh is not riggable, returns the
    static model as rigged_url with animated=[].
    """
    wanted = animation_set or DEMO_SET
    cid = character_id or uuid.uuid4().hex[:12]
    result: Dict[str, object] = {"character_id": cid, "animated": []}

    model_task_id = start_multiview_to_model(views)
    wait(model_task_id, "multiview_to_model")
    result["model_task_id"] = model_task_id

    riggable, rig_type, _raw = prerig_check(model_task_id)
    result["riggable"] = riggable
    result["rig_type"] = rig_type
    if not riggable:
        static = wait(model_task_id, "multiview_to_model")
        result["rigged_url"] = _model_url(static)
        if dest_dir and result["rigged_url"]:
            result["rigged_path"] = download(result["rigged_url"], dest_dir, f"{cid}_static")
        return result

    rig_task_id = rig(model_task_id, out_format=out_format, rig_type=rig_type)
    rig_data = wait(rig_task_id, "animate_rig")
    result["rig_task_id"] = rig_task_id
    log.info(f"TASK_IDS: model={result['model_task_id']} rig={rig_task_id}")
    result["rigged_url"] = _model_url(rig_data)
    if dest_dir and result["rigged_url"]:
        result["rigged_path"] = download(result["rigged_url"], dest_dir, f"{cid}_rigged")

    # Batch the clip set in chunks of 5 — one retarget task per chunk.
    animated: List[Dict[str, object]] = []
    for i, chunk in enumerate(_chunks(wanted, MAX_PRESETS_PER_RETARGET)):
        rt_id, clips = retarget(rig_task_id, chunk, out_format=out_format)
        rt_data = wait(rt_id, f"animate_retarget[{i}]")
        url = _model_url(rt_data)
        entry: Dict[str, object] = {"url": url, "clips": clips}
        if dest_dir and url:
            entry["path"] = download(url, dest_dir, f"{cid}_anim{i}")
        animated.append(entry)
    result["animated"] = animated
    return result


if __name__ == "__main__":
    # Smoke CLI:  python tripo_pipeline.py <front_url> [left] [back] [right]
    import json
    import sys

    urls = sys.argv[1:]
    if len(urls) < 2:
        print("usage: python tripo_pipeline.py <front_url> <another_view_url> [back_url] [right_url]")
        print("needs TRIPO_API_KEY + an allowed image host (SITE_URL / TRIPO_ALLOWED_IMAGE_HOSTS).")
        raise SystemExit(1)
    logging.basicConfig(level=logging.INFO)
    v = dict(zip(VIEW_ORDER, urls))
    out = build_animated_character(v, animation_set=DEMO_SET, dest_dir="assets_3d/characters")
    print(json.dumps(out, indent=2, default=str))
