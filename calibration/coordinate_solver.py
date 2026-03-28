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

# When re-running calibration, reuse a prior transform if it differs from a
# fresh naive scale/offset — e.g. perspective-corrected `scale_y` / `offset_y`
# in `grid_map.json`. Pure naive maps have scale ≈ screen/capture and zero offsets.
_TRANSFORM_SCALE_EPS = 0.001
_TRANSFORM_OFFSET_EPS = 0.5


def _try_reuse_transform_from_disk(
    naive_sx: float,
    naive_sy: float,
) -> tuple[float, float, float, float] | None:
    """
    Load existing `config/grid_map.json` and return (sx, sy, ox, oy) if it
    carries a non-naive capture→screen mapping worth preserving.

    Returns None if no file, parse error, or transform is effectively naive.
    """
    try:
        existing = GridMap.load()
    except (FileNotFoundError, OSError, ValueError, KeyError, TypeError) as e:
        logger.debug("No reusable transform from disk: %s", e)
        return None

    esx = float(existing.transform.get("scale_x", naive_sx))
    esy = float(existing.transform.get("scale_y", naive_sy))
    eox = float(existing.transform.get("offset_x", 0.0))
    eoy = float(existing.transform.get("offset_y", 0.0))

    if abs(eox) > _TRANSFORM_OFFSET_EPS or abs(eoy) > _TRANSFORM_OFFSET_EPS:
        return (esx, esy, eox, eoy)

    if abs(esx / naive_sx - 1.0) > _TRANSFORM_SCALE_EPS or abs(esy / naive_sy - 1.0) > _TRANSFORM_SCALE_EPS:
        return (esx, esy, eox, eoy)

    return None


class CalibrationResult:
    def __init__(self, success: bool, grid_map: Optional[GridMap] = None, message: str = "") -> None:
        self.success = success
        self.grid_map = grid_map
        self.message = message


