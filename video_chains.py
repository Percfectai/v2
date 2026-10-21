"""Video chain grouping helpers (extend / trim / re-roll share one chain_id).

chain_id is stored in generations.source_page as "chain:<id>" until
migrations/20260924_video_chain_id.sql adds a native column.
"""

from __future__ import annotations

import datetime
import logging
import uuid

log = logging.getLogger(__name__)

_VIDEO_CHAIN_PREFIX = "chain:"


def new_video_chain_id() -> str:
    return uuid.uuid4().hex[:16]


def parse_video_chain_id(row_or_page) -> str:
    if row_or_page is None:
        return ""
    if isinstance(row_or_page, dict):
        cid = str(row_or_page.get("chain_id") or "").strip()
        if cid:
            return cid
        page = str(row_or_page.get("source_page") or "").strip()
    else:
        page = str(row_or_page or "").strip()
    if page.startswith(_VIDEO_CHAIN_PREFIX):
        return page[len(_VIDEO_CHAIN_PREFIX) :].strip()
    return ""


def resolve_video_chain_id(
    supabase,
    user_id: int,
    *,
    chain_id: str = None,
    source_id=None,
    video_url: str = None,
) -> str:
    cid = str(chain_id or "").strip()
    if cid.startswith(_VIDEO_CHAIN_PREFIX):
        cid = cid[len(_VIDEO_CHAIN_PREFIX) :].strip()
    if cid:
        return cid
    if source_id not in (None, ""):
        try:
            try:
                res = (
                    supabase.table("generations")
                    .select("id,source_page,chain_id")
                    .eq("user_id", user_id)
                    .eq("id", source_id)
                    .limit(1)
                    .execute()
                )
            except Exception:
                res = (
                    supabase.table("generations")
                    .select("id")
                    .eq("user_id", user_id)
                    .eq("id", source_id)
                    .limit(1)
                    .execute()
                )
            row = (res.data or [None])[0]
            got = parse_video_chain_id(row)
            if got:
                return got
            if row and row.get("id") is not None:
                return str(row["id"])
        except Exception:
            log.exception("resolve_video_chain_id source_id lookup failed")
    url = (video_url or "").strip()
    if url.startswith(("http://", "https://")):
        try:
            try:
                res = (
                    supabase.table("generations")
                    .select("id,source_page,chain_id")
                    .eq("user_id", user_id)
                    .eq("output_url", url)
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                )
            except Exception:
                res = (
                    supabase.table("generations")
                    .select("id")
                    .eq("user_id", user_id)
                    .eq("output_url", url)
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                )
            row = (res.data or [None])[0]
            got = parse_video_chain_id(row)
            if got:
                return got
            if row and row.get("id") is not None:
                return str(row["id"])
        except Exception:
            log.exception("resolve_video_chain_id video_url lookup failed")
    return new_video_chain_id()


def insert_video_generation(
    supabase,
    user_id: int,
    prompt: str,
    output_url: str,
    *,
    chain_id: str = None,
    preview_url: str = None,
) -> dict:
    cid = str(chain_id or "").strip() or new_video_chain_id()
    if cid.startswith(_VIDEO_CHAIN_PREFIX):
        cid = cid[len(_VIDEO_CHAIN_PREFIX) :].strip() or new_video_chain_id()
    now = datetime.datetime.utcnow().isoformat()
    row = {
        "user_id": user_id,
        "type": "video",
        "prompt": prompt or "",
        "output_url": output_url,
        "source_page": f"{_VIDEO_CHAIN_PREFIX}{cid}",
        "created_at": now,
    }
    if preview_url:
        row["preview_url"] = preview_url
    inserted = {}
    try:
        res = supabase.table("generations").insert({**row, "chain_id": cid}).execute()
        inserted = (res.data or [{}])[0] or {}
    except Exception as e:
        msg = str(e).lower()
        # Live DB may lack chain_id and/or source_page until migrations run.
        if "column" in msg or "chain_id" in msg or "source_page" in msg:
            slim = {k: v for k, v in row.items() if k != "source_page"}
            try:
                res = supabase.table("generations").insert(slim).execute()
            except Exception:
                base = {
                    "user_id": user_id,
                    "type": "video",
                    "prompt": prompt or "",
                    "output_url": output_url,
                    "created_at": now,
                }
                if preview_url:
                    base["preview_url"] = preview_url
                res = supabase.table("generations").insert(base).execute()
            inserted = (res.data or [{}])[0] or {}
        else:
            raise
    return {
        "id": inserted.get("id"),
        "chain_id": cid,
        "url": output_url,
        "prompt": prompt or "",
    }
