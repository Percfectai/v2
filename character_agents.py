"""
character_agents.py — per-character agent persona (the LLM brain for each 3D character).

Pipeline step (Nick's spec): after a character is made 3D + rigged, the user sets up its
agent — who it is, how it talks, what it wants — and that saved prompt drives the character
once it's on the board (via the agent driver / world-chat).

Separation of concerns (Nick's rule: "I build fields, you own wording"):
  - The persona TEMPLATE + form labels live in static/data/agent_persona_template.json (Nick owns).
  - This module only SLOTS the user's own words into that template and stores it per character.
  - No persona copy is authored here.

Access model (read carefully):
  - Login required for all read/write.
  - A persona is namespaced under the logged-in user's id, so one user cannot read or write
    another user's personas. The character_id itself is NOT verified against the user's roster
    here — the page shows only the user's own roster, but a crafted character_id within the
    valid charset will still save under that user's own namespace. Roster-membership enforcement
    is a future tightening (see HANDOFFS/2026-11-12_RIVALS_SYSTEM_DESIGN.md).
  - Storage is the rivals_personas table (migrations/20261113_rivals_storage.sql), written with
    SUPABASE_SERVICE_ROLE_KEY. Disk files under data/agent_personas/ are not used.
  - This module never reads rivals_journals. A think snapshot that carries a journal key is stripped
    before it reaches the brain.

Routes (registered via init_app):
  GET  /studios/3d/agent-setup?character=<char_id>   → setup form (or character picker)
  GET  /api/3d/agent/persona/<char_id>               → load saved persona (owner only)
  POST /api/3d/agent/persona                          → save persona (owner only, JSON only)
  POST /api/3d/agent/think                            → one brain tick (owner only, JSON only)
  GET  /api/3d/agent/persona-template                → the Nick-owned template (public, no secrets)
  GET  /api/3d/agent/brain-status                     → is the brain configured (no secrets)
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import jinja2
from flask import Blueprint, jsonify, render_template, request

try:
    from flask_login import current_user
except Exception:  # pragma: no cover
    current_user = None  # type: ignore

bp = Blueprint("character_agents", __name__)

_TEMPLATE_PATH = Path(__file__).resolve().parent / "static" / "data" / "agent_persona_template.json"

# Only these user fields are accepted; everything else is ignored (no injection via extra keys).
_ALLOWED_FIELDS = ("display_name", "identity", "speech_style", "wants", "demeanor")
_MAX_FIELD_LEN = 4000
_CHAR_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_WORLD_ID = (os.environ.get("RIVALS_WORLD_ID") or "eternal-rivals").strip() or "eternal-rivals"
_JOURNAL_KEYS = ("journal", "journals", "private_journal")
_sb_client = None


class PersonaStoreError(RuntimeError):
    """Supabase persona storage is missing or refused the call. Never fall back to disk."""


# --- template ---------------------------------------------------------------
def load_template() -> Dict[str, Any]:
    try:
        return json.loads(_TEMPLATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {
            "form": {"heading": "Set up your character's mind",
                     "fields": [{"key": k, "label": k, "type": "textarea"} for k in _ALLOWED_FIELDS]},
            "system_prompt_template": "You are {display_name}. {identity}",
            "defaults": {k: "" for k in _ALLOWED_FIELDS},
        }


def _required_keys(tmpl: Dict[str, Any]) -> List[str]:
    """The field keys the template marks required:true — the server enforces exactly these."""
    fields = ((tmpl.get("form") or {}).get("fields")) or []
    return [f.get("key") for f in fields if isinstance(f, dict) and f.get("required") and f.get("key") in _ALLOWED_FIELDS]


# --- identity helpers -------------------------------------------------------
def _current_user_id() -> Optional[str]:
    """Resolve the user id the SAME way the 3D roster does, so persona ids match roster ids."""
    try:
        import three_d_character_gen
        uid = three_d_character_gen._current_user_id()
        if uid:
            return str(uid)
    except Exception:
        pass
    try:
        if current_user is not None and getattr(current_user, "is_authenticated", False):
            return str(current_user.get_id() or getattr(current_user, "id", "") or "") or None
    except Exception:
        pass
    return None


def _valid_char_id(char_id: str) -> bool:
    return bool(_CHAR_ID_RE.match(char_id or ""))


def _supabase():
    """Service-role client. The app-wide client uses the anon key and cannot pass RLS."""
    global _sb_client
    if _sb_client is not None:
        return _sb_client
    url = (os.environ.get("SUPABASE_URL") or "").strip()
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        raise PersonaStoreError("persona storage unavailable")
    from supabase import create_client
    _sb_client = create_client(url, key)
    return _sb_client


def _row_to_record(row: Dict[str, Any]) -> Dict[str, Any]:
    fields = row.get("fields") or {}
    if isinstance(fields, str):
        try:
            fields = json.loads(fields)
        except Exception:
            fields = {}
    return {
        "character_id": row.get("character_id"),
        "user_id": row.get("user_id"),
        "world_id": row.get("world_id") or _WORLD_ID,
        "fields": fields,
        "system_prompt": row.get("system_prompt") or "",
        "updated_at": row.get("updated_at"),
    }


def strip_journals(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Drop journal keys before a snapshot is handed to an agent."""
    if not isinstance(snapshot, dict):
        return {}
    out = {k: v for k, v in snapshot.items() if k not in _JOURNAL_KEYS}
    world = out.get("world")
    if isinstance(world, dict):
        out["world"] = {k: v for k, v in world.items() if k not in _JOURNAL_KEYS}
    return out


