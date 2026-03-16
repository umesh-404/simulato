"""
Coordinate solver — automated calibration workflow.

Analyzes a captured screenshot of the exam interface to automatically
detect the positions of interactive elements (options A–D, NEXT button,
scroll areas) and build a grid_map.json.

Detection approach:
    1. Convert to grayscale + edge detection
    2. Find rectangular regions (option boxes) via contour detection
    3. Sort regions vertically to identify A, B, C, D
    4. Detect NEXT button region (bottom-right area)
    5. Map detected pixel centers to grid coordinates
"""

from pathlib import Path
from typing import Optional

import numpy as np

from calibration.grid_mapper import GridMap
from controller.utils.logger import get_logger

logger = get_logger("coordinate_solver")


class CalibrationResult:
    def __init__(self, success: bool, grid_map: Optional[GridMap] = None, message: str = "") -> None:
        self.success = success
        self.grid_map = grid_map
        self.message = message


def calibrate_from_screenshot(image_path: Path, resolution: tuple[int, int] = (1920, 1080)) -> CalibrationResult:
    """
    Analyze an exam screenshot and produce a calibrated GridMap.

    Args:
        image_path: Path to the calibration screenshot.
        resolution: Screen resolution (width, height).

    Returns:
        CalibrationResult with the generated GridMap or error details.
    """
    try:
        import cv2
    except ImportError:
        return CalibrationResult(success=False, message="OpenCV required for calibration")

    img = cv2.imread(str(image_path))
    if img is None:
        return CalibrationResult(success=False, message=f"Cannot read image: {image_path}")

    h, w = img.shape[:2]
    logger.info("Calibration image: %dx%d", w, h)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    mean_intensity = float(gray.mean())
    if mean_intensity < 40.0:
        logger.warning(
            "Calibration image too dark (mean_intensity=%.2f) — likely no screen visible",
            mean_intensity,
        )
        return CalibrationResult(success=False, message="Calibration image too dark or no screen visible")

    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 30, 100)

    edge_ratio = float(np.count_nonzero(edges)) / float(w * h)
    if edge_ratio < 0.001:
        logger.warning(
            "Calibration image has too few edges (edge_ratio=%.5f) — not a valid exam screen",
            edge_ratio,
        )
        return CalibrationResult(success=False, message="Calibration image lacks structure (no exam UI detected)")

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    def _find_option_candidates(cnts, min_area_factor: float, max_area_factor: float, min_aspect: float, max_aspect: float):
        candidates = []
        for cnt in cnts:
            x, y, cw, ch = cv2.boundingRect(cnt)
            aspect = cw / max(ch, 1)
            area = cw * ch
            if min_aspect < aspect < max_aspect and area > (w * h * min_area_factor) and area < (w * h * max_area_factor):
                candidates.append((x, y, cw, ch))
        candidates.sort(key=lambda r: r[1])
        return candidates

    # First pass: stricter heuristics
    option_candidates = _find_option_candidates(
        contours,
        min_area_factor=0.002,
        max_area_factor=0.15,
        min_aspect=1.5,
        max_aspect=15.0,
    )

    logger.info("First-pass option-like regions: %d", len(option_candidates))

    # If we didn't find enough, try a more relaxed second pass using a thresholded image.
    if len(option_candidates) < 4:
        logger.info("Running relaxed second-pass detection for option regions")
        # Adaptive threshold to emphasize text/boxes
        thr = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_MEAN_C,
            cv2.THRESH_BINARY_INV,
            25,
            10,
        )
        thr_closed = cv2.morphologyEx(thr, cv2.MORPH_CLOSE, kernel, iterations=2)
        contours2, _ = cv2.findContours(thr_closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        option_candidates = _find_option_candidates(
            contours2,
            min_area_factor=0.0005,
            max_area_factor=0.20,
            min_aspect=0.8,
            max_aspect=15.0,
        )
        logger.info("Second-pass option-like regions: %d", len(option_candidates))

    gm = GridMap()
    gm.resolution = resolution
    gm.capture_resolution = (w, h)
    gm.transform = {
        "scale_x": float(resolution[0]) / float(max(1, w)),
        "scale_y": float(resolution[1]) / float(max(1, h)),
        "offset_x": 0.0,
        "offset_y": 0.0,
    }
    gm.grid_size = (20, 20)

    if len(option_candidates) < 4:
        logger.warning(
            "Calibration failed — only %d option-like regions detected (need at least 4)",
            len(option_candidates),
        )
        return CalibrationResult(
            success=False,
            message="Could not detect all four option regions — check camera framing and focus",
        )

    top_4 = option_candidates[:4]
    letters = ["A", "B", "C", "D"]
    for letter, (rx, ry, rw, rh) in zip(letters, top_4):
        cx = rx + rw // 2
        cy = ry + rh // 2

        scaled_x = int(cx * resolution[0] / w)
        scaled_y = int(cy * resolution[1] / h)

        grid_col = int(scaled_x / (resolution[0] / gm.grid_size[0]))
        grid_row = int(scaled_y / (resolution[1] / gm.grid_size[1]))

        gm.positions[letter] = (grid_col, grid_row)
        logger.info("Detected %s: pixel=(%d,%d) → grid=(%d,%d)", letter, scaled_x, scaled_y, grid_col, grid_row)

    button_candidates = []
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        aspect = cw / max(ch, 1)
        area = cw * ch
        if (x + cw) > w * 0.6 and (y + ch) > h * 0.7:
            if 1.0 < aspect < 5 and area > (w * h * 0.001):
                button_candidates.append((x, y, cw, ch))

    if not button_candidates:
        logger.warning("Calibration failed — NEXT button region not detected")
        return CalibrationResult(
            success=False,
            message="NEXT button not detected — ensure the full exam screen is visible",
        )

    button_candidates.sort(key=lambda r: r[1], reverse=True)
    bx, by, bw, bh = button_candidates[0]
    cx = bx + bw // 2
    cy = by + bh // 2
    scaled_x = int(cx * resolution[0] / w)
    scaled_y = int(cy * resolution[1] / h)
    grid_col = int(scaled_x / (resolution[0] / gm.grid_size[0]))
    grid_row = int(scaled_y / (resolution[1] / gm.grid_size[1]))
    gm.positions["NEXT"] = (grid_col, grid_row)
    logger.info("Detected NEXT: pixel=(%d,%d) → grid=(%d,%d)", scaled_x, scaled_y, grid_col, grid_row)

    gm.positions.setdefault("SCROLL_LEFT", (0, 10))
    gm.positions.setdefault("SCROLL_RIGHT", (19, 10))

    logger.info("Calibration complete: %d positions mapped", len(gm.positions))
    return CalibrationResult(success=True, grid_map=gm, message="Calibration successful")
