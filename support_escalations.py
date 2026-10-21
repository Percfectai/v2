"""Ashley → Sal escalation inbox (admin-only).

Why this exists
---------------
When Ashley escalates, the server calls Sal once in the background. That reply
was never written into Sal's browser chat history, so if you later ask Sal
"did you get the bug request?" he has zero memory of it.

This module persists escalations to data/support_escalations.json so:
  1) Sal's context is primed with the inbox on every admin chat
  2) The admin Support UI can show "Inbox from Ashley"
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from support_encoding import ensure_utf8_text

_lock = threading.Lock()
_DATA_DIR = Path(__file__).resolve().parent / "data"
_FILE = _DATA_DIR / "support_escalations.json"
_MAX_ROWS = 80


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> List[Dict[str, Any]]:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not _FILE.exists():
        return []
    try:
        raw = json.loads(_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else []
    except Exception:
        return []


def _save(rows: List[Dict[str, Any]]) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_FILE)


def _clean_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Repair mojibake on text fields (live + legacy rows)."""
    if not isinstance(row, dict):
        return row
    out = dict(row)
    for key in ("customer_message", "bug_summary", "ashley_customer_msg", "sal_reply", "queue_error"):
        if key in out and out[key] is not None:
            out[key] = ensure_utf8_text(out[key])
    return out


def record_escalation(
    *,
    customer_message: str,
    bug_summary: str,
    ashley_customer_msg: str = "",
    sal_reply: str = "",
    build_task_id: Any = None,
    build_queued: bool = False,
    queue_error: str = "",
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Persist one Ashley→Sal handoff. Newest first."""
    row = {
        "id": str(uuid.uuid4()),
        "created_at": _now(),
        "status": "open",
        "customer_message": ensure_utf8_text((customer_message or "").strip()[:4000]),
        "bug_summary": ensure_utf8_text((bug_summary or "").strip()[:500]),
        "ashley_customer_msg": ensure_utf8_text((ashley_customer_msg or "").strip()[:2000]),
        "sal_reply": ensure_utf8_text((sal_reply or "").strip()[:12000]),
        "build_task_id": build_task_id,
        "build_queued": bool(build_queued),
        "queue_error": ensure_utf8_text((queue_error or "")[:300]),
        "user_id": user_id,
    }
    with _lock:
        rows = _load()
        rows.insert(0, row)
        _save(rows[:_MAX_ROWS])
    return row


def list_escalations(limit: int = 12, status: Optional[str] = None) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit or 12), 40))
    with _lock:
        rows = _load()
    if status:
        st = status.strip().lower()
        rows = [r for r in rows if (r.get("status") or "").lower() == st]
    return [_clean_row(r) for r in rows[:limit]]


def format_inbox_for_sal(limit: int = 8) -> str:
    """Text block injected into Sal's prompt so he knows about open escalations."""
    rows = list_escalations(limit=limit)
    if not rows:
        return (
            "(No Ashley escalations stored yet. If a customer reported a bug and you were "
            "not called, Ashley may not have emitted [ESCALATE_TO_DEBUG].)"
        )
    lines = [
        "=== INBOX: recent Ashley → Sal escalations (server-stored) ===",
        "These were handed off when Ashley escalated. You MAY already have diagnosed them",
        "in a one-shot background call; the admin is asking you about this inbox.",
        "",
    ]
    for i, r in enumerate(rows, 1):
        lines.append(f"--- #{i} id={r.get('id')} · {r.get('created_at')} · status={r.get('status')} ---")
        lines.append(f"Bug summary: {r.get('bug_summary') or '(none)'}")
        lines.append(f"Customer said: {r.get('customer_message') or '(none)'}")
        if r.get("build_task_id"):
            lines.append(f"Build task: {r.get('build_task_id')} queued={r.get('build_queued')}")
        if r.get("queue_error"):
            lines.append(f"Queue error: {r.get('queue_error')}")
        sal = (r.get("sal_reply") or "").strip()
        if sal:
            # keep inbox prompt bounded
            snippet = sal if len(sal) <= 900 else sal[:900] + "…"
            lines.append(f"Your prior diagnosis (background call):\n{snippet}")
        lines.append("")
    lines.append("=== end inbox ===")
    return "\n".join(lines)


def mark_status(esc_id: str, status: str) -> Optional[Dict[str, Any]]:
    status = (status or "").strip().lower() or "open"
    with _lock:
        rows = _load()
        for r in rows:
            if str(r.get("id")) == str(esc_id):
                r["status"] = status
                r["updated_at"] = _now()
                _save(rows)
                return _clean_row(r)
    return None
