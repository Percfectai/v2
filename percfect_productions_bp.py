"""Percfect Productions stitcher — SPA at percfectai.com/percfectproductions."""

from __future__ import annotations

import os

from flask import Blueprint, abort, send_from_directory

percfect_productions_bp = Blueprint("percfect_productions", __name__)

SPA_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "static", "percfectproductions"
)

ASSET_EXTS = {
    ".js",
    ".css",
    ".map",
    ".png",
    ".jpg",
    ".jpeg",
    ".svg",
    ".webp",
    ".woff",
    ".woff2",
    ".json",
    ".webmanifest",
    ".ico",
    ".txt",
}


def _spa_index():
    index_path = os.path.join(SPA_DIR, "index.html")
    if not os.path.isfile(index_path):
        abort(404)
    resp = send_from_directory(SPA_DIR, "index.html")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


def serve_spa(filename: str | None = None):
    if not filename or filename in ("", "index.html"):
        return _spa_index()
    safe = os.path.normpath(filename).lstrip("/")
    if safe.startswith("..") or os.path.isabs(safe):
        abort(404)
    target = os.path.join(SPA_DIR, safe)
    if os.path.isfile(target):
        return send_from_directory(SPA_DIR, safe)
    ext = os.path.splitext(safe)[1].lower()
    if ext in ASSET_EXTS:
        abort(404)
    return _spa_index()


@percfect_productions_bp.route("/percfectproductions")
@percfect_productions_bp.route("/percfectproductions/")
def percfect_productions_page():
    return serve_spa()


@percfect_productions_bp.route("/percfectproductions/<path:filename>")
def percfect_productions_assets(filename):
    return serve_spa(filename)