def _pixel_to_grid(
    gm: GridMap,
    capture_x: int,
    capture_y: int,
    capture_w: int,
    capture_h: int,
    screen_w: int,
    screen_h: int,
) -> tuple[int, int, int, int]:
    """Convert capture-space pixel to screen-space pixel and grid cell."""
    scaled_x = int(capture_x * screen_w / max(1, capture_w))
    scaled_y = int(capture_y * screen_h / max(1, capture_h))
    scaled_x = max(0, min(max(1, screen_w) - 1, scaled_x))
    scaled_y = max(0, min(max(1, screen_h) - 1, scaled_y))

    cell_w = float(screen_w) / float(max(1, gm.grid_size[0]))
    cell_h = float(screen_h) / float(max(1, gm.grid_size[1]))
    grid_col = int(scaled_x / max(1e-6, cell_w))
    grid_row = int(scaled_y / max(1e-6, cell_h))
    grid_col = max(0, min(gm.grid_size[0] - 1, grid_col))
    grid_row = max(0, min(gm.grid_size[1] - 1, grid_row))
    return scaled_x, scaled_y, grid_col, grid_row


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
    # Provisional transform — will be refined after detecting reference points.
    naive_sx = float(resolution[0]) / float(max(1, w))
    naive_sy = float(resolution[1]) / float(max(1, h))
    gm.transform = {
        "scale_x": naive_sx,
        "scale_y": naive_sy,
        "offset_x": 0.0,
        "offset_y": 0.0,
    }
    gm.grid_size = (20, 20)

    # Primary calibration path (robust): exam layout + radio-row option detector.
    # This matches runtime click mapping behavior and is more stable than global contours.
    try:
        from controller.capture_pipeline.exam_layout import ExamLayoutDetector
        from controller.capture_pipeline.option_detector import OptionDetector

        layout = ExamLayoutDetector().detect(image_path)
        option_map = None
        if layout is not None and layout.answer_panel is not None:
            option_map = OptionDetector().detect(image_path, layout)

        if option_map is not None and option_map.count >= 3:
            ordered = sorted(option_map.options, key=lambda o: int(o.circle_y))
            ys = [int(o.click_y) for o in ordered]
            xs = [int(o.click_x) for o in ordered]
            x_anchor = int(round(sum(xs) / max(1, len(xs))))

            # Validate geometry so we do not persist obviously broken maps.
            if any(ys[i] >= ys[i + 1] for i in range(len(ys) - 1)):
                raise ValueError("non-monotonic option rows in primary calibration path")
            if layout.answer_panel is not None:
                ap = layout.answer_panel
                min_x = ap.x + int(ap.w * 0.02)
                max_x = ap.x + int(ap.w * 0.40)
                if not (min_x <= x_anchor <= max_x):
                    raise ValueError("option x-anchor outside expected answer-panel radio band")

            # Detect NEXT button in capture space.
            if layout.next_button is not None:
                next_cap_x, next_cap_y = layout.next_button.cx, layout.next_button.cy
            elif layout.answer_panel is not None:
                next_cap_x = int(layout.answer_panel.x + layout.answer_panel.w * 0.90)
                next_cap_y = int(layout.answer_panel.y + layout.answer_panel.h * 0.96)
            else:
                next_cap_x = int(w * 0.90)
                next_cap_y = int(h * 0.95)

            # ---------------------------------------------------------------
            # Build capture → screen affine transform.
            #
            # The naive transform (screen = capture * screen_res/capture_res)
            # assumes the camera image is an undistorted 1:1 map of the screen.
            # In practice the capture phone photographs the laptop at an angle,
            # introducing perspective distortion that the naive linear scale
            # cannot capture.
            #
            # If `grid_map.json` already contains a non-naive transform
            # (perspective correction: non-zero offsets and/or scale drift from
            # screen_size/capture_size), preserve it when re-calibrating so
            # option row positions refresh without losing the mapping fix.
            #
            # Otherwise start with the naive linear scale (zero offsets). If
            # clicks land consistently one row off, tune `transform` in
            # `grid_map.json` or copy a known-good file from a verified setup.
            # ---------------------------------------------------------------
            cell_w = float(resolution[0]) / float(max(1, gm.grid_size[0]))
            cell_h = float(resolution[1]) / float(max(1, gm.grid_size[1]))

            reused = _try_reuse_transform_from_disk(naive_sx, naive_sy)
            if reused is not None:
                fit_sx, fit_sy, fit_ox, fit_oy = reused
                logger.info(
                    "Reusing transform from existing grid_map: "
                    "scale=(%.6f, %.6f) offset=(%.1f, %.1f)",
                    fit_sx, fit_sy, fit_ox, fit_oy,
                )
            else:
                fit_sx = naive_sx
                fit_sy = naive_sy
                fit_ox = 0.0
                fit_oy = 0.0
                logger.info(
                    "Using naive transform: scale=(%.6f, %.6f) offset=(0, 0). "
                    "If clicks land one option row off, add perspective correction to grid_map.json.",
                    fit_sx, fit_sy,
                )

            gm.transform = {
                "scale_x": fit_sx,
                "scale_y": fit_sy,
                "offset_x": fit_ox,
                "offset_y": fit_oy,
            }
            logger.info(
                "Affine transform: scale=(%.6f, %.6f) offset=(%.1f, %.1f) "
                "(naive scale was %.6f, %.6f)",
                fit_sx, fit_sy, fit_ox, fit_oy, naive_sx, naive_sy,
            )

            # Now compute screen positions and grid cells using the fitted transform.
            def _cap_to_screen(cap_x: int, cap_y: int) -> tuple[int, int]:
                sx = int(round(cap_x * fit_sx + fit_ox))
                sy = int(round(cap_y * fit_sy + fit_oy))
                sx = max(0, min(resolution[0] - 1, sx))
                sy = max(0, min(resolution[1] - 1, sy))
                return sx, sy

            def _screen_to_grid(sx: int, sy: int) -> tuple[int, int]:
                gc = int(sx / max(1e-6, cell_w))
                gr = int(sy / max(1e-6, cell_h))
                gc = max(0, min(gm.grid_size[0] - 1, gc))
                gr = max(0, min(gm.grid_size[1] - 1, gr))
                return gc, gr

            for opt in ordered:
                sx, sy = _cap_to_screen(int(opt.click_x), int(opt.click_y))
                gc, gr = _screen_to_grid(sx, sy)
                gm.positions[opt.label] = (gc, gr)
                gm.pixel_positions[opt.label] = (sx, sy)
                logger.info("Detected %s: pixel=(%d,%d) → grid=(%d,%d)", opt.label, sx, sy, gc, gr)

            # Deterministically extrapolate missing rows (if any) so we avoid
            # fragile contour fallback when calibration screenshot has only 3 options.
            if len(ys) >= 2:
                steps = [ys[i + 1] - ys[i] for i in range(len(ys) - 1) if ys[i + 1] > ys[i]]
                step = int(round(float(np.median(steps)))) if steps else 0
            else:
                step = 0
            if 20 <= step <= 600:
                label_index = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
                first_label = ordered[0].label
                first_label_idx = label_index.get(first_label, 0)
                base_y = ys[0]
                for idx, letter in enumerate(("A", "B", "C", "D", "E")):
                    if letter in gm.positions:
                        continue
                    offset = idx - first_label_idx
                    est_y = int(base_y + offset * step)
                    est_y = max(0, min(h - 1, est_y))
                    est_sx, est_sy = _cap_to_screen(x_anchor, est_y)
                    egc, egr = _screen_to_grid(est_sx, est_sy)
                    gm.positions[letter] = (egc, egr)
                    gm.pixel_positions[letter] = (est_sx, est_sy)
                    logger.info("Estimated %s: pixel=(%d,%d) → grid=(%d,%d)", letter, est_sx, est_sy, egc, egr)

            sx_next, sy_next = _cap_to_screen(next_cap_x, next_cap_y)
            gc_next, gr_next = _screen_to_grid(sx_next, sy_next)
            gm.positions["NEXT"] = (gc_next, gr_next)
            gm.pixel_positions["NEXT"] = (sx_next, sy_next)
            logger.info("Detected NEXT: pixel=(%d,%d) → grid=(%d,%d)", sx_next, sy_next, gc_next, gr_next)

            gm.positions.setdefault("SCROLL_LEFT", (0, 10))
            gm.positions.setdefault("SCROLL_RIGHT", (19, 10))
            logger.info("Calibration complete: %d positions mapped", len(gm.positions))
            return CalibrationResult(success=True, grid_map=gm, message="Calibration successful")
    except Exception as e:
        logger.warning("Primary calibration path failed, falling back to legacy contour method: %s", e)

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
        gm.pixel_positions[letter] = (scaled_x, scaled_y)
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
    gm.pixel_positions["NEXT"] = (scaled_x, scaled_y)
    logger.info("Detected NEXT: pixel=(%d,%d) → grid=(%d,%d)", scaled_x, scaled_y, grid_col, grid_row)

    gm.positions.setdefault("SCROLL_LEFT", (0, 10))
    gm.positions.setdefault("SCROLL_RIGHT", (19, 10))

    logger.info("Calibration complete: %d positions mapped", len(gm.positions))
    return CalibrationResult(success=True, grid_map=gm, message="Calibration successful")