# --- store ------------------------------------------------------------------
def get_persona(user_id: str, char_id: str) -> Optional[Dict[str, Any]]:
    if not _valid_char_id(char_id) or not user_id:
        return None
    try:
        res = (
            _supabase()
            .table("rivals_personas")
            .select("world_id,user_id,character_id,fields,system_prompt,updated_at")
            .eq("world_id", _WORLD_ID)
            .eq("user_id", str(user_id))
            .eq("character_id", char_id)
            .limit(1)
            .execute()
        )
    except PersonaStoreError:
        raise
    except Exception as exc:
        raise PersonaStoreError("persona storage unavailable") from exc
    rows = res.data or []
    if not rows:
        return None
    return _row_to_record(rows[0])


def save_persona(user_id: str, char_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    tmpl = load_template()
    defaults = tmpl.get("defaults") or {}
    clean: Dict[str, str] = {}
    for k in _ALLOWED_FIELDS:
        v = fields.get(k, defaults.get(k, ""))
        clean[k] = str(v or "").strip()
    record = {
        "world_id": _WORLD_ID,
        "character_id": char_id,
        "user_id": str(user_id),
        "fields": clean,
        "system_prompt": assemble_prompt(clean, tmpl),
    }
    try:
        res = (
            _supabase()
            .table("rivals_personas")
            .upsert(record, on_conflict="world_id,user_id,character_id")
            .execute()
        )
    except PersonaStoreError:
        raise
    except Exception as exc:
        raise PersonaStoreError("persona storage unavailable") from exc
    rows = res.data or []
    if rows:
        return _row_to_record(rows[0])
    return record


def assemble_prompt(fields: Dict[str, str], tmpl: Optional[Dict[str, Any]] = None) -> str:
    """Slot the user's words into Nick's template. Wording comes from the template, not here."""
    tmpl = tmpl or load_template()
    template_str = tmpl.get("system_prompt_template") or "You are {display_name}. {identity}"
    defaults = tmpl.get("defaults") or {}
    slots = {k: (fields.get(k) or defaults.get(k) or "") for k in _ALLOWED_FIELDS}

    class _Safe(dict):
        def __missing__(self, key):  # unknown placeholder → empty, never crash
            return ""

    try:
        return template_str.format_map(_Safe(slots)).strip()
    except Exception:
        return (f"You are {slots.get('display_name','')}. {slots.get('identity','')}").strip()


def build_character_instructions(user_id: str, char_id: str) -> Optional[str]:
    """The system prompt the in-world agent brain should run with for this character."""
    rec = get_persona(user_id, char_id)
    return rec.get("system_prompt") if rec else None


# --- request helpers --------------------------------------------------------
def _require_login() -> Tuple[Optional[str], Optional[Any]]:
    uid = _current_user_id()
    if not uid:
        return None, (jsonify({"error": "login required"}), 401)
    return uid, None


def _require_json() -> Optional[Any]:
    if not request.is_json:
        return jsonify({"error": "JSON body required (Content-Type: application/json)"}), 415
    return None


def _roster(uid: str) -> List[Dict[str, Any]]:
    try:
        import three_d_character_gen
        return three_d_character_gen.list_user_characters(uid) or []
    except Exception:
        return []


# --- routes -----------------------------------------------------------------
@bp.route("/studios/3d/agent-setup")
def agent_setup_page():
    """Per-character agent setup. Login required (private, per 3D rules).
    With a valid ?character= that the user owns → the form; otherwise → a picker of their characters.
    """
    tmpl = load_template()
    uid = _current_user_id()
    char_id = (request.args.get("character") or "").strip()
    if not uid:
        return _render("agent_setup.html", needs_login=True, template=tmpl, character_id=char_id)

    roster = _roster(uid)
    match = next((c for c in roster if str(c.get("id")) == char_id), None) if char_id else None

    # No/invalid/unknown character → show the picker, not the form.
    if not char_id or not _valid_char_id(char_id) or match is None:
        return _render("agent_setup.html", needs_login=False, template=tmpl,
                       picker=True, characters=roster)

    try:
        existing = get_persona(uid, char_id)
    except PersonaStoreError:
        return _render("agent_setup.html", needs_login=False, template=tmpl, picker=False,
                       character_id=char_id, character=match, characters=roster, existing=None,
                       storage_error="Persona storage is not available yet.")
    return _render("agent_setup.html", needs_login=False, template=tmpl, picker=False,
                   character_id=char_id, character=match, characters=roster, existing=existing)


@bp.route("/api/3d/agent/persona-template", methods=["GET"])
def api_persona_template():
    return jsonify(load_template())


@bp.route("/api/3d/agent/persona/<char_id>", methods=["GET"])
def api_get_persona(char_id: str):
    uid, err = _require_login()
    if err:
        return err
    if not _valid_char_id(char_id):
        return jsonify({"error": "invalid character id"}), 400
    try:
        rec = get_persona(uid, char_id)
    except PersonaStoreError:
        return jsonify({"error": "persona storage unavailable"}), 503
    if not rec:
        return jsonify({"exists": False, "character_id": char_id}), 404
    return jsonify({"exists": True, **rec})


@bp.route("/api/3d/agent/persona", methods=["POST"])
def api_save_persona():
    uid, err = _require_login()
    if err:
        return err
    jerr = _require_json()
    if jerr:
        return jerr
    data = request.get_json(silent=True) or {}
    char_id = (data.get("character_id") or data.get("character") or "").strip()
    if not _valid_char_id(char_id):
        return jsonify({"error": "invalid character id (allowed: letters, digits, - and _, 1–64 chars)"}), 400

    fields = {k: data.get(k, "") for k in _ALLOWED_FIELDS}
    # Reject over-length instead of silently truncating.
    too_long = [k for k in _ALLOWED_FIELDS if len(str(fields.get(k) or "")) > _MAX_FIELD_LEN]
    if too_long:
        return jsonify({"error": f"fields over {_MAX_FIELD_LEN} chars", "fields": too_long}), 400
    # Enforce exactly the template's required fields.
    missing = [k for k in _required_keys(load_template()) if not str(fields.get(k) or "").strip()]
    if missing:
        return jsonify({"error": "required fields missing", "missing": missing}), 400

    try:
        rec = save_persona(uid, char_id, fields)
    except PersonaStoreError:
        return jsonify({"error": "persona storage unavailable"}), 503
    return jsonify({"ok": True, **rec})


@bp.route("/api/3d/agent/think", methods=["POST"])
def api_agent_think():
    """One decision tick: persona + world_state → {say, actions}. Login + owner gated, JSON only."""
    uid, err = _require_login()
    if err:
        return err
    jerr = _require_json()
    if jerr:
        return jerr
    data = request.get_json(silent=True) or {}
    char_id = (data.get("character_id") or data.get("character") or "").strip()
    if not _valid_char_id(char_id):
        return jsonify({"error": "invalid character id"}), 400
    try:
        system_prompt = build_character_instructions(uid, char_id)
    except PersonaStoreError:
        return jsonify({"error": "persona storage unavailable"}), 503
    if not system_prompt:
        return jsonify({"error": "no agent set up for this character", "character_id": char_id}), 404
    snapshot = data.get("world_state") if isinstance(data.get("world_state"), dict) else {}
    if not snapshot and isinstance(data.get("snapshot"), dict):
        snapshot = data["snapshot"]
    snapshot = strip_journals(snapshot)
    try:
        import character_brain
    except Exception as e:
        return jsonify({"error": f"brain unavailable: {e}"}), 500
    result = character_brain.decide(system_prompt, snapshot, character_id=char_id)
    return jsonify({"character_id": char_id, **result}), (503 if result.get("disabled") else 200)


@bp.route("/api/3d/agent/brain-status", methods=["GET"])
def api_brain_status():
    try:
        import character_brain
        return jsonify({"enabled": character_brain.enabled(), "provider": character_brain.provider(),
                        "model": character_brain.model_name()})
    except Exception as e:
        return jsonify({"enabled": False, "error": str(e)})


def _render(name: str, **ctx):
    """Render the setup template; only a MISSING template falls back to JSON (real bugs surface)."""
    try:
        return render_template(name, **ctx)
    except jinja2.TemplateNotFound:
        return jsonify({"note": f"{name} not found; data below is the live template + context.",
                        **{k: v for k, v in ctx.items()}})


def init_app(app) -> None:
    """Register the character-agents blueprint (idempotent)."""
    if "character_agents" in app.blueprints:
        return
    app.register_blueprint(bp)
