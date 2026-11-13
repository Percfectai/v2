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
  - Storage is data/agent_personas/<user_id>/<char_id>.json — gitignored, NOT web-served, and
    EPHEMERAL on Render (wiped on each deploy). Durable storage (Supabase) is a follow-up.

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
import time
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
# User persona content is private → non-served, gitignored dir.
_STORE_ROOT = Path(os.environ.get("AGENT_PERSONA_DIR") or (Path(__file__).resolve().parent / "data" / "agent_personas"))

# Only these user fields are accepted; everything else is ignored (no injection via extra keys).
_ALLOWED_FIELDS = ("display_name", "identity", "speech_style", "wants", "demeanor")
_MAX_FIELD_LEN = 4000
_CHAR_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


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


def _safe_segment(s: str) -> str:
    return "".join(c for c in str(s or "") if c.isalnum() or c in "-_") or "anon"


def _store_path(user_id: str, char_id: str) -> Path:
    return _STORE_ROOT / _safe_segment(user_id) / f"{char_id}.json"


# --- store ------------------------------------------------------------------
def get_persona(user_id: str, char_id: str) -> Optional[Dict[str, Any]]:
    if not _valid_char_id(char_id):
        return None
    p = _store_path(user_id, char_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_persona(user_id: str, char_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    tmpl = load_template()
    defaults = tmpl.get("defaults") or {}
    clean: Dict[str, str] = {}
    for k in _ALLOWED_FIELDS:
        v = fields.get(k, defaults.get(k, ""))
        clean[k] = str(v or "").strip()
    record = {
        "character_id": char_id,
        "user_id": _safe_segment(user_id),
        "fields": clean,
        "system_prompt": assemble_prompt(clean, tmpl),
        "updated_at": int(time.time()),
    }
    dest = _store_path(user_id, char_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, dest)  # atomic — never a half-written persona
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

    existing = get_persona(uid, char_id)
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
    rec = get_persona(uid, char_id)
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

    rec = save_persona(uid, char_id, fields)
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
    system_prompt = build_character_instructions(uid, char_id)
    if not system_prompt:
        return jsonify({"error": "no agent set up for this character", "character_id": char_id}), 404
    snapshot = data.get("world_state") if isinstance(data.get("world_state"), dict) else {}
    if not snapshot and isinstance(data.get("snapshot"), dict):
        snapshot = data["snapshot"]
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
    try:
        _STORE_ROOT.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    app.register_blueprint(bp)
