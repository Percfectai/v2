"""Upload bot-generated JPEGs to percfectai.com preview grid (Supabase)."""
from __future__ import annotations

import base64
from pathlib import Path

import requests

SITE = "https://percfectai.com"
KEYS = Path.home() / "claude" / "keys.txt"
BOT_SECRET = "percfect-princess-bot"


def _load_creds() -> tuple[str, str]:
    username = password = ""
    if KEYS.exists():
        for line in KEYS.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("PERCfect_USERNAME="):
                username = line.split("=", 1)[1].strip()
            elif line.startswith("PERCfect_PASSWORD="):
                password = line.split("=", 1)[1].strip()
    if not username or not password:
        raise RuntimeError(f"Missing PERCfect_USERNAME/PERCfect_PASSWORD in {KEYS}")
    return username, password


def login_session(site: str = SITE) -> requests.Session:
    username, password = _load_creds()
    s = requests.Session()
    r = s.post(
        f"{site}/auth/login",
        json={"username": username, "password": password},
        timeout=60,
    )
    if not r.ok:
        raise RuntimeError(f"Login failed ({r.status_code}): {r.text[:200]}")
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if not data.get("ok") and not data.get("username"):
        raise RuntimeError(f"Login rejected: {data}")
    return s


def upload_image_bytes(image_bytes: bytes, *, site: str = SITE, session: requests.Session | None = None) -> dict:
    if len(image_bytes) < 10_000:
        raise RuntimeError(f"Image too small ({len(image_bytes)} bytes)")
    s = session or login_session(site)
    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:image/jpeg;base64,{b64}"
    r = s.post(
        f"{site}/percfectstudios/preview-capture",
        data={"image_data": data_url},
        timeout=120,
    )
    try:
        payload = r.json()
    except Exception:
        payload = {"error": r.text[:200]}
    if not r.ok or payload.get("error"):
        raise RuntimeError(payload.get("error") or f"Upload failed ({r.status_code})")
    return payload


def upload_files(paths: list[Path], *, site: str = SITE) -> list[dict]:
    s = login_session(site)
    out: list[dict] = []
    for path in paths:
        payload = upload_image_bytes(path.read_bytes(), site=site, session=s)
        out.append(payload)
        print(f"  ↑ {path.name} → preview #{payload.get('generation_id')}")
    return out


def _bot_headers() -> dict:
    secret = BOT_SECRET
    if KEYS.exists():
        for line in KEYS.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("PRINCESS_BOT_SECRET="):
                secret = line.split("=", 1)[1].strip()
    return {"X-Princess-Bot-Secret": secret}


def bot_fetch_next_job(*, site: str = SITE) -> dict | None:
    r = requests.get(f"{site}/percfectstudios/bot/job-next", headers=_bot_headers(), timeout=60)
    if r.status_code == 500:
        return None
    r.raise_for_status()
    data = r.json()
    job = data.get("job") if isinstance(data, dict) else None
    return job if isinstance(job, dict) and job.get("id") else None


def bot_upload_job_image(job_id: str, image_bytes: bytes, *, site: str = SITE) -> dict:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    r = requests.post(
        f"{site}/percfectstudios/bot/job-upload",
        headers=_bot_headers(),
        data={"job_id": job_id, "image_data": f"data:image/jpeg;base64,{b64}"},
        timeout=120,
    )
    payload = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if not r.ok or payload.get("error"):
        raise RuntimeError(payload.get("error") or f"Bot upload failed ({r.status_code})")
    return payload


def bot_finish_job(job_id: str, *, status: str = "done", error: str = "", site: str = SITE) -> None:
    requests.post(
        f"{site}/percfectstudios/bot/job-done",
        headers={**_bot_headers(), "Content-Type": "application/json"},
        json={"job_id": job_id, "status": status, "error": error or None},
        timeout=60,
    ).raise_for_status()