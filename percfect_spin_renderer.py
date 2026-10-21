"""Percfect DIY 360° character spin — ortho shots + stage grid, no xAI video."""

from __future__ import annotations

import math
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw

# front → left → back → right (camera orbit CCW when viewed from above)
POSE_INDICES = (0, 1, 3, 2)
POSE_SEGMENTS = ((0, 1), (1, 3), (3, 2), (2, 0))

GRID_COLOR_BGR = (136, 255, 0)  # #00ff88
BG_BGR = (18, 10, 10)


def _default_key_out_white(im: Image.Image, thresh: int = 32) -> Image.Image:
    im = im.convert("RGBA")
    rgb = im.convert("RGB")
    sentinel = (0, 255, 1)
    for corner in ((0, 0), (im.width - 1, 0), (0, im.height - 1), (im.width - 1, im.height - 1)):
        try:
            ImageDraw.floodfill(rgb, corner, sentinel, thresh=thresh)
        except Exception:
            pass
    pr, px = rgb.load(), im.load()
    for y in range(im.height):
        for x in range(im.width):
            if pr[x, y] == sentinel:
                r, g, b, _ = px[x, y]
                px[x, y] = (r, g, b, 0)
    return im


def _prepare_cutout(im: Image.Image, target_h: int) -> Image.Image:
    im = im.convert("RGBA")
    scale = target_h / max(1, im.height)
    w = max(1, int(im.width * scale))
    return im.resize((w, target_h), Image.LANCZOS)


def _segment_blend(theta: float) -> Tuple[int, int, float]:
    """theta in [0, 2π) → two ortho indices + mix factor."""
    t = (theta / (2 * math.pi)) * 4.0
    seg = int(t) % 4
    mix = t - int(t)
    a, b = POSE_SEGMENTS[seg]
    return a, b, mix


def _draw_stage_frame(w: int, h: int, grid_opacity: float = 0.5) -> np.ndarray:
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    frame[:] = BG_BGR
    grid_top = int(h * 0.62)
    overlay = frame.copy()
    step = max(28, w // 20)
    for x in range(0, w + 1, step):
        cv2.line(overlay, (x, grid_top), (x, h), GRID_COLOR_BGR, 1, cv2.LINE_AA)
    for y in range(grid_top, h + 1, step):
        cv2.line(overlay, (0, y), (w, y), GRID_COLOR_BGR, 1, cv2.LINE_AA)
    # center cross on floor
    cx = w // 2
    cv2.line(overlay, (cx, grid_top), (cx, h), (68, 68, 255), 1, cv2.LINE_AA)
    cv2.line(overlay, (0, h - step), (w, h - step), (255, 136, 68), 1, cv2.LINE_AA)
    cv2.addWeighted(overlay, grid_opacity, frame, 1.0 - grid_opacity, 0, frame)
    return frame


def _blend_rgba_cutouts(
    base_bgr: np.ndarray,
    cut_a: Image.Image,
    cut_b: Image.Image,
    mix: float,
    foot_y: int,
) -> np.ndarray:
    w, h = base_bgr.shape[1], base_bgr.shape[0]
    out = Image.fromarray(cv2.cvtColor(base_bgr, cv2.COLOR_BGR2RGB)).convert("RGBA")

    def paste_cut(cut: Image.Image, weight: float):
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        x = (w - cut.width) // 2
        y = foot_y - cut.height
        if weight < 1.0:
            cut = cut.copy()
            r, g, b, a = cut.split()
            a = a.point(lambda p: int(p * weight))
            cut = Image.merge("RGBA", (r, g, b, a))
        layer.paste(cut, (x, y), cut)
        return layer

    if mix <= 0.001:
        out = Image.alpha_composite(out, paste_cut(cut_a, 1.0))
    elif mix >= 0.999:
        out = Image.alpha_composite(out, paste_cut(cut_b, 1.0))
    else:
        out = Image.alpha_composite(out, paste_cut(cut_a, 1.0 - mix))
        out = Image.alpha_composite(out, paste_cut(cut_b, mix))

    rgb = out.convert("RGB")
    return cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2BGR)


