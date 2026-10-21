"""Storage for Percfect API keys and jobs.

Stopgap: the api_keys / api_jobs tables (migrations/20261001_api_keys.sql)
can't be created until the Supabase account login is recovered, so records
live as JSON files in the private "originals" bucket (the same place the job
queue's storage backend keeps its files). Swap these functions for table
queries once the migration runs; percfect_api.py only calls this module.

The site's Supabase key may create files in storage but not overwrite or
delete them (storage RLS), so everything is append-only:
  keys/<sha256>.json               key record (never the raw key)
  keys/<sha256>.revoked.json       present = key revoked
  users/<uid>/keys/<key_id>.json   {"hash": ...} index for listing
  jobs/<job_id>.json               job as created
  jobs/<job_id>/t<NNN>.json        each later change, in order; creating step N
                                   is create-if-absent, so only one poll wins it
  users/<uid>/jobs/<job_id>.json   {} index for counting active jobs
"""
import json
import uuid
from datetime import datetime, timezone

BUCKET = "originals"
ROOT = "api"


def _bucket():
    import app
    return app.supabase.storage.from_(BUCKET)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _read(path):
    try:
        raw = _bucket().download(f"{ROOT}/{path}")
        if isinstance(raw, memoryview):
            raw = raw.tobytes()
        return json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
    except Exception:
        return None


def _write(path, data) -> bool:
    """Create a JSON file. False if it already exists (files are never overwritten)."""
    try:
        _bucket().upload(
            f"{ROOT}/{path}", json.dumps(data).encode("utf-8"),
            file_options={"content-type": "application/json", "upsert": "false"},
        )
        return True
    except Exception as e:
        if "409" in str(e) or "Duplicate" in str(e) or "already exists" in str(e):
            return False
        raise


def _list(prefix):
    try:
        rows = _bucket().list(f"{ROOT}/{prefix}", {"limit": 1000})
    except Exception:
        return []
    return [r["name"][:-5] for r in rows or [] if r.get("name", "").endswith(".json")]


# ---------------------------- keys ----------------------------

def key_insert(user_id, name, key_prefix, key_hash) -> dict:
    rec = {"id": str(uuid.uuid4()), "user_id": int(user_id), "name": name,
           "key_prefix": key_prefix, "created_at": _now(), "revoked_at": None}
    if not _write(f"keys/{key_hash}.json", rec):
        raise RuntimeError("key collision")
    _write(f"users/{int(user_id)}/keys/{rec['id']}.json", {"hash": key_hash})
    return rec


def key_by_hash(key_hash):
    rec = _read(f"keys/{key_hash}.json")
    if rec:
        rev = _read(f"keys/{key_hash}.revoked.json")
        rec["revoked_at"] = (rev or {}).get("at")
    return rec


def _user_keys(user_id):
    out = []
    for key_id in _list(f"users/{int(user_id)}/keys"):
        idx = _read(f"users/{int(user_id)}/keys/{key_id}.json") or {}
        rec = key_by_hash(idx["hash"]) if idx.get("hash") else None
        if rec:
            out.append((idx["hash"], rec))
    return out


def key_list(user_id) -> list:
    recs = [rec for _, rec in _user_keys(user_id)]
    return sorted(recs, key=lambda r: r.get("created_at") or "", reverse=True)


def key_active_count(user_id) -> int:
    return sum(1 for _, rec in _user_keys(user_id) if not rec.get("revoked_at"))


def key_revoke(user_id, key_id):
    for h, rec in _user_keys(user_id):
        if rec["id"] == key_id:
            _write(f"keys/{h}.revoked.json", {"at": _now()})


# ---------------------------- jobs ----------------------------

def _write_new(path, data):
    """Create a file at a fresh unique path. Storage sometimes errors after the
    write has landed, so a file that now exists counts as written."""
    try:
        _write(path, data)
    except Exception:
        if _read(path) is None:
            raise


def job_insert(fields) -> dict:
    job = {"id": str(uuid.uuid4()), "outputs": None, "error": None,
           "front_url": None, "created_at": _now(), "updated_at": _now(), **fields}
    _write_new(f"jobs/{job['id']}.json", job)
    _write_new(f"users/{int(job['user_id'])}/jobs/{job['id']}.json", {})
    return job


def _job_state(job_id):
    """(job with every change applied, number of changes). Steps are read by
    number, not listed: storage listings can lag a few seconds behind writes,
    direct reads don't."""
    job = _read(f"jobs/{job_id}.json")
    if not job:
        return None, 0
    n = 0
    while True:
        step = _read(f"jobs/{job_id}/t{n:03d}.json")
        if step is None:
            return job, n
        job.update(step)
        n += 1


def job_get(job_id, user_id):
    job, _ = _job_state(job_id)
    if not job or int(job.get("user_id") or 0) != int(user_id):
        return None
    return job


def job_claim(job_id, from_stage, update) -> bool:
    """Move a job out of from_stage exactly once, even with parallel polls."""
    job, n = _job_state(job_id)
    if not job or job.get("stage") != from_stage:
        return False
    return _write(f"jobs/{job_id}/t{n:03d}.json", {**update, "updated_at": _now()})


def job_retry_stage(job_id, stuck_stage, back_to):
    """A poll died mid-step: send the job back a stage so the next poll redoes it."""
    job_claim(job_id, stuck_stage, {"stage": back_to})


def active_job_count(user_id) -> int:
    n = 0
    for job_id in _list(f"users/{int(user_id)}/jobs")[-50:]:
        job, _ = _job_state(job_id)
        if job and job.get("stage") not in ("done", "preview"):  # preview = paid, idle
            n += 1
    return n
