"""Drop-in helper for app.py /api/analyze-motion — PoYo BG removal + analyzer fallback.

Usage from app.py (surgical — do not replace the existing route):

    from motion_analyze_poyo import enrich_analysis_with_poyo_bg

    # After proxying to MOTION_ANALYZER_URL and parsing JSON `data`:
    # `public_source_url` = durable https URL of the uploaded source clip
    data = enrich_analysis_with_poyo_bg(
        data,
        public_source_url,
        rehost_video=lambda url, kind="video": _rehost_motion_asset(url, kind=kind),
    )
    return jsonify(data)

Keeps the existing MediaPipe analyzer path as automatic fallback.
Response always includes bg_removal_engine / engine: "poyo" | "mediapipe".
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional


def enrich_analysis_with_poyo_bg(
    analysis: Dict[str, Any],
    public_source_url: str,
    *,
    rehost_video: Optional[Callable[..., str]] = None,
    skip_poyo: bool = False,
) -> Dict[str, Any]:
    """Try PoYo character-plate BG removal; fall back to analyzer plates.

    Never raises for PoYo failures — always returns a usable analysis dict.
    """
    from motion_bg_extract import apply_poyo_bg_removal, tag_mediapipe_engine

    if not isinstance(analysis, dict):
        return analysis

    if skip_poyo:
        return tag_mediapipe_engine(analysis)

    def _rehost(url: str, kind: str = "video") -> str:
        if not rehost_video:
            return url
        try:
            return rehost_video(url, kind)
        except TypeError:
            return rehost_video(url)

    return apply_poyo_bg_removal(
        analysis,
        public_source_url,
        rehost=_rehost if rehost_video else None,
    )