def _try_h264(in_path: Path, out_path: Path) -> bool:
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", str(in_path),
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                str(out_path),
            ],
            check=True,
            timeout=120,
        )
        return out_path.is_file() and out_path.stat().st_size > 0
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def render_character_spin(
    image_urls: Sequence[str],
    *,
    duration_sec: float = 5.0,
    fps: int = 24,
    width: int = 768,
    height: int = 768,
    load_image: Optional[Callable[[str], Image.Image]] = None,
    key_out_white: Optional[Callable[[Image.Image], Image.Image]] = None,
) -> bytes:
    """
    Build a 3–6s orbit spin from 4 ortho URLs [front, left, right, back].
    Returns MP4 bytes (H.264 if ffmpeg present, else mp4v).
    """
    duration_sec = max(3.0, min(6.0, float(duration_sec)))
    fps = max(12, min(30, int(fps)))

    if len(image_urls) < 4:
        raise ValueError("Need 4 ortho images (front, left, right, back).")

    load_image = load_image or (lambda u: Image.open(BytesIO(__import__("requests").get(u, timeout=60).content)).convert("RGB"))
    key_out = key_out_white or _default_key_out_white

    char_h = int(height * 0.84)
    foot_y = height - int(height * 0.06)
    cutouts = []
    for i in range(4):
        raw = load_image(image_urls[i])
        cutouts.append(_prepare_cutout(key_out(raw), char_h))

    total_frames = max(1, int(round(duration_sec * fps)))
    tmp = Path(tempfile.mkdtemp(prefix="percfect_spin_"))
    raw_mp4 = tmp / "spin_raw.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(raw_mp4), fourcc, fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError("Could not open video writer for spin.")

    try:
        for fi in range(total_frames):
            theta = (fi / total_frames) * 2 * math.pi
            ia, ib, mix = _segment_blend(theta)
            bg = _draw_stage_frame(width, height)
            frame = _blend_rgba_cutouts(bg, cutouts[ia], cutouts[ib], mix, foot_y)
            writer.write(frame)
        writer.release()

        h264_mp4 = tmp / "spin.mp4"
        if _try_h264(raw_mp4, h264_mp4):
            return h264_mp4.read_bytes()
        return raw_mp4.read_bytes()
    finally:
        try:
            writer.release()
        except Exception:
            pass
        for p in tmp.glob("*"):
            try:
                p.unlink()
            except OSError:
                pass
        try:
            tmp.rmdir()
        except OSError:
            pass


def render_character_spin_from_images(
    images: Sequence[Image.Image],
    *,
    duration_sec: float = 5.0,
    fps: int = 24,
    width: int = 768,
    height: int = 768,
    key_out_white: Optional[Callable[[Image.Image], Image.Image]] = None,
) -> bytes:
    """Build orbit spin from 4 PIL images [front, left, right, back]."""
    duration_sec = max(3.0, min(6.0, float(duration_sec)))
    fps = max(12, min(30, int(fps)))

    if len(images) < 4:
        raise ValueError("Need 4 ortho images (front, left, right, back).")

    key_out = key_out_white or _default_key_out_white
    char_h = int(height * 0.84)
    foot_y = height - int(height * 0.06)
    cutouts = [_prepare_cutout(key_out(im.convert("RGB")), char_h) for im in images[:4]]

    total_frames = max(1, int(round(duration_sec * fps)))
    tmp = Path(tempfile.mkdtemp(prefix="percfect_spin_"))
    raw_mp4 = tmp / "spin_raw.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(raw_mp4), fourcc, fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError("Could not open video writer for spin.")

    try:
        for fi in range(total_frames):
            theta = (fi / total_frames) * 2 * math.pi
            ia, ib, mix = _segment_blend(theta)
            bg = _draw_stage_frame(width, height)
            frame = _blend_rgba_cutouts(bg, cutouts[ia], cutouts[ib], mix, foot_y)
            writer.write(frame)
        writer.release()

        h264_mp4 = tmp / "spin.mp4"
        if _try_h264(raw_mp4, h264_mp4):
            return h264_mp4.read_bytes()
        return raw_mp4.read_bytes()
    finally:
        try:
            writer.release()
        except Exception:
            pass
        for p in tmp.glob("*"):
            try:
                p.unlink()
            except OSError:
                pass
        try:
            tmp.rmdir()
        except OSError:
            pass