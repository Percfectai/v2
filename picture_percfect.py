"""Picture Percfect — watermark + upscale + smart split, all in one.

Engine ported from Nick's proven local pipeline (SPLIT_SMART.py).
"""

from PIL import Image, ImageOps
from io import BytesIO


def process_photo(
    photo_bytes: bytes,
    logo_bytes: bytes,
    do_split: bool = True,
    do_upscale: bool = True,
    opacity: float = 0.75,
    position: str = "bottom_right",
    size_percent: int = 25,
) -> list[bytes]:
    """Process one photo: optional split, optional upscale, watermark.

    Returns list of JPEG byte arrays (1 if no split, 2+ if split detected).
    """
    img = Image.open(BytesIO(photo_bytes)).convert("RGBA")
    logo = Image.open(BytesIO(logo_bytes)).convert("RGBA")

    # Smart split detection
    panels = [img]
    if do_split:
        panels = _smart_split(img)

    results: list[bytes] = []
    for panel in panels:
        if do_upscale:
            panel = _upscale(panel)
        watermarked = _apply_watermark(panel, logo, opacity, position, size_percent)
        buf = BytesIO()
        watermarked.convert("RGB").save(buf, "JPEG", quality=92)
        results.append(buf.getvalue())

    return results


# ── internal helpers ─────────────────────────────────────────────


def _smart_split(img: Image.Image) -> list[Image.Image]:
    """Detect if image is a multi-panel collage and split it."""
    w, h = img.size
    if w == 0 or h == 0:
        return [img]
    aspect = w / h

    # Very wide → horizontal split (side-by-side panels)
    if aspect >= 1.8:
        mid = w // 2
        return [img.crop((0, 0, mid, h)), img.crop((mid, 0, w, h))]
    # Very tall → vertical split (stacked panels)
    if aspect <= 0.55:
        mid = h // 2
        return [img.crop((0, 0, w, mid)), img.crop((0, mid, w, h))]

    return [img]


def _upscale(img: Image.Image, target_min: int = 2048) -> Image.Image:
    """Upscale if smaller than *target_min* on its shortest side."""
    w, h = img.size
    if min(w, h) >= target_min:
        return img
    scale = target_min / min(w, h)
    new_w, new_h = int(w * scale), int(h * scale)
    return img.resize((new_w, new_h), Image.LANCZOS)


def _apply_watermark(
    img: Image.Image,
    logo: Image.Image,
    opacity: float,
    position: str,
    size_percent: int,
) -> Image.Image:
    """Overlay logo watermark on image."""
    img = img.copy()
    w, h = img.size

    # Scale logo to requested percentage of the smaller image dimension
    logo_size = int(min(w, h) * size_percent / 100)
    lw, lh = logo.size
    scale = logo_size / max(lw, lh, 1)
    logo_resized = logo.resize(
        (max(1, int(lw * scale)), max(1, int(lh * scale))),
        Image.LANCZOS,
    )

    # Apply opacity
    if opacity < 1.0:
        r, g, b, a = logo_resized.split()
        a = a.point(lambda p: int(p * opacity))
        logo_resized = Image.merge("RGBA", (r, g, b, a))

    lw, lh = logo_resized.size
    margin = int(min(w, h) * 0.03)

    positions = {
        "bottom_right": (w - lw - margin, h - lh - margin),
        "bottom_left":  (margin, h - lh - margin),
        "top_right":    (w - lw - margin, margin),
        "top_left":     (margin, margin),
        "center":       ((w - lw) // 2, (h - lh) // 2),
    }
    pos = positions.get(position, positions["bottom_right"])

    img.paste(logo_resized, pos, logo_resized)
    return img
