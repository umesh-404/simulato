"""
Input verification engine.

After a click command is dispatched, this module verifies
that the intended option is visually highlighted on screen.

Transaction flow (Canonical Law 5):
    1. Click dispatched
    2. Screenshot captured
    3. Highlight detection run
    4. If not highlighted: retry once
    5. If retry fails: trigger alert, halt execution

Detection approach:
    - Crop the region around the expected option using grid_map coordinates
    - Compare pixel color distribution before/after click
    - Highlighted options typically have a distinct background color shift
    - Uses HSV color space analysis for robustness to lighting variations
"""

from pathlib import Path
from typing import Optional, Callable

import numpy as np

from controller.utils.logger import get_logger

logger = get_logger("verification_engine")


class VerificationResult:
    def __init__(self, verified: bool, details: str = "", confidence: float = 0.0) -> None:
        self.verified = verified
        self.details = details
        self.confidence = confidence


class VerificationEngine:
    """
    Verifies that a click action was successful by analyzing
    a post-click screenshot for visual highlight changes.
    """

    HIGHLIGHT_SATURATION_THRESHOLD = 14
    HIGHLIGHT_VALUE_DIFF_THRESHOLD = 15
    HIGHLIGHT_BLUE_RATIO_THRESHOLD = 0.005
    OPTION_CROP_PADDING = 40

    def __init__(
        self,
        capture_callback: Optional[Callable[[], Path]] = None,
        grid_map: Optional[object] = None,
    ) -> None:
        self._capture_callback = capture_callback
        self._grid_map = grid_map
        self._pre_click_screenshot: Optional[Path] = None

    def set_capture_callback(self, callback: Callable[[], Path]) -> None:
        self._capture_callback = callback

    def set_grid_map(self, grid_map) -> None:
        self._grid_map = grid_map

    def capture_pre_click(self) -> None:
        """Capture a screenshot before click for comparison."""
        if self._capture_callback:
            self._pre_click_screenshot = self._capture_callback()
            logger.debug("Pre-click screenshot captured: %s", self._pre_click_screenshot)

    def verify_click(self, expected_letter: str) -> VerificationResult:
        """
        Verify that the expected option is highlighted after clicking.

        Uses two strategies:
            1. Color analysis of the option region (highlight detection)
            2. Before/after comparison if pre-click screenshot is available
        """
        if self._capture_callback is None:
            logger.warning("No capture callback set — skipping verification")
            return VerificationResult(verified=True, details="verification_skipped")

        post_screenshot = self._capture_callback()
        logger.info("Verifying click for option %s using: %s", expected_letter, post_screenshot)
        return self.verify_click_on_image(expected_letter, post_screenshot)

    def verify_click_on_image(self, expected_letter: str, post_screenshot: Path) -> VerificationResult:
        """
        Verify click using a specific post-click screenshot path.

        This is used by workflow paths that explicitly request a fresh
        verification capture frame and then pass that exact file here.
        """

        try:
            import cv2
        except ImportError:
            logger.warning("OpenCV not available — skipping verification")
            return VerificationResult(verified=True, details="opencv_unavailable")

        post_img = cv2.imread(str(post_screenshot))
        if post_img is None:
            logger.warning("Cannot read post-click screenshot")
            return VerificationResult(verified=False, details="unreadable_screenshot")

        if self._grid_map is not None:
            screen_coords = self._grid_map.get_pixel_for(expected_letter)
            if screen_coords:
                pixel_coords = self._screen_to_capture_pixel(screen_coords)
                return self._verify_with_grid(
                    post_img, pixel_coords, expected_letter
                )

        return self._verify_with_color_analysis(post_img, expected_letter)

    def verify_click_at_normalized_on_image(
        self,
        expected_letter: str,
        post_screenshot: Path,
        norm_x: float,
        norm_y: float,
    ) -> VerificationResult:
        """
        Verify click around explicit normalized target coordinates.

        This is used when click dispatch was done via OCR-derived normalized
        coordinates and is more reliable than stale calibration grid points.
        """
        try:
            import cv2
        except ImportError:
            logger.warning("OpenCV not available — skipping verification")
            return VerificationResult(verified=True, details="opencv_unavailable")

        post_img = cv2.imread(str(post_screenshot))
        if post_img is None:
            logger.warning("Cannot read post-click screenshot")
            return VerificationResult(verified=False, details="unreadable_screenshot")

        h, w = post_img.shape[:2]
        px = int(round(max(0.0, min(1.0, float(norm_x))) * max(1, w - 1)))
        py = int(round(max(0.0, min(1.0, float(norm_y))) * max(1, h - 1)))
        return self._verify_with_grid(post_img, (px, py), expected_letter)

    def _screen_to_capture_pixel(self, screen_coords: tuple[int, int]) -> tuple[int, int]:
        """
        Convert exam-screen pixel coordinates to capture-image pixel coordinates.
        GridMap stores option positions in screen space, while verification images
        are in capture camera space.
        """
        sx, sy = int(screen_coords[0]), int(screen_coords[1])
        gm = self._grid_map
        try:
            scale_x = float(gm.transform.get("scale_x", 1.0))
            scale_y = float(gm.transform.get("scale_y", 1.0))
            offset_x = float(gm.transform.get("offset_x", 0.0))
            offset_y = float(gm.transform.get("offset_y", 0.0))
            if abs(scale_x) > 1e-6 and abs(scale_y) > 1e-6:
                cx = int(round((sx - offset_x) / scale_x))
                cy = int(round((sy - offset_y) / scale_y))
            else:
                raise ValueError("invalid scale")
        except Exception:
            # Fallback ratio conversion.
            sw, sh = gm.resolution
            cw, ch = gm.capture_resolution
            cx = int(round(sx * (cw / max(1, sw))))
            cy = int(round(sy * (ch / max(1, sh))))

        cw, ch = gm.capture_resolution
        cx = max(0, min(max(1, cw) - 1, cx))
        cy = max(0, min(max(1, ch) - 1, cy))
        return (cx, cy)

    def _verify_with_grid(
        self, img: np.ndarray, pixel_coords: tuple[int, int], letter: str
    ) -> VerificationResult:
        """Verify by analyzing the color of the region around the expected option.

        Uses two concentric crops:
        - A tight crop (~30px radius) centred on the radio button itself,
          where any fill/highlight colour will be concentrated.
        - A wider crop (~120x80 px) for the before/after diff check.
        """
        import cv2

        h, w = img.shape[:2]
        cx, cy = pixel_coords
        pad = self.OPTION_CROP_PADDING

        # Tight crop around the radio button. Use a wider horizontal
        # band to tolerate slight click offset and capture the full
        # highlight row (selected options often get a full-width blue bar).
        tight_rx = 60
        tight_ry = 35
        tx1 = max(0, cx - tight_rx)
        ty1 = max(0, cy - tight_ry)
        tx2 = min(w, cx + tight_rx)
        ty2 = min(h, cy + tight_ry)

        # Wide crop for before/after diff.
        x1 = max(0, cx - pad * 3)
        y1 = max(0, cy - pad)
        x2 = min(w, cx + pad * 3)
        y2 = min(h, cy + pad)

        if tx2 <= tx1 or ty2 <= ty1:
            logger.warning("Invalid crop region for option %s", letter)
            return VerificationResult(verified=False, details="invalid_crop")

        tight_region = img[ty1:ty2, tx1:tx2]
        tight_hsv = cv2.cvtColor(tight_region, cv2.COLOR_BGR2HSV)

        mean_s = float(np.mean(tight_hsv[:, :, 1]))

        # Detect filled radio button: dark blue/teal fill or any saturated colour.
        blue_mask = cv2.inRange(tight_hsv, np.array([90, 30, 30]), np.array([140, 255, 255]))
        blue_ratio = float(np.count_nonzero(blue_mask)) / max(blue_mask.size, 1)

        green_mask = cv2.inRange(tight_hsv, np.array([35, 30, 30]), np.array([85, 255, 255]))
        green_ratio = float(np.count_nonzero(green_mask)) / max(green_mask.size, 1)

        # Any saturated colour at all (covers blue, green, orange highlights).
        sat_mask = tight_hsv[:, :, 1] > 20
        sat_ratio = float(np.count_nonzero(sat_mask)) / max(sat_mask.size, 1)

        highlight_detected = (
            mean_s > self.HIGHLIGHT_SATURATION_THRESHOLD
            or blue_ratio > self.HIGHLIGHT_BLUE_RATIO_THRESHOLD
            or green_ratio > self.HIGHLIGHT_BLUE_RATIO_THRESHOLD
            or sat_ratio > 0.02
        )

        confidence = max(
            mean_s / 100.0,
            blue_ratio / max(self.HIGHLIGHT_BLUE_RATIO_THRESHOLD, 1e-9),
            green_ratio / max(self.HIGHLIGHT_BLUE_RATIO_THRESHOLD, 1e-9),
            sat_ratio / 0.05,
        )
        confidence = min(confidence, 1.0)

        if self._pre_click_screenshot is not None and x2 > x1 and y2 > y1:
            pre_img = cv2.imread(str(self._pre_click_screenshot))
            if pre_img is not None and pre_img.shape == img.shape:
                pre_region = pre_img[y1:y2, x1:x2]
                post_region = img[y1:y2, x1:x2]
                pre_hsv_wide = cv2.cvtColor(pre_region, cv2.COLOR_BGR2HSV)
                post_hsv_wide = cv2.cvtColor(post_region, cv2.COLOR_BGR2HSV)
                diff = float(np.mean(np.abs(
                    post_hsv_wide.astype(np.float32) - pre_hsv_wide.astype(np.float32)
                )))
                if diff > self.HIGHLIGHT_VALUE_DIFF_THRESHOLD:
                    highlight_detected = True
                    confidence = max(confidence, min(diff / 50.0, 1.0))
                    logger.debug("Before/after diff: %.1f", diff)

        self._pre_click_screenshot = None

        # Save debug crop for post-mortem analysis.
        try:
            import tempfile
            debug_dir = Path(tempfile.gettempdir()) / "simulato_verify_debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(
                str(debug_dir / f"verify_{letter}_tight.jpg"),
                tight_region,
            )
        except Exception:
            pass

        if highlight_detected:
            logger.info(
                "Verification PASSED for %s (confidence=%.2f, saturation=%.1f, blue=%.3f, sat_ratio=%.3f)",
                letter, confidence, mean_s, blue_ratio, sat_ratio,
            )
            return VerificationResult(verified=True, details="highlight_detected", confidence=confidence)

        logger.warning(
            "Verification FAILED for %s (saturation=%.1f, blue=%.3f, green=%.3f, sat_ratio=%.3f, crop=%dx%d@(%d,%d))",
            letter, mean_s, blue_ratio, green_ratio, sat_ratio,
            tx2 - tx1, ty2 - ty1, cx, cy,
        )
        return VerificationResult(verified=False, details="no_highlight", confidence=confidence)

    def _verify_with_color_analysis(
        self, img: np.ndarray, letter: str
    ) -> VerificationResult:
        """Fallback: analyze full image for any highlight-colored region."""
        import cv2

        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        blue_mask = cv2.inRange(hsv, np.array([100, 50, 50]), np.array([130, 255, 255]))
        blue_ratio = float(np.count_nonzero(blue_mask)) / max(blue_mask.size, 1)

        if blue_ratio > 0.01:
            logger.info("Fallback verification PASSED for %s (blue_ratio=%.4f)", letter, blue_ratio)
            return VerificationResult(verified=True, details="fallback_color_detected", confidence=blue_ratio * 10)

        logger.warning("Fallback verification FAILED for %s", letter)
        return VerificationResult(verified=False, details="fallback_no_highlight")
