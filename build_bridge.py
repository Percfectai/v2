"""Grok Build bridge — queue tasks from Admin Architect to a coding agent.

Storage:
  1) Supabase table build_tasks (if present)
  2) Fallback: data/build_tasks.json (local / Render disk)

Statuses (Level 3/4 ready):
  pending → approved → running → done | failed | cancelled
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_lock = threading.Lock()
_DATA_DIR = Path(__file__).resolve().parent / "data"
_FILE = _DATA_DIR / "build_tasks.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_load() -> List[Dict[str, Any]]:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not _FILE.exists():
        return []
    try:
        raw = json.loads(_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else []
    except Exception:
        return []


def _file_save(rows: List[Dict[str, Any]]) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    tmp.replace(_FILE)


def _sb():
    try:
        from app import supabase  # late import — same process
        return supabase
    except Exception:
        return None


def _use_supabase() -> bool:
    sb = _sb()
    if not sb:
        return False
    try:
        sb.table("build_tasks").select("id").limit(1).execute()
        return True
    except Exception:
        return False


def create_task(
    prompt: str,
    *,
    title: str = "",
    created_by: Optional[int] = None,
    auto_approve: bool = True,
) -> Dict[str, Any]:
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("Empty build prompt")
    title = (title or "").strip() or _title_from_prompt(prompt)
    status = "approved" if auto_approve else "pending"
    row = {
        "id": str(uuid.uuid4()),
        "title": title[:160],
        "prompt": prompt[:50000],
        "status": status,
        "result": "",
        "created_by": created_by,
        "created_at": _now(),
        "updated_at": _now(),
        "claimed_at": None,
        "completed_at": None,
    }
    if _use_supabase():
        sb = _sb()
        payload = {
            "title": row["title"],
            "prompt": row["prompt"],
            "status": status,
            "created_by": created_by,
        }
        res = sb.table("build_tasks").insert(payload).execute()
        data = (res.data or [None])[0]
        if data:
            return _normalize_sb(data)
    with _lock:
        rows = _file_load()
        rows.insert(0, row)
        _file_save(rows[:200])  # cap
    return row


def list_tasks(limit: int = 30, status: Optional[str] = None) -> List[Dict[str, Any]]:
    limit = max(1, min(100, int(limit or 30)))
    if _use_supabase():
        sb = _sb()
        q = sb.table("build_tasks").select("*").order("id", desc=True).limit(limit)
        if status:
            q = q.eq("status", status)
        res = q.execute()
        return [_normalize_sb(r) for r in (res.data or [])]
    with _lock:
        rows = _file_load()
    if status:
        rows = [r for r in rows if r.get("status") == status]
    return rows[:limit]


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    if _use_supabase() and str(task_id).isdigit():
        sb = _sb()
        res = sb.table("build_tasks").select("*").eq("id", int(task_id)).limit(1).execute()
        rows = res.data or []
        return _normalize_sb(rows[0]) if rows else None
    with _lock:
        for r in _file_load():
            if str(r.get("id")) == str(task_id):
                return r
    return None


def claim_next() -> Optional[Dict[str, Any]]:
    """Atomically take oldest approved/pending task → running."""
    if _use_supabase():
        sb = _sb()
        for st in ("approved", "pending"):
            res = (
                sb.table("build_tasks")
                .select("*")
                .eq("status", st)
                .order("id", desc=False)
                .limit(1)
                .execute()
            )
            rows = res.data or []
            if not rows:
                continue
            row = rows[0]
            upd = (
                sb.table("build_tasks")
                .update({"status": "running", "claimed_at": _now(), "updated_at": _now()})
                .eq("id", row["id"])
                .eq("status", st)
                .execute()
            )
            if upd.data:
                return _normalize_sb(upd.data[0])
        return None

    with _lock:
        rows = _file_load()
        for r in reversed(rows):  # oldest first if we insert at 0
            pass
        # file list is newest-first; claim oldest pending/approved
        candidates = [r for r in rows if r.get("status") in ("approved", "pending")]
        if not candidates:
            return None
        # oldest = last in newest-first list among candidates
        pick = candidates[-1]
        for r in rows:
            if r.get("id") == pick.get("id"):
                r["status"] = "running"
                r["claimed_at"] = _now()
                r["updated_at"] = _now()
                _file_save(rows)
                return dict(r)
    return None


def complete_task(task_id: str, *, status: str = "done", result: str = "") -> Optional[Dict[str, Any]]:
    if status not in ("done", "failed", "cancelled"):
        status = "done"
    result = (result or "")[:100000]
    if _use_supabase() and str(task_id).isdigit():
        sb = _sb()
        res = (
            sb.table("build_tasks")
            .update({
                "status": status,
                "result": result,
                "completed_at": _now(),
                "updated_at": _now(),
            })
            .eq("id", int(task_id))
            .execute()
        )
        if res.data:
            return _normalize_sb(res.data[0])
        return None
    with _lock:
        rows = _file_load()
        for r in rows:
            if str(r.get("id")) == str(task_id):
                r["status"] = status
                r["result"] = result
                r["completed_at"] = _now()
                r["updated_at"] = _now()
                _file_save(rows)
                return dict(r)
    return None


def format_grok_build_prompt(text: str, *, source: str = "Admin Architect") -> str:
    """Wrap architect output as a Grok Build task prompt."""
    body = (text or "").strip()
    if not body:
        return ""
    # If already structured, keep it
    if "### BUILD_TASK" in body or "## Grok Build task" in body:
        return body
    return (
        f"## Grok Build task\n"
        f"**from:** {source}\n"
        f"**repo:** percfectstudios (percfectai.com)\n\n"
        f"### BUILD_TASK\n"
        f"{body}\n\n"
        f"### Instructions for Grok Build\n"
        f"- Implement the request in this repo with minimal safe diffs.\n"
        f"- Prefer existing patterns (Flask routes, Jinja templates, static JS).\n"
        f"- Do not invent secrets. Deploy-sensitive changes: call them out.\n"
        f"- When done, summarize files changed and how to verify.\n"
    )


def _title_from_prompt(prompt: str) -> str:
    line = (prompt or "").strip().splitlines()[0] if prompt else "Build task"
    line = line.lstrip("#").strip()
    return (line[:80] + ("…" if len(line) > 80 else "")) or "Build task"


def _normalize_sb(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row.get("id"),
        "title": row.get("title") or "",
        "prompt": row.get("prompt") or "",
        "status": row.get("status") or "pending",
        "result": row.get("result") or "",
        "created_by": row.get("created_by"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "claimed_at": row.get("claimed_at"),
        "completed_at": row.get("completed_at"),
    }


def bridge_token_ok(header_val: str) -> bool:
    token = (os.getenv("GROK_BUILD_BRIDGE_TOKEN") or os.getenv("BRIDGE_TOKEN") or "").strip()
    if not token:
        return False
    raw = (header_val or "").strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    return bool(raw) and raw == token
