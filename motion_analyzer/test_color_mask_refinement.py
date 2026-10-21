#!/usr/bin/env python3
"""Local-only color mask experiment. Not used in production."""

import sys
from pathlib import Path

import cv2
import numpy as np

COLOR_REFINE_LAB_TOLERANCE = 28.0
COLOR_REFINE_MAX_ITERATIONS = 35
COLOR_REFINE_LOCAL_WINDOW = 5


def as_2d_mask(mask: np.ndarray) -> np.ndarray:
    arr = np.asarray(mask)
    while arr.ndim > 2:
        arr = arr[..., 0] if arr.shape[-1] == 1 else np.squeeze(arr)
        if arr.ndim > 2:
            arr = arr[..., 0]
    return np.ascontiguousarray((arr > 0).astype(np.uint8))


def refine_mask_with_color_similarity(frame_bgr, mask):
    refined = as_2d_mask(mask)
    if refined.sum() == 0:
        return refined
    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    kernel = np.ones((3, 3), np.uint8)
    window = max(3, COLOR_REFINE_LOCAL_WINDOW | 1)
    for _ in range(COLOR_REFINE_MAX_ITERATIONS):
        dilated = as_2d_mask(cv2.dilate(refined, kernel, iterations=1))
        candidates = np.logical_and(dilated > 0, refined == 0)
        if not np.any(candidates):
            break
        refined_f = refined.astype(np.float32)
        neighbor_w = cv2.blur(refined_f, (window, window))
        local_lab = np.zeros_like(lab)
        for channel in range(3):
            blurred = cv2.blur(lab[:, :, channel] * refined_f, (window, window))
            local_lab[:, :, channel] = blurred / (neighbor_w + 1e-6)
        dist = np.linalg.norm(lab - local_lab, axis=2)
        refined[np.logical_and(candidates, dist <= COLOR_REFINE_LAB_TOLERANCE)] = 1
    return as_2d_mask(refined)


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_color_mask_refinement.py <image_or_video>")
        sys.exit(1)
    src = Path(sys.argv[1])
    if src.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        frame = cv2.imread(str(src))
    else:
        cap = cv2.VideoCapture(str(src))
        ok, frame = cap.read()
        cap.release()
        if not ok:
            print("Could not read frame")
            sys.exit(1)
    h, w = frame.shape[:2]
    base = np.zeros((h, w), dtype=np.uint8)
    base[h // 4 : 3 * h // 4, w // 4 : 3 * w // 4] = 1
    refined = refine_mask_with_color_similarity(frame, base)
    out = Path("color_mask_test_output")
    out.mkdir(exist_ok=True)
    cv2.imwrite(str(out / "mask_base.png"), base * 255)
    cv2.imwrite(str(out / "mask_refined.png"), refined * 255)
    print(f"Saved to {out} (+{int(refined.sum() - base.sum())} pixels)")


if __name__ == "__main__":
    main()
