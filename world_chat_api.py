"""
3D multi-body world group chat API.

Routes (no app.py edit required if init_app wires this):
  GET  /api/3d/world-chat/messages?after=
  POST /api/3d/world-chat/send   form: body, as_body?  → human + real agent replies
  GET  /api/3d/world-chat/crew   seat key readiness

Also helpers for optional Lounge integration (room=3d on chatroom_*).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, jsonify, request

WORLD_ROOMS = frozenset({"3d", "colosseum", "field", "world", "3d-world"})
WORLD_MSG_TYPE = "3d_world"
LOUNGE_TYPES = frozenset({"text", "fight", ""})

bp = Blueprint("world_chat_api", __name__)


def is_world_room(room: str) -> bool:
    return (room or "").strip().lower() in WORLD_ROOMS


def apply_room_filter(msgs: List[Dict[str, Any]], room: str) -> List[Dict[str, Any]]:
    room = (room or "lounge").strip().lower()
    if is_world_room(room):
        return [m for m in msgs if str(m.get("type") or "") == WORLD_MSG_TYPE]
    return [m for m in msgs if str(m.get("type") or "text") in LOUNGE_TYPES]


def enrich_world_send(
    body: str,
    room: str,
    form: Any,
    username: str,
) -> Tuple[str, str, str]:
    room = (room or "lounge").strip().lower()
    msg_type = WORLD_MSG_TYPE if is_world_room(room) else "text"
    display_name = username or "anon"
    as_body = ""
    try:
        as_body = (form.get("as_body") or form.get("body_id") or "").strip()[:32]
    except Exception:
        as_body = ""
    as_body = re.sub(r"[^a-zA-Z0-9 _\-]", "", as_body).strip()
    if as_body and msg_type == WORLD_MSG_TYPE:
        body = f"[{as_body}] {body}"[:500]
        display_name = f"{as_body} · {username}"[:80]
    return body, display_name, msg_type


def _app_bits():
    """Pull supabase + auth helpers from main app module."""
    import app as app_mod

    return app_mod


@bp.route("/api/3d/world-chat/messages", methods=["GET"])
def world_chat_messages():
    """Poll 3D world feed only (type=3d_world). Public read."""
    try:
        app_mod = _app_bits()
        res = (
            app_mod.supabase.table("chat_messages")
            .select("id,username,body,type,media_url,created_at")
            .eq("hidden", False)
            .eq("type", WORLD_MSG_TYPE)
            .order("id", desc=True)
            .limit(60)
            .execute()
        )
        msgs = list(reversed(res.data or []))
        after = request.args.get("after")
        if after:
            try:
                aid = int(after)
                msgs = [m for m in msgs if m["id"] > aid]
            except ValueError:
                pass
        return jsonify(msgs)
    except Exception:
        # Fallback: filter client-side from last 80 of any messages (old deploy)
        try:
            app_mod = _app_bits()
            res = (
                app_mod.supabase.table("chat_messages")
                .select("id,username,body,type,media_url,created_at")
                .eq("hidden", False)
                .order("id", desc=True)
                .limit(80)
                .execute()
            )
            msgs = apply_room_filter(list(reversed(res.data or [])), "3d")
            after = request.args.get("after")
            if after:
                try:
                    aid = int(after)
                    msgs = [m for m in msgs if m["id"] > aid]
                except ValueError:
                    pass
            return jsonify(msgs)
        except Exception:
            return jsonify([])


def _form_or_json():
    if request.form:
        return request.form
    return request.get_json(silent=True) or {}


def _insert_world_msg(app_mod, user_id, username: str, body: str) -> Optional[Dict[str, Any]]:
    try:
        row = app_mod.supabase.table("chat_messages").insert({
            "user_id": user_id,
            "username": username,
            "body": body,
            "type": WORLD_MSG_TYPE,
        }).execute()
        return (row.data or [None])[0]
    except Exception:
        return None


def _recent_world(app_mod, limit: int = 12) -> List[Dict[str, Any]]:
    try:
        res = (
            app_mod.supabase.table("chat_messages")
            .select("id,username,body,type,created_at")
            .eq("hidden", False)
            .eq("type", WORLD_MSG_TYPE)
            .order("id", desc=True)
            .limit(limit)
            .execute()
        )
        return list(reversed(res.data or []))
    except Exception:
        return []


def _agent_replies_for_message(
    app_mod,
    body: str,
    human_username: str,
    agent_user_id: Any,
    max_agents: int = 2,
) -> List[Dict[str, Any]]:
    """Run real crew brains and persist their replies into the world feed."""
    try:
        import field_world_agents as fwa
    except Exception:
        return []

    # opt-out: client can send agent_reply=0
    data = _form_or_json()
    flag = str(data.get("agent_reply") if hasattr(data, "get") else "1").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return []

    seats = fwa.pick_responders(body, max_n=max_agents)
    if not seats:
        return []

    recent = _recent_world(app_mod, 12)
    out: List[Dict[str, Any]] = []
    for seat in seats:
        result = fwa.agent_reply(
            seat,
            user_message=body,
            username=human_username,
            recent=recent,
        )
        if not result.get("ok") or not result.get("reply"):
            # Soft signal in feed when key missing so Nick sees why silence
            if result.get("error") and "No chat key" in str(result.get("error")):
                continue
            continue
        label = result.get("label") or seat
        reply_body = (result.get("reply") or "").strip()[:500]
        actions = result.get("actions") or []
        # Agents post as themselves (no "Agent · user" prefix)
        row = _insert_world_msg(
            app_mod,
            agent_user_id,
            label,
            reply_body,
        )
        entry: Dict[str, Any]
        if row:
            entry = dict(row)
            recent.append({"username": label, "body": reply_body})
        else:
            entry = {
                "ok": True,
                "username": label,
                "body": reply_body,
                "type": WORLD_MSG_TYPE,
            }
        # Body drive payload for Field / Colosseum clients (not stored in DB)
        entry["seat"] = result.get("seat") or seat
        entry["label"] = label
        entry["actions"] = actions
        out.append(entry)
    return out


@bp.route("/api/3d/world-chat/send", methods=["POST"])
def world_chat_send():
    """Send to 3D world feed. Login required. Triggers real agent replies."""
    app_mod = _app_bits()
    try:
        from flask_login import current_user, login_required  # noqa: F401
    except Exception:
        pass
    try:
        from flask_login import current_user
        if not getattr(current_user, "is_authenticated", False):
            return jsonify(error="Log in to chat on the 3D board.", login_required=True), 401
    except Exception:
        return jsonify(error="Log in to chat on the 3D board.", login_required=True), 401

    data = _form_or_json()
    raw_body = ""
    if hasattr(data, "get"):
        raw_body = data.get("body", "") or ""
    body, err = app_mod._chat_clean(raw_body)
    if err:
        return jsonify({"error": err}), 400
    if not getattr(current_user, "is_admin", False) and app_mod._chat_rate_limited(current_user.id):
        return jsonify({"error": "You're sending messages too fast — slow down a moment."}), 429

    body, display_name, msg_type = enrich_world_send(
        body, "3d", data, current_user.username
    )
    try:
        row = app_mod.supabase.table("chat_messages").insert({
            "user_id": current_user.id,
            "username": display_name,
            "body": body,
            "type": msg_type,
        }).execute()
        human = (row.data or [None])[0] or {
            "ok": True,
            "body": body,
            "username": display_name,
            "type": msg_type,
        }

        # Real agents answer in the same world feed (@mention or 1 random crew)
        agent_msgs = _agent_replies_for_message(
            app_mod,
            body=body,
            human_username=display_name,
            agent_user_id=current_user.id,  # attributed to room host account for RLS
            max_agents=2,
        )

        # Back-compat: top-level fields = human msg; plus agent_replies array
        payload = dict(human) if isinstance(human, dict) else {"ok": True, "body": body, "username": display_name}
        payload["agent_replies"] = agent_msgs
        payload["agents_replied"] = [m.get("username") for m in agent_msgs if m.get("username")]
        return jsonify(payload)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/3d/world-chat/crew", methods=["GET"])
def world_chat_crew_status():
    """Which Field seats have chat keys (no secrets)."""
    try:
        import field_world_agents as fwa
        return jsonify(fwa.crew_status())
    except Exception as e:
        return jsonify({"error": str(e), "any_ready": False}), 500


def init_app(app) -> None:
    """Register world-chat blueprint (idempotent)."""
    name = bp.name
    if name not in getattr(app, "blueprints", {}):
        app.register_blueprint(bp)

    # PoYo CDN GLB proxy for Colosseum recovered bodies (safe if already on app.py)
    try:
        import poyo_cdn_proxy
        poyo_cdn_proxy.init_app(app)
    except Exception:
        pass
