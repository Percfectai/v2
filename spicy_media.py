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

import os
import time
import uuid
import logging
from typing import Any, Dict, List, Optional

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


def wait_for_task(task_id: str, timeout_s: int = 600) -> List[str]:
    """Poll with backoff (2s×1.5, cap 15s) until terminal. Returns asset URLs. Webhooks are better in prod."""
    deadline = time.monotonic() + timeout_s
    wait = 2.0
    while time.monotonic() < deadline:
        time.sleep(wait)
        wait = min(wait * 1.5, 15.0)
        task = record_info(task_id)
        st = task.get("state")
        if st == "succeeded":
            assets = (task.get("output") or {}).get("assets") or []
            urls = [a["url"] for a in assets if a.get("url")]
            if urls:
                return urls
            if any(a.get("pending") for a in assets):
                continue
            raise SpicyError("task succeeded but result is unavailable")
        if st not in ("queued", "running"):
            raise SpicyError(f'{st}: {task.get("errorMessage", "no detail")}')
    raise SpicyError(f"task {task_id} timed out after {timeout_s}s")


def generate(model: str, input: Dict[str, Any], *, call_back_url: Optional[str] = None,
             idempotency_key: Optional[str] = None, timeout_s: int = 600) -> Dict[str, Any]:
    """Create a task and (unless a webhook is given) wait for the result.
    Returns {task_id, urls} — urls is [] when call_back_url is set (result arrives by webhook)."""
    tid = create_task(model, input, idempotency_key=idempotency_key, call_back_url=call_back_url)
    if call_back_url:
        return {"task_id": tid, "urls": [], "webhook": True}
    return {"task_id": tid, "urls": wait_for_task(tid, timeout_s)}


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
