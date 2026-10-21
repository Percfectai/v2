#!/usr/bin/env python3
"""
Percfect Motion Analyzer v2 — MediaPipe Tasks API (no mp.solutions).
Supports 1 or 2 characters. One analyzer instance per request (VIDEO mode state).

BG removal engine tag:
  Responses include bg_removal_engine="mediapipe" (local selfie-seg plates).
  Main app may overlay PoYo (poyo.ai) character plates via motion_bg_extract
  and rewrite engine to "poyo" while keeping motion tracks from this service.
"""

import os

os.environ.setdefault("MEDIAPIPE_DISABLE_GPU", "1")

import uuid
import json
import shutil
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

import cv2
import mediapipe as mp
import numpy as np
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import uvicorn

from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision

MAX_VIDEO_SECONDS = 45
MAX_FILE_SIZE_MB = 50
MAX_PROCESS_WIDTH = 1280
MAX_PROCESS_HEIGHT = 720
DEFAULT_SAMPLE_EVERY_N = 1
VALIDATION_JOINTS = (11, 12, 15, 16, 23, 24)
RECHECK_DRIFT_THRESHOLD = 0.08
LOW_VISIBILITY_THRESHOLD = 0.45
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm", "video/x-matroska"}

OUTPUT_BASE = Path("/tmp/percfect_motion_outputs")
OUTPUT_BASE.mkdir(parents=True, exist_ok=True)

POSE_MODEL_PATH = Path("/tmp/pose_landmarker_heavy.task")
POSE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_heavy/float16/1/pose_landmarker_heavy.task"
)

SEG_MODEL_PATH = Path("/tmp/selfie_segmenter.tflite")
SEG_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/image_segmenter/"
    "selfie_segmenter/float16/latest/selfie_segmenter.tflite"
)

