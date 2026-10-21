"""WAN 2.2 on Replicate (not fal).

Models:
  T2V: wan-video/wan-2.2-t2v-fast
  I2V: wan-video/wan-2.2-i2v-fast

Auth: REPLICATE_API_TOKEN (or REPLICATE_API_KEY)

No fal. Product places this LAST under Extend on Videos page.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

import requests

REPLICATE_API = "https://api.replicate.com/v1"
MODEL_T2V = "wan-video/wan-2.2-t2v-fast"
MODEL_I2V = "wan-video/wan-2.2-i2v-fast"
MODEL_ID = "wan-2.2"


class ReplicateWanError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(_token())


def _token() -> str:
    return (
        (os.getenv("REPLICATE_API_TOKEN") or "").strip()
        or (os.getenv("REPLICATE_API_KEY") or "").strip()
    )


def _headers() -> Dict[str, str]:
    tok = _token()
    if not tok:
        raise ReplicateWanError("REPLICATE_API_TOKEN is not set")
    return {
        "Authorization": f"Token {tok}",
        "Content-Type": "application/json",
        "Prefer": "wait=60",
    }


def _extract_url(output: Any) -> Optional[str]:
    if output is None:
        return None
    if isinstance(output, str) and output.startswith("http"):
        return output
    if isinstance(output, list):
        for item in output:
            u = _extract_url(item)
            if u:
                return u
    if isinstance(output, dict):
        for k in ("url", "video", "output", "mp4"):
            if k in output:
                u = _extract_url(output[k])
                if u:
                    return u
    # File-like object from replicate package
    url = getattr(output, "url", None)
    if isinstance(url, str) and url.startswith("http"):
        return url
    return None


# Nick: WAN clip length is fixed — no other choice
WAN_DURATION_SEC = 200
# Poll long enough for a long job
WAN_MAX_WAIT_SEC = 900.0


def generate_video_wan_replicate(
    prompt: str,
    *,
    image_url: Optional[str] = None,
    duration: int = WAN_DURATION_SEC,
    max_wait_sec: float = WAN_MAX_WAIT_SEC,
) -> Dict[str, Any]:
    """Run WAN 2.2 on Replicate. Returns {url, video: {url}, model}.

    Duration is forced to 200 seconds (product law).
    """
    prompt = (prompt or "").strip()
    if not prompt:
        raise ReplicateWanError("Prompt is required")

    # Force 200s — ignore caller choices
    duration = WAN_DURATION_SEC
    max_wait_sec = max(float(max_wait_sec or WAN_MAX_WAIT_SEC), WAN_MAX_WAIT_SEC)

    # Prefer official package when available
    try:
        import replicate as rep  # type: ignore
    except ImportError:
        rep = None

    model = MODEL_I2V if (image_url or "").strip() else MODEL_T2V

    # Minimal input; pass num_frames if schema accepts (approx 200s @ 16fps → 3200 is out of range
    # for many WAN builds). Duration is product-locked; model may clamp frames internally.
    clean: Dict[str, Any] = {"prompt": prompt}
    if image_url:
        clean["image"] = image_url.strip()
    # Some WAN schemas use seconds / duration / num_frames
    clean["duration"] = duration
    clean["seconds"] = duration

    if rep is not None:
        os.environ.setdefault("REPLICATE_API_TOKEN", _token())
        try:
            # Prefer minimal prompt+image first if duration fields 422
            try:
                output = rep.run(model, input=clean)
            except Exception:
                minimal = {"prompt": prompt}
                if image_url:
                    minimal["image"] = image_url.strip()
                output = rep.run(model, input=minimal)
            url = _extract_url(output)
            if not url:
                raise ReplicateWanError(f"Replicate returned no video URL: {type(output)}")
            return {
                "url": url,
                "video": {"url": url},
                "model": MODEL_ID,
                "provider": "replicate",
                "duration": duration,
            }
        except Exception as e:
            last_pkg_err = str(e)
    else:
        last_pkg_err = "replicate package not installed"

    # Raw HTTP predictions API
    owner, name = model.split("/", 1)
    meta = requests.get(
        f"{REPLICATE_API}/models/{owner}/{name}",
        headers=_headers(),
        timeout=30,
    )
    if not meta.ok:
        raise ReplicateWanError(
            f"Replicate model lookup failed HTTP {meta.status_code}: {(meta.text or '')[:300]} "
            f"(pkg: {last_pkg_err})"
        )
    version = (meta.json().get("latest_version") or {}).get("id")
    if not version:
        raise ReplicateWanError("Replicate model has no latest_version")

    def _create(inp: Dict[str, Any]) -> Dict[str, Any]:
        create = requests.post(
            f"{REPLICATE_API}/predictions",
            headers=_headers(),
            json={"version": version, "input": inp},
            timeout=60,
        )
        if not create.ok:
            raise ReplicateWanError(
                f"Replicate create failed HTTP {create.status_code}: {(create.text or '')[:400]}"
            )
        return create.json()

    try:
        pred = _create(clean)
    except ReplicateWanError:
        minimal = {"prompt": prompt}
        if image_url:
            minimal["image"] = image_url.strip()
        pred = _create(minimal)

    pred_id = pred.get("id")
    status = (pred.get("status") or "").lower()
    if status == "succeeded":
        url = _extract_url(pred.get("output"))
        if url:
            return {
                "url": url,
                "video": {"url": url},
                "model": MODEL_ID,
                "provider": "replicate",
                "duration": duration,
            }

    if not pred_id:
        raise ReplicateWanError("Replicate create returned no prediction id")

    deadline = time.time() + max_wait_sec
    while time.time() < deadline:
        time.sleep(2.5)
        st = requests.get(
            f"{REPLICATE_API}/predictions/{pred_id}",
            headers=_headers(),
            timeout=30,
        )
        if not st.ok:
            continue
        body = st.json()
        status = (body.get("status") or "").lower()
        if status == "succeeded":
            url = _extract_url(body.get("output"))
            if not url:
                raise ReplicateWanError("Replicate succeeded with no video URL")
            return {
                "url": url,
                "video": {"url": url},
                "model": MODEL_ID,
                "provider": "replicate",
                "prediction_id": pred_id,
                "duration": duration,
            }
        if status in ("failed", "canceled", "cancelled"):
            err = body.get("error") or status
            raise ReplicateWanError(f"Replicate WAN 2.2 {status}: {err}")

    raise ReplicateWanError(f"Replicate WAN 2.2 timed out after {int(max_wait_sec)}s")
