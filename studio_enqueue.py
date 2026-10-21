"""Enqueue studio generation tasks — one entry point for all routes."""

from __future__ import annotations

from typing import Any, Dict


def enqueue(runner, user_id: int, kind: str, payload: Dict[str, Any]) -> str:
    from studio_task_handlers import dispatch

    job_id = runner.create(user_id, kind, payload)
    runner.start(job_id, lambda: dispatch(kind, user_id, payload))
    return job_id


def async_payload(job_id: str) -> Dict[str, Any]:
    return {"job_id": job_id, "status": "pending", "async": True}


# Ensure /api/3d/world-chat/* is registered without editing app.py.
# Runs at import (app already exists when studio_enqueue is loaded).
def _wire_world_chat_api() -> None:
    try:
        import app as app_mod
        import world_chat_api

        flask_app = getattr(app_mod, "app", None)
        if flask_app is not None:
            world_chat_api.init_app(flask_app)
    except Exception:
        pass


def _wire_discord_bridge() -> None:
    try:
        import app as app_mod
        import discord_bridge

        flask_app = getattr(app_mod, "app", None)
        if flask_app is not None:
            discord_bridge.init_app(flask_app)
    except Exception:
        pass


def _wire_card_studio() -> None:
    try:
        import app as app_mod
        import card_studio

        flask_app = getattr(app_mod, "app", None)
        if flask_app is not None:
            card_studio.init_app(flask_app)
    except Exception:
        pass


def _wire_comics() -> None:
    try:
        import app as app_mod
        import percfect_comics

        flask_app = getattr(app_mod, "app", None)
        if flask_app is not None:
            percfect_comics.init_app(flask_app)
    except Exception:
        pass


_wire_world_chat_api()
_wire_discord_bridge()
_wire_card_studio()
_wire_comics()