CORS_ORIGINS = [
    "https://percfectai.com",
    "https://www.percfectai.com",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield


ANALYZER_VERSION = "2.8.2"

app = FastAPI(
    title="Percfect Motion Analyzer v2",
    description=(
        "Skeletal detection + multi-color outline palette + character spotting "
        "for 1–2 humans (short clips). Local BG plates use MediaPipe; main app "
        "may upgrade character plate via PoYo (poyo.ai)."
    ),
    version=ANALYZER_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/outputs", StaticFiles(directory=str(OUTPUT_BASE)), name="outputs")


def _ensure_model(path: Path, url: str) -> str:
    if not path.exists():
        urllib.request.urlretrieve(url, path)
    return str(path)


def _ensure_pose_model() -> str:
    return _ensure_model(POSE_MODEL_PATH, POSE_MODEL_URL)


def _ensure_seg_model() -> str:
    return _ensure_model(SEG_MODEL_PATH, SEG_MODEL_URL)


def _cpu_base_options(model_asset_path: str) -> mp_tasks.BaseOptions:
    return mp_tasks.BaseOptions(
        model_asset_path=model_asset_path,
        delegate=mp_tasks.BaseOptions.Delegate.CPU,
    )


def _landmarks_to_dict(landmarks) -> List[Dict[str, float]]:
    return [
        {
            "x": float(lm.x),
            "y": float(lm.y),
            "z": float(lm.z),
            "visibility": float(getattr(lm, "visibility", 1.0)),
        }
        for lm in landmarks
    ]


def _pose_center(landmarks, width: int, height: int) -> Tuple[float, float]:
    if len(landmarks) < 25:
        xs = [lm.x * width for lm in landmarks]
        ys = [lm.y * height for lm in landmarks]
        return float(np.mean(xs)), float(np.mean(ys))
    left_hip = landmarks[23]
    right_hip = landmarks[24]
    cx = (left_hip.x + right_hip.x) * 0.5 * width
    cy = (left_hip.y + right_hip.y) * 0.5 * height
    return float(cx), float(cy)


def _as_2d_mask(mask: np.ndarray) -> np.ndarray:
    """Force masks to (H, W). NumPy 2.x cannot broadcast (H, W) with (H, W, 1)."""
    arr = np.asarray(mask)
    while arr.ndim > 2:
        if arr.shape[-1] == 1:
            arr = arr[..., 0]
        else:
            arr = np.squeeze(arr)
            if arr.ndim > 2:
                arr = arr[..., 0]
    if arr.ndim != 2:
        raise ValueError(f"Expected 2D mask, got {np.asarray(mask).shape}")
    return np.ascontiguousarray((arr > 0).astype(np.uint8))


def _foreground_mask_from_segmentation(seg_result, threshold: float = 0.5) -> Optional[np.ndarray]:
    if not seg_result.confidence_masks:
        return None
    mask = seg_result.confidence_masks[0].numpy_view()
    return _as_2d_mask(mask > threshold)


def _processing_dimensions(width: int, height: int) -> Tuple[int, int]:
    if width <= MAX_PROCESS_WIDTH and height <= MAX_PROCESS_HEIGHT:
        return width, height
    scale = min(MAX_PROCESS_WIDTH / width, MAX_PROCESS_HEIGHT / height)
    proc_w = max(2, int(width * scale) // 2 * 2)
    proc_h = max(2, int(height * scale) // 2 * 2)
    return proc_w, proc_h


def _resize_for_processing(frame: np.ndarray, proc_w: int, proc_h: int) -> np.ndarray:
    h, w = frame.shape[:2]
    if w == proc_w and h == proc_h:
        return frame
    return cv2.resize(frame, (proc_w, proc_h), interpolation=cv2.INTER_AREA)


def _key_joint_quality(landmarks: List[Dict[str, float]]) -> float:
    if len(landmarks) < 25:
        return 0.0
    vis = [landmarks[i].get("visibility", 0.0) for i in VALIDATION_JOINTS]
    return float(sum(vis) / len(vis))


def _landmark_drift(
    a: List[Dict[str, float]], b: List[Dict[str, float]]
) -> float:
    if not a or not b:
        return 1.0
    max_delta = 0.0
    for idx in VALIDATION_JOINTS:
        if idx >= len(a) or idx >= len(b):
            continue
        dx = a[idx]["x"] - b[idx]["x"]
        dy = a[idx]["y"] - b[idx]["y"]
        max_delta = max(max_delta, float((dx * dx + dy * dy) ** 0.5))
    return max_delta


def _landmarks_in_range(landmarks: List[Dict[str, float]]) -> bool:
    for idx in VALIDATION_JOINTS:
        if idx >= len(landmarks):
            return False
        lm = landmarks[idx]
        if not (-0.25 <= lm["x"] <= 1.25 and -0.25 <= lm["y"] <= 1.25):
            return False
    return True


def _split_foreground_mask(
    foreground: np.ndarray,
    center_a: Tuple[float, float],
    center_b: Tuple[float, float],
) -> Tuple[np.ndarray, np.ndarray]:
    foreground = _as_2d_mask(foreground)
    h, w = foreground.shape
    yy, xx = np.mgrid[0:h, 0:w]
    fg = foreground > 0
    dist_a = (xx - center_a[0]) ** 2 + (yy - center_a[1]) ** 2
    dist_b = (xx - center_b[0]) ** 2 + (yy - center_b[1]) ** 2
    mask_a = (fg & (dist_a <= dist_b)).astype(np.uint8)
    mask_b = (fg & (dist_b < dist_a)).astype(np.uint8)
    return mask_a, mask_b


# ── Primary person isolation (ignore background movers) ────────────────────
# Seed body outline from pose joints + grow by LAB color differentials so
# moving backgrounds / extra people are not treated as the character skeleton.
# As the outline forms we recognize ALL colors inside its perimeter (palette),
# not just a single mean — multi-tone costumes (shirt + pants + hair) stay one body.

# Torso + limbs seed joints (MediaPipe 33)
_BODY_SEED_JOINTS = (0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28)
COLOR_LAB_TOLERANCE = 32.0
COLOR_REFINE_ITERS = 28
COLOR_REFINE_WINDOW = 7
# Max distinct colors sampled inside a forming outline perimeter
# Research: k≤5–6 dominant colors best for clothing (PyImageSearch k-means);
# person Re-ID uses part-wise HSV/LAB histograms (head / upper / lower).
OUTLINE_PALETTE_MAX = 6
OUTLINE_PALETTE_MIN_FRAC = 0.035
OUTLINE_PALETTE_REFRESH_EVERY = 6  # re-scan colors as outline grows
# Erode outline before color sample so edge bleed (BG) does not pollute palette
OUTLINE_INTERIOR_ERODE = 2
# Secondary poses smaller than this fraction of primary are treated as background
BG_POSE_SCALE_RATIO = 0.48


def _pose_body_height_px(landmarks, height: int) -> float:
    """Approximate body height in pixels from shoulders/hips to ankles."""
    if landmarks is None or len(landmarks) < 29:
        return 0.0

    def y(i):
        lm = landmarks[i]
        vis = float(getattr(lm, "visibility", 1.0) or 1.0)
        if vis < 0.2:
            return None
        return float(lm.y) * height

    tops = [y(i) for i in (0, 11, 12)]
    bots = [y(i) for i in (27, 28, 25, 26)]
    tops = [v for v in tops if v is not None]
    bots = [v for v in bots if v is not None]
    if not tops or not bots:
        return 0.0
    return max(0.0, float(max(bots) - min(tops)))


def _pose_visibility(landmarks) -> float:
    if landmarks is None or len(landmarks) < 25:
        return 0.0
    vis = []
    for i in VALIDATION_JOINTS:
        if i < len(landmarks):
            vis.append(float(getattr(landmarks[i], "visibility", 0.0) or 0.0))
    return float(sum(vis) / max(1, len(vis)))


def _pose_primary_score(landmarks, width: int, height: int) -> float:
    """Higher = more likely the intended foreground performer (not a tiny BG person)."""
    body_h = _pose_body_height_px(landmarks, height)
    if body_h < height * 0.12:
        return 0.0
    vis = _pose_visibility(landmarks)
    cx, cy = _pose_center(landmarks, width, height)
    # Prefer larger bodies near frame center (hero performer)
    center_bonus = 1.0 - min(1.0, abs(cx / max(1, width) - 0.5) * 1.4)
    y_bonus = 1.0 - min(1.0, abs(cy / max(1, height) - 0.55) * 0.8)
    return body_h * (0.45 + 0.55 * vis) * (0.55 + 0.45 * center_bonus) * (0.7 + 0.3 * y_bonus)


def _select_primary_poses(poses: Optional[List], width: int, height: int, n: int = 1) -> List:
    """Keep only the top-N real performers; drop tiny / edge background people."""
    if not poses:
        return []
    n = max(1, min(int(n), 2))
    scored = [(_pose_primary_score(p, width, height), p) for p in poses]
    scored = [(s, p) for s, p in scored if s > 0]
    if not scored:
        return list(poses)[:n]
    scored.sort(key=lambda t: t[0], reverse=True)
    primary_score = scored[0][0]
    kept = [scored[0][1]]
    for s, p in scored[1:]:
        if len(kept) >= n:
            break
        # Reject far-away / tiny extras that would pollute skeleton
        if s < primary_score * BG_POSE_SCALE_RATIO:
            continue
        # Reject nearly-overlapping same body
        c0 = _pose_center(kept[0], width, height)
        c1 = _pose_center(p, width, height)
        if abs(c0[0] - c1[0]) < width * 0.07 and abs(c0[1] - c1[1]) < height * 0.1:
            continue
        kept.append(p)
    return kept


def _pose_seed_mask(landmarks, width: int, height: int) -> np.ndarray:
    """Rough body seed from joint circles (torso + limbs) for color grow."""
    seed = np.zeros((height, width), dtype=np.uint8)
    if landmarks is None or len(landmarks) < 25:
        return seed
    body_h = max(24.0, _pose_body_height_px(landmarks, height))
    r_core = max(6, int(body_h * 0.07))
    r_limb = max(4, int(body_h * 0.045))
    for i in _BODY_SEED_JOINTS:
        if i >= len(landmarks):
            continue
        lm = landmarks[i]
        if float(getattr(lm, "visibility", 1.0) or 0.0) < 0.25:
            continue
        x = int(np.clip(lm.x * width, 0, width - 1))
        y = int(np.clip(lm.y * height, 0, height - 1))
        rad = r_core if i in (0, 11, 12, 23, 24) else r_limb
        cv2.circle(seed, (x, y), rad, 1, -1)
    # Connect shoulders–hips–ankles so seed is one connected body
    def pt(i):
        if i >= len(landmarks):
            return None
        lm = landmarks[i]
        if float(getattr(lm, "visibility", 1.0) or 0.0) < 0.25:
            return None
        return (int(np.clip(lm.x * width, 0, width - 1)), int(np.clip(lm.y * height, 0, height - 1)))

    for a, b in ((11, 12), (11, 23), (12, 24), (23, 24), (23, 27), (24, 28), (11, 15), (12, 16)):
        pa, pb = pt(a), pt(b)
        if pa and pb:
            cv2.line(seed, pa, pb, 1, thickness=max(3, r_limb))
    return seed


def _lab_to_hex_bgr_approx(sig: np.ndarray) -> str:
    """Rough hex for UI badge (convert mean LAB → BGR → hex)."""
    try:
        lab = np.uint8([[np.asarray(sig, dtype=np.float32).clip(0, 255)]])
        bgr = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)[0, 0]
        return "#{:02x}{:02x}{:02x}".format(int(bgr[2]), int(bgr[1]), int(bgr[0]))
    except Exception:
        return "#888888"


def _outline_interior_mask(mask: np.ndarray) -> np.ndarray:
    """Prefer interior of silhouette for color reads (avoid perimeter BG bleed)."""
    m = _as_2d_mask(mask)
    if m.sum() < 80 or OUTLINE_INTERIOR_ERODE <= 0:
        return m
    k = np.ones((3, 3), np.uint8)
    interior = cv2.erode(m, k, iterations=OUTLINE_INTERIOR_ERODE)
    if int(interior.sum()) < 40:
        return m
    return _as_2d_mask(interior)


def _kmeans_palette_from_pixels(
    pix_lab: np.ndarray,
    max_colors: int,
    min_fraction: float,
    region: str = "full",
) -> List[Dict[str, Any]]:
    """Cluster LAB pixels into dominant colors (masked silhouette only)."""
    if pix_lab is None or len(pix_lab) < 20:
        return []
    pix = np.asarray(pix_lab, dtype=np.float32)
    if len(pix) > 5000:
        rng = np.random.default_rng(42)
        pix = pix[rng.choice(len(pix), 5000, replace=False)]

    k = int(max(1, min(max_colors, max(1, len(pix) // 80))))
    if len(pix) < 400:
        k = min(k, 3)
    k = max(1, min(k, len(pix)))
    if k == 1:
        mean = pix.mean(axis=0)
        return [{
            "lab": [float(x) for x in mean],
            "fraction": 1.0,
            "hex": _lab_to_hex_bgr_approx(mean),
            "region": region,
        }]
    criteria = (
        cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
        25,
        0.8,
    )
    try:
        _compact, labels, centers = cv2.kmeans(
            pix, k, None, criteria, 4, cv2.KMEANS_PP_CENTERS
        )
    except cv2.error:
        mean = pix.mean(axis=0)
        return [{
            "lab": [float(x) for x in mean],
            "fraction": 1.0,
            "hex": _lab_to_hex_bgr_approx(mean),
            "region": region,
        }]

    labels = labels.flatten()
    counts = np.bincount(labels, minlength=k).astype(np.float32)
    total = float(counts.sum()) or 1.0
    fracs = counts / total
    palette: List[Dict[str, Any]] = []
    for i in range(k):
        frac = float(fracs[i])
        if frac < min_fraction and sum(1 for f in fracs if f >= min_fraction) >= 2:
            continue
        if frac < 0.012:
            continue
        c = centers[i].astype(np.float32)
        palette.append({
            "lab": [float(c[0]), float(c[1]), float(c[2])],
            "fraction": round(frac, 4),
            "hex": _lab_to_hex_bgr_approx(c),
            "region": region,
        })
    palette.sort(key=lambda p: -p["fraction"])
    return palette[:max_colors]


def _extract_outline_palette(
    frame_bgr: np.ndarray,
    mask: np.ndarray,
    max_colors: int = OUTLINE_PALETTE_MAX,
    min_fraction: float = OUTLINE_PALETTE_MIN_FRAC,
) -> List[Dict[str, Any]]:
    """Recognize ALL dominant colors inside a forming outline perimeter.

    Samples interior pixels only (eroded mask → no edge bleed), clusters in
    LAB (k≤6). Multi-tone outfits stay one character.
    """
    m = _outline_interior_mask(mask)
    if int(m.sum()) < 40:
        return []
    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    pix = lab[m > 0]
    if pix.size == 0:
        return []
    return _kmeans_palette_from_pixels(pix, max_colors, min_fraction, region="full")


def _pose_part_masks(
    landmarks,
    width: int,
    height: int,
    person_mask: Optional[np.ndarray] = None,
) -> Dict[str, np.ndarray]:
    """Skeletal body-part ROIs for pose-aware color reading (Re-ID style).

    head / upper (torso+arms) / lower (hips+legs) from MediaPipe joints,
    intersected with person outline when available.
    """
    h, w = height, width
    parts = {
        "head": np.zeros((h, w), dtype=np.uint8),
        "upper": np.zeros((h, w), dtype=np.uint8),
        "lower": np.zeros((h, w), dtype=np.uint8),
    }
    if landmarks is None or len(landmarks) < 29:
        return parts

    def pt(i):
        if i >= len(landmarks):
            return None
        lm = landmarks[i]
        if float(getattr(lm, "visibility", 1.0) or 0.0) < 0.2:
            return None
        return (
            int(np.clip(float(lm.x) * w, 0, w - 1)),
            int(np.clip(float(lm.y) * h, 0, h - 1)),
        )

    body_h = max(24.0, _pose_body_height_px(landmarks, h))
    r_head = max(8, int(body_h * 0.10))
    r_torso = max(10, int(body_h * 0.11))
    r_limb = max(7, int(body_h * 0.07))
    r_leg = max(8, int(body_h * 0.08))

    for i in (0, 7, 8, 9, 10):
        p = pt(i)
        if p:
            cv2.circle(parts["head"], p, r_head, 1, -1)
    for i in (11, 12, 13, 14, 15, 16):
        p = pt(i)
        if p:
            cv2.circle(parts["upper"], p, r_limb if i >= 13 else r_torso, 1, -1)
    for a, b in ((11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (11, 23), (12, 24)):
        pa, pb = pt(a), pt(b)
        if pa and pb:
            cv2.line(parts["upper"], pa, pb, 1, thickness=max(6, r_torso // 2))
    sh_l, sh_r, hip_l, hip_r = pt(11), pt(12), pt(23), pt(24)
    if sh_l and sh_r and hip_l and hip_r:
        poly = np.array([sh_l, sh_r, hip_r, hip_l], dtype=np.int32)
        cv2.fillConvexPoly(parts["upper"], poly, 1)

    for i in (23, 24, 25, 26, 27, 28):
        p = pt(i)
        if p:
            cv2.circle(parts["lower"], p, r_leg if i >= 25 else r_torso, 1, -1)
    for a, b in ((23, 24), (23, 25), (25, 27), (24, 26), (26, 28)):
        pa, pb = pt(a), pt(b)
        if pa and pb:
            cv2.line(parts["lower"], pa, pb, 1, thickness=max(6, r_leg // 2))

    if person_mask is not None:
        pm = _as_2d_mask(person_mask)
        for key in parts:
            parts[key] = _as_2d_mask(parts[key] & pm)
    return parts


def _extract_pose_region_palette(
    frame_bgr: np.ndarray,
    landmarks,
    person_mask: np.ndarray,
    max_colors: int = OUTLINE_PALETTE_MAX,
) -> List[Dict[str, Any]]:
    """Pose-aware multi-color read: all colors per skeletal body region.

    Research-backed aid for character analysis with skeletal detection:
      - Part-wise appearance (head/upper/lower) beats whole-body mean (Re-ID)
      - Interior outline only — no background pixels in k-means
      - LAB clusters for costume tones used in grow + track lock
    """
    h, w = frame_bgr.shape[:2]
    full = _extract_outline_palette(frame_bgr, person_mask, max_colors=max_colors)
    parts = _pose_part_masks(landmarks, w, h, person_mask)
    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)

    region_budget = {"head": 2, "upper": 3, "lower": 3}
    regional: List[Dict[str, Any]] = []
    for region, budget in region_budget.items():
        rm = parts[region]
        if int(rm.sum()) < 25:
            continue
        if int(rm.sum()) >= 80:
            rm = _outline_interior_mask(rm)
        pix = lab[rm > 0]
        regional.extend(
            _kmeans_palette_from_pixels(
                pix, budget, OUTLINE_PALETTE_MIN_FRAC, region=region
            )
        )

    merged: List[Dict[str, Any]] = []
    seen_hex = set()
    for p in regional + full:
        hx = str(p.get("hex") or "")
        if hx in seen_hex:
            continue
        seen_hex.add(hx)
        merged.append(p)
        if len(merged) >= max_colors:
            break
    if not merged:
        return full
    tot = sum(float(p.get("fraction") or 0) for p in merged) or 1.0
    for p in merged:
        p["fraction"] = round(float(p.get("fraction") or 0) / tot, 4)
    merged.sort(key=lambda p: -float(p.get("fraction") or 0))
    return merged


def _hsv_histogram_signature(
    frame_bgr: np.ndarray,
    mask: np.ndarray,
    h_bins: int = 16,
    s_bins: int = 8,
) -> Optional[np.ndarray]:
    """HSV HS histogram of outline interior — classic clothing Re-ID feature."""
    m = _outline_interior_mask(mask)
    if int(m.sum()) < 40:
        return None
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist(
        [hsv], [0, 1], (m * 255).astype(np.uint8), [h_bins, s_bins], [0, 180, 0, 256]
    )
    hist = cv2.normalize(hist, hist).flatten().astype(np.float32)
    return hist


def _hist_distance(a: Optional[np.ndarray], b: Optional[np.ndarray]) -> float:
    """Bhattacharyya distance in [0,1]; higher = more different costumes."""
    if a is None or b is None:
        return 1.0
    ha = a.reshape(-1, 1).astype(np.float32)
    hb = b.reshape(-1, 1).astype(np.float32)
    if ha.shape != hb.shape:
        return 1.0
    d = float(cv2.compareHist(ha, hb, cv2.HISTCMP_BHATTACHARYYA))
    return float(np.clip(d, 0.0, 1.0))


def _palette_lab_centers(palette: Optional[List[Dict[str, Any]]]) -> Optional[np.ndarray]:
    if not palette:
        return None
    return np.array([p["lab"] for p in palette], dtype=np.float32)


def _palette_primary_hex(palette: Optional[List[Dict[str, Any]]]) -> str:
    if not palette:
        return "#888888"
    return str(palette[0].get("hex") or "#888888")


def _palette_hex_list(palette: Optional[List[Dict[str, Any]]]) -> List[str]:
    if not palette:
        return []
    return [str(p.get("hex") or "#888888") for p in palette]


def _min_dist_to_palette(
    lab_img: np.ndarray,
    centers: np.ndarray,
) -> np.ndarray:
    """Per-pixel min LAB distance to any palette color (H,W)."""
    # lab_img: HxWx3, centers: Kx3
    h, w = lab_img.shape[:2]
    flat = lab_img.reshape(-1, 3)
    # chunk to avoid huge broadcast on big frames
    best = np.full(flat.shape[0], 1e9, dtype=np.float32)
    for c in centers:
        d = np.linalg.norm(flat - c.reshape(1, 3), axis=1)
        best = np.minimum(best, d.astype(np.float32))
    return best.reshape(h, w)


def _refine_mask_color_lab(
    frame_bgr: np.ndarray,
    seed_mask: np.ndarray,
    allow_mask: Optional[np.ndarray] = None,
    lab_tol: float = COLOR_LAB_TOLERANCE,
    iterations: int = COLOR_REFINE_ITERS,
) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
    """Grow person outline using ALL colors already inside the perimeter.

    1) Seed outline from pose
    2) Immediately recognize multi-color palette inside seed
    3) Grow ring: accept pixels that match any palette color OR local neighbor
    4) Refresh palette as outline expands so new costume tones are learned
    """
    refined = _as_2d_mask(seed_mask)
    empty_pal: List[Dict[str, Any]] = []
    if refined.sum() == 0:
        return refined, empty_pal
    if allow_mask is not None:
        allow = _as_2d_mask(allow_mask)
        refined = _as_2d_mask(refined & allow)
    else:
        allow = None
    if refined.sum() == 0:
        return refined, empty_pal

    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    kernel = np.ones((3, 3), np.uint8)
    window = max(3, COLOR_REFINE_WINDOW | 1)

    # Recognize colors as soon as outline begins forming
    palette = _extract_outline_palette(frame_bgr, refined)
    centers = _palette_lab_centers(palette)

    for it in range(max(1, iterations)):
        # Re-scan all colors inside current outline perimeter
        if it > 0 and it % OUTLINE_PALETTE_REFRESH_EVERY == 0:
            palette = _extract_outline_palette(frame_bgr, refined)
            centers = _palette_lab_centers(palette)

        dilated = _as_2d_mask(cv2.dilate(refined, kernel, iterations=1))
        candidates = np.logical_and(dilated > 0, refined == 0)
        if allow is not None:
            candidates = np.logical_and(candidates, allow > 0)
        if not np.any(candidates):
            break

        # Local continuity (neighbor LAB mean inside outline)
        refined_f = refined.astype(np.float32)
        neighbor_w = cv2.blur(refined_f, (window, window))
        local_lab = np.zeros_like(lab)
        for ch in range(3):
            blurred = cv2.blur(lab[:, :, ch] * refined_f, (window, window))
            local_lab[:, :, ch] = blurred / (neighbor_w + 1e-6)
        dist_local = np.linalg.norm(lab - local_lab, axis=2)
        match_local = dist_local <= lab_tol

        # Multi-color: pixel matches ANY recognized outline color
        if centers is not None and len(centers) > 0:
            dist_pal = _min_dist_to_palette(lab, centers)
            # Slightly looser on palette so shirt vs pants both pull in
            match_pal = dist_pal <= (lab_tol * 1.12)
            match = np.logical_or(match_local, match_pal)
        else:
            match = match_local

        add = np.logical_and(candidates, match)
        if not np.any(add):
            break
        refined[add] = 1

    # Keep only largest blob that overlaps the original seed
    refined = _as_2d_mask(refined)
    seed = _as_2d_mask(seed_mask)
    num, labels, stats, _ = cv2.connectedComponentsWithStats(refined, connectivity=8)
    if num <= 1:
        final = refined
    else:
        best_lab, best_area = 0, 0
        for lab_i in range(1, num):
            area = int(stats[lab_i, cv2.CC_STAT_AREA])
            overlap = int(np.logical_and(labels == lab_i, seed > 0).sum())
            if overlap <= 0:
                continue
            if area > best_area:
                best_area = area
                best_lab = lab_i
        if best_lab == 0:
            final = seed
        else:
            final = np.where(labels == best_lab, 1, 0).astype(np.uint8)
            # Light close to fill small holes inside body
            final = cv2.morphologyEx(
                final, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=1
            )
            final = _as_2d_mask(final)

    # Final palette = all colors inside finished outline perimeter
    palette = _extract_outline_palette(frame_bgr, final)
    return final, palette


def _person_mask_from_pose(
    frame_bgr: np.ndarray,
    landmarks,
    fg_mask: Optional[np.ndarray],
) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
    """Person-only outline + full color palette inside perimeter.

    Returns (mask, palette) where palette lists every dominant color recognized
    while the outline formed (shirt, pants, skin, hair, accents), refined with
    pose-region (head/upper/lower) reads for more accurate character analysis.
    """
    h, w = frame_bgr.shape[:2]
    seed = _pose_seed_mask(landmarks, w, h)
    if seed.sum() < 20:
        # Fallback: small disk at hip center
        cx, cy = _pose_center(landmarks, w, h)
        cv2.circle(seed, (int(cx), int(cy)), max(20, h // 12), 1, -1)
    allow = _as_2d_mask(fg_mask) if fg_mask is not None else None
    # Soften allow: dilate FG so color grow can reach limbs selfie seg missed
    if allow is not None:
        allow = _as_2d_mask(cv2.dilate(allow, np.ones((7, 7), np.uint8), iterations=2))
    person, palette = _refine_mask_color_lab(frame_bgr, seed, allow_mask=allow)
    if person.sum() < seed.sum() * 0.5:
        # Color grow failed — use dilated seed ∩ FG, still read colors
        person = seed
        if allow is not None:
            person = _as_2d_mask(person & allow)
        person = _as_2d_mask(cv2.dilate(person, np.ones((9, 9), np.uint8), iterations=2))
        palette = _extract_outline_palette(frame_bgr, person)
    # Pose-region multi-color (shirt/pants/head) — Re-ID aid for skeletal mimicry
    if landmarks is not None and int(person.sum()) > 40:
        regional = _extract_pose_region_palette(frame_bgr, landmarks, person)
        if regional:
            palette = regional
    return person, palette


# ── Character spotter (multi-color palette differentiator for dual humans) ─
# MediaPipe finds skeletons; full outline palettes lock which body is track 1
# vs 2 when people cross (pure L/R x-sort swaps identities).

def _color_signature_lab(frame_bgr: np.ndarray, mask: np.ndarray) -> Optional[np.ndarray]:
    """Mean LAB of person mask — fallback single-color fingerprint."""
    m = _as_2d_mask(mask)
    if m.sum() < 40:
        return None
    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    pix = lab[m > 0]
    if pix.size == 0:
        return None
    lo = np.percentile(pix, 15, axis=0)
    hi = np.percentile(pix, 85, axis=0)
    clipped = np.clip(pix, lo, hi)
    return clipped.mean(axis=0)


def _palette_distance(
    a: Optional[List[Dict[str, Any]]],
    b: Optional[List[Dict[str, Any]]],
) -> float:
    """How different two outline color sets are (0 = same costume palette).

    Bidirectional weighted nearest-neighbor in LAB — multi-color outfits compare
    as sets, not single averages (so red+blue ≠ purple mush).
    """
    if not a or not b:
        return 1e9
    labs_a = np.array([p["lab"] for p in a], dtype=np.float32)
    labs_b = np.array([p["lab"] for p in b], dtype=np.float32)
    frac_a = np.array([float(p.get("fraction", 1.0 / len(a))) for p in a], dtype=np.float32)
    frac_b = np.array([float(p.get("fraction", 1.0 / len(b))) for p in b], dtype=np.float32)
    frac_a = frac_a / (frac_a.sum() + 1e-6)
    frac_b = frac_b / (frac_b.sum() + 1e-6)

    d_ab = 0.0
    for i, lab in enumerate(labs_a):
        d_ab += float(np.linalg.norm(labs_b - lab, axis=1).min()) * float(frac_a[i])
    d_ba = 0.0
    for i, lab in enumerate(labs_b):
        d_ba += float(np.linalg.norm(labs_a - lab, axis=1).min()) * float(frac_b[i])
    return 0.5 * (d_ab + d_ba)


def _blend_palette(
    prev: Optional[List[Dict[str, Any]]],
    cur: Optional[List[Dict[str, Any]]],
    alpha: float = 0.32,
) -> Optional[List[Dict[str, Any]]]:
    """Temporal blend of outline palettes via re-cluster of weighted centers."""
    if not cur:
        return prev
    if not prev:
        return [dict(p) for p in cur]
    # Merge as weighted point cloud then re-extract via kmeans on centers
    pts: List[np.ndarray] = []
    weights: List[float] = []
    for p in prev:
        pts.append(np.asarray(p["lab"], dtype=np.float32))
        weights.append(float(p.get("fraction", 0.1)) * (1.0 - alpha))
    for p in cur:
        pts.append(np.asarray(p["lab"], dtype=np.float32))
        weights.append(float(p.get("fraction", 0.1)) * alpha)
    if not pts:
        return cur
    arr = np.stack(pts, axis=0)
    w = np.asarray(weights, dtype=np.float32)
    w = w / (w.sum() + 1e-6)
    # Expand centers proportional to weight for kmeans (repeat)
    expanded = []
    for i, c in enumerate(arr):
        n_rep = max(1, int(round(float(w[i]) * 40)))
        for _ in range(n_rep):
            expanded.append(c)
    cloud = np.stack(expanded, axis=0).astype(np.float32)
    k = min(OUTLINE_PALETTE_MAX, max(2, len(cloud) // 8), len(cloud))
    if k < 2 or len(cloud) < 2:
        mean = (arr * w.reshape(-1, 1)).sum(axis=0)
        return [{
            "lab": [float(x) for x in mean],
            "fraction": 1.0,
            "hex": _lab_to_hex_bgr_approx(mean),
        }]
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.8)
    try:
        _c, labels, centers = cv2.kmeans(
            cloud, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS
        )
    except cv2.error:
        return [dict(p) for p in cur]
    labels = labels.flatten()
    counts = np.bincount(labels, minlength=k).astype(np.float32)
    total = float(counts.sum()) or 1.0
    out: List[Dict[str, Any]] = []
    for i in range(k):
        frac = float(counts[i] / total)
        if frac < OUTLINE_PALETTE_MIN_FRAC and sum(
            1 for j in range(k) if counts[j] / total >= OUTLINE_PALETTE_MIN_FRAC
        ) >= 2:
            continue
        c = centers[i].astype(np.float32)
        out.append({
            "lab": [float(c[0]), float(c[1]), float(c[2])],
            "fraction": round(frac, 4),
            "hex": _lab_to_hex_bgr_approx(c),
        })
    out.sort(key=lambda p: -p["fraction"])
    return out[:OUTLINE_PALETTE_MAX] if out else [dict(p) for p in cur]


def _color_distance(a: Optional[np.ndarray], b: Optional[np.ndarray]) -> float:
    if a is None or b is None:
        return 1e9
    return float(np.linalg.norm(a.astype(np.float32) - b.astype(np.float32)))


def _blend_signature(
    prev: Optional[np.ndarray], cur: Optional[np.ndarray], alpha: float = 0.28
) -> Optional[np.ndarray]:
    if cur is None:
        return prev
    if prev is None:
        return cur.copy()
    return (1.0 - alpha) * prev + alpha * cur


def _assign_dual_tracks(
    poses: List,
    centers: List[Tuple[float, float]],
    palettes: List[Optional[List[Dict[str, Any]]]],
    track_palettes: List[Optional[List[Dict[str, Any]]]],
    width: int,
    height: int,
) -> Tuple[List, List[Tuple[float, float]], List[Optional[List[Dict[str, Any]]]]]:
    """Map detections → stable tracks using full outline color palettes + position.

    Returns poses/centers/palettes ordered as [track1, track2].
    """
    if len(poses) < 2:
        return poses, centers, palettes

    # No history yet: seed by left-to-right (stable first frame)
    if track_palettes[0] is None and track_palettes[1] is None:
        order = [0, 1] if centers[0][0] <= centers[1][0] else [1, 0]
        return (
            [poses[order[0]], poses[order[1]]],
            [centers[order[0]], centers[order[1]]],
            [palettes[order[0]], palettes[order[1]]],
        )

    def cost(det_i: int, track_j: int) -> float:
        c_col = _palette_distance(palettes[det_i], track_palettes[track_j])
        # Palette distances often 0–60 LAB units
        c_col_n = min(1.0, c_col / 48.0)
        cx = centers[det_i][0]
        side_bias = 0.0
        if track_j == 0:
            side_bias = max(0.0, (cx / max(1, width) - 0.5)) * 0.35
        else:
            side_bias = max(0.0, (0.5 - cx / max(1, width))) * 0.35
        return c_col_n + side_bias

    cost_ab = cost(0, 0) + cost(1, 1)
    cost_ba = cost(0, 1) + cost(1, 0)
    if cost_ba + 0.08 < cost_ab:
        return (
            [poses[1], poses[0]],
            [centers[1], centers[0]],
            [palettes[1], palettes[0]],
        )
    return poses, centers, palettes


def _draw_palette_swatches(
    out: np.ndarray,
    palette: Optional[List[Dict[str, Any]]],
    origin: Tuple[int, int],
    label: str = "",
) -> None:
    """Draw small color chips for every recognized outline color."""
    if not palette:
        return
    x0, y0 = origin
    if label:
        cv2.putText(
            out, label, (x0, y0 - 4),
            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (240, 240, 240), 1, cv2.LINE_AA,
        )
    for i, p in enumerate(palette[:OUTLINE_PALETTE_MAX]):
        hx = str(p.get("hex") or "#888888").lstrip("#")
        try:
            r, g, b = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
            bgr = (b, g, r)
        except Exception:
            bgr = (136, 136, 136)
        x1 = x0 + i * 18
        cv2.rectangle(out, (x1, y0), (x1 + 16, y0 + 14), bgr, -1, cv2.LINE_AA)
        cv2.rectangle(out, (x1, y0), (x1 + 16, y0 + 14), (255, 255, 255), 1, cv2.LINE_AA)


def _lm_xy(landmarks, i: int) -> Optional[Tuple[float, float, float]]:
    """Normalized (x, y, visibility) for landmark i."""
    if landmarks is None:
        return None
    # Accept raw MediaPipe or dict-list from motion_data
    if isinstance(landmarks, list) and landmarks and isinstance(landmarks[0], dict):
        if i >= len(landmarks):
            return None
        d = landmarks[i]
        vis = float(d.get("visibility", 1.0) or 1.0)
        if vis < 0.2:
            return None
        return float(d["x"]), float(d["y"]), vis
    if len(landmarks) <= i:
        return None
    lm = landmarks[i]
    vis = float(getattr(lm, "visibility", 1.0) or 1.0)
    if vis < 0.2:
        return None
    return float(lm.x), float(lm.y), vis


def _skeleton_scale_box(landmarks) -> Optional[Dict[str, float]]:
    """Feet-anchored scale box from skeleton (for stage metric + mimicry)."""
    head = _lm_xy(landmarks, 0)
    sh_l, sh_r = _lm_xy(landmarks, 11), _lm_xy(landmarks, 12)
    hip_l, hip_r = _lm_xy(landmarks, 23), _lm_xy(landmarks, 24)
    an_l, an_r = _lm_xy(landmarks, 27), _lm_xy(landmarks, 28)
    if not an_l and not an_r:
        return None
    feet_y = np.mean([p[1] for p in (an_l, an_r) if p])
    feet_x = np.mean([p[0] for p in (an_l, an_r) if p])
    tops = [p[1] for p in (head, sh_l, sh_r) if p]
    if not tops:
        return None
    head_y = float(min(tops))
    body_h = max(0.12, float(feet_y) - head_y)
    hips = [p for p in (hip_l, hip_r) if p]
    if hips:
        cx = float(np.mean([p[0] for p in hips]))
    else:
        cx = float(feet_x)
    shoulders = [p for p in (sh_l, sh_r) if p]
    if len(shoulders) == 2:
        shoulder_w = abs(shoulders[0][0] - shoulders[1][0])
    else:
        shoulder_w = body_h * 0.28
    return {
        "head_y": round(head_y, 5),
        "feet_y": round(float(feet_y), 5),
        "center_x": round(cx, 5),
        "feet_x": round(float(feet_x), 5),
        "body_height_norm": round(body_h, 5),
        "shoulder_width_norm": round(float(shoulder_w), 5),
    }


def _build_stage_from_tracks(
    motion_tracks: List[List[Dict[str, Any]]],
    width: int,
    height: int,
    fps: float,
) -> Dict[str, Any]:
    """Calibrate a transparent 3D stage from skeletal feet + body height.

    Floor Y=0 at median ankle plane. Body height ≈ 1.7 m → metric grid so
    roster characters can mimic movement in the same world coordinates.
    """
    feet_ys: List[float] = []
    body_hs: List[float] = []
    for track in motion_tracks:
        for entry in track or []:
            lm = entry.get("landmarks") if isinstance(entry, dict) else None
            box = _skeleton_scale_box(lm) if lm else None
            if not box:
                continue
            feet_ys.append(box["feet_y"])
            body_hs.append(box["body_height_norm"])

    floor_y_norm = float(np.median(feet_ys)) if feet_ys else 0.92
    mean_body_h = float(np.median(body_hs)) if body_hs else 0.55
    mean_body_h = max(0.2, min(0.95, mean_body_h))
    # 1.7 m performer → meters per normalized image height unit
    meters_per_norm = 1.7 / mean_body_h
    # Weak pinhole: principal point center, fx ≈ 1.2 * width
    fx = float(width) * 1.15
    fy = fx
    cx, cy = width * 0.5, height * 0.5

    return {
        "version": 1,
        "type": "3d_stage",
        "analyzer_version": ANALYZER_VERSION,
        "world": {
            "up": [0, 1, 0],
            "floor_y": 0.0,
            "grid": {
                "spacing": 0.5,
                "extent_x": 6.0,
                "extent_z": 6.0,
                "show_axes": True,
                "opacity": 0.5,
                "color": "#00ff88",
            },
            "reference_body_height_m": 1.7,
            "meters_per_norm_y": round(meters_per_norm, 5),
            "floor_y_norm_image": round(floor_y_norm, 5),
        },
        "camera": {
            "fov_deg": 50,
            "position": [0.0, 1.6, 4.5],
            "target": [0.0, 0.8, 0.0],
            "near": 0.1,
            "far": 50,
        },
        "floor_plane": {"normal": [0, 1, 0], "point": [0, 0, 0]},
        "projection": {
            "image_width": int(width),
            "image_height": int(height),
            "fps": round(float(fps or 30), 3),
            "K": [
                [round(fx, 2), 0.0, round(cx, 2)],
                [0.0, round(fy, 2), round(cy, 2)],
                [0.0, 0.0, 1.0],
            ],
            "floor_y_norm": round(floor_y_norm, 5),
        },
        "calibration_source": "skeletal_ankle_plane+body_height",
    }


def _norm_to_world(
    feet_x: float,
    feet_y: float,
    stage: Dict[str, Any],
) -> Dict[str, float]:
    """Map image-normalized feet to stage world (x, 0, z) on the floor plane."""
    w = stage.get("world") or {}
    mpn = float(w.get("meters_per_norm_y") or 3.0)
    floor_y = float(w.get("floor_y_norm_image") or 0.92)
    # Lateral: centered on frame, scale by same metric as height
    x = (float(feet_x) - 0.5) * mpn
    # Depth: ankle below floor plane → closer (smaller z), above → farther
    z = (floor_y - float(feet_y)) * mpn * 1.35
    return {
        "x": round(x, 4),
        "y": 0.0,
        "z": round(z, 4),
    }


def _enrich_track_with_stage(
    track: List[Dict[str, Any]],
    stage: Dict[str, Any],
    track_id: int = 1,
) -> List[Dict[str, Any]]:
    """Attach scale_box + world_anchor to each motion frame for mimicry."""
    out: List[Dict[str, Any]] = []
    for entry in track or []:
        e = dict(entry) if isinstance(entry, dict) else {"landmarks": entry}
        lm = e.get("landmarks")
        box = _skeleton_scale_box(lm) if lm else None
        if box:
            e["scale_box"] = box
            e["world_anchor"] = _norm_to_world(box["feet_x"], box["feet_y"], stage)
            e["track_id"] = track_id
        out.append(e)
    return out


def _build_perimeter_track(
    tracks: List[List[Dict[str, Any]]],
    stage: Dict[str, Any],
) -> Dict[str, Any]:
    """Export per-character perimeters for skeletal overlay / integration."""
    perims: Dict[str, Any] = {}
    for ti, track in enumerate(tracks):
        key = f"char_{ti}"
        frames = []
        for entry in track or []:
            if not isinstance(entry, dict):
                continue
            lm = entry.get("landmarks")
            box = entry.get("scale_box") or (_skeleton_scale_box(lm) if lm else None)
            if not box:
                continue
            wa = entry.get("world_anchor") or _norm_to_world(
                box["feet_x"], box["feet_y"], stage
            )
            # Convex hull-ish bbox from key joints
            xs, ys = [], []
            if isinstance(lm, list):
                for i in (0, 11, 12, 15, 16, 23, 24, 27, 28):
                    p = _lm_xy(lm, i)
                    if p:
                        xs.append(p[0])
                        ys.append(p[1])
            bbox = None
            if xs and ys:
                bbox = {
                    "x0": round(min(xs), 4),
                    "y0": round(min(ys), 4),
                    "x1": round(max(xs), 4),
                    "y1": round(max(ys), 4),
                }
            frames.append({
                "frame": entry.get("frame"),
                "bbox_norm": bbox,
                "scale_box": box,
                "world_anchor": wa,
                "footprint": {
                    "feet_x": box["feet_x"],
                    "feet_y": box["feet_y"],
                    "width_norm": round(box["shoulder_width_norm"] * 0.85, 4),
                },
                "outline_colors": entry.get("outline_colors") or [],
                "color_spot": entry.get("color_spot"),
            })
        perims[key] = {"track_id": ti + 1, "frames": frames}
    return {
        "version": 1,
        "type": "perimeter_track",
        "stage_ref": "stage.json",
        "characters": perims,
        "analyzer_version": ANALYZER_VERSION,
    }


def _draw_stage_grid_overlay(
    frame_bgr: np.ndarray,
    stage: Optional[Dict[str, Any]] = None,
    opacity: float = 0.50,
) -> np.ndarray:
    """50% transparent green coordinate grid (stage aid for movement reading)."""
    out = frame_bgr.copy()
    h, w = out.shape[:2]
    overlay = out.copy()
    floor_y_norm = 0.92
    if stage:
        floor_y_norm = float(
            (stage.get("world") or {}).get("floor_y_norm_image")
            or (stage.get("projection") or {}).get("floor_y_norm")
            or 0.92
        )
    floor_y = int(np.clip(floor_y_norm, 0.55, 0.98) * h)
    # Perspective floor grid (vanishing toward mid-horizon)
    horizon = int(h * 0.38)
    green = (0, 255, 136)
    dark = (0, 68, 34)
    # Vertical-ish depth lines (converge toward vanishing point)
    vp = (w // 2, horizon)
    for t in np.linspace(-1.2, 1.2, 13):
        x_floor = int(w * 0.5 + t * w * 0.55)
        cv2.line(overlay, vp, (x_floor, h - 1), dark if abs(t) > 0.01 else green, 1, cv2.LINE_AA)
    # Horizontal floor bands (denser near camera)
    for i, frac in enumerate(np.linspace(0.05, 1.0, 10)):
        y = int(horizon + (h - 1 - horizon) * (frac ** 0.85))
        if y >= h:
            continue
        # Width of band grows toward bottom
        half = int((w * 0.15) + (w * 0.45) * frac)
        x0, x1 = max(0, w // 2 - half), min(w - 1, w // 2 + half)
        col = green if i % 2 == 0 else dark
        cv2.line(overlay, (x0, y), (x1, y), col, 1, cv2.LINE_AA)
    # Floor line (ankle plane)
    cv2.line(overlay, (0, floor_y), (w - 1, floor_y), green, 2, cv2.LINE_AA)
    # World axes badge
    ax, ay = 28, h - 28
    cv2.arrowedLine(overlay, (ax, ay), (ax + 40, ay), (68, 68, 255), 2, tipLength=0.25)  # X red
    cv2.arrowedLine(overlay, (ax, ay), (ax, ay - 40), (68, 255, 68), 2, tipLength=0.25)  # Y green
    cv2.arrowedLine(overlay, (ax, ay), (ax + 22, ay - 18), (255, 180, 68), 2, tipLength=0.25)  # Z
    cv2.putText(overlay, "stage", (ax + 48, ay - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.4, green, 1, cv2.LINE_AA)
    cv2.addWeighted(overlay, opacity, out, 1.0 - opacity, 0, out)
    return out


def _draw_skeleton_overlay(
    frame_bgr: np.ndarray,
    landmarks,
    color_bgr: Tuple[int, int, int],
    spot_hex: str = "",
    palette: Optional[List[Dict[str, Any]]] = None,
    world_anchor: Optional[Dict[str, float]] = None,
) -> np.ndarray:
    """Draw pose sticks + hip color spot + outline palette + world anchor."""
    out = frame_bgr  # already may include stage grid; mutate carefully
    h, w = out.shape[:2]
    if landmarks is None or len(landmarks) < 25:
        return out
    # MediaPipe pose connections (subset for clean UI)
    edges = (
        (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
        (11, 23), (12, 24), (23, 24),
        (23, 25), (25, 27), (24, 26), (26, 28),
        (0, 11), (0, 12),
    )

    def pt(i):
        p = _lm_xy(landmarks, i)
        if not p:
            return None
        return (
            int(np.clip(p[0] * w, 0, w - 1)),
            int(np.clip(p[1] * h, 0, h - 1)),
        )

    for a, b in edges:
        pa, pb = pt(a), pt(b)
        if pa and pb:
            cv2.line(out, pa, pb, color_bgr, 2, cv2.LINE_AA)
    for i in (0, 11, 12, 15, 16, 23, 24, 27, 28):
        p = pt(i)
        if p:
            cv2.circle(out, p, 4, color_bgr, -1, cv2.LINE_AA)
    # Color spot badge at hip
    hip = pt(23) or pt(24) or pt(0)
    if hip:
        cv2.circle(out, hip, 14, color_bgr, 2, cv2.LINE_AA)
        cv2.circle(out, hip, 8, color_bgr, -1, cv2.LINE_AA)
        if spot_hex:
            cv2.putText(
                out, spot_hex, (hip[0] + 12, hip[1] - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, color_bgr, 1, cv2.LINE_AA,
            )
        # Swatches of ALL colors recognized inside outline perimeter
        if palette:
            _draw_palette_swatches(
                out, palette, (hip[0] + 12, hip[1] + 10), label=""
            )
    # World anchor at feet (stage coordinate for mimicry)
    an_l, an_r = pt(27), pt(28)
    if an_l or an_r:
        fx = int(np.mean([p[0] for p in (an_l, an_r) if p]))
        fy = int(np.mean([p[1] for p in (an_l, an_r) if p]))
        cv2.drawMarker(out, (fx, fy), color_bgr, cv2.MARKER_CROSS, 16, 2, cv2.LINE_AA)
        if world_anchor:
            label = "({:.1f},0,{:.1f})m".format(
                float(world_anchor.get("x", 0)),
                float(world_anchor.get("z", 0)),
            )
            cv2.putText(
                out, label, (fx + 10, fy + 16),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, color_bgr, 1, cv2.LINE_AA,
            )
    return out


class PercfectMotionAnalyzer:
    """Fresh instance per request — MediaPipe VIDEO mode tracks timestamps per object."""

    def __init__(self):
        self._segmenter = None
        self._landmarkers: Dict[int, vision.PoseLandmarker] = {}
        self._image_landmarkers: Dict[int, vision.PoseLandmarker] = {}

    def _get_segmenter(self) -> vision.ImageSegmenter:
        if self._segmenter is None:
            base_options = _cpu_base_options(_ensure_seg_model())
            options = vision.ImageSegmenterOptions(
                base_options=base_options,
                running_mode=vision.RunningMode.VIDEO,
                output_confidence_masks=True,
            )
            self._segmenter = vision.ImageSegmenter.create_from_options(options)
        return self._segmenter

    def _get_landmarker(self, num_poses: int) -> vision.PoseLandmarker:
        if num_poses not in self._landmarkers:
            confidence = 0.65 if num_poses == 1 else 0.5
            base_options = _cpu_base_options(_ensure_pose_model())
            options = vision.PoseLandmarkerOptions(
                base_options=base_options,
                running_mode=vision.RunningMode.VIDEO,
                num_poses=num_poses,
                min_pose_detection_confidence=confidence,
                min_pose_presence_confidence=confidence,
                min_tracking_confidence=confidence,
            )
            self._landmarkers[num_poses] = vision.PoseLandmarker.create_from_options(options)
        return self._landmarkers[num_poses]

    def _get_image_landmarker(self, num_poses: int) -> vision.PoseLandmarker:
        if num_poses not in self._image_landmarkers:
            confidence = 0.65 if num_poses == 1 else 0.5
            base_options = _cpu_base_options(_ensure_pose_model())
            options = vision.PoseLandmarkerOptions(
                base_options=base_options,
                running_mode=vision.RunningMode.IMAGE,
                num_poses=num_poses,
                min_pose_detection_confidence=confidence,
                min_pose_presence_confidence=confidence,
                min_tracking_confidence=confidence,
            )
            self._image_landmarkers[num_poses] = vision.PoseLandmarker.create_from_options(
                options
            )
        return self._image_landmarkers[num_poses]

    def _detect_poses_image(
        self, landmarker: vision.PoseLandmarker, frame: np.ndarray
    ) -> Optional[List]:
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        pose_result = landmarker.detect(mp_image)
        if not pose_result.pose_landmarks:
            return None
        return list(pose_result.pose_landmarks)

    def _verify_motion_coordinates(
        self,
        video_path: str,
        motion_tracks: List[List[Dict[str, Any]]],
        fps: float,
        proc_w: int,
        proc_h: int,
        num_poses: int,
    ) -> Tuple[List[List[Dict[str, Any]]], Dict[str, Any]]:
        """Second pass: re-detect pose per stored frame and fix suspect coordinates."""
        if not motion_tracks or not motion_tracks[0]:
            return motion_tracks, {
                "ran": False,
                "frames_checked": 0,
                "frames_corrected": 0,
            }

        frame_map: Dict[int, List[Dict[str, Any]]] = {}
        for track in motion_tracks:
            for entry in track:
                frame_map[entry["frame"]] = entry

        all_frames = sorted(frame_map.keys())
        # Dense tracks (full-duration extract) — recheck evenly spaced subset only
        max_recheck = 80
        if len(all_frames) > max_recheck:
            step = max(1, len(all_frames) // max_recheck)
            target_frames = all_frames[::step]
        else:
            target_frames = all_frames
        landmarker = self._get_image_landmarker(num_poses)
        checked = corrected = 0
        max_drift_seen = 0.0

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return motion_tracks, {"ran": False, "error": "cannot_open_video_for_recheck"}

        try:
            frame_idx = 0
            target_set = set(target_frames)
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break
                if frame_idx not in target_set:
                    frame_idx += 1
                    continue

                frame = _resize_for_processing(frame, proc_w, proc_h)
                poses = self._detect_poses_image(landmarker, frame)
                checked += 1

                if num_poses == 1:
                    if not poses:
                        frame_idx += 1
                        continue
                    primary = _select_primary_poses(poses, proc_w, proc_h, n=1)
                    if not primary:
                        frame_idx += 1
                        continue
                    recheck_lm = _landmarks_to_dict(primary[0])
                    stored_lm = frame_map[frame_idx]["landmarks"]
                    drift = _landmark_drift(stored_lm, recheck_lm)
                    max_drift_seen = max(max_drift_seen, drift)
                    use_recheck = (
                        drift > RECHECK_DRIFT_THRESHOLD
                        or not _landmarks_in_range(stored_lm)
                        or _key_joint_quality(recheck_lm)
                        > _key_joint_quality(stored_lm) + 0.1
                    )
                    if use_recheck:
                        frame_map[frame_idx]["landmarks"] = recheck_lm
                        corrected += 1
                else:
                    if not poses:
                        frame_idx += 1
                        continue
                    primary = _select_primary_poses(poses, proc_w, proc_h, n=2)
                    if len(primary) < 2:
                        frame_idx += 1
                        continue
                    poses = list(primary[:2])
                    centers = [_pose_center(p, proc_w, proc_h) for p in poses]
                    if centers[0][0] > centers[1][0]:
                        poses = [poses[1], poses[0]]
                    for track_idx, pose in enumerate(poses):
                        if track_idx >= len(motion_tracks):
                            break
                        recheck_lm = _landmarks_to_dict(pose)
                        stored_entry = next(
                            (e for e in motion_tracks[track_idx] if e["frame"] == frame_idx),
                            None,
                        )
                        if not stored_entry:
                            continue
                        stored_lm = stored_entry["landmarks"]
                        drift = _landmark_drift(stored_lm, recheck_lm)
                        max_drift_seen = max(max_drift_seen, drift)
                        use_recheck = (
                            drift > RECHECK_DRIFT_THRESHOLD
                            or not _landmarks_in_range(stored_lm)
                            or _key_joint_quality(recheck_lm)
                            > _key_joint_quality(stored_lm) + 0.1
                        )
                        if use_recheck:
                            stored_entry["landmarks"] = recheck_lm
                            corrected += 1

                frame_idx += 1
                if checked >= len(target_frames):
                    break
        finally:
            cap.release()

        # Keep full-duration tracks; dual corrections already applied in-place
        updated_tracks = []
        for track in motion_tracks:
            by_frame = {e["frame"]: e for e in track}
            if num_poses == 1:
                for f, entry in frame_map.items():
                    if f in by_frame:
                        by_frame[f] = entry
            ordered = sorted(by_frame.keys())
            updated_tracks.append([by_frame[f] for f in ordered])

        return updated_tracks, {
            "ran": True,
            "frames_checked": checked,
            "frames_corrected": corrected,
            "max_drift": round(max_drift_seen, 4),
            "drift_threshold": RECHECK_DRIFT_THRESHOLD,
            "recheck_frames": len(target_frames),
            "track_frames": len(all_frames),
        }

    def close(self):
        if self._segmenter is not None:
            try:
                self._segmenter.close()
            except Exception:
                pass
            self._segmenter = None
        for landmarker in list(self._landmarkers.values()) + list(
            self._image_landmarkers.values()
        ):
            try:
                landmarker.close()
            except Exception:
                pass
        self._landmarkers.clear()
        self._image_landmarkers.clear()

    def process_video(
        self,
        video_path: str,
        output_dir: str = "output",
        sample_every_n: int = 1,
        max_seconds: int = MAX_VIDEO_SECONDS,
        character_count: int = 1,
    ) -> Dict[str, Any]:
        try:
            character_count = int(character_count)
        except (TypeError, ValueError):
            character_count = 1
        character_count = 2 if character_count == 2 else 1
        if character_count == 2:
            return self._process_dual(video_path, output_dir, sample_every_n, max_seconds)
        return self._process_single(video_path, output_dir, sample_every_n, max_seconds)

    def _read_video_meta(self, video_path: str, max_seconds: int):
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Cannot open video file: {video_path}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        if fps <= 0:
            fps = 30.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        duration_sec = total_frames / fps if fps > 0 else 0
        if duration_sec > max_seconds:
            cap.release()
            raise ValueError(
                f"Video too long ({duration_sec:.1f}s). Max allowed: {max_seconds}s for stability."
            )
        return cap, fps, width, height, total_frames, duration_sec

    def _detect_frame(
        self,
        segmenter: vision.ImageSegmenter,
        landmarker: vision.PoseLandmarker,
        frame: np.ndarray,
        frame_idx: int,
        fps: float,
    ) -> Tuple[Optional[np.ndarray], Optional[List]]:
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        timestamp_ms = int((frame_idx / fps) * 1000)
        seg_results = segmenter.segment_for_video(mp_image, timestamp_ms)
        mask = _foreground_mask_from_segmentation(seg_results)
        if mask is None:
            return None, None
        pose_result = landmarker.detect_for_video(mp_image, timestamp_ms)
        poses = list(pose_result.pose_landmarks) if pose_result.pose_landmarks else None
        return mask, poses

    def _process_single(self, video_path, output_dir, sample_every_n, max_seconds):
        """Full-duration extract: every source frame is written at source fps.
        sample_every_n only thins MediaPipe re-detect cost; non-sample frames
        hold last person mask + pose so output length ≈ source length.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        cap, fps, width, height, _total_frames, duration_sec = self._read_video_meta(
            video_path, max_seconds
        )
        proc_w, proc_h = _processing_dimensions(width, height)
        segmenter = self._get_segmenter()
        # Detect up to 3 poses so BG people can be discarded by primary scoring
        landmarker = self._get_landmarker(3)
        motion_data = []
        frame_idx = processed_count = detect_count = 0
        last_mask = None
        last_pose = None
        sample_every_n = max(1, int(sample_every_n or 1))

        char_path = output_dir / "character.mp4"
        bg_path = output_dir / "background.mp4"
        overlay_path = output_dir / "skeleton_overlay.mp4"
        json_path = output_dir / "motion_data.json"
        meta_path = output_dir / "metadata.json"
        char_writer = self._open_video_writer(char_path, proc_w, proc_h, fps)
        bg_writer = self._open_video_writer(bg_path, proc_w, proc_h, fps)
        overlay_writer = self._open_video_writer(overlay_path, proc_w, proc_h, fps)
        last_palette: List[Dict[str, Any]] = []
        spot_hex = "#00ff88"

        try:
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break
                frame = _resize_for_processing(frame, proc_w, proc_h)
                run_detect = (
                    sample_every_n <= 1
                    or (frame_idx % sample_every_n == 0)
                    or last_mask is None
                )
                if run_detect:
                    fg_mask, poses = self._detect_frame(
                        segmenter, landmarker, frame, frame_idx, fps
                    )
                    detect_count += 1
                    if fg_mask is not None:
                        primary = _select_primary_poses(poses, proc_w, proc_h, n=1)
                        if primary:
                            person, palette = _person_mask_from_pose(
                                frame, primary[0], fg_mask
                            )
                            if person is not None and int(person.sum()) > 0:
                                last_mask = person
                                last_pose = primary[0]
                                if palette:
                                    last_palette = palette
                                    spot_hex = _palette_primary_hex(palette)
                            else:
                                last_mask = _as_2d_mask(fg_mask)
                                last_pose = primary[0]
                                last_palette = _extract_outline_palette(
                                    frame, last_mask
                                )
                                if last_palette:
                                    spot_hex = _palette_primary_hex(last_palette)
                        else:
                            # No scored pose — still use selfie FG as plate
                            last_mask = _as_2d_mask(fg_mask)
                            last_pose = poses[0] if poses else last_pose
                            last_palette = _extract_outline_palette(frame, last_mask)
                            if last_palette:
                                spot_hex = _palette_primary_hex(last_palette)

                # Always write a frame so wall-clock duration is preserved
                # Transparent stage grid first — metric aid for skeletal mimicry
                overlay = _draw_stage_grid_overlay(frame, opacity=0.50)
                if last_mask is not None:
                    mask = _as_2d_mask(last_mask)
                    char_writer.write(cv2.bitwise_and(frame, frame, mask=mask))
                    bg_writer.write(
                        cv2.bitwise_and(frame, frame, mask=_as_2d_mask(1 - mask))
                    )
                    if last_pose is not None:
                        entry = {
                            "frame": frame_idx,
                            "landmarks": _landmarks_to_dict(last_pose),
                            "color_spot": spot_hex,
                            "outline_colors": _palette_hex_list(last_palette),
                        }
                        box = _skeleton_scale_box(last_pose)
                        if box:
                            entry["scale_box"] = box
                        motion_data.append(entry)
                        wa = None
                        if box:
                            # Provisional world before final stage calibrate
                            wa = {
                                "x": round((box["feet_x"] - 0.5) * 3.0, 4),
                                "y": 0.0,
                                "z": round((0.92 - box["feet_y"]) * 3.0, 4),
                            }
                            entry["world_anchor"] = wa
                        _draw_skeleton_overlay(
                            overlay,
                            last_pose,
                            (0, 255, 136),
                            spot_hex,
                            palette=last_palette,
                            world_anchor=wa,
                        )
                else:
                    char_writer.write(np.zeros_like(frame))
                    bg_writer.write(frame)

                # Legend: all colors inside outline perimeter
                cv2.putText(
                    overlay, f"T1 {spot_hex}", (10, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 136), 2, cv2.LINE_AA,
                )
                _draw_palette_swatches(
                    overlay, last_palette, (10, 36), label="outline colors"
                )
                overlay_writer.write(overlay)

                processed_count += 1
                frame_idx += 1
                if processed_count > (max_seconds * fps * 1.5):
                    break
        finally:
            cap.release()
            if processed_count == 0:
                self._write_empty_video(char_writer, proc_w, proc_h)
                self._write_empty_video(bg_writer, proc_w, proc_h)
                self._write_empty_video(overlay_writer, proc_w, proc_h)
            char_writer.release()
            bg_writer.release()
            overlay_writer.release()

        validation_report = {"ran": False}
        if motion_data:
            [motion_data], validation_report = self._verify_motion_coordinates(
                video_path,
                [motion_data],
                fps,
                proc_w,
                proc_h,
                num_poses=1,
            )

        output_duration_sec = round(processed_count / fps, 2) if fps > 0 else 0.0
        # Transparent 3D stage + world anchors for skeletal mimicry
        stage = _build_stage_from_tracks([motion_data], proc_w, proc_h, fps)
        motion_data = _enrich_track_with_stage(motion_data, stage, track_id=1)
        perimeter = _build_perimeter_track([motion_data], stage)
        stage_path = output_dir / "stage.json"
        perim_path = output_dir / "perimeter_track.json"
        with open(json_path, "w") as f:
            json.dump(motion_data, f, indent=2)
        with open(stage_path, "w") as f:
            json.dump(stage, f, indent=2)
        with open(perim_path, "w") as f:
            json.dump(perimeter, f, indent=2)
        character_spots = {
            "track_1": {
                "color_hex": spot_hex,
                "outline_colors": _palette_hex_list(last_palette),
                "palette": [
                    {
                        "hex": p.get("hex"),
                        "fraction": p.get("fraction"),
                        "region": p.get("region", "full"),
                    }
                    for p in (last_palette or [])
                ],
                "label": "Character 1",
            },
            "method": "pose_spotter+outline_multi_color_palette+stage_coords",
        }
        # Local plates always MediaPipe; main app may upgrade character plate via PoYo
        bg_removal_engine = "mediapipe"
        metadata = {
            "character_count": 1,
            "fps": round(fps, 3),
            "source_width": width,
            "source_height": height,
            "width": proc_w,
            "height": proc_h,
            "total_frames": frame_idx,
            "processed_frames": processed_count,
            "detect_frames": detect_count,
            "motion_frames": len(motion_data),
            "source_duration_sec": round(duration_sec, 2),
            "output_duration_sec": output_duration_sec,
            "duration_sec": output_duration_sec,
            "sample_every_n": sample_every_n,
            "coordinate_validation": validation_report,
            "has_pose_data": len(motion_data) > 0,
            "character_spots": character_spots,
            "bg_removal_engine": bg_removal_engine,
            "engine": bg_removal_engine,
            "features": [
                "skeletal_pose_heavy",
                "selfie_segmentation",
                "outline_multi_color_palette",
                "pose_region_color_read",
                "color_lab_differentiator",
                "character_spotter_primary",
                "skeleton_overlay",
                "transparent_3d_stage",
                "world_anchor_feet",
                "perimeter_track",
                "poyo_bg_removal_hook",
            ],
            "character_video": str(char_path.name),
            "background_video": str(bg_path.name),
            "skeleton_overlay": str(overlay_path.name),
            "motion_data": str(json_path.name),
            "stage": str(stage_path.name),
            "perimeter_track": str(perim_path.name),
            "analyzer_version": ANALYZER_VERSION,
        }
        with open(meta_path, "w") as f:
            json.dump(metadata, f, indent=2)
        job = output_dir.name
        return {
            "status": "success",
            "character_count": 1,
            "job_id": job,
            "character_video": f"/outputs/{job}/character.mp4",
            "background_video": f"/outputs/{job}/background.mp4",
            "skeleton_overlay": f"/outputs/{job}/skeleton_overlay.mp4",
            "motion_data": f"/outputs/{job}/motion_data.json",
            "stage": f"/outputs/{job}/stage.json",
            "perimeter_track": f"/outputs/{job}/perimeter_track.json",
            "metadata": f"/outputs/{job}/metadata.json",
            "character_spots": character_spots,
            "bg_removal_engine": bg_removal_engine,
            "engine": bg_removal_engine,
            "total_frames": frame_idx,
            "processed_frames": processed_count,
            "motion_frames": len(motion_data),
            "coordinate_validation": validation_report,
            "fps": round(fps, 3),
            "resolution": f"{proc_w}x{proc_h}",
            "source_resolution": f"{width}x{height}",
            "source_duration_sec": round(duration_sec, 2),
            "output_duration_sec": output_duration_sec,
            "duration_sec": output_duration_sec,
            "analyzer_version": ANALYZER_VERSION,
        }

    def _process_dual(self, video_path, output_dir, sample_every_n, max_seconds):
        """Full-duration dual extract: skeleton + multi-color outline + spotter.

        Pipeline per detect frame:
          1) Selfie FG + multi-pose → character spotter (primary scores)
          2) Per-body pose seed → recognize ALL colors in outline perimeter
          3) Grow outline using full palette (shirt+pants+skin stay one body)
          4) Palette ID lock so tracks don't swap on cross
          5) Write char1/char2 plates + skeleton overlay with color swatches
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        cap, fps, width, height, _total_frames, duration_sec = self._read_video_meta(
            video_path, max_seconds
        )
        proc_w, proc_h = _processing_dimensions(width, height)
        segmenter = self._get_segmenter()
        landmarker = self._get_landmarker(3)
        motion_data_1, motion_data_2 = [], []
        frame_idx = processed_count = detect_count = frames_with_two_poses = 0
        sample_every_n = max(1, int(sample_every_n or 1))

        char1_path = output_dir / "character_1.mp4"
        char2_path = output_dir / "character_2.mp4"
        bg_path = output_dir / "background.mp4"
        overlay_path = output_dir / "skeleton_overlay.mp4"
        json1_path = output_dir / "motion_data_1.json"
        json2_path = output_dir / "motion_data_2.json"
        meta_path = output_dir / "metadata.json"
        char1_writer = self._open_video_writer(char1_path, proc_w, proc_h, fps)
        char2_writer = self._open_video_writer(char2_path, proc_w, proc_h, fps)
        bg_writer = self._open_video_writer(bg_path, proc_w, proc_h, fps)
        overlay_writer = self._open_video_writer(overlay_path, proc_w, proc_h, fps)
        last_poses = None
        last_centers = None
        last_mask1 = last_mask2 = None
        last_mode = None  # "dual" | "single" | None
        # Running multi-color outline palettes for track lock
        track_pal: List[Optional[List[Dict[str, Any]]]] = [None, None]
        last_pal: List[List[Dict[str, Any]]] = [[], []]
        spot_hex = ["#00ff88", "#66b3ff"]
        color_lock_swaps = 0

        try:
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break
                frame = _resize_for_processing(frame, proc_w, proc_h)
                run_detect = (
                    sample_every_n <= 1
                    or (frame_idx % sample_every_n == 0)
                    or last_mode is None
                )

                if run_detect:
                    mask, poses = self._detect_frame(
                        segmenter, landmarker, frame, frame_idx, fps
                    )
                    detect_count += 1
                    dual_ready = False
                    poses_list = []
                    centers = None

                    if mask is not None:
                        # Character spotter: top-2 real performers (drop BG extras)
                        primary = _select_primary_poses(poses, proc_w, proc_h, n=2)
                        poses_list = list(primary) if primary else []

                        if len(poses_list) >= 2:
                            centers = [
                                _pose_center(p, proc_w, proc_h) for p in poses_list
                            ]
                            # Provisional outlines + full color palettes inside each
                            m_a, pal_a = _person_mask_from_pose(
                                frame, poses_list[0], mask
                            )
                            m_b, pal_b = _person_mask_from_pose(
                                frame, poses_list[1], mask
                            )
                            m_tmp = [m_a, m_b]
                            pals = [pal_a or None, pal_b or None]
                            before_ids = (id(poses_list[0]), id(poses_list[1]))
                            poses_list, centers, pals = _assign_dual_tracks(
                                poses_list, centers, pals, track_pal, proc_w, proc_h
                            )
                            after_ids = (id(poses_list[0]), id(poses_list[1]))
                            if before_ids != after_ids and track_pal[0] is not None:
                                color_lock_swaps += 1
                            # Update running multi-color palettes
                            track_pal[0] = _blend_palette(track_pal[0], pals[0])
                            track_pal[1] = _blend_palette(track_pal[1], pals[1])
                            if track_pal[0]:
                                last_pal[0] = track_pal[0]
                                spot_hex[0] = _palette_primary_hex(track_pal[0])
                            if track_pal[1]:
                                last_pal[1] = track_pal[1]
                                spot_hex[1] = _palette_primary_hex(track_pal[1])
                            # Re-order provisional masks to match track assignment
                            if before_ids != after_ids:
                                m_tmp = [m_tmp[1], m_tmp[0]]

                            dx = abs(centers[0][0] - centers[1][0])
                            dy = abs(centers[0][1] - centers[1][1])
                            if dx >= proc_w * 0.06 or dy >= proc_h * 0.10:
                                last_poses = poses_list
                                last_centers = centers
                                frames_with_two_poses += 1
                                dual_ready = True
                            elif last_poses is not None:
                                poses_list = last_poses
                                centers = last_centers
                                dual_ready = True
                            else:
                                poses_list = [poses_list[0]]
                                centers = [centers[0]]

                        if not dual_ready and len(poses_list) == 1 and last_poses is not None:
                            poses_list = last_poses
                            centers = last_centers
                            dual_ready = True

                        if dual_ready and poses_list and centers and len(poses_list) >= 2:
                            # Fresh outline + palette per skeleton (color differentiator)
                            m1, pal1 = _person_mask_from_pose(
                                frame, poses_list[0], mask
                            )
                            m2, pal2 = _person_mask_from_pose(
                                frame, poses_list[1], mask
                            )
                            if int(m1.sum()) < 50 or int(m2.sum()) < 50:
                                m1, m2 = _split_foreground_mask(
                                    mask, centers[0], centers[1]
                                )
                                pal1 = _extract_outline_palette(frame, m1)
                                pal2 = _extract_outline_palette(frame, m2)
                            both = _as_2d_mask(m1 & m2)
                            if both.sum() > 0:
                                yy, xx = np.where(both > 0)
                                d1 = (xx - centers[0][0]) ** 2 + (yy - centers[0][1]) ** 2
                                d2 = (xx - centers[1][0]) ** 2 + (yy - centers[1][1]) ** 2
                                nearer1 = d1 <= d2
                                m1[yy[~nearer1], xx[~nearer1]] = 0
                                m2[yy[nearer1], xx[nearer1]] = 0
                                # Re-read colors after split cleanup
                                pal1 = _extract_outline_palette(frame, m1)
                                pal2 = _extract_outline_palette(frame, m2)
                            last_mask1 = _as_2d_mask(m1)
                            last_mask2 = _as_2d_mask(m2)
                            if pal1:
                                track_pal[0] = _blend_palette(track_pal[0], pal1)
                                last_pal[0] = track_pal[0] or pal1
                                spot_hex[0] = _palette_primary_hex(last_pal[0])
                            if pal2:
                                track_pal[1] = _blend_palette(track_pal[1], pal2)
                                last_pal[1] = track_pal[1] or pal2
                                spot_hex[1] = _palette_primary_hex(last_pal[1])
                            last_poses = poses_list
                            last_centers = centers
                            last_mode = "dual"
                        elif len(poses_list) == 1 and mask is not None:
                            m1, pal1 = _person_mask_from_pose(
                                frame, poses_list[0], mask
                            )
                            if int(m1.sum()) < 50:
                                m1 = _as_2d_mask(mask)
                                pal1 = _extract_outline_palette(frame, m1)
                            last_mask1 = m1
                            last_mask2 = np.zeros((proc_h, proc_w), dtype=np.uint8)
                            if pal1:
                                track_pal[0] = _blend_palette(track_pal[0], pal1)
                                last_pal[0] = track_pal[0] or pal1
                                spot_hex[0] = _palette_primary_hex(last_pal[0])
                            last_mode = "single"
                        else:
                            pass

                # Always write timeline — stage grid under skeletons
                overlay = _draw_stage_grid_overlay(frame, opacity=0.50)
                if last_mode == "dual" and last_mask1 is not None and last_mask2 is not None:
                    both_people = _as_2d_mask(last_mask1 | last_mask2)
                    bg_mask = _as_2d_mask(1 - both_people)
                    char1_writer.write(
                        cv2.bitwise_and(frame, frame, mask=last_mask1)
                    )
                    char2_writer.write(
                        cv2.bitwise_and(frame, frame, mask=last_mask2)
                    )
                    bg_writer.write(cv2.bitwise_and(frame, frame, mask=bg_mask))
                    if last_poses is not None and len(last_poses) >= 2:
                        e1 = {
                            "frame": frame_idx,
                            "landmarks": _landmarks_to_dict(last_poses[0]),
                            "color_spot": spot_hex[0],
                            "outline_colors": _palette_hex_list(last_pal[0]),
                        }
                        e2 = {
                            "frame": frame_idx,
                            "landmarks": _landmarks_to_dict(last_poses[1]),
                            "color_spot": spot_hex[1],
                            "outline_colors": _palette_hex_list(last_pal[1]),
                        }
                        for e, pose in ((e1, last_poses[0]), (e2, last_poses[1])):
                            box = _skeleton_scale_box(pose)
                            if box:
                                e["scale_box"] = box
                                e["world_anchor"] = {
                                    "x": round((box["feet_x"] - 0.5) * 3.0, 4),
                                    "y": 0.0,
                                    "z": round((0.92 - box["feet_y"]) * 3.0, 4),
                                }
                        motion_data_1.append(e1)
                        motion_data_2.append(e2)
                        _draw_skeleton_overlay(
                            overlay,
                            last_poses[0],
                            (0, 255, 136),
                            spot_hex[0],
                            palette=last_pal[0],
                            world_anchor=e1.get("world_anchor"),
                        )
                        _draw_skeleton_overlay(
                            overlay,
                            last_poses[1],
                            (255, 179, 102),
                            spot_hex[1],
                            palette=last_pal[1],
                            world_anchor=e2.get("world_anchor"),
                        )
                elif last_mode == "single" and last_mask1 is not None:
                    char1_writer.write(
                        cv2.bitwise_and(frame, frame, mask=last_mask1)
                    )
                    char2_writer.write(np.zeros_like(frame))
                    bg_writer.write(
                        cv2.bitwise_and(
                            frame, frame, mask=_as_2d_mask(1 - last_mask1)
                        )
                    )
                    if last_poses is not None and len(last_poses) >= 1:
                        _draw_skeleton_overlay(
                            overlay,
                            last_poses[0],
                            (0, 255, 136),
                            spot_hex[0],
                            palette=last_pal[0],
                        )
                else:
                    char1_writer.write(np.zeros_like(frame))
                    char2_writer.write(np.zeros_like(frame))
                    bg_writer.write(frame)

                # Legend + full outline color chips
                cv2.putText(
                    overlay, f"T1 {spot_hex[0]}", (10, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 136), 2, cv2.LINE_AA,
                )
                _draw_palette_swatches(overlay, last_pal[0], (10, 30))
                cv2.putText(
                    overlay, f"T2 {spot_hex[1]}", (10, 66),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 179, 102), 2, cv2.LINE_AA,
                )
                _draw_palette_swatches(overlay, last_pal[1], (10, 74))
                overlay_writer.write(overlay)

                processed_count += 1
                frame_idx += 1
                if processed_count > (max_seconds * fps * 1.5):
                    break
        finally:
            cap.release()
            if processed_count == 0:
                self._write_empty_video(char1_writer, proc_w, proc_h)
                self._write_empty_video(char2_writer, proc_w, proc_h)
                self._write_empty_video(bg_writer, proc_w, proc_h)
                self._write_empty_video(overlay_writer, proc_w, proc_h)
            char1_writer.release()
            char2_writer.release()
            bg_writer.release()
            overlay_writer.release()

        if frames_with_two_poses < 1 or len(motion_data_1) < 1 or len(motion_data_2) < 1:
            raise ValueError(
                "2-character mode needs BOTH people visible in the same frames. "
                "Only one body was tracked, so dual plates would be the same person twice. "
                "Use a side-by-side / duel clip with both fully in view, or switch to 1 Character."
            )

        validation_report = {"ran": False}
        if motion_data_1:
            [motion_data_1, motion_data_2], validation_report = (
                self._verify_motion_coordinates(
                    video_path,
                    [motion_data_1, motion_data_2],
                    fps,
                    proc_w,
                    proc_h,
                    num_poses=2,
                )
            )

        output_duration_sec = round(processed_count / fps, 2) if fps > 0 else 0.0
        # Transparent 3D stage + dual world anchors for skeletal mimicry
        stage = _build_stage_from_tracks(
            [motion_data_1, motion_data_2], proc_w, proc_h, fps
        )
        motion_data_1 = _enrich_track_with_stage(motion_data_1, stage, track_id=1)
        motion_data_2 = _enrich_track_with_stage(motion_data_2, stage, track_id=2)
        perimeter = _build_perimeter_track([motion_data_1, motion_data_2], stage)
        stage_path = output_dir / "stage.json"
        perim_path = output_dir / "perimeter_track.json"
        with open(json1_path, "w") as f:
            json.dump(motion_data_1, f, indent=2)
        with open(json2_path, "w") as f:
            json.dump(motion_data_2, f, indent=2)
        with open(stage_path, "w") as f:
            json.dump(stage, f, indent=2)
        with open(perim_path, "w") as f:
            json.dump(perimeter, f, indent=2)
        character_spots = {
            "track_1": {
                "color_hex": spot_hex[0],
                "outline_colors": _palette_hex_list(last_pal[0]),
                "palette": [
                    {
                        "hex": p.get("hex"),
                        "fraction": p.get("fraction"),
                        "region": p.get("region", "full"),
                    }
                    for p in (last_pal[0] or [])
                ],
                "label": "Character 1",
            },
            "track_2": {
                "color_hex": spot_hex[1],
                "outline_colors": _palette_hex_list(last_pal[1]),
                "palette": [
                    {
                        "hex": p.get("hex"),
                        "fraction": p.get("fraction"),
                        "region": p.get("region", "full"),
                    }
                    for p in (last_pal[1] or [])
                ],
                "label": "Character 2",
            },
            "method": "pose_spotter+outline_multi_color_palette_lock+stage_coords",
            "color_lock_reassignments": color_lock_swaps,
        }
        bg_removal_engine = "mediapipe"
        metadata = {
            "character_count": 2,
            "fps": round(fps, 3),
            "source_width": width,
            "source_height": height,
            "width": proc_w,
            "height": proc_h,
            "total_frames": frame_idx,
            "processed_frames": processed_count,
            "detect_frames": detect_count,
            "motion_frames_1": len(motion_data_1),
            "motion_frames_2": len(motion_data_2),
            "frames_with_two_poses": frames_with_two_poses,
            "source_duration_sec": round(duration_sec, 2),
            "output_duration_sec": output_duration_sec,
            "duration_sec": output_duration_sec,
            "sample_every_n": sample_every_n,
            "coordinate_validation": validation_report,
            "character_spots": character_spots,
            "bg_removal_engine": bg_removal_engine,
            "engine": bg_removal_engine,
            "features": [
                "skeletal_pose_heavy",
                "selfie_segmentation",
                "outline_multi_color_palette",
                "pose_region_color_read",
                "color_lab_differentiator",
                "character_spotter_primary",
                "color_signature_id_lock",
                "skeleton_overlay",
                "transparent_3d_stage",
                "world_anchor_feet",
                "perimeter_track",
                "poyo_bg_removal_hook",
            ],
            "character_1_video": str(char1_path.name),
            "character_2_video": str(char2_path.name),
            "background_video": str(bg_path.name),
            "skeleton_overlay": str(overlay_path.name),
            "motion_data_1": str(json1_path.name),
            "motion_data_2": str(json2_path.name),
            "stage": str(stage_path.name),
            "perimeter_track": str(perim_path.name),
            "analyzer_version": ANALYZER_VERSION,
        }
        with open(meta_path, "w") as f:
            json.dump(metadata, f, indent=2)
        job = output_dir.name
        return {
            "status": "success",
            "character_count": 2,
            "job_id": job,
            "character_1_video": f"/outputs/{job}/character_1.mp4",
            "character_2_video": f"/outputs/{job}/character_2.mp4",
            "background_video": f"/outputs/{job}/background.mp4",
            "skeleton_overlay": f"/outputs/{job}/skeleton_overlay.mp4",
            "motion_data_1": f"/outputs/{job}/motion_data_1.json",
            "motion_data_2": f"/outputs/{job}/motion_data_2.json",
            "motion_data": f"/outputs/{job}/motion_data_1.json",
            "stage": f"/outputs/{job}/stage.json",
            "perimeter_track": f"/outputs/{job}/perimeter_track.json",
            "metadata": f"/outputs/{job}/metadata.json",
            "character_spots": character_spots,
            "bg_removal_engine": bg_removal_engine,
            "engine": bg_removal_engine,
            "total_frames": frame_idx,
            "processed_frames": processed_count,
            "motion_frames": len(motion_data_1),
            "motion_frames_1": len(motion_data_1),
            "motion_frames_2": len(motion_data_2),
            "frames_with_two_poses": frames_with_two_poses,
            "coordinate_validation": validation_report,
            "fps": round(fps, 3),
            "resolution": f"{proc_w}x{proc_h}",
            "source_resolution": f"{width}x{height}",
            "source_duration_sec": round(duration_sec, 2),
            "output_duration_sec": output_duration_sec,
            "duration_sec": output_duration_sec,
            "analyzer_version": ANALYZER_VERSION,
            "motion_product": "4.5-stage-spotter",
        }

    def _open_video_writer(self, output_path, width, height, fps):
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        return cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

    def _write_empty_video(self, writer, width, height):
        writer.write(np.zeros((height, width, 3), dtype=np.uint8))


@app.post("/analyze-motion")
async def analyze_motion_endpoint(
    video: UploadFile = File(...),
    character_count: int = Form(1),
    sample_every_n: int = Form(DEFAULT_SAMPLE_EVERY_N),
    background_tasks: BackgroundTasks = None,
):
    try:
        character_count = int(character_count)
    except (TypeError, ValueError):
        character_count = 1
    if character_count not in (1, 2):
        raise HTTPException(status_code=400, detail="character_count must be 1 or 2.")
    if video.content_type not in ALLOWED_VIDEO_TYPES and not video.filename.lower().endswith(
        (".mp4", ".mov", ".webm", ".mkv")
    ):
        raise HTTPException(status_code=400, detail="Unsupported video format.")
    contents = await video.read()
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(status_code=413, detail=f"Video too large ({size_mb:.1f}MB).")
    job_id = str(uuid.uuid4())[:8]
    job_dir = OUTPUT_BASE / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    input_path = job_dir / f"input_{video.filename}"
    with open(input_path, "wb") as f:
        f.write(contents)

    analyzer = PercfectMotionAnalyzer()
    try:
        result = analyzer.process_video(
            str(input_path),
            output_dir=str(job_dir),
            sample_every_n=max(1, min(sample_every_n, 5)),
            max_seconds=MAX_VIDEO_SECONDS,
            character_count=character_count,
        )
        # Always tag local engine (main app may upgrade character plate via PoYo)
        result.setdefault("bg_removal_engine", "mediapipe")
        result.setdefault("engine", result.get("bg_removal_engine") or "mediapipe")
        if background_tasks:
            background_tasks.add_task(os.unlink, input_path)
        return JSONResponse(content=result)
    except ValueError as ve:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Motion analysis failed: {str(e)}")
    finally:
        analyzer.close()


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "percfect-motion-analyzer-v2",
        "version": ANALYZER_VERSION,
        "features": [
            "outline_multi_color_palette",
            "transparent_3d_stage",
            "skeleton_overlay",
            "character_spotter",
            "poyo_bg_removal_hook",
        ],
        "bg_removal_engine_default": "mediapipe",
        "mediapipe": mp.__version__,
        "api": "tasks",
        "duration_policy": "write_every_frame",
        "motion_product": "4.5-stage-spotter",
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
