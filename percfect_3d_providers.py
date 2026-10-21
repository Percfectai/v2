"""Swappable 3D engines behind "PercfectAI v1" — four shots in, one GLB out.

Pick the engine with env PERCFECT_3D_PROVIDER = meshy | tripo | replicate
(default meshy). Each engine exposes:
    start(views)      -> provider task id      (views = {front,left,back,right} public URLs)
    poll(task_id)     -> (status, glb_url, error)   status: running | success | failed

Customers never see any of these names; the API always reports "PercfectAI v1".
Keys (set on Render, only the chosen engine's key is needed):
    meshy     POYO_API_KEY                         (Meshy-6 multi-image via PoYo)
    tripo     TRIPO_API_KEY                        (Tripo multiview-to-model)
    replicate REPLICATE_API_TOKEN + REPLICATE_3D_MODEL (default firtoz/trellis)
"""
import os
from typing import Optional, Tuple

import requests

VIEW_ORDER = ("front", "back", "left", "right")


def current() -> str:
    return (os.environ.get("PERCFECT_3D_PROVIDER") or "meshy").strip().lower()


def start(provider: str, views: dict) -> str:
    return _ENGINES[provider]["start"](views)


def poll(provider: str, task_id: str) -> Tuple[str, Optional[str], Optional[str]]:
    return _ENGINES[provider]["poll"](task_id)


def _ordered_urls(views: dict) -> list:
    return [views[v] for v in VIEW_ORDER if views.get(v)]


def _find_glb(obj) -> Optional[str]:
    """Walk any JSON shape and return the first .glb (or any model) URL."""
    found_any = [None]

    def walk(x):
        if isinstance(x, str):
            if x.startswith("http"):
                low = x.split("?")[0].lower()
                if low.endswith(".glb"):
                    return x
                if any(low.endswith(e) for e in (".gltf", ".fbx", ".obj", ".usdz")) and not found_any[0]:
                    found_any[0] = x
            return None
        if isinstance(x, dict):
            for v in x.values():
                hit = walk(v)
                if hit:
                    return hit
        if isinstance(x, list):
            for v in x:
                hit = walk(v)
                if hit:
                    return hit
        return None

    return walk(obj) or found_any[0]


# ---------------------------- Meshy-6 (via PoYo) ----------------------------

def _meshy_start(views: dict) -> str:
    import poyo_client
    data = poyo_client.create_meshy_task(image_urls=_ordered_urls(views), options={"name": "percfect-api"})
    return poyo_client._task_id_from_create(data)


def _meshy_poll(task_id: str):
    import poyo_client
    data = poyo_client.get_task(task_id)
    st = poyo_client._status_of(data)
    if st in {"failed", "error", "canceled", "cancelled", "rejected"}:
        inner = data.get("data") if isinstance(data.get("data"), dict) else {}
        return "failed", None, str(inner.get("error_message") or data.get("error") or st)
    if st in {"succeeded", "success", "completed", "complete", "done", "finished"}:
        glb = poyo_client._output_glb_url(data) or _find_glb(data)
        return ("success", glb, None) if glb else ("failed", None, "no GLB came back")
    return "running", None, None


# ---------------------------- Tripo ----------------------------

TRIPO_BASE = (os.environ.get("TRIPO_API_BASE") or "https://api.tripo3d.ai/v2/openapi").rstrip("/")


def _tripo_headers():
    tok = (os.environ.get("TRIPO_API_KEY") or "").strip()
    if not tok:
        raise RuntimeError("TRIPO_API_KEY is not set")
    return {"Authorization": f"Bearer {tok}"}


def _tripo_upload(url: str) -> str:
    img = requests.get(url, timeout=120)
    img.raise_for_status()
    r = requests.post(f"{TRIPO_BASE}/upload", headers=_tripo_headers(),
                      files={"file": ("view.jpg", img.content, "image/jpeg")}, timeout=120)
    r.raise_for_status()
    data = (r.json() or {}).get("data") or {}
    tok = data.get("image_token") or data.get("file_token") or data.get("token")
    if not tok:
        raise RuntimeError(f"Tripo upload returned no token: {str(r.text)[:200]}")
    return tok


