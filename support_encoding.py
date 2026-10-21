"""UTF-8 helpers for support-chat text (Ashley / Sal / companions).

xAI returns proper UTF-8 JSON, but if the HTTP body is decoded with the wrong
charset (requests defaulting to ISO-8859-1 / a bad chardet guess), multi-byte
characters such as em-dashes become mojibake (— → â€" / Ã¢â‚¬â€).

Use ensure_utf8_text() on every model reply before jsonify / storage / display.
Prefer fixing at the source:

    data = json.loads(resp.content.decode("utf-8"))
    reply = ensure_utf8_text(extract_reply(data))
"""

from __future__ import annotations

from typing import Any

# Markers that almost never appear in clean English support copy but show up
# when UTF-8 was misread as Latin-1/CP1252 (or double-encoded).
_MOJIBAKE_MARKERS = (
    "Ã",  # common lead-in for double-encoded UTF-8
    "Â",  # UTF-8 C2 xx misread
    "â€",  # em/en dash, curly quotes family
    "â€™",
    "â€œ",
    "â€\x9d",
    "Ã©",
    "Ã¨",
    "Ã ",
    "Ã¢â‚¬",
)


def ensure_utf8_text(text: Any) -> str:
    """Return text with common UTF-8 mojibake repaired; never raises."""
    if text is None:
        return ""
    if not isinstance(text, str):
        try:
            text = str(text)
        except Exception:
            return ""
    if not text:
        return text

    # Up to two passes: handles single mis-decode and occasional double-encoding.
    out = text
    for _ in range(2):
        if not any(m in out for m in _MOJIBAKE_MARKERS):
            break
        try:
            fixed = out.encode("latin-1").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            break
        if fixed == out:
            break
        out = fixed
    return out


def decode_http_body_utf8(content: bytes) -> str:
    """Decode an HTTP response body strictly as UTF-8 (xAI / JSON APIs)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return ensure_utf8_text(content)
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        # Last resort: replace errors, then still run mojibake repair.
        return ensure_utf8_text(content.decode("utf-8", errors="replace"))
