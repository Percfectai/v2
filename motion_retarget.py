"""
Percfect Motion — mastered skeletal overlay (CGI plate composite)

Pipeline:
  1. Analyze roster character SHOT with MediaPipe Pose → skeletal structure
  2. Load motion_data track(s) → per-frame skeleton + optional scale_box / world_anchor
  3. Map track frames onto plate timeline (sparse sample_every_n safe)
  4. Per frame: scale + translate so roster feet/hips lock to motion feet/hips
  5. EMA smooth placement (kill jitter), quality-hold on bad frames
  6. Dual: paint far→near by world z / feet depth
  7. Composite onto extracted background plate

CPU only. MediaPipe Tasks Pose Landmarker (IMAGE) for character analysis.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from PIL import Image

os.environ.setdefault("MEDIAPIPE_DISABLE_GPU", "1")

NOSE = 0
L_SHOULDER, R_SHOULDER = 11, 12
L_HIP, R_HIP = 23, 24
L_ANKLE, R_ANKLE = 27, 28

# Placement quality gates (skeletal-align skill)
VIS_GATE = 0.45
PLACE_EMA_ALPHA = 0.32  # lower = smoother, higher = snappier
MIN_QUALITY_HOLD = 0.28

POSE_MODEL_PATH = Path(os.environ.get("POSE_MODEL_PATH", "/tmp/pose_landmarker_heavy.task"))
POSE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_heavy/float16/1/pose_landmarker_heavy.task"
)

_landmarker = None


def _ensure_pose_model() -> str:
    if not POSE_MODEL_PATH.exists():
        POSE_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(POSE_MODEL_URL, POSE_MODEL_PATH)
    return str(POSE_MODEL_PATH)


def _get_image_landmarker():
    global _landmarker
    if _landmarker is not None:
        return _landmarker
    import mediapipe as mp  # noqa: F401
    from mediapipe.tasks import python as mp_tasks
    from mediapipe.tasks.python import vision

    base = mp_tasks.BaseOptions(
        model_asset_path=_ensure_pose_model(),
        delegate=mp_tasks.BaseOptions.Delegate.CPU,
    )
    opts = vision.PoseLandmarkerOptions(
        base_options=base,
        running_mode=vision.RunningMode.IMAGE,
        num_poses=1,
        min_pose_detection_confidence=0.35,
        min_pose_presence_confidence=0.35,
        min_tracking_confidence=0.35,
    )
    _landmarker = vision.PoseLandmarker.create_from_options(opts)
    return _landmarker


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
            timeout=300,
        )
        return out_path.is_file() and out_path.stat().st_size > 0
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def default_profile() -> dict:
    return {
        "version": 1,
        "source": "default",
        "anchor": {
            "feet_y": 0.94,
            "center_x": 0.5,
            "head_y": 0.08,
            "body_height_norm": 0.86,
            "hip_y": 0.55,
        },
        "landmarks": None,
        "quality": 0.0,
    }


def _pt(lm_list, idx: int) -> Optional[Tuple[float, float, float]]:
    if not lm_list or idx >= len(lm_list):
        return None
    p = lm_list[idx]
    if isinstance(p, dict):
        try:
            vis = float(p.get("visibility", 1) or 1)
            return float(p["x"]), float(p["y"]), vis
        except Exception:
            return None
    try:
        return float(p.x), float(p.y), float(getattr(p, "visibility", 1) or 1)
    except Exception:
        return None


def _mid(a, b):
    if a and b:
        return (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, min(a[2], b[2])
    return a or b


def skeleton_anchors(landmarks) -> dict:
    """Feet / hips / head / body_height from MediaPipe 33 landmarks (normalized 0–1)."""
    nose = _pt(landmarks, NOSE)
    l_hip, r_hip = _pt(landmarks, L_HIP), _pt(landmarks, R_HIP)
    l_ank, r_ank = _pt(landmarks, L_ANKLE), _pt(landmarks, R_ANKLE)
    l_sh, r_sh = _pt(landmarks, L_SHOULDER), _pt(landmarks, R_SHOULDER)

    # Prefer high-visibility ankles for floor lock
    feet = None
    if l_ank and r_ank and l_ank[2] >= VIS_GATE and r_ank[2] >= VIS_GATE:
        feet = _mid(l_ank, r_ank)
    elif l_ank and l_ank[2] >= VIS_GATE:
        feet = l_ank
    elif r_ank and r_ank[2] >= VIS_GATE:
        feet = r_ank
    else:
        feet = _mid(l_ank, r_ank)

    hips = _mid(l_hip, r_hip)
    shoulders = _mid(l_sh, r_sh)
    head = nose or shoulders

    if not feet or not head:
        return {
            "feet_y": 0.94,
            "center_x": 0.5,
            "head_y": 0.08,
            "body_height_norm": 0.86,
            "hip_y": 0.55,
            "quality": 0.0,
        }

    head_y = float(head[1])
    feet_y = float(feet[1])
    center_x = float(hips[0]) if hips else float(feet[0])
    hip_y = float(hips[1]) if hips else (head_y + feet_y) * 0.55
    body_h = max(0.18, min(0.98, feet_y - head_y))

    key = []
    for p in (nose, l_hip, r_hip, l_ank, r_ank, l_sh, r_sh):
        if p and p[2] >= VIS_GATE:
            key.append(p)
    quality = len(key) / 7.0
    return {
        "feet_y": feet_y,
        "center_x": center_x,
        "head_y": head_y,
        "body_height_norm": body_h,
        "hip_y": hip_y,
        "quality": quality,
    }


def landmarks_to_list(pose_landmarks) -> List[dict]:
    return [
        {
            "x": float(lm.x),
            "y": float(lm.y),
            "z": float(lm.z),
            "visibility": float(getattr(lm, "visibility", 1.0) or 1.0),
        }
        for lm in pose_landmarks
    ]


def analyze_character_image(im: Image.Image) -> dict:
    """MediaPipe Pose on roster still → skeletal structure for retarget.

    Never raises — always returns a usable profile so overlay cannot die on pose.
    """
    rgb = np.array(im.convert("RGB"))
    h, w = rgb.shape[:2]
    profile = default_profile()
    profile["image_size"] = {"width": int(w), "height": int(h)}

    try:
        import mediapipe as mp

        landmarker = _get_image_landmarker()
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        result = landmarker.detect(mp_image)
        if not result.pose_landmarks:
            profile["source"] = "default_no_pose"
            return profile
        lms = landmarks_to_list(result.pose_landmarks[0])
        anchors = skeleton_anchors(lms)
        profile["source"] = "mediapipe_image"
        profile["anchor"] = {
            "feet_y": anchors["feet_y"],
            "center_x": anchors["center_x"],
            "head_y": anchors["head_y"],
            "body_height_norm": anchors["body_height_norm"],
            "hip_y": anchors["hip_y"],
        }
        profile["landmarks"] = lms
        profile["quality"] = anchors["quality"]
        return profile
    except Exception as e:
        profile["source"] = "default_error"
        profile["error"] = str(e)[:200]
        return profile


def _trim_alpha_bbox(bgra: np.ndarray, pad: int = 2) -> np.ndarray:
    """Crop to opaque content so feet_y / center_x match the sprite, not empty padding."""
    if bgra is None or bgra.size == 0:
        return bgra
    alpha = bgra[:, :, 3]
    ys, xs = np.where(alpha > 18)
    if len(xs) < 20 or len(ys) < 20:
        return bgra
    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    h, w = bgra.shape[:2]
    y0 = max(0, y0 - pad)
    x0 = max(0, x0 - pad)
    y1 = min(h - 1, y1 + pad)
    x1 = min(w - 1, x1 + pad)
    return bgra[y0 : y1 + 1, x0 : x1 + 1].copy()


def _feather_alpha(bgra: np.ndarray, radius: int = 2) -> np.ndarray:
    """Soft edge so hard cutouts blend into the plate."""
    if radius <= 0 or bgra is None:
        return bgra
    out = bgra.copy()
    a = out[:, :, 3].astype(np.float32)
    if float(a.mean()) < 1:
        return out
    k = max(3, radius * 2 + 1)
    soft = cv2.GaussianBlur(a, (k, k), 0)
    # Keep interior solid, only soften silhouette edge
    solid = (a > 200).astype(np.float32)
    solid = cv2.erode(solid, np.ones((3, 3), np.uint8), iterations=1)
    mixed = a * solid + soft * (1.0 - solid)
    out[:, :, 3] = np.clip(mixed, 0, 255).astype(np.uint8)
    return out


def make_cutout_bgra(im: Image.Image, key_out_white: Optional[Callable] = None) -> np.ndarray:
    """Character cutout BGRA — trimmed, feathered, never fully transparent."""
    base = im.convert("RGBA")
    arr = np.array(base)
    arr[:, :, 3] = 255

    if key_out_white is not None:
        try:
            k = key_out_white(base.copy()).convert("RGBA")
            ka = np.array(k)
            cov = float((ka[:, :, 3] > 20).mean())
            if 0.06 < cov < 0.98:
                arr = ka
        except Exception:
            pass

    if float((arr[:, :, 3] > 20).mean()) < 0.06:
        rgb = arr[:, :, :3].astype(np.float32)
        dist = np.linalg.norm(rgb - 255.0, axis=2)
        corners = [dist[1, 1], dist[1, -2], dist[-2, 1], dist[-2, -2]]
        if float(np.mean(corners)) < 50:
            alpha = np.clip((dist - 22) / 50.0, 0, 1)
            arr[:, :, 3] = (alpha * 255).astype(np.uint8)
        if float((arr[:, :, 3] > 20).mean()) < 0.06:
            arr[:, :, 3] = 255

    # Mild auto white-ish corner key when no key_out_white
    if key_out_white is None and float((arr[:, :, 3] > 200).mean()) > 0.95:
        rgb = arr[:, :, :3].astype(np.float32)
        # Near-white + low saturation background
        mx = rgb.max(axis=2)
        mn = rgb.min(axis=2)
        near_white = (mx > 235) & ((mx - mn) < 28)
        if float(near_white.mean()) > 0.12:
            a = arr[:, :, 3].astype(np.float32)
            a[near_white] = np.minimum(a[near_white], 0)
            # Soft threshold
            dist = np.linalg.norm(rgb - 255.0, axis=2)
            a = np.where(dist < 40, np.clip((dist - 12) / 35.0, 0, 1) * 255, a)
            arr[:, :, 3] = a.astype(np.uint8)
            if float((arr[:, :, 3] > 20).mean()) < 0.08:
                arr[:, :, 3] = 255

    bgra = arr[:, :, [2, 1, 0, 3]].copy()
    bgra = _trim_alpha_bbox(bgra, pad=3)
    bgra = _feather_alpha(bgra, radius=2)
    return bgra


def prepare_cutout(im: Image.Image, key_out_white: Optional[Callable] = None) -> Image.Image:
    bgra = make_cutout_bgra(im, key_out_white)
    return Image.fromarray(bgra[:, :, [2, 1, 0, 3]], "RGBA")


def _overlay_bgra(frame_bgr: np.ndarray, cut_bgra: np.ndarray, x: int, y: int) -> np.ndarray:
    """Alpha-composite cutout onto plate. Allows partial overhang (feet lock)."""
    out = frame_bgr
    fh, fw = out.shape[:2]
    ch, cw = cut_bgra.shape[:2]
    x0, y0 = int(x), int(y)
    sx0, sy0 = max(0, -x0), max(0, -y0)
    sx1 = cw - max(0, x0 + cw - fw)
    sy1 = ch - max(0, y0 + ch - fh)
    dx0, dy0 = max(0, x0), max(0, y0)
    dx1, dy1 = min(fw, x0 + cw), min(fh, y0 + ch)
    if sx1 <= sx0 or sy1 <= sy0 or dx1 <= dx0 or dy1 <= dy0:
        return out
    roi = out[dy0:dy1, dx0:dx1].astype(np.float32)
    patch = cut_bgra[sy0:sy1, sx0:sx1].astype(np.float32)
    if roi.shape[:2] != patch.shape[:2]:
        return out
    alpha = patch[:, :, 3:4] / 255.0
    if float(alpha.max()) < 0.02:
        return out
    out[dy0:dy1, dx0:dx1] = np.clip(
        patch[:, :, :3] * alpha + roi * (1.0 - alpha), 0, 255
    ).astype(np.uint8)
    return out


def skeletal_place(
    frame_h: int,
    frame_w: int,
    cut_h: int,
    cut_w: int,
    roster_profile: dict,
    motion_landmarks,
    scale_box: Optional[dict] = None,
    world_anchor: Optional[dict] = None,
) -> Tuple[int, int, int, int, dict]:
    """
    Align roster cutout into frame by matching skeletal anchors.

    Feet-bottom + hip center lock. Prefers analyzer scale_box when present.
    Soft edge clamp preserves floor contact (does not force full sprite in-frame).
    """
    r = (roster_profile or default_profile()).get("anchor") or default_profile()["anchor"]
    r_feet_y = float(r.get("feet_y") or 0.94)
    r_cx = float(r.get("center_x") or 0.5)
    r_body = float(r.get("body_height_norm") or 0.86)
    r_body = max(0.15, min(0.98, r_body))

    info: Dict[str, Any] = {"mode": "skeletal", "quality": 0.0}

    m = None
    if isinstance(scale_box, dict) and scale_box.get("body_height_norm"):
        m = {
            "body_height_norm": float(scale_box["body_height_norm"]),
            "feet_y": float(scale_box.get("feet_y") or 0.94),
            "center_x": float(scale_box.get("center_x") or scale_box.get("feet_x") or 0.5),
            "quality": 0.9,
        }
        info["mode"] = "stage_scale_box"
    elif motion_landmarks and len(motion_landmarks) >= 25:
        m = skeleton_anchors(motion_landmarks)

    if m and m.get("quality", 0) >= MIN_QUALITY_HOLD:
        m_body = max(0.15, float(m["body_height_norm"]))
        m_feet_y = float(np.clip(m["feet_y"], 0.05, 0.99))
        m_cx = float(np.clip(m["center_x"], 0.02, 0.98))
        info["quality"] = float(m.get("quality") or 0)

        # scale so roster body height matches motion body height in pixels
        motion_body_px = m_body * frame_h
        roster_body_px = r_body * cut_h
        scale = motion_body_px / max(1.0, roster_body_px)
        scale = float(np.clip(scale, 0.18, 4.5))

        new_h = max(32, int(round(cut_h * scale)))
        new_w = max(32, int(round(cut_w * scale)))

        # Cap size without breaking feet lock (prefer shrinking, not recentering)
        max_h = int(frame_h * 0.95)
        max_w = int(frame_w * 0.95)
        if new_h > max_h or new_w > max_w:
            s = min(max_h / max(1, new_h), max_w / max(1, new_w))
            new_h = max(32, int(new_h * s))
            new_w = max(32, int(new_w * s))
            scale *= s

        # Feet + hip lock (CGI plate composite on stage)
        place_x = int(round(m_cx * frame_w - r_cx * new_w))
        place_y = int(round(m_feet_y * frame_h - r_feet_y * new_h))

        info.update({
            "scale": round(scale, 4),
            "motion_body_h": round(m_body, 4),
            "roster_body_h": round(r_body, 4),
            "motion_feet_y": round(m_feet_y, 4),
            "motion_center_x": round(m_cx, 4),
            "roster_source": (roster_profile or {}).get("source"),
        })
        if isinstance(world_anchor, dict):
            info["world_anchor"] = {
                "x": world_anchor.get("x"),
                "y": world_anchor.get("y"),
                "z": world_anchor.get("z"),
            }
            info["depth"] = float(world_anchor.get("z") or 0)
        else:
            # Image depth proxy: larger feet_y → closer to camera
            info["depth"] = float(m_feet_y)
    else:
        info["mode"] = "geometric"
        info["quality"] = float(m.get("quality") if m else 0)
        target_h = int(frame_h * 0.72)
        scale = target_h / max(1, cut_h)
        new_h = max(32, int(round(cut_h * scale)))
        new_w = max(32, int(round(cut_w * scale)))
        if new_h > int(frame_h * 0.9):
            s = (frame_h * 0.9) / new_h
            new_h, new_w = int(new_h * s), int(new_w * s)
        place_x = (frame_w - new_w) // 2
        place_y = int(frame_h - r_feet_y * new_h)
        info["depth"] = 0.9
        info["scale"] = round(new_h / max(1, cut_h), 4)

    # Soft clamp: allow overhang so feet stay on motion feet line
    place_x = int(np.clip(place_x, int(-new_w * 0.35), int(frame_w - new_w * 0.65)))
    # Head may clip top; feet may sit near bottom edge
    place_y = int(np.clip(place_y, int(-new_h * 0.15), int(frame_h - new_h * 0.12)))

    return place_x, place_y, new_w, new_h, info


def _normalize_track(track) -> List[dict]:
    if track is None:
        return []
    if isinstance(track, dict):
        track = track.get("frames") or track.get("motion") or track.get("landmarks") or []
    if not isinstance(track, list):
        return []
    out = []
    for i, entry in enumerate(track):
        if isinstance(entry, dict) and "landmarks" in entry:
            e = dict(entry)
            if "frame" not in e:
                e["frame"] = i
            out.append(e)
        elif isinstance(entry, list) and entry and isinstance(entry[0], dict):
            out.append({"frame": i, "landmarks": entry})
        elif isinstance(entry, dict):
            e = dict(entry)
            if "frame" not in e:
                e["frame"] = i
            out.append(e)
    return out


def _landmarks_from_entry(entry) -> Optional[list]:
    if not entry:
        return None
    if isinstance(entry, dict):
        lm = entry.get("landmarks") or entry.get("pose")
        if isinstance(lm, list) and len(lm) >= 25:
            return lm
    if isinstance(entry, list) and len(entry) >= 25:
        return entry
    return None


def _build_frame_index(track: List[dict]) -> Dict[int, dict]:
    """Map source frame number → entry for sparse tracks."""
    idx: Dict[int, dict] = {}
    for i, e in enumerate(track):
        if not isinstance(e, dict):
            continue
        f = e.get("frame")
        try:
            f = int(f) if f is not None else i
        except (TypeError, ValueError):
            f = i
        idx[f] = e
    return idx


def _entry_for_video_frame(
    frame_i: int,
    track: List[dict],
    frame_index: Dict[int, dict],
    total_video_frames: int,
) -> Optional[dict]:
    """Map plate frame → best motion entry (exact, nearest, or ratio map)."""
    if not track:
        return None
    if frame_i in frame_index:
        return frame_index[frame_i]
    # Nearest known frame
    if frame_index:
        keys = sorted(frame_index.keys())
        # Prefer last key ≤ frame_i, else nearest
        lo = [k for k in keys if k <= frame_i]
        if lo:
            return frame_index[lo[-1]]
        # Ahead only
        return frame_index[keys[0]]
    # Dense list without frame ids: ratio map
    if total_video_frames <= 1:
        return track[0]
    t = frame_i / max(1, total_video_frames - 1)
    ti = int(round(t * (len(track) - 1)))
    ti = max(0, min(len(track) - 1, ti))
    return track[ti]


def _ema_box(
    prev: Optional[Tuple[float, float, float, float]],
    x: int,
    y: int,
    nw: int,
    nh: int,
    alpha: float = PLACE_EMA_ALPHA,
) -> Tuple[int, int, int, int]:
    """Smooth placement to kill skeleton jitter."""
    if prev is None:
        return x, y, nw, nh
    px, py, pnw, pnh = prev
    nx = (1 - alpha) * px + alpha * x
    ny = (1 - alpha) * py + alpha * y
    nnw = (1 - alpha) * pnw + alpha * nw
    nnh = (1 - alpha) * pnh + alpha * nh
    return int(round(nx)), int(round(ny)), max(32, int(round(nnw))), max(32, int(round(nnh)))


def _draw_debug_skeleton(
    frame_bgr: np.ndarray,
    landmarks,
    color: Tuple[int, int, int] = (0, 255, 136),
) -> None:
    """Optional debug sticks on composite (in-place)."""
    if not landmarks or len(landmarks) < 25:
        return
    h, w = frame_bgr.shape[:2]
    edges = (
        (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
        (11, 23), (12, 24), (23, 24),
        (23, 25), (25, 27), (24, 26), (26, 28),
    )

    def pt(i):
        p = _pt(landmarks, i)
        if not p or p[2] < 0.25:
            return None
        return int(p[0] * w), int(p[1] * h)

    for a, b in edges:
        pa, pb = pt(a), pt(b)
        if pa and pb:
            cv2.line(frame_bgr, pa, pb, color, 1, cv2.LINE_AA)


def retarget_video(
    background_video_path: str,
    tracks: Sequence,
    cutouts: Sequence,
    profiles: Sequence[dict],
    *,
    fps_override: Optional[float] = None,
    max_frames: int = 900,
    key_out_white: Optional[Callable] = None,
    character_images: Optional[Sequence[Image.Image]] = None,
    draw_debug_skeleton: bool = False,
    smooth: bool = True,
) -> bytes:
    """
    Mastered CGI-style plate overlay:
      analyze character skeleton → map to motion skeleton → composite on plate
    """
    if not cutouts:
        raise ValueError("Need at least one character.")

    cut_list = list(cutouts)
    n = len(cut_list)
    cut_bgra: List[np.ndarray] = []
    final_profiles: List[dict] = []

    for i, c in enumerate(cut_list):
        if isinstance(c, Image.Image):
            pil = c.convert("RGBA")
            src_for_pose = (
                character_images[i].convert("RGB")
                if character_images and i < len(character_images)
                else c.convert("RGB")
            )
        elif isinstance(c, np.ndarray) and c.ndim == 3 and c.shape[2] == 4:
            pil = Image.fromarray(c[:, :, [2, 1, 0, 3]], "RGBA")
            src_for_pose = pil.convert("RGB")
        else:
            raise ValueError("Cutouts must be PIL Images or BGRA arrays")

        cut_bgra.append(make_cutout_bgra(pil, key_out_white))

        # ALWAYS analyze character shot skeleton for placement
        try:
            prof = analyze_character_image(src_for_pose)
        except Exception:
            prof = (profiles[i] if profiles and i < len(profiles) else None) or default_profile()
        if prof.get("source") in ("default_no_pose", "default_error", "default"):
            stored = (profiles[i] if profiles and i < len(profiles) else None) or {}
            if isinstance(stored, dict) and stored.get("anchor") and stored.get("source") not in (
                None, "default",
            ):
                # Re-analyze may fail; use stored roster motion_profile
                if float(prof.get("quality") or 0) < 0.3:
                    prof = stored
        # After trim, re-weight anchors toward bottom-center if pose missing
        if float(prof.get("quality") or 0) < 0.2:
            a = dict(prof.get("anchor") or default_profile()["anchor"])
            a.setdefault("feet_y", 0.96)
            a.setdefault("center_x", 0.5)
            a.setdefault("body_height_norm", 0.88)
            prof = dict(prof)
            prof["anchor"] = a
        final_profiles.append(prof)

    tracks_n = [_normalize_track(t) for t in (tracks or [])]
    while len(tracks_n) < n:
        tracks_n.append(tracks_n[0] if tracks_n else [])
    tracks_n = tracks_n[:n]
    frame_indexes = [_build_frame_index(t) for t in tracks_n]

    cap = cv2.VideoCapture(background_video_path)
    if not cap.isOpened():
        raise ValueError("Could not open background plate video.")

    fps = fps_override or cap.get(cv2.CAP_PROP_FPS) or 24.0
    if not fps or fps < 1:
        fps = 24.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1280)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 720)
    total_est = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0) or max_frames
    if width % 2:
        width -= 1
    if height % 2:
        height -= 1

    tmp = Path(tempfile.mkdtemp(prefix="percfect_skel_overlay_"))
    raw_mp4 = tmp / "overlay_raw.mp4"
    writer = None
    for name, fourcc, ext in (
        ("mp4v", "mp4v", ".mp4"),
        ("avc1", "avc1", ".mp4"),
        ("XVID", "XVID", ".avi"),
        ("MJPG", "MJPG", ".avi"),
    ):
        raw_mp4 = tmp / f"overlay_raw{ext}"
        writer = cv2.VideoWriter(
            str(raw_mp4), cv2.VideoWriter_fourcc(*fourcc), float(fps), (width, height)
        )
        if writer.isOpened():
            break
        writer.release()
        writer = None
    if writer is None or not writer.isOpened():
        cap.release()
        raise RuntimeError("Could not open video writer (tried mp4v/avc1/XVID/MJPG).")

    # Per-track smoothed placement state
    smooth_box: List[Optional[Tuple[float, float, float, float]]] = [None] * n
    last_good: List[Optional[Tuple[int, int, int, int]]] = [None] * n
    written = painted = skeletal = held = 0
    modes_count: Dict[str, int] = {}

    try:
        while written < max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            if frame.shape[1] != width or frame.shape[0] != height:
                frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
            out = frame.copy()

            # Gather placements first so we can depth-sort dual
            placements: List[Tuple[int, int, int, int, int, np.ndarray, dict, Optional[list]]] = []
            # (ti, x, y, nw, nh, cut, info, landmarks)

            for ti in range(n):
                track = tracks_n[ti]
                entry = _entry_for_video_frame(
                    written, track, frame_indexes[ti], total_est
                )
                motion_lm = _landmarks_from_entry(entry)
                scale_box = entry.get("scale_box") if isinstance(entry, dict) else None
                world_anchor = entry.get("world_anchor") if isinstance(entry, dict) else None

                ch0, cw0 = cut_bgra[ti].shape[:2]
                use_hold = False
                info: Dict[str, Any] = {"mode": "hold", "quality": 0}

                if motion_lm is None and scale_box is None:
                    use_hold = True
                else:
                    x, y, nw, nh, info = skeletal_place(
                        height,
                        width,
                        ch0,
                        cw0,
                        final_profiles[ti],
                        motion_lm,
                        scale_box=scale_box,
                        world_anchor=world_anchor,
                    )
                    if info.get("quality", 1) < MIN_QUALITY_HOLD and last_good[ti] is not None:
                        use_hold = True
                        info["mode"] = "hold_low_quality"

                if use_hold and last_good[ti] is not None:
                    x, y, nw, nh = last_good[ti]
                    held += 1
                    modes_count["hold"] = modes_count.get("hold", 0) + 1
                elif use_hold:
                    # First frames with no track: geometric bottom
                    x, y, nw, nh, info = skeletal_place(
                        height, width, ch0, cw0, final_profiles[ti], None
                    )
                    modes_count["geometric"] = modes_count.get("geometric", 0) + 1
                else:
                    mode = info.get("mode", "?")
                    modes_count[mode] = modes_count.get(mode, 0) + 1
                    if mode in ("skeletal", "stage_scale_box"):
                        skeletal += 1

                if smooth and not use_hold:
                    x, y, nw, nh = _ema_box(smooth_box[ti], x, y, nw, nh)
                    smooth_box[ti] = (float(x), float(y), float(nw), float(nh))
                elif use_hold and last_good[ti] is not None:
                    pass
                else:
                    smooth_box[ti] = (float(x), float(y), float(nw), float(nh))

                cut = cut_bgra[ti]
                if (nh, nw) != (ch0, cw0):
                    cut = cv2.resize(
                        cut, (max(8, nw), max(8, nh)), interpolation=cv2.INTER_LINEAR
                    )

                last_good[ti] = (x, y, nw, nh)
                placements.append((ti, x, y, nw, nh, cut, info, motion_lm))

            # Far → near (higher depth z or larger feet_y = closer = paint later)
            def depth_key(p):
                info = p[6]
                d = info.get("depth")
                if d is None and isinstance(info.get("world_anchor"), dict):
                    d = info["world_anchor"].get("z", 0)
                if d is None:
                    d = info.get("motion_feet_y", 0.5)
                return float(d)

            placements.sort(key=depth_key)

            for ti, x, y, nw, nh, cut, info, motion_lm in placements:
                mean_before = float(out.mean())
                out = _overlay_bgra(out, cut, x, y)
                if abs(float(out.mean()) - mean_before) > 0.003:
                    painted += 1
                else:
                    # Last resort: opaque sprite still locked to place (not center)
                    cut2 = cut.copy()
                    cut2[:, :, 3] = 255
                    out = _overlay_bgra(out, cut2, x, y)
                    painted += 1
                if draw_debug_skeleton and motion_lm:
                    colors = [(0, 255, 136), (255, 179, 102)]
                    _draw_debug_skeleton(out, motion_lm, colors[ti % 2])

            writer.write(out)
            written += 1
    finally:
        cap.release()
        writer.release()

    if written == 0:
        raise ValueError("Background plate had no frames.")
    if painted == 0:
        raise ValueError("Overlay painted 0 frames — character never appeared on plate.")

    meta = {
        "written": written,
        "painted": painted,
        "skeletal_frames": skeletal,
        "held_frames": held,
        "modes": modes_count,
        "smooth": smooth,
        "profiles": [
            {
                "source": p.get("source"),
                "anchor": p.get("anchor"),
                "quality": p.get("quality"),
            }
            for p in final_profiles
        ],
        "engine": "percfect_overlay_v2",
    }
    try:
        (tmp / "overlay_meta.json").write_text(json.dumps(meta, indent=2))
    except Exception:
        pass

    h264 = tmp / "overlay.mp4"
    if _try_h264(raw_mp4, h264):
        return h264.read_bytes()
    return raw_mp4.read_bytes()


def estimate_retarget_credits(duration_sec: float, video_rate: int = 6) -> int:
    d = max(1.0, min(float(duration_sec or 6), 45.0))
    return max(6, min(90, int(math.ceil(d * video_rate * 0.5))))