def _tripo_start(views: dict) -> str:
    files = [{"type": "jpeg", "file_token": _tripo_upload(views[v])}
             for v in VIEW_ORDER if views.get(v)]
    r = requests.post(f"{TRIPO_BASE}/task", headers={**_tripo_headers(), "Content-Type": "application/json"},
                      json={"type": "multiview_to_model", "files": files}, timeout=60)
    r.raise_for_status()
    body = r.json() or {}
    task_id = (body.get("data") or {}).get("task_id") or body.get("task_id")
    if not task_id:
        raise RuntimeError(f"Tripo task create returned no id: {str(r.text)[:200]}")
    return str(task_id)


def _tripo_poll(task_id: str):
    r = requests.get(f"{TRIPO_BASE}/task/{task_id}", headers=_tripo_headers(), timeout=30)
    r.raise_for_status()
    data = (r.json() or {}).get("data") or {}
    st = str(data.get("status") or "").lower()
    if st in {"failed", "cancelled", "canceled", "error", "banned", "expired"}:
        return "failed", None, str(data.get("error") or st)
    if st in {"success", "succeeded", "completed", "done"}:
        glb = _find_glb(data.get("output") or data.get("result") or data)
        return ("success", glb, None) if glb else ("failed", None, "no GLB came back")
    return "running", None, None


# ---------------------------- Replicate ----------------------------

REPLICATE_API = "https://api.replicate.com/v1"


def _rep_headers():
    tok = (os.environ.get("REPLICATE_API_TOKEN") or os.environ.get("REPLICATE_API_KEY") or "").strip()
    if not tok:
        raise RuntimeError("REPLICATE_API_TOKEN is not set")
    return {"Authorization": f"Token {tok}", "Content-Type": "application/json"}


def _rep_input(views: dict) -> dict:
    """Default TRELLIS-style multi-image input; override the images field name with
    REPLICATE_3D_IMAGES_KEY and add/replace fields with REPLICATE_3D_EXTRA_INPUT (JSON)."""
    import json
    urls = _ordered_urls(views)
    images_key = (os.environ.get("REPLICATE_3D_IMAGES_KEY") or "images").strip()
    inp = {images_key: urls, "image": urls[0], "generate_model": True}
    extra = (os.environ.get("REPLICATE_3D_EXTRA_INPUT") or "").strip()
    if extra:
        try:
            inp.update(json.loads(extra))
        except Exception:
            pass
    return inp


def _rep_start(views: dict) -> str:
    model = (os.environ.get("REPLICATE_3D_MODEL") or "firtoz/trellis").strip()
    if ":" in model:  # owner/name:version
        version = model.split(":", 1)[1]
    else:
        owner, _, name = model.partition("/")
        meta = requests.get(f"{REPLICATE_API}/models/{owner}/{name}", headers=_rep_headers(), timeout=30)
        meta.raise_for_status()
        version = ((meta.json() or {}).get("latest_version") or {}).get("id")
        if not version:
            raise RuntimeError(f"Replicate model {model} has no latest_version")
    r = requests.post(f"{REPLICATE_API}/predictions", headers=_rep_headers(),
                      json={"version": version, "input": _rep_input(views)}, timeout=60)
    if not r.ok:
        raise RuntimeError(f"Replicate create failed HTTP {r.status_code}: {(r.text or '')[:300]}")
    pid = (r.json() or {}).get("id")
    if not pid:
        raise RuntimeError("Replicate create returned no prediction id")
    return str(pid)


def _rep_poll(task_id: str):
    r = requests.get(f"{REPLICATE_API}/predictions/{task_id}", headers=_rep_headers(), timeout=30)
    r.raise_for_status()
    body = r.json() or {}
    st = str(body.get("status") or "").lower()
    if st in {"failed", "canceled", "cancelled"}:
        return "failed", None, str(body.get("error") or st)
    if st == "succeeded":
        glb = _find_glb(body.get("output"))
        return ("success", glb, None) if glb else ("failed", None, "no GLB came back")
    return "running", None, None


_ENGINES = {
    "meshy": {"start": _meshy_start, "poll": _meshy_poll},
    "tripo": {"start": _tripo_start, "poll": _tripo_poll},
    "replicate": {"start": _rep_start, "poll": _rep_poll},
}
