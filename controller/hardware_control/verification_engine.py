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

    HIGHLIGHT_SATURATION_THRESHOLD = 30
    HIGHLIGHT_VALUE_DIFF_THRESHOLD = 20
    HIGHLIGHT_BLUE_RATIO_THRESHOLD = 0.15
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
            pixel_coords = self._grid_map.get_pixel_for(expected_letter)
            if pixel_coords:
                return self._verify_with_grid(
                    post_img, pixel_coords, expected_letter
                )

        return self._verify_with_color_analysis(post_img, expected_letter)

    def _verify_with_grid(
        self, img: np.ndarray, pixel_coords: tuple[int, int], letter: str
    ) -> VerificationResult:
        """Verify by analyzing the color of the region around the expected option."""
        import cv2

        h, w = img.shape[:2]
        cx, cy = pixel_coords
        pad = self.OPTION_CROP_PADDING

        x1 = max(0, cx - pad * 3)
        y1 = max(0, cy - pad)
        x2 = min(w, cx + pad * 3)
        y2 = min(h, cy + pad)

        if x2 <= x1 or y2 <= y1:
            logger.warning("Invalid crop region for option %s", letter)
            return VerificationResult(verified=False, details="invalid_crop")

        region = img[y1:y2, x1:x2]
        hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)

        mean_s = float(np.mean(hsv[:, :, 1]))
        mean_v = float(np.mean(hsv[:, :, 2]))

        blue_mask = cv2.inRange(hsv, np.array([100, 40, 40]), np.array([130, 255, 255]))
        blue_ratio = float(np.count_nonzero(blue_mask)) / max(blue_mask.size, 1)

        green_mask = cv2.inRange(hsv, np.array([35, 40, 40]), np.array([85, 255, 255]))
        green_ratio = float(np.count_nonzero(green_mask)) / max(green_mask.size, 1)

        highlight_detected = (
            mean_s > self.HIGHLIGHT_SATURATION_THRESHOLD
            or blue_ratio > self.HIGHLIGHT_BLUE_RATIO_THRESHOLD
            or green_ratio > self.HIGHLIGHT_BLUE_RATIO_THRESHOLD
        )

        confidence = max(
            mean_s / 100.0,
            blue_ratio / self.HIGHLIGHT_BLUE_RATIO_THRESHOLD,
            green_ratio / self.HIGHLIGHT_BLUE_RATIO_THRESHOLD,
        )
        confidence = min(confidence, 1.0)

        if self._pre_click_screenshot is not None:
            pre_img = cv2.imread(str(self._pre_click_screenshot))
            if pre_img is not None and pre_img.shape == img.shape:
                pre_region = pre_img[y1:y2, x1:x2]
                pre_hsv = cv2.cvtColor(pre_region, cv2.COLOR_BGR2HSV)
                diff = float(np.mean(np.abs(
                    hsv.astype(np.float32) - pre_hsv.astype(np.float32)
                )))
                if diff > self.HIGHLIGHT_VALUE_DIFF_THRESHOLD:
                    highlight_detected = True
                    confidence = max(confidence, min(diff / 50.0, 1.0))
                    logger.debug("Before/after diff: %.1f", diff)

        self._pre_click_screenshot = None

        if highlight_detected:
            logger.info(
                "Verification PASSED for %s (confidence=%.2f, saturation=%.1f, blue=%.3f)",
                letter, confidence, mean_s, blue_ratio,
            )
            return VerificationResult(verified=True, details="highlight_detected", confidence=confidence)

        logger.warning(
            "Verification FAILED for %s (saturation=%.1f, blue=%.3f, green=%.3f)",
            letter, mean_s, blue_ratio, green_ratio,
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
